#!/usr/bin/env python3
"""Lightweight end-to-end smoke test for auth and pricing endpoints.

Usage:
  python scripts/integration_smoke_test.py
  python scripts/integration_smoke_test.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    token: str | None = None,
    *,
    expected_status: int | tuple[int, ...] = tuple(range(200, 300)),
) -> dict:
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
            if response.status not in _expected_statuses(expected_status):
                raise RuntimeError(
                    f"{method} {url} returned {response.status}; expected {expected_status}"
                )
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        if exc.code in _expected_statuses(expected_status):
            return json.loads(raw) if raw else {}
        raise RuntimeError(f"{method} {url} failed ({exc.code}): {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc


def _expected_statuses(value: int | tuple[int, ...]) -> tuple[int, ...]:
    return (value,) if isinstance(value, int) else value


def require_error_detail(payload: dict, label: str) -> None:
    if not isinstance(payload.get("detail"), (str, list)):
        raise RuntimeError(f"{label} error response missing detail")


def require_history(payload: dict, asset: str) -> None:
    if payload.get("asset") != asset:
        raise RuntimeError(f"{asset} history response names the wrong asset")
    if not isinstance(payload.get("points"), list):
        raise RuntimeError(f"{asset} history response missing points")
    if payload.get("status") not in {"complete", "partial", "unavailable"}:
        raise RuntimeError(f"{asset} history response has an unknown status")


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

    print(f"[1/14] Waiting for readiness: {base_url}/api/health/ready")
    wait_for_health(base_url)

    print("[2/14] Proving anonymous guards")
    for path in (
        "/api/auth/me",
        "/api/alerts",
        "/api/instruments/BTC_USD/sources/history",
    ):
        denied = request_json("GET", f"{base_url}{path}", expected_status=401)
        require_error_detail(denied, path)

    print("[3/14] Signing up")
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

    duplicate = request_json(
        "POST",
        f"{base_url}/api/auth/signup",
        payload={"username": username, "full_name": full_name, "email": email, "password": password},
        expected_status=409,
    )
    require_error_detail(duplicate, "duplicate signup")

    print("[4/14] Signing in")
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

    print("[5/14] Fetching current user and sessions")
    current_user = request_json("GET", f"{base_url}/api/auth/me", token=signin_token)
    if current_user.get("email") != email:
        raise RuntimeError("Current-user response does not match signed-in user")
    sessions = request_json("GET", f"{base_url}/api/auth/sessions", token=signin_token)
    if not isinstance(sessions, list) or not any(row.get("current") for row in sessions):
        raise RuntimeError("Session list does not mark the active session")

    print("[6/14] Rotating refresh token")
    refreshed = request_json(
        "POST",
        f"{base_url}/api/auth/refresh",
        payload={"refresh_token": signin_refresh},
    )
    rotated_token = refreshed.get("access_token")
    rotated_refresh = refreshed.get("refresh_token")
    if not rotated_token or not rotated_refresh or rotated_refresh == signin_refresh:
        raise RuntimeError("Refresh response did not rotate both tokens")

    print("[7/14] Proving alert validation")
    invalid_alert = request_json(
        "POST",
        f"{base_url}/api/alerts",
        payload={
            "asset": "gold",
            "target_price": 1000,
            "condition": "above",
            "notify_sms": True,
        },
        token=rotated_token,
        expected_status=422,
    )
    require_error_detail(invalid_alert, "invalid alert")

    print("[8/14] Creating alert")
    created_alert = request_json(
        "POST",
        f"{base_url}/api/alerts",
        payload={"asset": "gold", "target_price": 1000, "condition": "above"},
        token=rotated_token,
    )
    alert_id = created_alert.get("id")
    if not isinstance(alert_id, int):
        raise RuntimeError("Create-alert response missing numeric id")

    print("[9/14] Listing and editing alert")
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

    print("[10/14] Fetching public pricing contracts")
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

    print("[11/14] Proving chart and instrument routes")
    for asset in ("gold", "silver", "btc"):
        history = request_json(
            "GET", f"{base_url}/api/prices/{asset}/history?timeframe=30d"
        )
        require_history(history, asset)
    unknown_history = request_json(
        "GET",
        f"{base_url}/api/prices/not-real/history?timeframe=30d",
        expected_status=422,
    )
    require_error_detail(unknown_history, "unknown history asset")
    instrument_history = request_json(
        "GET", f"{base_url}/api/instruments/BTC_USD/history?timeframe=24h"
    )
    if not isinstance(instrument_history.get("points"), list):
        raise RuntimeError("Instrument history response missing points")
    unknown_instrument = request_json(
        "GET", f"{base_url}/api/instruments/NOT_REAL", expected_status=404
    )
    require_error_detail(unknown_instrument, "unknown instrument")

    print("[12/14] Fetching authenticated source and provider contracts")
    source_history = request_json(
        "GET",
        f"{base_url}/api/instruments/BTC_USD/sources/history?timeframe=24h",
        token=rotated_token,
    )
    if not isinstance(source_history, dict):
        raise RuntimeError("Authenticated source history response is not an object")
    provider_details = request_json("GET", f"{base_url}/api/providers", token=rotated_token)
    if "_health" not in provider_details:
        raise RuntimeError("Authenticated provider response missing health data")

    print("[13/14] Deleting alert")
    request_json("DELETE", f"{base_url}/api/alerts/{alert_id}", token=rotated_token)
    remaining_alerts = request_json("GET", f"{base_url}/api/alerts", token=rotated_token)
    if alert_id in {row.get("id") for row in remaining_alerts}:
        raise RuntimeError("Deleted alert remained active")

    print("[14/14] Proving refresh-token reuse revokes the family")
    reuse = request_json(
        "POST",
        f"{base_url}/api/auth/refresh",
        payload={"refresh_token": signin_refresh},
        expected_status=401,
    )
    require_error_detail(reuse, "refresh reuse")
    revoked = request_json(
        "GET",
        f"{base_url}/api/auth/me",
        token=rotated_token,
        expected_status=401,
    )
    require_error_detail(revoked, "revoked access token")

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
