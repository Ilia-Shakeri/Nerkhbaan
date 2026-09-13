#!/usr/bin/env python3
"""Build the small public market feed consumed by the Iran deployment."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import Request, urlopen

TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 1_000_000
USER_AGENT = "Nerkhbaan-Public-Price-Feed/1"


def _get_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected source status {response.status}")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Source response is too large")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Source response is too large")
        return json.loads(payload.decode("utf-8"))


def _decimal(value: object, label: str, minimum: str, maximum: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric") from exc
    if not number.is_finite() or not Decimal(minimum) <= number <= Decimal(maximum):
        raise ValueError(f"{label} is outside the safe range")
    return number


def _time(value: object, label: str, now: datetime, maximum_age: timedelta) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    if parsed > now + timedelta(minutes=5) or now - parsed > maximum_age:
        raise ValueError(f"{label} is outside the safe time window")
    return parsed


def build_feed(metals: object, crypto: object, now: datetime | None = None) -> dict:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if not isinstance(metals, dict) or metals.get("symbol") != "XAG":
        raise ValueError("Silver source contract changed")
    if metals.get("currency") != "USD":
        raise ValueError("Silver source currency changed")
    silver_time = _time(
        metals.get("updatedAt"), "Silver timestamp", current, timedelta(minutes=15)
    )
    silver = _decimal(metals.get("price"), "Silver price", "5", "500")

    if not isinstance(crypto, dict):
        raise ValueError("Crypto source contract changed")
    quotes = [
        {
            "instrument_id": "XAG_USD_OZ",
            "provider_id": "gold_api_free_xag",
            "price": str(silver),
            "observed_at": silver_time.isoformat(),
            "historical": False,
        }
    ]
    for asset, provider, instrument, low, high in (
        ("bitcoin", "coingecko_btc", "BTC_USD", "1000", "1000000"),
        ("tether", "coingecko_usdt", "USDT_USD", "0.8", "1.2"),
    ):
        row = crypto.get(asset)
        if not isinstance(row, dict):
            raise ValueError(f"Crypto source omitted {asset}")
        observed = datetime.fromtimestamp(int(row.get("last_updated_at", 0)), UTC)
        if observed > current + timedelta(minutes=5) or current - observed > timedelta(minutes=15):
            raise ValueError(f"Crypto timestamp for {asset} is stale")
        price = _decimal(row.get("usd"), f"{asset} price", low, high)
        quotes.append(
            {
                "instrument_id": instrument,
                "provider_id": provider,
                "price": str(price),
                "observed_at": observed.isoformat(),
                "historical": False,
            }
        )
    return {
        "feed_version": 1,
        "source": "public-market-relay",
        "updated_at": current.isoformat(),
        "quotes": quotes,
    }


def main(output: Path) -> None:
    metals = _get_json("https://api.gold-api.com/price/XAG")
    crypto = _get_json(
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin,tether&vs_currencies=usd&include_last_updated_at=true"
    )
    payload = build_feed(metals, crypto)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build-price-feed.py OUTPUT")
    main(Path(sys.argv[1]))
