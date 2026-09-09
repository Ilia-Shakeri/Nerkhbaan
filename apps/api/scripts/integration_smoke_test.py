#!/usr/bin/env python3
"""Lightweight end-to-end smoke test for auth and pricing endpoints.

Usage:
  python backend/scripts/integration_smoke_test.py
  python backend/scripts/integration_smoke_test.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime


def request_json(method: str, url: str, payload: dict | None = None, token: str | None = None) -> dict:
    body = None
    headers = {"Content-Type": "application/json", "X-Client-Type": "desktop"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url=url, data=body, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        raise RuntimeError(f"{method} {url} failed ({exc.code}): {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc


def wait_for_health(base_url: str, timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    health_url = f"{base_url}/api/health/ready"

    while time.time() < deadline:
        try:
            payload = request_json("GET", health_url)
            if payload.get("ready") is True:
                return
        except RuntimeError:
            pass
        time.sleep(1)

    raise RuntimeError(f"Backend did not become healthy within {timeout_seconds}s ({health_url})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run route-level integration smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    nonce = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    username = f"smoke_user_{nonce}"
    email = f"smoke.{nonce}@example.com"
    password = "TestPass123!"
    full_name = "Smoke Test User"

    print(f"[1/10] Waiting for readiness: {base_url}/api/health/ready")
    wait_for_health(base_url)

    print("[2/10] Signing up")
    signup = request_json(
        "POST",
        f"{base_url}/api/auth/signup",
        payload={"username": username, "full_name": full_name, "email": email, "password": password},
    )
    signup_token = signup.get("access_token")
    if not signup_token:
        raise RuntimeError("Signup response missing access_token")

    signup_refresh = signup.get("refresh_token")
    if not signup_refresh:
        raise RuntimeError("Signup response missing refresh_token")

    print("[3/10] Signing in")
    signin = request_json(
        "POST",
        f"{base_url}/api/auth/signin",
        payload={"username_or_email": email, "password": password},
    )
    signin_token = signin.get("access_token")
    if not signin_token:
        raise RuntimeError("Signin response missing access_token")

    signin_refresh = signin.get("refresh_token")
    if not signin_refresh:
        raise RuntimeError("Signin response missing refresh_token")

    print("[4/10] Fetching current user")
    current_user = request_json("GET", f"{base_url}/api/auth/me", token=signin_token)
    if current_user.get("email") != email:
        raise RuntimeError("Current-user response does not match signed-in user")

    print("[5/10] Rotating refresh token")
    refreshed = request_json(
        "POST",
        f"{base_url}/api/auth/refresh",
        payload={"refresh_token": signin_refresh},
    )
    rotated_token = refreshed.get("access_token")
    rotated_refresh = refreshed.get("refresh_token")
    if not rotated_token or not rotated_refresh or rotated_refresh == signin_refresh:
        raise RuntimeError("Refresh response did not rotate both tokens")

    print("[6/10] Creating alert")
    created_alert = request_json(
        "POST",
        f"{base_url}/api/alerts",
        payload={"asset": "gold", "target_price": 1000, "condition": "above"},
        token=rotated_token,
    )
    alert_id = created_alert.get("id")
    if not isinstance(alert_id, int):
        raise RuntimeError("Create-alert response missing numeric id")

    print("[7/10] Listing and editing alert")
    alerts = request_json("GET", f"{base_url}/api/alerts", token=rotated_token)
    if not isinstance(alerts, list) or alert_id not in {row.get("id") for row in alerts}:
        raise RuntimeError("Created alert is missing from list")
    updated_alert = request_json(
        "PATCH",
        f"{base_url}/api/alerts/{alert_id}",
        payload={"target_price": 1100},
        token=rotated_token,
    )
    if updated_alert.get("target_price") != 1100:
        raise RuntimeError("Alert update was not persisted")

    print("[8/10] Fetching public pricing contracts")
    prices = request_json("GET", f"{base_url}/api/prices")
    assets = prices.get("assets")
    if not isinstance(assets, list) or len(assets) < 2:
        raise RuntimeError("Prices response missing assets")

    symbols = {asset.get("asset") for asset in assets if isinstance(asset, dict)}
    missing = {"gold", "silver"} - symbols
    if missing:
        raise RuntimeError(f"Prices response missing assets: {sorted(missing)}")

    instruments = request_json("GET", f"{base_url}/api/instruments")
    if not isinstance(instruments.get("instruments"), list):
        raise RuntimeError("Instruments response missing list")

    providers = request_json("GET", f"{base_url}/api/providers")
    if providers.get("authentication_required_for_details") is not True:
        raise RuntimeError("Anonymous provider response leaked or lost its contract")

    print("[9/10] Fetching authenticated provider contract")
    provider_details = request_json("GET", f"{base_url}/api/providers", token=rotated_token)
    if "_health" not in provider_details:
        raise RuntimeError("Authenticated provider response missing health data")

    print("[10/10] Deleting alert")
    request_json("DELETE", f"{base_url}/api/alerts/{alert_id}", token=rotated_token)
    remaining_alerts = request_json("GET", f"{base_url}/api/alerts", token=rotated_token)
    if alert_id in {row.get("id") for row in remaining_alerts}:
        raise RuntimeError("Deleted alert remained active")

    print("\nSmoke test passed.")
    print(f"- User: {email} / {username}")
    print(f"- Assets: {sorted(symbols)}")
    print(f"- Sources: {prices.get('source')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - explicit CLI failure path
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
