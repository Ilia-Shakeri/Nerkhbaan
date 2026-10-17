from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.models import User
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.db_models import InstrumentRecord, PricingBackfillJobRecord
from app.pricing.history import HistoryResult
from app.pricing.instruments import get_instrument
from app.pricing.registry import PROVIDERS
from app.pricing.service import InstrumentPricingService


NOW = datetime(2026, 10, 11, 12, 5, tzinfo=UTC)


class _Redis:
    def __init__(self):
        self.values = {}
        self.ttls = []
        self.available = True

    async def set(self, key, value, *, nx, px):
        if not self.available:
            raise OSError("test outage")
        self.ttls.append(px)
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script, _number, key, owner):
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0

    async def xadd(self, *_args, **_kwargs):
        raise OSError("test stream outage")


class AutomaticBackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nerkhbaan-auto-test-")
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / "jobs.sqlite"
        self.engine = create_engine(f"sqlite:///{path.as_posix()}", poolclass=QueuePool,
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        for table in (User.__table__, InstrumentRecord.__table__, PricingBackfillJobRecord.__table__):
            table.to_metadata(metadata)
        # SQLite generates row IDs only for the exact INTEGER declaration.
        metadata.tables["pricing_backfill_jobs"].c.id.type = Integer()
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        patcher = patch("app.pricing.backfill.SessionLocal", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.redis = _Redis()
        self.store = AsyncMock()
        self.store.client = lambda: self.redis
        self.operational = AsyncMock()
        self.operational.instrument.return_value = get_instrument("BTC_USD")
        self.operational.feature_enabled.return_value = True
        self.operational.providers_for.return_value = (PROVIDERS["coingecko_btc"],)
        self.queue = PricingBackfillQueue(store=self.store, operational=self.operational)

    async def enqueue(self, shift=timedelta(), *, automatic=True):
        method = self.queue.enqueue_automatic if automatic else self.queue.enqueue
        options = {"bucket_seconds": 900} if automatic else {}
        return await method(instrument_id="BTC_USD", range_start=NOW-timedelta(days=1)+shift,
                            range_end=NOW+shift, **options)

    def jobs(self):
        with self.sessions() as session:
            return session.scalars(select(PricingBackfillJobRecord)).all()

    async def test_200_microsecond_requests_create_one_exact_durable_range(self):
        results = await asyncio.gather(*(
            self.enqueue(timedelta(microseconds=index)) for index in range(200)
        ))
        self.assertEqual(sum(item.status == "queued" for item in results), 1)
        self.assertEqual(sum(item.status == "coalesced" for item in results), 199)
        self.assertEqual(len(self.jobs()), 1)
        job = self.jobs()[0]
        self.assertEqual(job.range_start.replace(tzinfo=UTC), NOW-timedelta(days=1))
        self.assertEqual(job.range_end.replace(tzinfo=UTC), NOW)
        self.assertEqual(job.attempt_count, 0)
        self.assertTrue(all(value == 60_000 for value in self.redis.ttls))

    async def test_manual_enqueue_and_new_bucket_keep_exact_ranges(self):
        self.assertEqual((await self.enqueue()).status, "queued")
        self.assertEqual((await self.enqueue(timedelta(microseconds=1), automatic=False)).status, "queued")
        self.assertEqual((await self.enqueue(timedelta(minutes=15))).status, "queued")
        self.assertEqual(len(self.jobs()), 3)
        self.assertEqual((await self.enqueue(timedelta(minutes=15, microseconds=1))).status, "coalesced")
        self.assertEqual(len(self.jobs()), 3)

    async def test_failed_storage_releases_guard_and_next_request_retries(self):
        with patch.object(self.queue, "_insert_job", side_effect=OSError("test db outage")):
            with self.assertRaises(OSError):
                await self.enqueue()
        self.assertEqual(self.redis.values, {})
        self.assertEqual((await self.enqueue()).status, "queued")
        self.assertEqual(len(self.jobs()), 1)

    async def test_redis_outage_defers_automatic_but_manual_database_still_works(self):
        self.redis.available = False
        self.assertEqual((await self.enqueue()).status, "deferred")
        self.assertEqual(self.jobs(), [])
        self.assertEqual((await self.enqueue(automatic=False)).status, "queued")
        self.assertEqual(len(self.jobs()), 1)

    async def test_cancelled_enqueue_releases_own_guard_and_preserves_other_owner(self):
        started = asyncio.Event()
        async def wait_forever(**_kwargs):
            started.set()
            await asyncio.Event().wait()
        with patch.object(self.queue, "enqueue", side_effect=wait_forever):
            task = asyncio.create_task(self.enqueue())
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.redis.values, {})
        self.assertEqual((await self.enqueue()).status, "queued")
        key = next(iter(self.redis.values))
        async def lost_lease(**_kwargs):
            self.redis.values[key] = "another-owner"
            raise OSError("test failure after lease changed")
        self.redis.values.clear()
        with patch.object(self.queue, "enqueue", side_effect=lost_lease):
            with self.assertRaises(OSError):
                await self.enqueue()
        self.assertEqual(self.redis.values[key], "another-owner")

    async def test_fresh_scoped_policy_disable_is_checked_even_with_existing_guard(self):
        await self.enqueue()
        self.operational.feature_enabled.return_value = False
        self.assertEqual((await self.enqueue(timedelta(microseconds=1))).status, "disabled")
        self.assertEqual(len(self.jobs()), 1)
        self.operational.feature_enabled.return_value = True
        self.operational.providers_for.return_value = ()
        self.assertEqual((await self.enqueue()).status, "coalesced")
        self.redis.values.clear()
        self.assertEqual((await self.enqueue()).status, "unsupported")
        self.assertEqual(self.redis.values, {})
        self.assertEqual(len(self.jobs()), 1)

    async def test_expired_guard_rechecks_queue_without_changing_original_job(self):
        first = await self.enqueue()
        original = self.jobs()[0]
        self.redis.values.clear()
        repeated = await self.enqueue()
        self.assertEqual(first.database_job_id, repeated.database_job_id)
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.jobs()[0].range_start, original.range_start)
        self.assertEqual(self.jobs()[0].range_end, original.range_end)

    async def test_static_missing_history_route_skips_policy_and_enqueue(self):
        history = AsyncMock()
        history.canonical_history.return_value = HistoryResult(
            "SILVER_999_TOMAN_GRAM", "30d", "partial", NOW-timedelta(days=30), NOW, []
        )
        service = InstrumentPricingService(history=history, backfill=self.queue,
                                           operational=self.operational)
        with patch("app.pricing.service.PROVIDERS_BY_INSTRUMENT", {"SILVER_999_TOMAN_GRAM": ()}):
            result = await service.canonical_history("SILVER_999_TOMAN_GRAM", "30d")
        self.assertEqual(result.status, "partial")
        self.operational.instrument.assert_not_awaited()
        self.operational.providers_for.assert_not_awaited()
        self.assertEqual(self.jobs(), [])


if __name__ == "__main__":
    unittest.main()
