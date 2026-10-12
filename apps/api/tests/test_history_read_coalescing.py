from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
from threading import Event, Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import create_engine
from app.pricing.history import InternalPriceHistory, _history_supports_bookends


NOW = datetime(2026, 10, 12, 8, tzinfo=UTC)


def point(start):
    return [{"timestamp": start.isoformat(), "open": 100, "close": 101,
             "high": 102, "low": 99, "value": 101, "sample_count": 2}]


class _CapabilitySession:
    def __init__(self, engine, value):
        self.engine, self.value, self.calls = engine, value, 0
        self.lock = Lock()
        self.fail_once = False

    def get_bind(self):
        return self.engine

    def execute(self, _query):
        with self.lock:
            self.calls += 1
            if self.fail_once:
                self.fail_once = False
                raise OSError("test metadata outage")
        return SimpleNamespace(scalar_one=lambda: self.value)


class HistoryCapabilityTests(unittest.TestCase):
    def session(self, value):
        engine = create_engine("postgresql+psycopg://test:test@127.0.0.1:1/history_test")
        self.addCleanup(engine.dispose)
        return _CapabilitySession(engine, value)

    def test_capability_is_once_per_actual_engine_with_true_and_false_isolation(self):
        supported, portable = self.session(True), self.session(False)
        for _index in range(3):
            self.assertTrue(_history_supports_bookends(supported))
            self.assertFalse(_history_supports_bookends(portable))
        self.assertEqual((supported.calls, portable.calls), (1, 1))

    def test_metadata_outage_is_not_cached_as_absent_forever(self):
        session = self.session(True)
        session.fail_once = True
        with self.assertRaises(OSError):
            _history_supports_bookends(session)
        self.assertTrue(_history_supports_bookends(session))
        self.assertTrue(_history_supports_bookends(session))
        self.assertEqual(session.calls, 2)

    def test_200_concurrent_cold_capability_checks_share_one_probe(self):
        session = self.session(True)
        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(executor.map(lambda _index: _history_supports_bookends(session), range(200)))
        self.assertTrue(all(results))
        self.assertEqual(session.calls, 1)

    def test_non_postgres_falls_back_without_database_metadata_probe(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        session = _CapabilitySession(engine, True)
        self.assertFalse(_history_supports_bookends(session))
        self.assertEqual(session.calls, 0)


class HistoryReadCoalescingTests(unittest.IsolatedAsyncioTestCase):
    async def test_200_overlapping_reads_use_one_query_and_next_read_has_fresh_range(self):
        history, started, release = InternalPriceHistory(), Event(), Event()
        self.addCleanup(release.set)
        def read(_instrument, start, _end, _bucket):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test release missing")
            return point(start)
        with patch.object(history, "_query_canonical_history", side_effect=read) as query, \
             patch("app.pricing.history.utc_now", return_value=NOW) as clock:
            readers = [asyncio.create_task(history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h")) for _ in range(200)]
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            await asyncio.sleep(0)
            self.assertEqual(query.call_count, 1)
            release.set()
            results = await asyncio.gather(*readers)
            self.assertTrue(all(result.range_end == NOW for result in results))
            self.assertTrue(all(result.range_start == NOW-timedelta(hours=1) for result in results))
            clock.return_value = NOW+timedelta(seconds=1)
            next_result = await history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h")
            self.assertEqual(query.call_count, 2)
            self.assertEqual(next_result.range_end, NOW+timedelta(seconds=1))

    async def test_waiter_cancellation_does_not_kill_other_readers(self):
        history, started, release = InternalPriceHistory(), Event(), Event()
        self.addCleanup(release.set)
        def read(_instrument, start, _end, _bucket):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test release missing")
            return point(start)
        with patch.object(history, "_query_canonical_history", side_effect=read) as query:
            first = asyncio.create_task(history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW))
            second = asyncio.create_task(history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW))
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            release.set()
            self.assertEqual((await second).range_end, NOW)
            self.assertEqual(query.call_count, 1)

    async def test_shared_failure_clears_for_next_retry(self):
        history = InternalPriceHistory()
        with patch.object(history, "_query_canonical_history", side_effect=OSError("test read failure")) as query:
            results = await asyncio.gather(*(
                history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW) for _ in range(2)
            ), return_exceptions=True)
            self.assertTrue(all(isinstance(result, OSError) for result in results))
            self.assertEqual(query.call_count, 1)
            query.side_effect = lambda _instrument, start, _end, _bucket: point(start)
            self.assertEqual((await history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW)).range_end, NOW)
            self.assertEqual(query.call_count, 2)

    async def test_distinct_ranges_timeframes_and_instances_do_not_share_query(self):
        first, second = InternalPriceHistory(), InternalPriceHistory()
        with patch.object(InternalPriceHistory, "_query_canonical_history", side_effect=lambda _instrument, start, _end, _bucket: point(start)) as query:
            results = await asyncio.gather(
                first.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW),
                first.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW+timedelta(seconds=1)),
                first.canonical_history("GOLD_18K_TOMAN_GRAM", "24h", end=NOW),
                second.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW),
            )
            self.assertEqual(query.call_count, 4)
            self.assertEqual(results[1].range_end, NOW+timedelta(seconds=1))
            self.assertEqual(results[2].range_start, NOW-timedelta(days=1))

    async def test_orphan_failure_is_consumed_and_new_reader_can_retry(self):
        history, started, release = InternalPriceHistory(), Event(), Event()
        self.addCleanup(release.set)
        def read(*_args):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test release missing")
            raise OSError("test abandoned read")
        errors = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        try:
            with patch.object(history, "_query_canonical_history", side_effect=read) as query:
                task = asyncio.create_task(history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW))
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                shared = next(iter(history._canonical_reads.values()))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                release.set()
                await asyncio.wait({shared})
                await asyncio.sleep(0)
                self.assertEqual(history._canonical_reads, {})
                self.assertEqual(errors, [])
                query.side_effect = lambda _instrument, start, _end, _bucket: point(start)
                self.assertEqual((await history.canonical_history("GOLD_18K_TOMAN_GRAM", "1h", end=NOW)).range_end, NOW)
        finally:
            loop.set_exception_handler(previous)


if __name__ == "__main__":
    unittest.main()
