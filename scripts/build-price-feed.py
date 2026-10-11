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
MAX_QUOTE_AGE_SECONDS = 600


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
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed > now + timedelta(minutes=5) or now - parsed > maximum_age:
        raise ValueError(f"{label} is outside the safe time window")
    return parsed


def _silver_quote(metals: object, current: datetime, silver_provider: str) -> dict:
    if not isinstance(metals, dict):
        raise ValueError("Silver source contract changed")
    if silver_provider == "gold_api_free_xag":
        if metals.get("symbol") != "XAG":
            raise ValueError("Silver source contract changed")
        if metals.get("currency") != "USD":
            raise ValueError("Silver source currency changed")
        silver_time = _time(
            metals.get("updatedAt"), "Silver timestamp", current, timedelta(seconds=MAX_QUOTE_AGE_SECONDS)
        )
        silver = _decimal(metals.get("price"), "Silver price", "5", "500")
    elif silver_provider == "xaus_xag":
        state = metals.get("data_state")
        if not isinstance(state, dict) or state.get("status") != "fresh":
            raise ValueError("XAUS silver source is not fresh")
        silver_time = _time(
            state.get("as_of") or metals.get("price_as_of"),
            "Silver timestamp",
            current,
            timedelta(seconds=MAX_QUOTE_AGE_SECONDS),
        )
        silver = _decimal(metals.get("silver_usd_oz"), "Silver price", "5", "500")
    else:
        raise ValueError("Silver provider is not allowed")

    return {
        "instrument_id": "XAG_USD_OZ", "provider_id": silver_provider,
        "price": str(silver), "observed_at": silver_time.isoformat(), "historical": False,
    }


def _crypto_quote(crypto: object, current: datetime, asset: str, provider: str,
                  instrument: str, low: str, high: str) -> dict:
    if not isinstance(crypto, dict):
        raise ValueError("Crypto source contract changed")
    row = crypto.get(asset)
    if not isinstance(row, dict):
        raise ValueError(f"Crypto source omitted {asset}")
    observed = datetime.fromtimestamp(int(row.get("last_updated_at", 0)), UTC)
    if observed > current + timedelta(minutes=5) or current - observed > timedelta(seconds=MAX_QUOTE_AGE_SECONDS):
        raise ValueError(f"Crypto timestamp for {asset} is stale")
    price = _decimal(row.get("usd"), f"{asset} price", low, high)
    return {
        "instrument_id": instrument, "provider_id": provider, "price": str(price),
        "observed_at": observed.isoformat(), "historical": False,
    }


_CRYPTO_ROUTES = (
    ("bitcoin", "coingecko_btc", "BTC_USD", "1000", "1000000"),
    ("tether", "coingecko_usdt", "USDT_USD", "0.8", "1.2"),
)


def build_feed(metals: object, crypto: object, now: datetime | None = None,
               silver_provider: str = "gold_api_free_xag") -> dict:
    """The legacy version-one contract still requires all three instruments."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    quotes = [_silver_quote(metals, current, silver_provider)]
    for route in _CRYPTO_ROUTES:
        quotes.append(_crypto_quote(crypto, current, *route))
    return {"feed_version": 1, "source": "public-market-relay",
            "updated_at": current.isoformat(), "quotes": quotes}


def _gold_quote(gold: object, current: datetime) -> dict:
    if not isinstance(gold, dict) or gold.get("symbol") != "XAU" or gold.get("currency") != "USD":
        raise ValueError("Gold source symbol or USD contract changed")
    observed = _time(gold.get("updatedAt"), "Gold timestamp", current,
                     timedelta(seconds=MAX_QUOTE_AGE_SECONDS))
    price = _decimal(gold.get("price"), "Gold price", "500", "10000")
    return {"instrument_id": "XAU_USD_OZ", "provider_id": "gold_api_free_xau",
            "price": str(price), "observed_at": observed.isoformat(), "historical": False}


def build_partial_feed(metals: object, crypto: object, now: datetime | None = None,
                       silver_provider: str = "gold_api_free_xag", gold: object = None) -> dict:
    """Each failed instrument is omitted; healthy observations keep their source time."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    quotes = []
    omitted = []
    try:
        quotes.append(_silver_quote(metals, current, silver_provider))
    except (TypeError, ValueError, OverflowError, OSError):
        omitted.append({"instrument_id": "XAG_USD_OZ", "reason": "source_contract_or_freshness_rejected"})
    for route in _CRYPTO_ROUTES:
        try:
            quotes.append(_crypto_quote(crypto, current, *route))
        except (TypeError, ValueError, OverflowError, OSError):
            omitted.append({"instrument_id": route[2], "reason": "source_contract_or_freshness_rejected"})
    try:
        quotes.append(_gold_quote(gold, current))
    except (TypeError, ValueError, OverflowError, OSError):
        omitted.append({"instrument_id": "XAU_USD_OZ", "reason": "source_contract_or_freshness_rejected"})
    if not quotes:
        raise ValueError("No validated fresh instrument available; previous feed preserved")
    return {"feed_version": 2, "source": "public-market-relay",
            "updated_at": current.isoformat(), "quotes": quotes, "omitted": omitted}


def main(output: Path) -> None:
    silver_provider = "gold_api_free_xag"
    metals = None
    try:
        metals = _get_json("https://api.gold-api.com/price/XAG")
    except Exception:
        try:
            metals = _get_json("https://xaus.com/api/v1/spot?compact=1")
            silver_provider = "xaus_xag"
        except Exception:
            pass
    try:
        crypto = _get_json(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,tether&vs_currencies=usd&include_last_updated_at=true"
        )
    except Exception:
        crypto = None
    try:
        gold = _get_json("https://api.gold-api.com/price/XAU")
    except Exception:
        gold = None
    payload = build_partial_feed(metals, crypto, silver_provider=silver_provider, gold=gold)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build-price-feed.py OUTPUT")
    main(Path(sys.argv[1]))
