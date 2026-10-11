#!/usr/bin/env python3
"""Fetch free crypto prices outside Iran and send authenticated updates home."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = os.environ.get("NERKHBAAN_WORKER_ENDPOINT", "").rstrip("/")
SECRET = os.environ.get("NERKHBAAN_WORKER_SECRET", "")
STATE_FILE = Path(os.environ.get("NERKHBAAN_WORKER_STATE_FILE", "/var/lib/nerkhbaan-price-worker/history-complete"))
TIMEOUT = 20
MAX_RESPONSE_BYTES = 2_000_000
ASSETS = (("bitcoin", "coingecko_btc", "BTC_USD"), ("tether", "coingecko_usdt", "USDT_USD"))
MAX_LIVE_AGE_SECONDS = 600
logger = logging.getLogger("price_worker")


def get_json(url: str) -> object:
    with urlopen(Request(url, headers={"User-Agent": "Nerkhbaan-Price-Worker/1"}), timeout=TIMEOUT) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Source payload exceeds the size limit")
        return json.loads(body.decode("utf-8"))


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
        result = json.loads(response.read(4096).decode("utf-8"))
        if not isinstance(result, dict) or result.get("accepted") != len(quotes):
            raise RuntimeError("Core did not acknowledge every submitted quote")
        historical_count = sum(bool(quote.get("historical")) for quote in quotes)
        if historical_count and result.get("history_persisted") != historical_count:
            raise RuntimeError("Core did not persist every historical quote; retry progress retained")


def backfill() -> None:
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except (ValueError, OSError):
        state = {}
    state = {key: value for key, value in state.items() if isinstance(value, dict)}
    failed = False
    for asset_id, provider_id, instrument_id in ASSETS:
        if state.get(asset_id, {}).get("complete"):
            continue
        try:
            query = urlencode({"vs_currency": "usd", "days": "365", "interval": "daily"})
            payload = get_json(f"https://api.coingecko.com/api/v3/coins/{asset_id}/market_chart?{query}")
            prices = payload.get("prices", []) if isinstance(payload, dict) else []
            if not prices:
                raise RuntimeError("Historical feed is empty")
            watermark = int(state.get(asset_id, {}).get("last_timestamp", 0))
            quotes = [
                {
                    "instrument_id": instrument_id,
                    "provider_id": provider_id,
                    "price": str(price),
                    "observed_at": datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(),
                    "historical": True,
                }
                for timestamp, price in sorted(prices)
                if timestamp > watermark
            ]
            # One bounded chunk per asset leaves the next timer run free for live prices.
            batch = quotes[:300]
            if batch:
                send(batch)
                watermark = int(datetime.fromisoformat(str(batch[-1]["observed_at"])).timestamp() * 1000)
            state[asset_id] = {"last_timestamp": watermark, "complete": len(quotes) <= 300}
            STATE_FILE.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            temporary = STATE_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.chmod(0o640)
            temporary.replace(STATE_FILE)
        except Exception:
            logger.error("Historical refresh failed for %s; progress retained", instrument_id)
            failed = True
    if failed:
        raise RuntimeError("One or more historical refreshes failed")


def live() -> None:
    payload = get_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,tether&vs_currencies=usd&include_last_updated_at=true")
    if not isinstance(payload, dict):
        raise RuntimeError("CoinGecko returned an invalid live payload")
    quotes = []
    failed = False
    for asset_id, provider_id, instrument_id in ASSETS:
        data = payload.get(asset_id, {})
        price = data.get("usd") if isinstance(data, dict) else None
        timestamp = data.get("last_updated_at") if isinstance(data, dict) else None
        try:
            number = Decimal(str(price))
            price_valid = number.is_finite() and number > 0
        except InvalidOperation:
            price_valid = False
        if not price_valid or not isinstance(timestamp, (int, float)) or not 0 <= time.time() - timestamp <= MAX_LIVE_AGE_SECONDS:
            logger.error("Live refresh rejected missing or stale data for %s", instrument_id)
            failed = True
            continue
        observed_at = datetime.fromtimestamp(timestamp, UTC).isoformat()
        quotes.append({"instrument_id": instrument_id, "provider_id": provider_id, "price": str(price), "observed_at": observed_at, "historical": False})
    if quotes:
        send(quotes)
    if failed or not quotes:
        raise RuntimeError("One or more live prices are unavailable")


def run() -> None:
    failed = False
    for name, operation in (("live", live), ("backfill", backfill)):
        try:
            operation()
        except Exception:
            logger.error("%s operation failed; other work remains independent", name)
            failed = True
    if failed:
        raise RuntimeError("Price worker has incomplete work; next timer run retries")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not ENDPOINT.startswith("https://") or len(SECRET) < 32:
        raise RuntimeError("NERKHBAAN_WORKER_SECRET must be at least 32 characters")
    run()
