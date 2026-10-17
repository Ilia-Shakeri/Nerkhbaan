from __future__ import annotations

import math
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.budgets import BudgetDecision, RedisRequestBudget
from app.pricing.instruments import get_instrument
from app.pricing.models import ProviderRuntimeState, RequestPurpose
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import PROVIDERS
from app.pricing.source_snapshots import SourceSnapshotUnavailable
from tests.test_source_snapshots import _Redis


class _ClockedRedis:
    def __init__(self):
        self.now = 0.0
        self.values = {}
        self.expires = {}
        self.evaluations = 0

    def _value(self, key):
        if self.expires.get(key, math.inf) <= self.now:
            self.values.pop(key, None)
            self.expires.pop(key, None)
        return self.values.get(key)

    async def ttl(self, key):
        value = await self.pttl(key)
        return value if value < 0 else math.ceil(value / 1000)

    async def pttl(self, key):
        if self._value(key) is None:
            return -2
        if key not in self.expires:
            return -1
        return math.ceil((self.expires[key] - self.now) * 1000)

    async def eval(self, script, count, *args):
        self.evaluations += 1
        keys, values = args[:count], args[count:]
        if count == 1 and "local requested" in script:
            key, seconds = keys[0], int(values[0])
            current = await self.pttl(key)
            if current != -1 and current < seconds * 1000:
                self.values[key] = 1
                self.expires[key] = self.now + seconds
            return 1
        for index, key in enumerate(keys):
            if int(self._value(key) or 0) >= int(values[index * 2]):
                return [0, index + 1, int(self.values[key])]
        remaining = []
        for index, key in enumerate(keys):
            current = int(self._value(key) or 0) + 1
            self.values[key] = current
            if current == 1:
                self.expires[key] = self.now + int(values[index * 2 + 1])
            remaining.append(int(values[index * 2]) - current)
        return [1, min(remaining), 0]


class SharedSourceCooldownTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.redis = _ClockedRedis()
        self.budgets = RedisRequestBudget(SimpleNamespace(client=lambda: self.redis))
        self.live = PROVIDERS["nerkhsanj_usd_toman"]
        self.sibling = PROVIDERS["nerkhsanj_gold18_toman"]
        self.enterContext(patch("app.pricing.budgets.time.time", side_effect=lambda: 1_700_000_000 + self.redis.now))

    async def consume(self, provider, url=None):
        return await self.budgets.consume(provider, RequestPurpose.NORMAL, source_url=url)

    async def test_sibling_is_blocked_after_minute_lease_has_expired(self):
        self.assertTrue((await self.consume(self.live)).allowed)
        await self.budgets.record_rate_limit(self.live)
        self.redis.now = 61
        for provider in (self.live, self.sibling):
            decision = await self.consume(provider)
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, "provider_cooldown")
            self.assertEqual(await self.budgets.cooldown_remaining(provider), 239)
        self.assertEqual(await self.budgets.cooldown_remaining(self.live.provider_id), 239)

    async def test_longer_retry_after_is_shared_and_survives_configured_cooldown(self):
        await self.budgets.record_rate_limit(self.live, retry_after_seconds=900)
        self.redis.now = 301
        self.assertFalse((await self.consume(self.sibling)).allowed)
        self.assertEqual(await self.budgets.cooldown_remaining(self.sibling), 599)
        self.redis.now = 900
        self.assertTrue((await self.consume(self.sibling)).allowed)

    async def test_live_cooldown_leaves_other_documents_independent(self):
        await self.budgets.record_rate_limit(self.live, retry_after_seconds=900)
        self.redis.now = 61
        for url in ("https://nerkh.jahankhahan.shop/data/intraday.json",
                    "https://nerkh.jahankhahan.shop/data/rates.json",
                    "https://nerkh.jahankhahan.shop/data/rates-usd.json"):
            with self.subTest(url=url):
                provider = replace(self.live, provider_id="source_" + url.rsplit("/", 1)[-1])
                self.assertTrue((await self.consume(provider, url)).allowed)
        self.assertFalse((await self.consume(self.sibling)).allowed)

    async def test_archive_429_uses_exact_archive_url_instead_of_live_url(self):
        archive = self.live.history_url
        await self.budgets.record_rate_limit(self.live, source_url=archive, retry_after_seconds=900)
        self.assertFalse((await self.consume(self.sibling, archive)).allowed)
        self.assertTrue((await self.consume(self.live)).allowed)

    async def test_default_https_port_does_not_split_source_cooldown(self):
        await self.budgets.record_rate_limit(self.live, source_url=self.live.url.replace(".shop/", ".shop:443/"))
        self.assertFalse((await self.consume(self.sibling)).allowed)

    async def test_gta_sibling_uses_shared_canonical_url_cooldown(self):
        gta = PROVIDERS["gta_silver925_toman"]
        sibling = replace(gta, provider_id="gta_sibling", url="https://gtasilver.com:443/api/silver-price")
        await self.budgets.record_rate_limit(gta, retry_after_seconds=900)
        self.redis.now = 61
        self.assertFalse((await self.consume(sibling)).allowed)
        self.assertEqual(await self.budgets.cooldown_remaining(sibling), 839)
        self.assertTrue((await self.consume(self.live)).allowed)

    async def test_malformed_retry_values_cannot_weaken_configured_or_longer_cooldown(self):
        values = (None, -1, True, 1.5, "900", float("nan"), float("inf"), {}, [])
        for value in values:
            with self.subTest(value=value):
                self.redis.values.clear()
                self.redis.expires.clear()
                self.redis.now = 0
                await self.budgets.record_rate_limit(self.live, retry_after_seconds=value)
                self.assertEqual(await self.budgets.cooldown_remaining(self.sibling), 300)
                await self.budgets.record_rate_limit(self.live, retry_after_seconds=900)
                self.redis.now = 61
                await self.budgets.record_rate_limit(self.sibling, retry_after_seconds=value)
                self.assertEqual(await self.budgets.cooldown_remaining(self.live), 839)

    async def test_shorter_duplicate_429_cannot_shorten_longer_shared_deadline(self):
        await self.budgets.record_rate_limit(self.live, retry_after_seconds=900)
        self.redis.now = 61
        await self.budgets.record_rate_limit(self.sibling, retry_after_seconds=10)
        self.assertEqual(await self.budgets.cooldown_remaining(self.live), 839)

    async def test_retry_after_uses_existing_one_day_safety_bound(self):
        await self.budgets.record_rate_limit(self.live, retry_after_seconds=10**100)
        self.assertEqual(await self.budgets.cooldown_remaining(self.sibling), 86_400)

    async def test_fractional_last_second_and_unbounded_existing_cooldown_stay_blocked(self):
        await self.budgets.record_rate_limit(self.live)
        self.redis.now = 299.999
        self.assertEqual(await self.budgets.cooldown_remaining(self.sibling), 1)
        self.assertFalse((await self.consume(self.sibling)).allowed)
        shared_key = next(iter(self.redis.values))
        self.redis.expires.pop(shared_key)
        await self.budgets.record_rate_limit(self.sibling, retry_after_seconds=900)
        self.assertEqual(await self.budgets.cooldown_remaining(self.live), 1)
        self.assertNotIn(shared_key, self.redis.expires)

    async def test_legacy_route_cooldown_survives_worker_upgrade(self):
        key = f"pricing:budget:{self.live.provider_id}:cooldown"
        self.redis.values[key] = 1
        self.redis.expires[key] = 300
        self.assertFalse((await self.consume(self.live)).allowed)
        self.assertEqual(await self.budgets.cooldown_remaining(self.live), 300)

    async def test_unshared_provider_retains_route_cooldown(self):
        provider = PROVIDERS["tetherland_usdt"]
        await self.budgets.record_rate_limit(provider, retry_after_seconds=900)
        self.redis.now = 301
        self.assertFalse((await self.consume(provider)).allowed)
        self.assertIn(f"pricing:budget:{provider.provider_id}:cooldown", self.redis.values)

    async def test_malformed_source_cannot_consume_or_write_a_cooldown(self):
        for provider in (self.live, PROVIDERS["gta_silver925_toman"]):
            for url in ("http://gtasilver.com/api/silver-price", "https://other.invalid/data/live.json",
                        provider.url + "?ignored=1"):
                with self.subTest(provider=provider.provider_id, url=url):
                    decision = await self.consume(provider, url)
                    self.assertFalse(decision.allowed)
                    with self.assertRaises((ValueError, SourceSnapshotUnavailable)):
                        await self.budgets.record_rate_limit(provider, source_url=url)
        self.assertEqual(self.redis.evaluations, 0)


class RateLimitPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_collector_passes_exact_live_url_and_parsed_retry_after(self):
        provider = PROVIDERS["nerkhsanj_usd_toman"]
        budgets = AsyncMock()
        collector = ProviderQuoteCollector(store=AsyncMock(), budgets=budgets, persistence=AsyncMock())
        failure = ProviderCallFailure("rate_limited", "Limited", http_status=429, retry_after_seconds=900)
        with patch.object(collector, "_source_snapshot", side_effect=failure), \
             patch.object(collector, "_rejected_quote", return_value=None), \
             patch.object(collector, "_record_failure"), \
             patch("app.pricing.providers.rights.provider_allowed", return_value=True), \
             patch("app.pricing.providers.rights.endpoint_allowed", return_value=True):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
                await collector._call_and_parse(provider, RequestPurpose.NORMAL, ProviderRuntimeState(
                    provider_id=provider.provider_id, instrument_id=provider.instrument_id),
                    client, get_instrument(provider.instrument_id))
        budgets.record_rate_limit.assert_awaited_once_with(provider, source_url=provider.url, retry_after_seconds=900)

    async def test_backfill_passes_exact_archive_url_and_parsed_retry_after(self):
        store, budgets, operational = AsyncMock(), AsyncMock(), AsyncMock()
        store.client = Mock(return_value=_Redis())
        budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        operational.instrument.side_effect = get_instrument
        queue = PricingBackfillQueue(store=store, budgets=budgets,
            persistence=AsyncMock(), operational=operational)
        self.enterContext(patch("app.pricing.backfill.rights.provider_allowed", return_value=True))
        self.enterContext(patch("app.pricing.backfill.rights.endpoint_allowed", return_value=True))
        end = datetime(2026, 10, 17, 12, tzinfo=UTC)
        for provider in (PROVIDERS["nerkhsanj_silver999_toman"], PROVIDERS["nobitex_stats_btc"]):
            with self.subTest(provider=provider.provider_id):
                budgets.reset_mock()
                client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(429, json={"error": "limited"}, headers={"Retry-After": "900"})))
                error = httpx.HTTPStatusError if provider.source_family == "nerkhsanj" else RuntimeError
                job = {"id": 1, "instrument_id": provider.instrument_id,
                       "range_start": end - timedelta(hours=1), "range_end": end, "attempt_count": 1}
                with patch("app.pricing.backfill.httpx.AsyncClient", return_value=client), \
                     patch.object(settings, "pricing_provider_allowed_hosts", urlsplit(provider.history_url).hostname):
                    with self.assertRaises(error) as raised:
                        await queue._execute_history_job(job, provider)
                if provider.source_family != "nerkhsanj":
                    self.assertEqual(str(raised.exception), "history_provider_rate_limited")
                budgets.record_rate_limit.assert_awaited_once_with(
                    provider, source_url=provider.history_url, retry_after_seconds=900)


if __name__ == "__main__":
    unittest.main()
