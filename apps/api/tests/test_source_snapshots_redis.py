from __future__ import annotations

import asyncio
import hashlib
import math
import os
import time
import unittest
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from redis.asyncio import Redis

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")

from app.config import settings
from app.pricing import rights
from app.pricing.budgets import RedisRequestBudget
from app.pricing.models import RequestPurpose
from app.pricing.registry import PROVIDERS
from app.pricing.source_snapshots import SharedSourceSnapshots, source_url_digest


TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")
LIVE = "https://nerkh.jahankhahan.shop/data/live.json"
NOW = datetime(2026, 10, 17, 11, 30, tzinfo=UTC)
PAYLOAD = {"date": "1405/07/25", "time": "15:00", "rates": {"silver": 500000}}


class _OwnedRedis:
    def __init__(self, raw, prefix):
        self.raw = raw
        self.prefix = prefix
        self.keys: set[str] = set()

    def key(self, value):
        if not isinstance(value, str) or not value.startswith(("pricing:budget:", "pricing:source-snapshot:")):
            raise AssertionError("Unexpected source test key")
        key = self.prefix + value
        self.keys.add(key)
        return key

    async def get(self, key):
        return await self.raw.get(self.key(key))

    async def set(self, key, *args, **kwargs):
        return await self.raw.set(self.key(key), *args, **kwargs)

    async def ttl(self, key):
        return await self.raw.ttl(self.key(key))

    async def pttl(self, key):
        return await self.raw.pttl(self.key(key))

    async def eval(self, script, count, *args):
        if count < 1 or len(args) < count:
            raise AssertionError("Source test script requires explicit owned keys")
        return await self.raw.eval(script, count, *(self.key(key) for key in args[:count]), *args[count:])


