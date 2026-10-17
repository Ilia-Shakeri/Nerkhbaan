#!/usr/bin/env python3
"""Build the reviewed application feed; public publication needs a separate grant."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("price_feed_source_contract", Path(__file__).resolve().parents[1]/"infra/price-worker/worker.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Source contract unavailable")
_SOURCE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SOURCE)
_time = _SOURCE._time
_get_json = _SOURCE.get_json


def build_partial_feed(metals: object, crypto: object, now: datetime | None = None,
                       silver_provider: str = "gold_api_free_xag", gold: object = None) -> dict:
    if silver_provider != "gold_api_free_xag":
        raise ValueError("Silver provider is not allowed")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    quotes, omitted = [], []
    for provider, value in (("gold_api_free_xag", metals), ("gold_api_free_btc", crypto), ("gold_api_free_xau", gold)):
        try:
            quotes.append(_SOURCE.gold_quote(value, provider, current))
        except (ValueError, TypeError, OverflowError, OSError):
            omitted.append({"instrument_id": _SOURCE.ROUTES[provider][1], "reason": "source_contract_or_freshness_rejected"})
    if not quotes:
        raise ValueError("No validated fresh instrument available; previous feed preserved")
    return {"feed_version": 3, "source": "own-app-market-feed", "audience": "nerkhbaan-own-app", "updated_at": current.isoformat(), "quotes": quotes, "omitted": omitted, "attributions": [dict(_SOURCE.ATTRIBUTION)]}


def build_feed(metals: object, crypto: object, now: datetime | None = None,
               silver_provider: str = "gold_api_free_xag", gold: object = None) -> dict:
    result = build_partial_feed(metals, crypto, now, silver_provider, gold)
    if len(result["quotes"]) != 3:
        raise ValueError("Complete feed requires three approved source observations")
    return result


def main(output: Path) -> None:
    providers = tuple(_SOURCE.ROUTES)
    if not all(_SOURCE.source_allowed(provider, "relay") for provider in providers):
        raise RuntimeError("Public feed publication permission unavailable")
    values = {}
    for provider, route in _SOURCE.ROUTES.items():
        if not _SOURCE.source_allowed(provider, "relay"):
            raise RuntimeError("Public feed publication permission revoked")
        try:
            values[provider] = _get_json(f"https://api.gold-api.com/price/{route[0]}")
        except (OSError, ValueError, TypeError, RuntimeError):
            values[provider] = None
    payload = build_partial_feed(values.get("gold_api_free_xag"), values.get("gold_api_free_btc"), gold=values.get("gold_api_free_xau"))
    if not all(_SOURCE.source_allowed(row["provider_id"], "relay") for row in payload["quotes"]):
        raise RuntimeError("Public feed publication permission revoked")
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))+"\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build-price-feed.py OUTPUT")
    main(Path(sys.argv[1]))
