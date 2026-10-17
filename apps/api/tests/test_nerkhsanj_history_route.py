from __future__ import annotations

import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing import rights
from app.pricing.budgets import RedisRequestBudget
from app.pricing.health import PricingHealthService
from app.pricing.models import ProviderRole, RequestPurpose
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import PROVIDERS, instrument_source_coverage, providers_for
from app.pricing.service import InstrumentPricingService


class NerkhsanjHistoryRouteTests(unittest.IsolatedAsyncioTestCase):
    def route(self):
        provider = PROVIDERS.get("nerkhsanj_silver999_history")
        self.assertIsNotNone(provider, "A permitted physical silver archive must be registered")
        return provider

    def test_only_historical_silver_route_is_registered_with_narrow_rights(self):
        provider = self.route()
        self.assertTrue(provider.enabled)
        self.assertTrue(provider.history_only)
        self.assertEqual(provider.instrument_id, "SILVER_999_TOMAN_GRAM")
        self.assertFalse(provider.history_requires_live_quote)
        self.assertEqual(provider.history_url, "https://nerkh.jahankhahan.shop/data/rates.json")
        with patch.object(settings, "pricing_rights_enforced", True), patch.object(settings, "pricing_rights_manifest_path", None):
            for action in ("collect", "store", "display", "history", "own_app_transport"):
                self.assertTrue(rights.provider_allowed(provider.provider_id, action), action)
            for action in ("relay", "external_processing", "derive"):
                self.assertFalse(rights.provider_allowed(provider.provider_id, action), action)
        self.assertNotIn("nerkhsanj_silver925_history", PROVIDERS)
        self.assertNotIn("nerkhsanj_gold24_history", PROVIDERS)

    async def test_history_route_cannot_make_live_requests_or_read_a_cached_quote(self):
        provider = self.route()
        store = AsyncMock()
        collector = ProviderQuoteCollector(store=store)
        result = await collector.quote(provider, RequestPurpose.NORMAL, client=SimpleNamespace())
        self.assertFalse(result.usable)
        self.assertFalse(result.external_called)
        self.assertEqual(result.failure_reason, "history_only")
        store.get_provider_quote.assert_not_awaited()
        with self.assertRaises(ProviderCallFailure) as raised:
            await collector._request_payload(SimpleNamespace(), provider)
        self.assertEqual(raised.exception.code, "history_only")
        with self.assertRaises(ProviderCallFailure) as direct:
            await collector._request_once(SimpleNamespace(), provider, {}, {})
        self.assertEqual(direct.exception.code, "history_only")

    async def test_live_selection_cannot_revive_an_injected_history_cache(self):
        provider = self.route()
        service = InstrumentPricingService(store=AsyncMock())
        result = await service._first_usable([provider], RequestPurpose.NORMAL, SimpleNamespace(),
                                             maximum_external_calls=1, instrument=SimpleNamespace())
        self.assertIsNone(result)
        service.store.get_provider_quote.assert_not_awaited()
        self.assertEqual(await service._rank_verifiers([provider]), [])

    def test_history_route_is_absent_from_live_source_coverage_and_canaries(self):
        provider = self.route()
        for role in ProviderRole:
            self.assertNotIn(provider, providers_for(provider.instrument_id, role))
        row = instrument_source_coverage(settings)[provider.instrument_id]
        self.assertNotIn(provider.provider_id, row["configured"])
        self.assertIn(provider.provider_id, row["registered"])
        self.assertNotIn(provider.provider_id, [row["provider_id"] for row in PricingHealthService().provider_canaries()])

    async def test_family_request_interval_is_atomic_and_cannot_be_lowered_by_route_override(self):
        provider = self.route()
        store = AsyncMock()
        store.client = lambda: redis
        redis = AsyncMock()
        redis.ttl.return_value = 0
        redis.eval.return_value = [1, 0, 0]
        budget = RedisRequestBudget(store)
        lowered = replace(provider, budget=replace(provider.budget, minimum_interval_seconds=1))
        self.assertTrue((await budget.consume(lowered, RequestPurpose.BACKFILL)).allowed)
        args = redis.eval.await_args.args
        count = args[1]
        keys, values = args[2:2 + count], args[2 + count:]
        key = "pricing:budget:family:nerkhsanj:minimum_interval"
        self.assertIn(key, keys)
        index = keys.index(key)
        self.assertEqual(values[index * 2:index * 2 + 2], (1, 60))
        self.assertIn("redis.call('get'", args[0])
        self.assertIn("redis.call('incr'", args[0])


if __name__ == "__main__":
    unittest.main()