@unittest.skipUnless(TEST_REDIS_URL, "TEST_REDIS_URL is not set")
class SourceSnapshotsRedisTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        destination = urlsplit(TEST_REDIS_URL)
        if destination.scheme not in {"redis", "rediss"} or destination.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise unittest.SkipTest("The owned Redis test endpoint must be loopback")

    async def asyncSetUp(self):
        self.prefix = "pricing:test:source-snapshots:" + uuid.uuid4().hex + ":"
        self.raw = Redis.from_url(TEST_REDIS_URL, decode_responses=True,
                                  socket_connect_timeout=3, socket_timeout=3)
        self.redis = _OwnedRedis(self.raw, self.prefix + "data:")
        self.sentinel = self.prefix + "untouched-sentinel"
        self.sentinel_created = False
        self.addAsyncCleanup(self._cleanup)
        self.assertTrue(await self.raw.ping())
        self.assertTrue(await self.raw.set(self.sentinel, "keep-original", nx=True, ex=120))
        self.sentinel_created = True
        self.store = SimpleNamespace(client=lambda: self.redis)
        self.budget = RedisRequestBudget(self.store)
        self.provider = replace(PROVIDERS["nerkhsanj_silver999_toman"], enabled=True,
                                budget=replace(PROVIDERS["nerkhsanj_silver999_toman"].budget,
                                               minimum_interval_seconds=1, cooldown_after_429_seconds=300))

    async def _cleanup(self):
        owned = sorted(self.redis.keys | {self.sentinel})
        try:
            self.assertTrue(all(key.startswith(self.prefix) for key in owned))
            try:
                if self.sentinel_created:
                    self.assertEqual(await self.raw.get(self.sentinel), "keep-original")
            finally:
                if owned:
                    await self.raw.unlink(*owned)
                    self.assertEqual(await self.raw.exists(*owned), 0)
        finally:
            await self.raw.aclose()

    def _assert_minute_ttl(self, ttl, started):
        elapsed_ms = math.ceil((time.monotonic() - started) * 1000)
        self.assertGreaterEqual(ttl, max(1, 60000 - elapsed_ms - 1000))
        self.assertLessEqual(ttl, 60000)

    async def test_twelve_consumers_share_one_fetch_and_keep_original_receive_clock(self):
        calls = 0

        async def loader():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.04)
            return dict(PAYLOAD), "application/json", 200

        with patch.object(rights, "provider_allowed", return_value=True), \
                patch.object(rights, "endpoint_allowed", return_value=True), \
                patch.object(settings, "pricing_provider_allowed_hosts", "nerkh.jahankhahan.shop"), \
                patch("app.pricing.source_snapshots.utc_now", return_value=NOW) as clock:
            started = time.monotonic()
            snapshots = await asyncio.gather(*(
                SharedSourceSnapshots(self.store, self.budget).get(
                    replace(self.provider, provider_id=f"snapshot_replica_{index}"), LIVE, loader)
                for index in range(12)
            ))
            self.assertEqual(calls, 1)
            self.assertEqual(sum(snapshot.network_called for snapshot in snapshots), 1)
            self.assertTrue(all(snapshot.payload == PAYLOAD and snapshot.fetched_at == NOW for snapshot in snapshots))
            key = SharedSourceSnapshots.cache_key(LIVE)
            self._assert_minute_ttl(await self.redis.pttl(key), started)
            self.assertIsNone(await self.redis.get(key + ":lock"))
            clock.return_value = NOW + timedelta(seconds=40)
            reused = await SharedSourceSnapshots(self.store, self.budget).get(self.provider, LIVE, loader)
            self.assertFalse(reused.network_called)
            self.assertEqual(reused.fetched_at, NOW)
            self.assertEqual(calls, 1)

    async def test_real_lua_enforces_hard_url_caps_and_keeps_archives_independent(self):
        intraday = LIVE.replace("live.json", "intraday.json")
        gta = replace(PROVIDERS["gta_silver925_toman"],
                      budget=replace(PROVIDERS["gta_silver925_toman"].budget, minimum_interval_seconds=1))
        cases = (
            (self.provider, intraday, "nerkhsanj", source_url_digest(intraday)),
            (gta, gta.url, "gta_silver", hashlib.sha256(gta.url.encode()).hexdigest()),
        )
        for provider, url, family, digest in cases:
            with self.subTest(family=family):
                started = time.monotonic()
                decisions = await asyncio.gather(*(
                    self.budget.consume(replace(provider, provider_id=f"interval_replica_{family}_{index}"),
                                        RequestPurpose.BACKFILL, source_url=url)
                    for index in range(12)
                ))
                self.assertEqual(sum(decision.allowed for decision in decisions), 1)
                self.assertTrue(all(decision.allowed or decision.reason == "budget_limit_1" for decision in decisions))
                key = f"pricing:budget:source:{family}:{digest}:minimum_interval"
                self.assertEqual(await self.redis.get(key), "1")
                self._assert_minute_ttl(await self.redis.pttl(key), started)
        for index, filename in enumerate(("rates.json", "rates-usd.json")):
            url = LIVE.replace("live.json", filename)
            allowed = await self.budget.consume(replace(self.provider, provider_id=f"independent_archive_{index}"),
                                                RequestPurpose.BACKFILL, source_url=url)
            self.assertTrue(allowed.allowed)
            denied = await self.budget.consume(replace(self.provider, provider_id=f"archive_sibling_{index}"),
                                               RequestPurpose.BACKFILL, source_url=url)
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.reason, "budget_limit_1")

    async def test_shared_cooldown_keeps_longest_of_thirty_two_writers_without_blocking_archives(self):
        sibling = replace(self.provider, provider_id="cooldown_sibling", url=LIVE.replace(".shop/", ".shop:443/"))
        await self.budget.record_rate_limit(self.provider, retry_after_seconds=900)
        self.assertEqual((await self.budget.consume(sibling, RequestPurpose.NORMAL)).reason, "provider_cooldown")
        started = time.monotonic()
        await asyncio.gather(*(
            self.budget.record_rate_limit(self.provider if index % 2 else sibling,
                                          retry_after_seconds=(300, 900, 600, 1200)[index % 4])
            for index in range(32)
        ))
        key = f"pricing:budget:source:nerkhsanj:{source_url_digest(LIVE)}:cooldown"
        longest = await self.redis.pttl(key)
        elapsed_ms = math.ceil((time.monotonic() - started) * 1000)
        self.assertGreaterEqual(longest, 1200000 - elapsed_ms - 1000)
        self.assertLessEqual(longest, 1200000)
        shorter_started = time.monotonic()
        for shorter in (None, -1, True, 30, 600):
            await self.budget.record_rate_limit(sibling, retry_after_seconds=shorter)
        after_shorter = await self.redis.pttl(key)
        self.assertLessEqual(after_shorter, longest)
        elapsed_ms = math.ceil((time.monotonic() - shorter_started) * 1000)
        self.assertGreaterEqual(after_shorter, longest - elapsed_ms - 1000)
        self.assertEqual((await self.budget.consume(sibling, RequestPurpose.NORMAL)).reason, "provider_cooldown")
        for index, filename in enumerate(("rates.json", "rates-usd.json")):
            archive = replace(self.provider, provider_id=f"cooldown_archive_{index}")
            self.assertTrue((await self.budget.consume(archive, RequestPurpose.BACKFILL,
                                                      source_url=LIVE.replace("live.json", filename))).allowed)
        gta = replace(PROVIDERS["gta_silver925_toman"],
                      budget=replace(PROVIDERS["gta_silver925_toman"].budget, cooldown_after_429_seconds=300))
        gta_sibling = replace(gta, provider_id="gta_cooldown_sibling", url="https://gtasilver.com:443/api/silver-price")
        gta_started = time.monotonic()
        await self.budget.record_rate_limit(gta, retry_after_seconds=900)
        remaining = await self.budget.cooldown_remaining(gta_sibling)
        self.assertGreaterEqual(remaining, 900 - math.ceil(time.monotonic() - gta_started) - 1)
        self.assertLessEqual(remaining, 900)
        self.assertEqual((await self.budget.consume(gta_sibling, RequestPurpose.NORMAL)).reason, "provider_cooldown")


if __name__ == "__main__":
    unittest.main()
