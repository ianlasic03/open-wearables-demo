#!/usr/bin/env python3
"""Create a demo user, connect a wearable provider via OAuth, trigger a sync, and fetch data.

Standalone script - no imports from app.* required. Just httpx + stdlib.

Usage:
    uv run python scripts/create_demo_user.py \
        --email demo@example.com \
        --external-id demo-user-123 \
        --api-key YOUR_API_KEY \
        [--first-name Jane] \
        [--last-name Doe] \
        [--api-url http://localhost:8000] \
        [--provider oura] \
        [--fetch-only USER_ID]

Steps:
    1. Create a user via POST /api/v1/users
    2. Fetch the OAuth authorization URL for the provider
    3. Print the URL — open it in your browser to authorize
    4. After OAuth: trigger a sync, then fetch timeseries, workouts, and sleep data

    Use --fetch-only <user_id> to skip user creation and just sync + fetch for an existing user.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a demo user, initiate OAuth, sync, and fetch wearable data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", help="Email address for the new user")
    parser.add_argument("--external-id", help="Your app's user ID to link to this user")
    parser.add_argument("--first-name", default=None, help="User's first name")
    parser.add_argument("--last-name", default=None, help="User's last name")
    parser.add_argument("--api-key", required=True, help="Open Wearables API key")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Base URL of the Open Wearables API")
    parser.add_argument("--provider", default="oura", help="Wearable provider to connect (default: oura)")
    parser.add_argument(
        "--redirect-uri",
        default=None,
        help="Where to redirect after OAuth completes (default: built-in success page)",
    )
    parser.add_argument(
        "--fetch-only",
        metavar="USER_ID",
        default=None,
        help="Skip user creation — just sync and fetch data for this existing user ID",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of historical data to fetch (default: 30)",
    )
    return parser.parse_args()


def create_user(
    client: httpx.Client, api_url: str, email: str, external_id: str, first_name: str | None, last_name: str | None
) -> dict:
    """POST /api/v1/users — create a new user, return the user dict."""
    response = client.post(
        f"{api_url}/api/v1/users",
        json={
            "email": email,
            "external_user_id": external_id,
            "first_name": first_name,
            "last_name": last_name,
        },
    )
    response.raise_for_status()
    return response.json()


def get_authorization_url(
    client: httpx.Client, api_url: str, provider: str, user_id: str, redirect_uri: str | None
) -> str:
    """GET /api/v1/oauth/{provider}/authorize — return the provider OAuth URL."""
    params: dict = {"user_id": user_id}
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    response = client.get(f"{api_url}/api/v1/oauth/{provider}/authorize", params=params)
    response.raise_for_status()
    return response.json()["authorization_url"]


def trigger_sync(client: httpx.Client, api_url: str, provider: str, user_id: str, start: str, end: str) -> dict:
    """POST /api/v1/providers/{provider}/users/{user_id}/sync — trigger a synchronous data sync."""
    response = client.post(
        f"{api_url}/api/v1/providers/{provider}/users/{user_id}/sync",
        params={"start_date": start, "end_date": end, "async": "false"},
    )
    response.raise_for_status()
    return response.json()


def fetch_timeseries(client: httpx.Client, api_url: str, user_id: str, start: str, end: str) -> dict:
    """GET /api/v1/users/{user_id}/timeseries — fetch heart rate and steps."""
    response = client.get(
        f"{api_url}/api/v1/users/{user_id}/timeseries",
        params={"start_time": start, "end_time": end, "types": ["heart_rate", "steps"]},
    )
    response.raise_for_status()
    return response.json()


def fetch_workouts(client: httpx.Client, api_url: str, user_id: str, start: str, end: str) -> dict:
    """GET /api/v1/users/{user_id}/events/workouts — fetch workout sessions."""
    response = client.get(
        f"{api_url}/api/v1/users/{user_id}/events/workouts",
        params={"start_date": start, "end_date": end},
    )
    response.raise_for_status()
    return response.json()


def fetch_sleep(client: httpx.Client, api_url: str, user_id: str, start: str, end: str) -> dict:
    """GET /api/v1/users/{user_id}/events/sleep — fetch sleep sessions."""
    response = client.get(
        f"{api_url}/api/v1/users/{user_id}/events/sleep",
        params={"start_date": start, "end_date": end},
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    args = parse_args()

    headers = {
        "X-Open-Wearables-API-Key": args.api_key,
        "Content-Type": "application/json",
    }

    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=args.days)).isoformat()
    end = now.isoformat()

    with httpx.Client(headers=headers, timeout=120) as client:
        # --- User creation + OAuth (skipped if --fetch-only) ---
        if args.fetch_only:
            user_id = args.fetch_only
            print(f"\nUsing existing user: {user_id}")
        else:
            if not args.email or not args.external_id:
                print("Error: --email and --external-id are required unless using --fetch-only")
                sys.exit(1)

            # Step 1: Create user
            print(f"\nCreating user: {args.email} ...")
            try:
                user = create_user(
                    client, args.api_url, args.email, args.external_id, args.first_name, args.last_name
                )
            except httpx.HTTPStatusError as e:
                print(f"Failed to create user: {e.response.status_code} {e.response.text}")
                sys.exit(1)

            print("User created:")
            print(json.dumps(user, indent=2))
            user_id = user["id"]

            # Step 2: Get OAuth URL
            print(f"\nFetching {args.provider} OAuth URL for user {user_id} ...")
            try:
                auth_url = get_authorization_url(client, args.api_url, args.provider, user_id, args.redirect_uri)
            except httpx.HTTPStatusError as e:
                print(f"Failed to get authorization URL: {e.response.status_code} {e.response.text}")
                sys.exit(1)

            # Step 3: Prompt user to authorize in browser
            print(f"\nOpen this URL in your browser to connect {args.provider}:\n")
            print(f"  {auth_url}\n")
            input("Press Enter after you have authorized in the browser...")

        # --- Sync + Fetch ---

        # Step 4: Trigger sync
        print(f"\nTriggering {args.provider} sync for the last {args.days} days ...")
        try:
            sync_result = trigger_sync(client, args.api_url, args.provider, user_id, start, end)
            print("Sync triggered:")
            print(json.dumps(sync_result, indent=2))
        except httpx.HTTPStatusError as e:
            print(f"Sync failed: {e.response.status_code} {e.response.text}")

        # Step 5: Fetch timeseries
        print(f"\nFetching timeseries (heart_rate, steps) ...")
        try:
            timeseries = fetch_timeseries(client, args.api_url, user_id, start, end)
            print(f"Timeseries ({timeseries.get('total', 0)} records):")
            print(json.dumps(timeseries, indent=2))
        except httpx.HTTPStatusError as e:
            print(f"Timeseries fetch failed: {e.response.status_code} {e.response.text}")

        # Step 6: Fetch workouts
        print(f"\nFetching workouts ...")
        try:
            workouts = fetch_workouts(client, args.api_url, user_id, start, end)
            print(f"Workouts ({workouts.get('total', 0)} records):")
            print(json.dumps(workouts, indent=2))
        except httpx.HTTPStatusError as e:
            print(f"Workouts fetch failed: {e.response.status_code} {e.response.text}")

        # Step 7: Fetch sleep
        print(f"\nFetching sleep sessions ...")
        try:
            sleep = fetch_sleep(client, args.api_url, user_id, start, end)
            print(f"Sleep ({sleep.get('total', 0)} records):")
            print(json.dumps(sleep, indent=2))
        except httpx.HTTPStatusError as e:
            print(f"Sleep fetch failed: {e.response.status_code} {e.response.text}")


if __name__ == "__main__":
    main()
