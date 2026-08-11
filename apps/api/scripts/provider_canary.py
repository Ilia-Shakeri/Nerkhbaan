from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET_KEY", "canary-local-secret-that-is-never-used")
os.environ.setdefault("DEBUG", "false")

from app.pricing.contracts import provider_contract
from app.pricing.instruments import get_instrument
from app.pricing.models import utc_now
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import PROVIDERS
from app.config import settings


async def probe_provider(provider_id: str) -> dict[str, object]:
    provider = PROVIDERS[provider_id]
    contract = provider_contract(provider)
    try:
        ProviderQuoteCollector._validate_destination(provider)
    except ProviderCallFailure as exc:
        return {
            "provider_id": provider_id,
            "status": "blocked",
            "reason": exc.code,
            "tier": contract.tier,
            "owner": contract.owner,
        }
    if not provider.enabled:
        return {
            "provider_id": provider_id,
            "status": "skipped",
            "reason": "provider_disabled",
            "tier": contract.tier,
            "owner": contract.owner,
        }
    if not provider.configured(settings):
        return {
            "provider_id": provider_id,
            "status": "skipped",
            "reason": "not_configured",
            "tier": contract.tier,
            "owner": contract.owner,
        }
    collector = ProviderQuoteCollector()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(
            float(settings.pricing_provider_request_timeout_seconds),
            connect=float(settings.pricing_provider_connect_timeout_seconds),
        ),
        follow_redirects=False,
    ) as client:
        try:
            payload, _content_type, status_code = await collector._request_payload(client, provider)
            instrument = get_instrument(provider.instrument_id)
            build_parser(provider.parser_id).parse(
                payload,
                ParserContext(
                    instrument=instrument,
                    received_at=utc_now(),
                    maximum_timestamp_age_seconds=min(
                        provider.operational_ttl_seconds,
                        instrument.operational_ttl_seconds,
                        instrument.expire_after_seconds,
                    ),
                ),
            )
        except ProviderCallFailure as exc:
            return {
                "provider_id": provider_id,
                "status": "failed",
                "reason": exc.code,
                "tier": contract.tier,
                "owner": contract.owner,
            }
        except ParserError as exc:
            return {
                "provider_id": provider_id,
                "status": "failed",
                "reason": exc.code,
                "tier": contract.tier,
                "owner": contract.owner,
            }
    return {
        "provider_id": provider_id,
        "status": "ok",
        "http_status": status_code,
        "tier": contract.tier,
        "owner": contract.owner,
    }


async def main() -> int:
    requested = sys.argv[1:] or sorted(PROVIDERS)
    rows = []
    for provider_id in requested:
        if provider_id not in PROVIDERS:
            rows.append(
                {
                    "provider_id": provider_id,
                    "status": "failed",
                    "reason": "unknown_provider",
                    "tier": "unknown",
                    "owner": "pricing-ops",
                }
            )
            continue
        rows.append(await probe_provider(provider_id))
    print(json.dumps({"providers": rows}, ensure_ascii=False, separators=(",", ":")))
    return 1 if any(row["status"] == "failed" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
