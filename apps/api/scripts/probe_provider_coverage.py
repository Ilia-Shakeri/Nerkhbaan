"""Read-only coverage proof using effective policies and production parsers.

No prices, budgets, runtime states or policies are written. Output contains no
raw payload, URLs, credentials or price values. Network probes may use provider
quota; callers explicitly select --execute-network for one bounded call per
enabled, configured route. This proof does not establish redistribution rights.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.pricing.backfill import _history_request_options
from app.pricing.contracts import provider_contract
from app.pricing.freshness import FreshnessPolicy, freshness_boundaries
from app.pricing.instruments import INSTRUMENTS
from app.pricing.models import InstrumentDefinition, utc_now
from app.pricing.operational import operational_pricing_settings
from app.pricing.parsers import ParserContext, build_parser
from app.pricing.parsers.history import build_history_parser
from app.pricing.providers import ProviderQuoteCollector
from app.pricing.registry import ProviderDefinition


def safe_error(exc: Exception) -> dict[str, object]:
    """Names/codes only: request exceptions can contain credentials in URLs."""
    causes = []
    current: BaseException | None = exc
    while current is not None and len(causes) < 6:
        causes.append(type(current).__name__)
        current = current.__cause__
    return {
        "reason": getattr(exc, "code", "request_or_parse_failed"),
        "error_types": causes,
        "http_status": getattr(exc, "http_status", None),
    }


def value_proof(provider: ProviderDefinition, instrument: InstrumentDefinition,
                parsed, received_at: datetime) -> dict[str, object]:
    maximum_age = min(provider.maximum_source_age_seconds or provider.operational_ttl_seconds,
                      instrument.expire_after_seconds)
    boundaries = freshness_boundaries(parsed.observed_at, received_at, FreshnessPolicy(
        maximum_source_age_seconds=maximum_age,
        provider_live_ttl_seconds=provider.operational_ttl_seconds,
        instrument_operational_ttl_seconds=instrument.operational_ttl_seconds,
        instrument_stale_after_seconds=instrument.stale_after_seconds,
        instrument_expire_after_seconds=instrument.expire_after_seconds,
        anchor_live_window_at_receive_time=provider.anchor_live_window_at_receive_time,
    ))
    return {
        "observed_at": parsed.observed_at.isoformat(),
        "received_at": received_at.isoformat(),
        "source_age_seconds": round((received_at - parsed.observed_at).total_seconds(), 3),
        "timestamp_basis": parsed.metadata.get("timestamp_basis") or (
            "receive_time_no_distinct_source_timestamp"
            if parsed.observed_at == received_at else "provider_timestamp"),
        "currency": parsed.currency.value,
        "weight_unit": parsed.weight_unit.value,
        "purity": str(parsed.purity) if parsed.purity is not None else None,
        "normalization": parsed.metadata.get("normalization", "parser_explicit_contract"),
        "live_eligible_until": boundaries.live_eligible_until.isoformat(),
        "live_at_receive": boundaries.status_at(received_at).value == "live",
    }


def independence_proof(parsed_rows: list[tuple[ProviderDefinition, InstrumentDefinition, object,
                                                dict[str, object]]]) -> list[dict[str, object]]:
    result = []
    for index, (left, instrument, left_value, left_proof) in enumerate(parsed_rows):
        for right, _, right_value, right_proof in parsed_rows[index + 1:]:
            if left.instrument_id != right.instrument_id:
                continue
            independent = left.source_family != right.source_family and left.venue != right.venue
            # A quote that expired while another source was fetched cannot corroborate it.
            overlapping = max(
                datetime.fromisoformat(str(left_proof["received_at"])),
                datetime.fromisoformat(str(right_proof["received_at"])),
            ) <= min(
                datetime.fromisoformat(str(left_proof["live_eligible_until"])),
                datetime.fromisoformat(str(right_proof["live_eligible_until"])),
            )
            deviation = abs(left_value.price - right_value.price) / right_value.price * Decimal(100)
            result.append({
                "instrument_id": left.instrument_id,
                "providers": [left.provider_id, right.provider_id],
                "independent_family_and_venue": independent,
                "live_windows_overlap": overlapping,
                "deviation_percent": str(deviation.quantize(Decimal("0.0001"))),
                "within_base_anomaly_threshold": deviation <= instrument.base_anomaly_threshold_percent,
                "eligible_to_corroborate": independent and overlapping
                    and bool(left_proof["live_at_receive"]) and bool(right_proof["live_at_receive"]),
                "scope": "read_only_pair_comparison_not_persisted_consensus",
            })
    return result


async def bounded_history(client: httpx.AsyncClient, provider: ProviderDefinition,
                          instrument: InstrumentDefinition) -> dict[str, object]:
    if not provider.history_url or not provider.history_parser_id:
        return {"status": "unsupported", "reason": "no_explicit_history_route"}
    range_end = utc_now()
    range_start = range_end - timedelta(hours=24)
    try:
        parser = build_history_parser(provider.history_parser_id)
        params, headers = _history_request_options(provider, parser, range_start, range_end)
        async with client.stream("GET", provider.history_url, params=params, headers=headers) as response:
            status = response.status_code
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > min(provider.maximum_payload_bytes * 4, 4_194_304):
                    raise ValueError("history_payload_too_large")
            points = parser.parse(json.loads(body), instrument, range_start, range_end)
        return {"status": "ok" if points else "empty", "http_status": status,
                "point_count": len(points), "range_start": range_start.isoformat(),
                "range_end": range_end.isoformat(),
                "first_observed_at": points[0].observed_at.isoformat() if points else None,
                "last_observed_at": points[-1].observed_at.isoformat() if points else None,
                "parser_version": parser.parser_version}
    except Exception as exc:
        result = {"status": "failed", **safe_error(exc)}
        if isinstance(exc, httpx.HTTPStatusError):
            result["http_status"] = exc.response.status_code
        return result


async def run(*, execute_network: bool = False, history: bool = False) -> dict[str, object]:
    started = utc_now()
    result: dict[str, object] = {"checked_at": started.isoformat(), "read_only": True,
                               "network_requested": execute_network,
                               "redis_or_database_writes": False,
                               "rights_confirmed_by_probe": False, "providers": []}
    rows: list[dict[str, object]] = []
    parsed_rows = []
    # Aggregate routes are downloaded once with a common receive time.
    payloads: dict[tuple[str, str | None, str], tuple[object, str | None, int, datetime]] = {}
    collector = ProviderQuoteCollector()
    retries_before = settings.pricing_provider_max_retries
    settings.pricing_provider_max_retries = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0),
                                     follow_redirects=False, trust_env=False) as client:
            for iid in INSTRUMENTS:
                instrument = await operational_pricing_settings.instrument(iid)
                for provider in await operational_pricing_settings.providers_for(iid):
                    contract = provider_contract(provider)
                    row: dict[str, object] = {
                        "provider_id": provider.provider_id, "instrument_id": iid,
                        "enabled": provider.enabled,
                        "configured": None if provider.history_only else provider.configured(settings),
                        "history_only": provider.history_only,
                        "instrument_enabled": instrument.enabled, "role": provider.role.value,
                        "source_family": provider.source_family, "venue": provider.venue,
                        "history_supported": bool(provider.history_url and provider.history_parser_id),
                        "commercial_status": contract.commercial_status,
                        "redistribution_status": contract.redistribution_status,
                        "official_docs": list(contract.docs), "route_host": urlsplit(provider.url).hostname,
                    }
                    rows.append(row)
                    if provider.history_only:
                        row.update(status="skipped", reason="history_only")
                        continue
                    if not instrument.enabled or not provider.enabled:
                        row.update(status="skipped", reason="disabled_by_effective_policy")
                        continue
                    if not row["configured"]:
                        row.update(status="skipped", reason="missing_required_configuration")
                        continue
                    if not execute_network:
                        row.update(status="pending", reason="network_probe_not_requested")
                        continue
                    request_started = time.monotonic()
                    try:
                        # Include credential placement in cache identity, without serializing any key.
                        identity = (provider.url, provider.api_key_setting, provider.credential_placement)
                        if identity not in payloads:
                            async with asyncio.timeout(12):
                                payload, content_type, status = await collector._request_payload(client, provider)
                            payloads[identity] = (payload, content_type, status, utc_now())
                        payload, content_type, status, received_at = payloads[identity]
                        parsed = build_parser(provider.parser_id).parse(payload, ParserContext(
                            instrument=instrument, received_at=received_at,
                            maximum_timestamp_age_seconds=min(provider.maximum_source_age_seconds
                                or provider.operational_ttl_seconds, instrument.expire_after_seconds),
                        ))
                        proof = value_proof(provider, instrument, parsed, received_at)
                        row.update(status="ok", http_status=status, content_type=content_type,
                                   latency_ms=round((time.monotonic() - request_started) * 1000),
                                   parser_version=build_parser(provider.parser_id).parser_version,
                                   value_proof=proof)
                        parsed_rows.append((provider, instrument, parsed, proof))
                    except Exception as exc:
                        row.update(status="failed", **safe_error(exc))
                    if history:
                        row["history_probe"] = await bounded_history(client, provider, instrument)
    finally:
        settings.pricing_provider_max_retries = retries_before
    result["providers"] = rows
    result["independent_comparisons"] = independence_proof(parsed_rows)
    result["finished_at"] = utc_now().isoformat()
    result["summary"] = {status: sum(row["status"] == status for row in rows)
                         for status in ("ok", "failed", "skipped", "pending")}
    result["all_enabled_configured_routes_passed"] = execute_network and bool(parsed_rows) and not any(
        row["status"] == "failed" for row in rows)
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.history and not args.execute_network:
        parser.error("--history requires --execute-network")
    result = await run(execute_network=args.execute_network, history=args.history)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return int(bool(args.execute_network) and not result["all_enabled_configured_routes_passed"])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
