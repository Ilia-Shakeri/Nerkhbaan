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
from datetime import datetime


def request_json(method: str, url: str, payload: dict | None = None, token: str | None = None) -> dict:
    body = None
    headers = {"Content-Type": "application/json"}

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
    health_url = f"{base_url}/health"

    while time.time() < deadline:
        try:
            payload = request_json("GET", health_url)
            if payload.get("status") == "ok":
                return
        except RuntimeError:
            pass
        time.sleep(1)

    raise RuntimeError(f"Backend did not become healthy within {timeout_seconds}s ({health_url})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run auth+prices smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    nonce = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    email = f"smoke.{nonce}@example.com"
    password = "TestPass123!"
    full_name = "Smoke Test User"

    print(f"[1/4] Waiting for health: {base_url}/health")
    wait_for_health(base_url)

    print("[2/4] Signing up")
    signup = request_json(
        "POST",
        f"{base_url}/api/auth/signup",
        payload={"full_name": full_name, "email": email, "password": password},
    )
    signup_token = signup.get("access_token")
    if not signup_token:
        raise RuntimeError("Signup response missing access_token")

    print("[3/4] Signing in")
    signin = request_json(
        "POST",
        f"{base_url}/api/auth/signin",
        payload={"email": email, "password": password},
    )
    signin_token = signin.get("access_token")
    if not signin_token:
        raise RuntimeError("Signin response missing access_token")

    print("[4/4] Fetching /api/prices")
    prices = request_json("GET", f"{base_url}/api/prices")
    assets = prices.get("assets")
    if not isinstance(assets, list) or len(assets) < 2:
        raise RuntimeError("Prices response missing assets")

    symbols = {asset.get("asset") for asset in assets if isinstance(asset, dict)}
    missing = {"gold", "silver"} - symbols
    if missing:
        raise RuntimeError(f"Prices response missing assets: {sorted(missing)}")

    print("\nSmoke test passed.")
    print(f"- User: {email}")
    print(f"- Assets: {sorted(symbols)}")
    print(f"- Sources: {prices.get('source')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - explicit CLI failure path
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
