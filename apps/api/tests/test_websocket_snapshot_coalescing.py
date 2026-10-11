from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.websocket import PriceWebSocketHub


class WebSocketSnapshotCoalescingTests(unittest.IsolatedAsyncioTestCase):
    async def test_200_concurrent_readers_share_one_current_read(self):
        gate = asyncio.Event()
        async def read():
            await gate.wait()
            return {}
        reader = AsyncMock(side_effect=read)
        hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=reader)
        waiters = [asyncio.create_task(hub._read_snapshot()) for _ in range(200)]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        reader.assert_awaited_once()
        gate.set()
        self.assertEqual(await asyncio.gather(*waiters), [{}]*200)
        self.assertIsNone(hub._snapshot_task)
        # A completed read is not a retained cache or policy bypass.
        await hub._read_snapshot()
        self.assertEqual(reader.await_count, 2)

    async def test_cancelled_waiter_does_not_cancel_shared_read(self):
        started, gate = asyncio.Event(), asyncio.Event()
        async def read():
            started.set()
            await gate.wait()
            return {}
        reader = AsyncMock(side_effect=read)
        hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=reader)
        first = asyncio.create_task(hub._read_snapshot())
        second = asyncio.create_task(hub._read_snapshot())
        await started.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(hub._snapshot_task.cancelled())
        gate.set()
        self.assertEqual(await second, {})
        reader.assert_awaited_once()
        self.assertIsNone(hub._snapshot_task)

    async def test_shared_failure_is_cleared_and_next_read_retries(self):
        gate = asyncio.Event()
        async def read():
            await gate.wait()
            raise RuntimeError("snapshot_read_failed")
        reader = AsyncMock(side_effect=read)
        hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=reader)
        waiters = [asyncio.create_task(hub._read_snapshot()) for _ in range(20)]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gate.set()
        results = await asyncio.gather(*waiters, return_exceptions=True)
        self.assertTrue(all(isinstance(result, RuntimeError) for result in results))
        self.assertIsNone(hub._snapshot_task)
        reader.side_effect = None
        reader.return_value = {}
        self.assertEqual(await hub._read_snapshot(), {})
        self.assertEqual(reader.await_count, 2)

    async def test_independent_hubs_do_not_share_snapshot_task(self):
        gate = asyncio.Event()
        async def read():
            await gate.wait()
            return {}
        reader = AsyncMock(side_effect=read)
        first_hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=reader)
        second_hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=reader)
        first = asyncio.create_task(first_hub._read_snapshot())
        second = asyncio.create_task(second_hub._read_snapshot())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(reader.await_count, 2)
        self.assertIsNot(first_hub._snapshot_task, second_hub._snapshot_task)
        gate.set()
        self.assertEqual(await asyncio.gather(first, second), [{}, {}])

    async def test_orphaned_failed_read_is_consumed_and_retryable(self):
        started, gate = asyncio.Event(), asyncio.Event()
        async def read():
            started.set()
            await gate.wait()
            raise RuntimeError("orphaned_snapshot_failure")
        reader = AsyncMock(side_effect=read)
        hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=reader)
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        errors = []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        try:
            waiter = asyncio.create_task(hub._read_snapshot())
            await started.wait()
            shared = hub._snapshot_task
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            gate.set()
            await asyncio.wait({shared})
            await asyncio.sleep(0)
            self.assertIsNone(hub._snapshot_task)
            self.assertEqual(errors, [])
            reader.side_effect = None
            reader.return_value = {}
            self.assertEqual(await hub._read_snapshot(), {})
        finally:
            loop.set_exception_handler(previous_handler)


if __name__ == "__main__":
    unittest.main()
