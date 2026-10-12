from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.compatibility import LegacyPricingAdapter
from app.pricing.models import CanonicalQuote, CanonicalStatus


NOW = datetime(2026, 10, 12, 6, 50, tzinfo=UTC)


class PublicPriceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = NOW
        self.enabled = True
        self.quote = self.make_quote()
        async def read():
            return {"BTC_USD": self.quote} if self.enabled else {}
        self.service = SimpleNamespace(get_all_canonical=AsyncMock(side_effect=read),
                                       store=SimpleNamespace(recent_canonical=AsyncMock(return_value=[])))
        self.adapter = LegacyPricingAdapter(self.service)
        owner = self
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.now if tz else owner.now.replace(tzinfo=None)
        for target, value in (("app.pricing.compatibility.datetime", Clock),
                              ("app.pricing.models.utc_now", lambda: self.now)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_quote(self, *, price=Decimal("64000"), observed_at=NOW):
        return CanonicalQuote.create(
            instrument_id="BTC_USD", price=price, status=CanonicalStatus.LIVE,
            primary_quote_id=1, verification_quote_ids=[],
            source_summary={"primary_provider_id": "test-source", "derived": False},
            observed_at=observed_at, canonical_at=observed_at,
            valid_until=observed_at+timedelta(seconds=1),
            stale_at=observed_at+timedelta(seconds=3),
            expires_at=observed_at+timedelta(seconds=4), is_persisted=True,
            decision_reason="test-public-read",
        )

    @staticmethod
    def btc(payload):
        return next(asset for asset in payload["assets"] if asset["asset"] == "btc")

    async def test_deadlines_cross_within_old_five_second_cache_window(self):
        initial = self.btc(await self.adapter.get_prices())
        self.assertTrue(initial["usd_live_eligible"])
        self.now += timedelta(seconds=2)
        later = self.btc(await self.adapter.get_prices())
        self.assertFalse(later["usd_live_eligible"])
        self.assertEqual(later["usd_status"], "fresh_cache")
        self.now += timedelta(seconds=3)
        expired = self.btc(await self.adapter.get_prices())
        self.assertTrue(expired["usd_expired"])
        self.assertEqual(expired["usd_status"], "expired")
        self.assertEqual(self.service.get_all_canonical.await_count, 3)

    async def test_instant_runtime_disable_is_seen_on_next_public_get(self):
        self.assertIsNotNone(self.btc(await self.adapter.get_prices())["price_usd"])
        self.enabled = False
        disabled = self.btc(await self.adapter.get_prices())
        self.assertIsNone(disabled["price_usd"])
        self.assertFalse(disabled["usd_live_eligible"])
        self.assertEqual(disabled["usd_status"], "unavailable")
        self.assertEqual(self.service.get_all_canonical.await_count, 2)

    async def test_newer_canonical_is_visible_on_next_public_get(self):
        before = self.btc(await self.adapter.get_prices())
        self.quote = self.make_quote(price=Decimal("64100"), observed_at=NOW+timedelta(milliseconds=1))
        after = self.btc(await self.adapter.get_prices())
        self.assertEqual(before["price_usd"], 64000)
        self.assertEqual(after["price_usd"], 64100)
        self.assertEqual(self.service.get_all_canonical.await_count, 2)

    async def test_200_concurrent_gets_share_only_unfinished_reads(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_read():
            started.set()
            await release.wait()
            return {"BTC_USD": self.quote}
        self.service.get_all_canonical.side_effect = slow_read
        readers = [asyncio.create_task(self.adapter.get_prices()) for _ in range(200)]
        await started.wait()
        await asyncio.sleep(0)
        self.assertEqual(self.service.get_all_canonical.await_count, 1)
        release.set()
        results = await asyncio.gather(*readers)
        self.assertEqual(len(results), 200)
        self.assertTrue(all(self.btc(item)["usd_live_eligible"] for item in results))
        self.assertEqual(self.service.store.recent_canonical.await_count, 8)
        await self.adapter.get_prices()
        self.assertEqual(self.service.get_all_canonical.await_count, 2)
        self.assertEqual(self.service.store.recent_canonical.await_count, 16)

    async def test_cancelled_waiter_does_not_kill_shared_read_and_failure_retries(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_read():
            started.set()
            await release.wait()
            return {"BTC_USD": self.quote}
        self.service.get_all_canonical.side_effect = slow_read
        first = asyncio.create_task(self.adapter.get_prices())
        second = asyncio.create_task(self.adapter.get_prices())
        await started.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        self.assertTrue(self.btc(await second)["usd_live_eligible"])
        self.assertEqual(self.service.get_all_canonical.await_count, 1)
        self.service.get_all_canonical.side_effect = OSError("test snapshot failure")
        with self.assertRaises(OSError):
            await self.adapter.get_prices()
        self.service.get_all_canonical.side_effect = slow_read
        self.assertTrue(self.btc(await self.adapter.get_prices())["usd_live_eligible"])
        self.assertEqual(self.service.get_all_canonical.await_count, 3)

    async def test_expiry_during_history_read_is_evaluated_when_serving_payload(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_history(*_args, **_kwargs):
            started.set()
            await release.wait()
            return []
        self.service.store.recent_canonical.side_effect = slow_history
        task = asyncio.create_task(self.adapter.get_prices())
        await started.wait()
        self.now += timedelta(seconds=2)
        release.set()
        asset = self.btc(await task)
        self.assertFalse(asset["usd_live_eligible"])
        self.assertEqual(asset["usd_status"], "fresh_cache")

    async def test_disable_during_blocked_history_applies_to_original_and_joining_caller(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_history(*_args, **_kwargs):
            started.set()
            await release.wait()
            return []
        self.service.store.recent_canonical.side_effect = slow_history
        first = asyncio.create_task(self.adapter.get_prices())
        await started.wait()
        self.enabled = False
        second = asyncio.create_task(self.adapter.get_prices())
        await asyncio.sleep(0)
        self.service.get_all_canonical.assert_not_awaited()
        release.set()
        for result in await asyncio.gather(first, second):
            self.assertIsNone(self.btc(result)["price_usd"])
            self.assertEqual(self.btc(result)["usd_status"], "unavailable")
        self.assertEqual(self.service.get_all_canonical.await_count, 1)
        self.assertEqual(self.service.store.recent_canonical.await_count, 8)

    def test_public_http_response_does_not_cache_current_policy_or_deadlines(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers import prices

        app = FastAPI()
        app.include_router(prices.router)
        with patch.object(prices, "legacy_pricing_adapter", self.adapter), TestClient(app) as client:
            response = client.get("/api/prices")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(self.btc(response.json())["usd_status"], "live")
            self.enabled = False
            response = client.get("/api/prices")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIsNone(self.btc(response.json())["price_usd"])
            self.assertEqual(self.btc(response.json())["usd_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
