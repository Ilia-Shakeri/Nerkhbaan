#!/usr/bin/env python3
"""Fetch free crypto prices outside Iran and send authenticated updates home."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = os.environ["NERKHBAAN_WORKER_ENDPOINT"].rstrip("/")
SECRET = os.environ["NERKHBAAN_WORKER_SECRET"]
STATE_FILE = Path(os.environ.get("NERKHBAAN_WORKER_STATE_FILE", "/var/lib/nerkhbaan-price-worker/history-complete"))
TIMEOUT = 20
ASSETS = (("bitcoin", "coingecko_btc", "BTC_USD"), ("tether", "coingecko_usdt", "USDT_USD"))


def get_json(url: str) -> object:
    with urlopen(Request(url, headers={"User-Agent": "Nerkhbaan-Price-Worker/1"}), timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def send(quotes: list[dict[str, object]]) -> None:
    body = json.dumps({"quotes": quotes}, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    request = Request(
        f"{ENDPOINT}/ingest",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Pricing-Worker-Timestamp": timestamp,
            "X-Pricing-Worker-Signature": signature,
        },
        method="POST",
    )
    with urlopen(request, timeout=TIMEOUT) as response:
        if response.status != 202:
            raise RuntimeError(f"Unexpected ingest status {response.status}")


def backfill() -> None:
    if STATE_FILE.exists():
        return
    for asset_id, provider_id, instrument_id in ASSETS:
        query = urlencode({"vs_currency": "usd", "days": "365", "interval": "daily"})
        payload = get_json(f"https://api.coingecko.com/api/v3/coins/{asset_id}/market_chart?{query}")
        prices = payload.get("prices", []) if isinstance(payload, dict) else []
        quotes = [
            {
                "instrument_id": instrument_id,
                "provider_id": provider_id,
                "price": str(price),
                "observed_at": datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(),
                "historical": True,
            }
            for timestamp, price in prices
        ]
        for offset in range(0, len(quotes), 300):
            send(quotes[offset : offset + 300])
    STATE_FILE.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    STATE_FILE.touch(mode=0o640)


def live() -> None:
    payload = get_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether&vs_currencies=usd")
    if not isinstance(payload, dict):
        raise RuntimeError("CoinGecko returned an invalid live payload")
    observed_at = datetime.now(UTC).isoformat()
    quotes = []
    for asset_id, provider_id, instrument_id in ASSETS:
        price = payload.get(asset_id, {}).get("usd")
        if price is None:
            raise RuntimeError(f"CoinGecko omitted {asset_id}")
        quotes.append({"instrument_id": instrument_id, "provider_id": provider_id, "price": str(price), "observed_at": observed_at, "historical": False})
    send(quotes)


if __name__ == "__main__":
    if len(SECRET) < 32:
        raise RuntimeError("NERKHBAAN_WORKER_SECRET must be at least 32 characters")
    backfill()
    live()
