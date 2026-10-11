from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")
os.environ["DEBUG"] = "false"

import httpx

from app.pricing.instruments import get_instrument
from app.pricing.models import utc_now
from app.pricing.parsers.base import ParsedProviderValue
from app.pricing.registry import PROVIDERS
from scripts.probe_provider_coverage import (
    bounded_history, independence_proof, run, safe_error, value_proof,
)


def value(instrument_id: str, age: int = 0):
    instrument = get_instrument(instrument_id)
    provider = next(p for p in PROVIDERS.values() if p.instrument_id == instrument_id)
    received = utc_now()
    parsed = ParsedProviderValue(
        price=instrument.minimum_price * 2,
        currency=instrument.quote_currency, weight_unit=instrument.weight_unit,
        purity=instrument.purity, observed_at=received - timedelta(seconds=age),
    )
    return provider, instrument, parsed, received


class ProviderCoverageProofTests(unittest.TestCase):
    def test_transport_receipt_never_serializes_exception_message(self):
        secret = "test-secret-never-in-result"
        exc = httpx.ConnectError("https://example.invalid?api_key=" + secret)
        row = safe_error(exc)
        self.assertEqual(row["error_types"], ["ConnectError"])
        self.assertNotIn(secret, json.dumps(row))

    def test_receive_time_is_explicit_not_exchange_timestamp(self):
        provider, instrument, parsed, received = value("GOLD_18K_TOMAN_GRAM")
        row = value_proof(provider, instrument, parsed, received)
        self.assertEqual(row["timestamp_basis"], "receive_time_no_distinct_source_timestamp")
        self.assertEqual(row["currency"], "TOMAN")
        self.assertEqual(row["weight_unit"], "gram")
        self.assertEqual(row["purity"], "0.750")
        self.assertNotIn("price", row)

    def test_parse_success_does_not_mean_live_at_receive(self):
        provider, instrument, parsed, received = value("BTC_TOMAN", age=40)
        provider = replace(provider, maximum_source_age_seconds=60)
        self.assertFalse(value_proof(provider, instrument, parsed, received)["live_at_receive"])

    def test_same_family_routes_cannot_independently_corroborate(self):
        provider, instrument, parsed, received = value("USDT_TOMAN")
        other = replace(provider, provider_id="other_route", venue="another_venue")
        proof = value_proof(provider, instrument, parsed, received)
        rows = independence_proof([(provider, instrument, parsed, proof),
                                   (other, instrument, parsed, proof)])
        self.assertFalse(rows[0]["independent_family_and_venue"])
        self.assertFalse(rows[0]["eligible_to_corroborate"])

    def test_distinct_sources_need_overlapping_live_windows(self):
        provider, instrument, parsed, received = value("USDT_TOMAN")
        other = replace(provider, provider_id="other", source_family="other", venue="other")
        later = replace(parsed, observed_at=received + timedelta(seconds=21))
        left = value_proof(provider, instrument, parsed, received)
        right = value_proof(other, instrument, later, later.observed_at)
        row = independence_proof([(provider, instrument, parsed, left),
                                  (other, instrument, later, right)])[0]
        self.assertTrue(row["independent_family_and_venue"])
        self.assertFalse(row["live_windows_overlap"])
        self.assertFalse(row["eligible_to_corroborate"])


class ProviderCoverageNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_network_gate_and_effective_disabled_policy(self):
        provider = replace(PROVIDERS["wallgold_gold18"], enabled=False)
        instrument = get_instrument(provider.instrument_id)
        with patch("scripts.probe_provider_coverage.INSTRUMENTS", {provider.instrument_id: instrument}), \
             patch("scripts.probe_provider_coverage.operational_pricing_settings.instrument", AsyncMock(return_value=instrument)), \
             patch("scripts.probe_provider_coverage.operational_pricing_settings.providers_for", AsyncMock(return_value=(provider,))), \
             patch("scripts.probe_provider_coverage.ProviderQuoteCollector._request_payload", AsyncMock()) as request:
            result = await run(execute_network=True)
        request.assert_not_called()
        self.assertEqual(result["providers"][0]["reason"], "disabled_by_effective_policy")
        self.assertFalse(result["redis_or_database_writes"])
        self.assertFalse(result["rights_confirmed_by_probe"])

    async def test_aggregate_route_has_single_request_and_common_receive_time(self):
        first = PROVIDERS["nobitex_stats_usdt"]
        second = PROVIDERS["nobitex_stats_btc"]
        payload = {"stats": {"usdt-rls": {"latest": "1000000"},
                             "btc-rls": {"latest": "500000000000"}}}
        async def instrument(iid):
            return get_instrument(iid)
        async def providers(iid):
            return (first,) if iid == first.instrument_id else (second,)
        with patch("scripts.probe_provider_coverage.INSTRUMENTS", {first.instrument_id: None, second.instrument_id: None}), \
             patch("scripts.probe_provider_coverage.operational_pricing_settings.instrument", instrument), \
             patch("scripts.probe_provider_coverage.operational_pricing_settings.providers_for", providers), \
             patch("scripts.probe_provider_coverage.ProviderQuoteCollector._request_payload", AsyncMock(return_value=(payload, "application/json", 200))) as request:
            result = await run(execute_network=True)
        self.assertEqual(request.await_count, 1)
        self.assertEqual(result["summary"]["ok"], 2)
        times = {row["value_proof"]["received_at"] for row in result["providers"]}
        self.assertEqual(len(times), 1)

    async def test_history_http_failure_is_sanitized_and_not_a_pass(self):
        provider = PROVIDERS["nobitex_stats_btc"]
        transport = httpx.MockTransport(lambda _request: httpx.Response(503, text="private upstream error"))
        async with httpx.AsyncClient(transport=transport) as client:
            row = await bounded_history(client, provider, get_instrument(provider.instrument_id))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["http_status"], 503)
        self.assertNotIn("private upstream error", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
