"""Read-only public-provider canary. Never writes prices or prints credentials."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.pricing.instruments import get_instrument
from app.pricing.models import utc_now
from app.pricing.parsers import ParserContext, build_parser
from app.pricing.registry import PROVIDERS

PUBLIC_PROVIDERS = (
    "bitpin_usdt_toman", "bitpin_btc_toman", "wallgold_gold18", "wallgold_silver925",
    "wallex_usdt_toman", "wallex_btc_toman", "nobitex_stats_usdt", "nobitex_stats_btc",
    "nobitex_orderbook_usdt", "nobitex_orderbook_btc", "tetherland_usdt",
)


async def main() -> int:
    payloads: dict[str, object] = {}
    failures = 0
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        for provider_id in PUBLIC_PROVIDERS:
            definition = PROVIDERS[provider_id]
            try:
                if definition.url not in payloads:
                    async with client.stream("GET", definition.url) as response:
                        response.raise_for_status()
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > definition.maximum_payload_bytes:
                                raise ValueError("payload_too_large")
                        payloads[definition.url] = json.loads(body)
                value = build_parser(definition.parser_id).parse(
                    payloads[definition.url],
                    ParserContext(get_instrument(definition.instrument_id), utc_now(),
                                  definition.maximum_source_age_seconds or 300),
                )
                print(json.dumps({"provider": provider_id, "status": "ok", "price": str(value.price),
                                  "observed_at": value.observed_at.isoformat(),
                                  "timestamp_basis": value.metadata.get("timestamp_basis", "parser_contract")}))
            except Exception as exc:
                failures += 1
                print(json.dumps({"provider": provider_id, "status": "failed",
                                  "error_type": type(exc).__name__, "code": getattr(exc, "code", None)}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
