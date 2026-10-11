from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import MetaData, create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.admin.models import OperationalSetting
from app.models import User
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.db_models import InstrumentRecord, PricingBackfillJobRecord
from app.pricing.instruments import get_instrument
from app.pricing.operational import OperationalPricingSettings
from app.pricing.registry import PROVIDERS


NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


class _Locks:
    @asynccontextmanager
    async def backfill_lock(self, _instrument_id):
        yield object()


class BackfillFairnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nerkhbaan-fairness-test-")
        self.addCleanup(self.directory.cleanup)
        database = Path(self.directory.name) / "fairness.sqlite"
        # Worker threads need separate connections, as they have in production.
        self.engine = create_engine(f"sqlite:///{database.as_posix()}", poolclass=QueuePool,
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        for table in (User.__table__, OperationalSetting.__table__, InstrumentRecord.__table__, PricingBackfillJobRecord.__table__):
            table.to_metadata(metadata)
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.providers = {
            "BTC_USD": (PROVIDERS["coingecko_btc"],),
            "USD_TOMAN": (replace(PROVIDERS["servix_usd_toman"], enabled=True, api_key_setting=None),),
        }
        for target, value in (
            ("app.pricing.backfill.SessionLocal", self.sessions),
            ("app.pricing.operational.SessionLocal", self.sessions),
            ("app.pricing.backfill.utc_now", lambda: NOW),
            ("app.pricing.backfill.PROVIDERS_BY_INSTRUMENT", self.providers),
            ("app.pricing.operational.PROVIDERS_BY_INSTRUMENT", self.providers),
        ):
            patched = patch(target, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.store = AsyncMock()
        self.store.ping.return_value = True
        self.store.get_canonical.return_value = SimpleNamespace(valid_until=NOW + timedelta(minutes=5))
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = SimpleNamespace(allowed=True)
        self.operational = OperationalPricingSettings()
        self.queue = PricingBackfillQueue(store=self.store, budgets=self.budgets, locks=_Locks(), operational=self.operational)
        self.queue._drain_redis_jobs = AsyncMock()
        self.queue._execute_history_job = AsyncMock(return_value=3)
        with self.sessions() as db:
            for instrument_id in ("BTC_USD", "USD_TOMAN", "XAU_USD_OZ"):
                instrument = get_instrument(instrument_id)
                db.add(InstrumentRecord(
                    instrument_id=instrument_id, base_asset=instrument.base_asset,
                    quote_currency=instrument.quote_currency.value, market=instrument.market.value,
                    region=instrument.region.value, weight_unit=instrument.weight_unit.value,
                    purity=str(instrument.purity) if instrument.purity is not None else None,
                    display_decimals=instrument.display_decimals,
                    operational_ttl_seconds=instrument.operational_ttl_seconds,
                    stale_after_seconds=instrument.stale_after_seconds, expire_after_seconds=instrument.expire_after_seconds,
                    base_anomaly_threshold_percent=instrument.base_anomaly_threshold_percent,
                    maximum_dynamic_threshold_percent=instrument.maximum_dynamic_threshold_percent,
                    minimum_sanity_price=instrument.minimum_price, maximum_sanity_price=instrument.maximum_price,
                    importance=instrument.importance, enabled=True, allow_derived_fallback=instrument.allow_derived_fallback,
                ))
            db.add(OperationalSetting(key="backfill_enabled", scope_id="global", value=True))
            db.commit()

    def _job(self, job_id, instrument_id="BTC_USD", **values):
        fields = dict(
            id=job_id, instrument_id=instrument_id, range_start=NOW - timedelta(hours=1), range_end=NOW,
            status="deferred", priority=100, attempt_count=0, idempotency_key=f"job-{job_id}",
            created_at=NOW - timedelta(days=2), updated_at=NOW - timedelta(minutes=6),
            next_attempt_at=NOW - timedelta(minutes=1), last_error="no_explicit_history_provider",
        )
        fields.update(values)
        return PricingBackfillJobRecord(**fields)

    def _setting(self, key, scope_id, value):
        with self.sessions() as db:
            row = db.scalar(select(OperationalSetting).where(OperationalSetting.key == key, OperationalSetting.scope_id == scope_id))
            if row is None:
                db.add(OperationalSetting(key=key, scope_id=scope_id, value=value))
            else:
                row.value = value
            db.commit()

    async def test_eligible_history_behind_thousand_unsupported_jobs_completes(self):
        with self.sessions() as db:
            db.add_all(self._job(job_id, "XAU_USD_OZ", priority=1) for job_id in range(1, 1001))
            db.add(self._job(1001, priority=200, created_at=NOW))
            db.commit()
        with patch.object(self.operational, "instrument", wraps=self.operational.instrument) as resolve:
            counts = await self.queue.process_jobs(maximum_jobs=1)
        self.assertEqual(counts, {"completed": 1, "deferred": 0, "failed": 0})
        self.assertLessEqual(resolve.await_count, len(self.providers) + 1)
        self.assertEqual(self.queue._execute_history_job.call_args.args[0]["id"], 1001)
        with self.sessions() as db:
            untouched = db.scalar(select(func.count()).select_from(PricingBackfillJobRecord).where(
                PricingBackfillJobRecord.instrument_id == "XAU_USD_OZ",
                PricingBackfillJobRecord.status == "deferred", PricingBackfillJobRecord.attempt_count == 0,
                PricingBackfillJobRecord.last_error == "no_explicit_history_provider",
                PricingBackfillJobRecord.updated_at == NOW - timedelta(minutes=6),
                PricingBackfillJobRecord.next_attempt_at == NOW - timedelta(minutes=1),
            ))
            self.assertEqual(untouched, 1000)
            completed = db.get(PricingBackfillJobRecord, 1001)
            self.assertEqual(completed.attempt_count, 1)
            self.assertIsNotNone(completed.completed_at)

    async def test_provider_policy_enable_reactivates_existing_deferred_job(self):
        with self.sessions() as db:
            db.add(self._job(1))
            db.commit()
        self._setting("provider.config", "coingecko_btc", {"enabled": False})
        self.assertEqual(await self.queue.process_jobs(maximum_jobs=1), {"completed": 0, "deferred": 0, "failed": 0})
        self.queue._execute_history_job.assert_not_called()
        with self.sessions() as db:
            old = db.get(PricingBackfillJobRecord, 1)
            self.assertEqual((old.status, old.attempt_count, old.last_error), ("deferred", 0, "no_explicit_history_provider"))
        self._setting("provider.config", "coingecko_btc", {"enabled": True})
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 1)
        self.assertEqual(self.queue._execute_history_job.call_args.args[0]["id"], 1)

    async def test_scoped_feature_and_instrument_enable_reactivate_old_job(self):
        with self.sessions() as db:
            db.add(self._job(1))
            db.get(InstrumentRecord, "BTC_USD").enabled = False
            db.commit()
        self._setting("backfill_enabled", "BTC_USD", False)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 0)
        with self.sessions() as db:
            db.get(InstrumentRecord, "BTC_USD").enabled = True
            db.commit()
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 0)
        self._setting("backfill_enabled", "BTC_USD", True)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 1)

    async def test_missing_live_quote_cannot_starve_independent_history_and_fresh_live_resumes(self):
        with self.sessions() as db:
            db.add_all([self._job(1, priority=1, last_error="live_refresh_has_priority"),
                        self._job(2, "USD_TOMAN", priority=200, created_at=NOW)])
            db.commit()
        self.store.get_canonical.return_value = None
        self.assertEqual(await self.queue.process_jobs(maximum_jobs=1), {"completed": 1, "deferred": 0, "failed": 0})
        self.assertEqual(self.queue._execute_history_job.call_args.args[0]["id"], 2)
        with self.sessions() as db:
            old = db.get(PricingBackfillJobRecord, 1)
            self.assertEqual((old.status, old.attempt_count, old.last_error), ("deferred", 0, "live_refresh_has_priority"))
        self.store.get_canonical.return_value = SimpleNamespace(valid_until=NOW + timedelta(minutes=5))
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 1)
        self.assertEqual(self.queue._execute_history_job.call_args.args[0]["id"], 1)

    async def test_independent_history_remains_eligible_when_live_cache_is_unavailable(self):
        self.store.get_canonical.side_effect = RuntimeError("live cache unavailable")
        with self.sessions() as db:
            db.add(self._job(1, "USD_TOMAN"))
            db.commit()
        self.assertEqual(await self.queue.process_jobs(maximum_jobs=1), {"completed": 1, "deferred": 0, "failed": 0})

    async def test_expired_live_quote_skips_shared_history_without_mutating_old_job(self):
        self.store.get_canonical.return_value = SimpleNamespace(valid_until=NOW - timedelta(seconds=1))
        with self.sessions() as db:
            db.add(self._job(1, last_error="live_refresh_has_priority"))
            db.commit()
        self.assertEqual(await self.queue.process_jobs(maximum_jobs=1), {"completed": 0, "deferred": 0, "failed": 0})
        self.queue._execute_history_job.assert_not_called()
        self.budgets.consume.assert_not_called()
        with self.sessions() as db:
            old = db.get(PricingBackfillJobRecord, 1)
            self.assertEqual((old.status, old.attempt_count, old.last_error), ("deferred", 0, "live_refresh_has_priority"))
            self.assertEqual(old.next_attempt_at.replace(tzinfo=UTC), NOW - timedelta(minutes=1))

    async def test_filtered_claim_preserves_due_times_leases_and_attempts(self):
        with self.sessions() as db:
            db.add_all([
                self._job(1, status="processing", updated_at=NOW - timedelta(minutes=9), attempt_count=1),
                self._job(2, status="retrying", next_attempt_at=NOW + timedelta(minutes=1), attempt_count=1),
                self._job(3, status="processing", updated_at=NOW - timedelta(minutes=11), attempt_count=2),
                self._job(4, status="cancelled"),
            ])
            db.commit()
        job = self.queue._claim_job(("BTC_USD",))
        self.assertEqual((job["id"], job["attempt_count"]), (3, 3))
        self.assertTrue(self.queue._renew_job(3, 3))
        self.assertFalse(self.queue._renew_job(3, 2))
        self.queue._retry_job(3, "fetch unavailable", 3)
        self.assertIsNone(self.queue._claim_job(("BTC_USD",)))
        with self.sessions() as db:
            retry = db.get(PricingBackfillJobRecord, 3)
            self.assertEqual((retry.status, retry.attempt_count), ("retrying", 3))
            self.assertEqual(retry.next_attempt_at.replace(tzinfo=UTC), NOW + timedelta(minutes=15))
            self.assertEqual(db.get(PricingBackfillJobRecord, 1).attempt_count, 1)
            self.assertEqual(db.get(PricingBackfillJobRecord, 4).status, "cancelled")

    def test_empty_eligibility_does_not_touch_database_queue(self):
        with patch("app.pricing.backfill.SessionLocal") as sessions:
            self.assertIsNone(self.queue._claim_job(()))
        sessions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
