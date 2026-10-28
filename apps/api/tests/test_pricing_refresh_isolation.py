from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "refresh-isolation-test-secret-0123456789")

from app.pricing.service import InstrumentPricingService


class RefreshIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = InstrumentPricingService(store=SimpleNamespace(ping=AsyncMock(return_value=True)))
        self.service.get_canonical = AsyncMock(return_value=None)
        self.service._record_refresh_metrics = lambda *args: None
        self.order = patch("app.pricing.service._REFRESH_ORDER", ("BTC_TOMAN", "XAU_USD_OZ"))
        self.order.start()
        self.addCleanup(self.order.stop)
        self.jitter = patch("app.pricing.service.secrets.randbelow", return_value=0)
        self.jitter.start()
        self.addCleanup(self.jitter.stop)
        from app.config import settings
        self.interval = patch.object(settings, "pricing_refresh_interval_seconds", 0.2)
        self.interval.start()
        self.addCleanup(self.interval.stop)

    async def asyncTearDown(self):
        await self.service.cancel_refreshes()

    async def test_stalled_source_does_not_delay_next_crypto_refresh_or_duplicate_work(self):
        gate = asyncio.Event()
        calls = []

        async def refresh(name):
            calls.append(name)
            if name == "XAU_USD_OZ":
                await gate.wait()
            return None

        self.service.refresh_instrument = refresh
        first = await asyncio.wait_for(self.service.refresh_cycle(), timeout=1)
        self.assertEqual(first, {"BTC_TOMAN": "unavailable", "XAU_USD_OZ": "refreshing"})
        slow = self.service._refresh_tasks["XAU_USD_OZ"]
        second = await asyncio.wait_for(self.service.refresh_cycle(), timeout=1)
        self.assertIs(self.service._refresh_tasks["XAU_USD_OZ"], slow)
        self.assertEqual(calls.count("BTC_TOMAN"), 2)
        self.assertEqual(calls.count("XAU_USD_OZ"), 1)
        self.assertEqual(second["XAU_USD_OZ"], "refreshing")

    async def test_cached_live_quote_avoids_provider_calls(self):
        current = SimpleNamespace(valid_until=datetime.now(UTC) + timedelta(seconds=60))
        self.service.get_canonical = AsyncMock(return_value=current)
        self.service.refresh_instrument = AsyncMock()
        result = await self.service.refresh_cycle()
        self.assertEqual(set(result.values()), {"fresh"})
        self.service.refresh_instrument.assert_not_awaited()

    async def test_bad_cached_record_is_contained_to_one_instrument(self):
        async def current(name):
            if name == "XAU_USD_OZ":
                raise ValueError("private source detail")
            return None

        self.service.get_canonical = current
        self.service.refresh_instrument = AsyncMock(return_value=None)
        with self.assertLogs("app.pricing.service", level="WARNING") as logs:
            result = await self.service.refresh_cycle()
        self.assertEqual(result["XAU_USD_OZ"], "failed:ValueError")
        self.assertEqual(result["BTC_TOMAN"], "unavailable")
        self.assertNotIn("private source detail", str(logs.output))

    async def test_redis_loss_cancels_owned_pending_work(self):
        entered, finished = asyncio.Event(), asyncio.Event()

        async def refresh(name):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        self.service.refresh_instrument = refresh
        await self.service.refresh_cycle()
        self.assertTrue(entered.is_set())
        self.service.store.ping.return_value = False
        result = await self.service.refresh_cycle()
        self.assertEqual(set(result.values()), {"suspended_redis_unavailable"})
        self.assertTrue(finished.is_set())
        self.assertEqual(self.service._refresh_tasks, {})

    async def test_cancelled_cycle_awaits_all_children(self):
        entered = asyncio.Event()

        async def refresh(name):
            entered.set()
            await asyncio.Event().wait()

        self.service.refresh_instrument = refresh
        cycle = asyncio.create_task(self.service.refresh_cycle())
        await asyncio.wait_for(entered.wait(), timeout=1)
        children = tuple(self.service._refresh_tasks.values())
        cycle.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cycle
        self.assertTrue(all(task.done() for task in children))
        self.assertEqual(self.service._refresh_tasks, {})
