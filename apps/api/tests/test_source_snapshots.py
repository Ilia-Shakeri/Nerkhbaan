from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing import rights
from app.pricing.budgets import BudgetDecision, RedisRequestBudget
from app.pricing.instruments import get_instrument
from app.pricing.models import ProviderRuntimeState, RequestPurpose
from app.pricing.parsers.nerkhsanj_markets import NerkhsanjSnapshotParser
from app.pricing.persistence import PersistenceResult
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import PROVIDERS
from app.pricing.source_snapshots import SharedSourceSnapshots, SourceSnapshotUnavailable, source_url_digest

NOW = datetime(2026, 10, 17, 11, 30, tzinfo=UTC)
LIVE = "https://nerkh.jahankhahan.shop/data/live.json"
RATES = "https://nerkh.jahankhahan.shop/data/rates.json"
PAYLOAD = {"date": "1405/07/25", "time": "15:00", "rates": {"silver": 500000}}


class _Redis:
    def __init__(self):
        self.values = {}
        self.expires = {}

    async def get(self, key):
        if self.expires.get(key, float("inf")) <= time.monotonic():
            self.values.pop(key, None)
            self.expires.pop(key, None)
        return self.values.get(key)

    async def set(self, key, value, *, nx=False, px=None):
        if nx and await self.get(key) is not None:
            return None
        self.values[key] = value
        if px is not None:
            self.expires[key] = time.monotonic() + px / 1000
        return True

    async def pttl(self, key):
        if await self.get(key) is None:
            return -2
        if key not in self.expires:
            return -1
        return max(0, int((self.expires[key] - time.monotonic()) * 1000))

    async def eval(self, _script, count, *args):
        lock = args[0]
        owner = args[count]
        if await self.get(lock) != owner:
            return 0
        if count == 2:
            await self.set(args[1], args[count + 1], px=int(args[count + 2]))
        self.values.pop(lock, None)
        self.expires.pop(lock, None)
        return 1


class SourceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def test_closed_market_intraday_can_retain_point_clocks_without_a_live_publication_clock(self):
        payload = {"date": "1405/07/25", "time": "", "series": {}}
        SharedSourceSnapshots._source_clock(payload, LIVE.replace("live.json", "intraday.json"), NOW)
        with self.assertRaises(SourceSnapshotUnavailable):
            SharedSourceSnapshots._source_clock(payload, LIVE, NOW)

    def setUp(self):
        self.redis = _Redis()
        self.store = SimpleNamespace(client=lambda: self.redis)
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        self.provider = replace(PROVIDERS["nerkhsanj_silver999_history"],
                                provider_id="nerkhsanj_snapshot_test", history_only=False,
                                url=LIVE, maximum_payload_bytes=262144)
        self.snapshots = SharedSourceSnapshots(self.store, self.budgets)
        self.loader = AsyncMock(return_value=(dict(PAYLOAD), "application/json", 200))
        self.enterContext(patch.object(rights, "provider_allowed", return_value=True))
        self.enterContext(patch.object(rights, "endpoint_allowed", return_value=True))
        self.enterContext(patch.object(settings, "pricing_provider_allowed_hosts", "nerkh.jahankhahan.shop"))
        self.clock = self.enterContext(patch("app.pricing.source_snapshots.utc_now", return_value=NOW))

    async def envelope(self, **changes):
        envelope = {
            "schema_version": 1, "source_url": LIVE, "content_type": "application/json",
            "http_status": 200, "fetched_at": NOW.isoformat(), "payload": dict(PAYLOAD),
        }
        envelope.update(changes)
        await self.redis.set(self.snapshots.cache_key(LIVE), json.dumps(envelope), px=60000)

    async def test_two_replicas_and_eight_instruments_share_one_actual_request(self):
        async def load():
            await asyncio.sleep(0.02)
            return dict(PAYLOAD), "application/json", 200

        self.loader.side_effect = load
        replicas = [SharedSourceSnapshots(self.store, self.budgets) for _index in range(8)]
        snapshots = await asyncio.gather(*(
            replica.get(replace(self.provider, provider_id=f"nerkhsanj_test_{index}"), LIVE,
                        self.loader, RequestPurpose.NORMAL) for index, replica in enumerate(replicas)
        ))
        self.assertEqual(self.loader.await_count, 1)
        self.assertEqual(self.budgets.consume.await_count, 1)
        self.assertEqual(sum(snapshot.network_called for snapshot in snapshots), 1)
        self.assertTrue(all(snapshot.fetched_at == NOW for snapshot in snapshots))
        self.assertTrue(all(snapshot.payload == PAYLOAD for snapshot in snapshots))
        self.assertLessEqual(await self.redis.pttl(self.snapshots.cache_key(LIVE)), 60000)

    async def test_cache_reuse_does_not_renew_http_receive_clock_or_consume_budget(self):
        first = await self.snapshots.get(self.provider, LIVE, self.loader)
        self.clock.return_value = NOW + timedelta(seconds=40)
        second = await SharedSourceSnapshots(self.store, self.budgets).get(self.provider, LIVE, self.loader)
        self.assertTrue(first.network_called)
        self.assertFalse(second.network_called)
        self.assertEqual(first.fetched_at, second.fetched_at)
        self.loader.assert_awaited_once()
        self.budgets.consume.assert_awaited_once()

    async def test_expired_receive_clock_never_becomes_a_fresh_cache_hit(self):
        await self.envelope(fetched_at=(NOW - timedelta(seconds=61)).isoformat())
        snapshot = await self.snapshots.get(self.provider, LIVE, self.loader)
        self.assertTrue(snapshot.network_called)
        self.assertEqual(snapshot.fetched_at, NOW)

    async def test_future_or_naive_cache_time_is_rejected_without_a_request(self):
        for timestamp in ((NOW + timedelta(microseconds=1)).isoformat(), NOW.replace(tzinfo=None).isoformat()):
            with self.subTest(timestamp=timestamp):
                await self.envelope(fetched_at=timestamp)
                with self.assertRaises(SourceSnapshotUnavailable):
                    await self.snapshots.get(self.provider, LIVE, self.loader)
        self.loader.assert_not_awaited()
        self.budgets.consume.assert_not_awaited()

    async def test_unbounded_or_overlong_cache_ttl_is_rejected(self):
        for ttl in (None, 61000):
            with self.subTest(ttl=ttl):
                await self.envelope()
                key = self.snapshots.cache_key(LIVE)
                if ttl is None:
                    self.redis.expires.pop(key, None)
                else:
                    self.redis.expires[key] = time.monotonic() + ttl / 1000
                with self.assertRaisesRegex(SourceSnapshotUnavailable, "snapshot_invalid_cache_ttl"):
                    await self.snapshots.get(self.provider, LIVE, self.loader)
        self.loader.assert_not_awaited()

    async def test_cache_payload_url_status_and_unicode_byte_bounds_are_checked(self):
        for changes in ({"source_url": RATES}, {"http_status": True}, {"schema_version": True},
                        {"payload": {**PAYLOAD, "padding": "ن" * 140000}}):
            with self.subTest(keys=list(changes)):
                await self.envelope(**changes)
                with self.assertRaises(SourceSnapshotUnavailable):
                    await self.snapshots.get(self.provider, LIVE, self.loader)
        self.loader.assert_not_awaited()

    async def test_missing_or_future_source_clock_is_rejected_before_publication(self):
        for clock in ("", "15:01"):
            with self.subTest(clock=clock):
                self.loader.return_value = ({**PAYLOAD, "time": clock}, "application/json", 200)
                with self.assertRaises(SourceSnapshotUnavailable) as raised:
                    await self.snapshots.get(self.provider, LIVE, self.loader)
                self.assertTrue(raised.exception.network_called)
                self.assertIsNone(await self.redis.get(self.snapshots.cache_key(LIVE)))

    async def test_oversize_network_payload_is_never_cached(self):
        self.loader.return_value = ({**PAYLOAD, "padding": "x" * 262144}, "application/json", 200)
        with self.assertRaisesRegex(SourceSnapshotUnavailable, "payload_too_large"):
            await self.snapshots.get(self.provider, LIVE, self.loader)
        self.assertIsNone(await self.redis.get(self.snapshots.cache_key(LIVE)))

    async def test_permission_denial_is_checked_before_redis_or_loader(self):
        self.store.client = AsyncMock(side_effect=AssertionError("Redis must not be read"))
        with patch.object(rights, "provider_allowed", return_value=False):
            with self.assertRaisesRegex(SourceSnapshotUnavailable, "provider_rights_denied"):
                await self.snapshots.get(self.provider, LIVE, self.loader)
        self.store.client.assert_not_called()
        self.loader.assert_not_awaited()

    async def test_revocation_during_http_prevents_cache_publication(self):
        allowed = True

        async def load():
            nonlocal allowed
            allowed = False
            return dict(PAYLOAD), "application/json", 200

        with patch.object(rights, "provider_allowed", side_effect=lambda *_args: allowed):
            with self.assertRaisesRegex(SourceSnapshotUnavailable, "provider_rights_denied") as raised:
                await self.snapshots.get(self.provider, LIVE, load)
        self.assertTrue(raised.exception.network_called)
        self.assertIsNone(await self.redis.get(self.snapshots.cache_key(LIVE)))

    async def test_allowed_host_and_keyless_get_are_enforced_even_for_cached_payloads(self):
        await self.envelope()
        with patch.object(settings, "pricing_provider_allowed_hosts", "other.example.invalid"):
            with self.assertRaisesRegex(SourceSnapshotUnavailable, "provider_host_not_allowed"):
                await self.snapshots.get(self.provider, LIVE, self.loader)
        for change in ({"api_key_setting": "servix_api_key"}, {"method": "POST"}, {"enabled": False}):
            with self.subTest(change=change), self.assertRaises(SourceSnapshotUnavailable):
                await self.snapshots.get(replace(self.provider, **change), LIVE, self.loader)
        self.loader.assert_not_awaited()

    async def test_redis_failure_and_budget_denial_never_call_loader(self):
        with patch.object(self.redis, "get", side_effect=OSError("owned Redis unavailable")):
            with self.assertRaisesRegex(SourceSnapshotUnavailable, "snapshot_cache_unavailable"):
                await self.snapshots.get(self.provider, LIVE, self.loader)
        self.budgets.consume.return_value = BudgetDecision(False, "budget_limit_1", 0)
        with self.assertRaisesRegex(SourceSnapshotUnavailable, "budget_limit_1"):
            await self.snapshots.get(self.provider, LIVE, self.loader)
        self.loader.assert_not_awaited()

    async def test_stolen_lock_cannot_publish_or_remove_new_owners_lock(self):
        key = self.snapshots.cache_key(LIVE)

        async def load():
            await self.redis.set(key + ":lock", "new-owner", px=20000)
            return dict(PAYLOAD), "application/json", 200

        with self.assertRaisesRegex(SourceSnapshotUnavailable, "snapshot_lease_lost"):
            await self.snapshots.get(self.provider, LIVE, load)
        self.assertIsNone(await self.redis.get(key))
        self.assertEqual(await self.redis.get(key + ":lock"), "new-owner")

    async def test_different_archive_urls_do_not_share_a_snapshot(self):
        daily = replace(self.provider, history_only=True, maximum_payload_bytes=8388608)
        one = await self.snapshots.get(daily, RATES, self.loader, RequestPurpose.BACKFILL)
        two = await self.snapshots.get(daily, RATES.replace("rates.json", "rates-usd.json"),
                                       self.loader, RequestPurpose.BACKFILL)
        self.assertTrue(one.network_called and two.network_called)
        self.assertEqual(self.loader.await_count, 2)
        urls = {call.kwargs["source_url"] for call in self.budgets.consume.await_args_list}
        self.assertEqual(len(urls), 2)

    async def test_collector_cache_hit_retains_received_and_runtime_success_time(self):
        await self.envelope()
        provider = replace(self.provider, operational_ttl_seconds=20,
                           maximum_source_age_seconds=120, anchor_live_window_at_receive_time=True)
        store = AsyncMock()
        store.client = lambda: self.redis
        persistence = AsyncMock()
        persistence.persist_provider_quote.return_value = PersistenceResult(True, False, None, None)
        collector = ProviderQuoteCollector(store=store, budgets=self.budgets, persistence=persistence)
        runtime = ProviderRuntimeState(provider.provider_id, provider.instrument_id)
        later = NOW + timedelta(seconds=40)
        self.clock.return_value = later
        with patch("app.pricing.providers.utc_now", return_value=later):
            with patch("app.pricing.providers.build_parser", return_value=NerkhsanjSnapshotParser("silver")):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        lambda _request: (_ for _ in ()).throw(AssertionError("No HTTP on cache hit")))) as client:
                    outcome = await collector._call_and_parse(provider, RequestPurpose.NORMAL, runtime, client,
                                                              get_instrument(provider.instrument_id))
        self.assertFalse(outcome.external_called)
        self.assertFalse(outcome.usable)
        self.assertEqual(outcome.failure_reason, "source_not_live")
        self.assertEqual(outcome.quote.received_at, NOW)
        self.assertEqual(runtime.last_success_at, NOW)
        self.assertEqual(runtime.operational_status, "source_snapshot")
        self.budgets.consume.assert_not_awaited()

    async def test_collector_503_uses_one_network_attempt_despite_retry_configuration(self):
        calls = []

        def fail(request):
            calls.append(request)
            return httpx.Response(503, json={"error": "temporary"})

        collector = ProviderQuoteCollector(store=self.store, budgets=self.budgets)
        with patch.object(settings, "pricing_provider_max_retries", 5):
            async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
                with self.assertRaises(ProviderCallFailure) as raised:
                    await collector._request_payload(client, self.provider)
        self.assertEqual(raised.exception.http_status, 503)
        self.assertTrue(raised.exception.network_called)
        self.assertEqual(len(calls), 1)
        self.budgets.consume.assert_awaited_once()


class SourceUrlBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_documented_url_has_an_atomic_unweakenable_minute_lease(self):
        provider = PROVIDERS["nerkhsanj_silver999_history"]
        redis = AsyncMock()
        redis.ttl.return_value = 0
        redis.pttl.return_value = 0
        redis.eval.return_value = [1, 0, 0]
        store = SimpleNamespace(client=lambda: redis)
        budget = RedisRequestBudget(store)
        provider = replace(provider, budget=replace(provider.budget, minimum_interval_seconds=1))
        keys = []
        for url in (LIVE, RATES):
            self.assertTrue((await budget.consume(provider, RequestPurpose.NORMAL, source_url=url)).allowed)
            args = redis.eval.await_args.args
            count = args[1]
            names, values = args[2:2 + count], args[2 + count:]
            key = f"pricing:budget:source:nerkhsanj:{source_url_digest(url)}:minimum_interval"
            keys.append(key)
            index = names.index(key)
            self.assertEqual(values[index * 2:index * 2 + 2], (1, 60))
            self.assertNotIn("pricing:budget:family:nerkhsanj:minimum_interval", names)
        self.assertNotEqual(*keys)

    async def test_gta_silver_contract_has_a_hard_url_minute_lease(self):
        import hashlib

        provider = replace(PROVIDERS["nerkhsanj_silver999_history"], source_family="gta_silver",
                           url="https://gtasilver.com/api/silver-price")
        provider = replace(provider, budget=replace(provider.budget, minimum_interval_seconds=1))
        redis = AsyncMock()
        redis.ttl.return_value = 0
        redis.pttl.return_value = 0
        redis.eval.return_value = [1, 0, 0]
        budget = RedisRequestBudget(SimpleNamespace(client=lambda: redis))
        self.assertTrue((await budget.consume(provider, RequestPurpose.NORMAL)).allowed)
        args = redis.eval.await_args.args
        count = args[1]
        names, values = args[2:2 + count], args[2 + count:]
        digest = hashlib.sha256(provider.url.encode()).hexdigest()
        key = f"pricing:budget:source:gta_silver:{digest}:minimum_interval"
        index = names.index(key)
        self.assertEqual(values[index * 2:index * 2 + 2], (1, 60))


if __name__ == "__main__":
    unittest.main()
