from __future__ import annotations

import asyncio
import os
import re
import unittest
import uuid
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import Column, MetaData, String, Table, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing import rights
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.budgets import BudgetDecision
from app.pricing.db_models import CanonicalQuoteRecord, ProviderQuoteRecord, PricingBackfillJobRecord
from app.pricing.history import InternalPriceHistory
from app.pricing.history import _history_supports_bookends
from app.pricing.instruments import get_instrument
from app.pricing.persistence import PricingPersistence
from app.pricing.registry import PROVIDERS
from app.pricing.models import CanonicalQuote, CanonicalStatus, ProviderQuote, SourceType, ValidationStatus
from app.pricing.parsers.wallgold_history import WallgoldSilver925HistoryParser
if __package__:
    from .test_pricing_rights_postgres import _OwnedPostgresFixture
    from .test_source_snapshots import _Redis
else:
    from test_pricing_rights_postgres import _OwnedPostgresFixture
    from test_source_snapshots import _Redis

TEST_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "Requires an explicitly owned test PostgreSQL database")
class NerkhsanjHistoryPostgresTests(_OwnedPostgresFixture, unittest.TestCase):
    owned_table_names = ("instruments", "canonical_quotes", "provider_quotes", "pricing_backfill_jobs")

    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("Only a named test/CI PostgreSQL database is permitted")
        cls.schema = "nerkhsanj_history_test_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, hide_parameters=True)
        cls.public_fingerprint = cls._public_fingerprint()
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        try:
            cls.engine = create_engine(url, hide_parameters=True,
                                       connect_args={"options": f"-csearch_path={cls.schema},public"})
            cls.sessions = sessionmaker(bind=cls.engine)
            metadata = MetaData(schema=cls.schema)
            Table("instruments", metadata, Column("instrument_id", String(64), primary_key=True), schema=cls.schema)
            for model in (CanonicalQuoteRecord, ProviderQuoteRecord, PricingBackfillJobRecord):
                model.__table__.to_metadata(metadata, schema=cls.schema)
            metadata.create_all(cls.engine)
            cls._install_ownership_guard()
        except Exception:
            cls.cleanup()
            raise

    @classmethod
    def cleanup(cls):
        if hasattr(cls, "public_fingerprint"):
            if cls._public_fingerprint() != cls.public_fingerprint:
                raise AssertionError("Existing public data changed during the isolated fixture")
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        try:
            if not re.fullmatch(r"nerkhsanj_history_test_[0-9a-f]{32}", cls.schema):
                raise AssertionError("Refusing cleanup outside the owned schema")
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
        finally:
            cls.admin_engine.dispose()

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    def setUp(self):
        self.addCleanup(self._assert_public_unchanged)
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        self.enterContext(patch.object(settings, "pricing_rights_manifest_path", None))
        self.enterContext(patch("app.pricing.history.SessionLocal", self.sessions))
        self.enterContext(patch("app.pricing.persistence.SessionLocal", self.sessions))
        self.enterContext(patch("app.pricing.backfill.SessionLocal", self.sessions))
        self.provider = PROVIDERS["nerkhsanj_silver999_history"]
        self.start, self.end = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 16, tzinfo=UTC)
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM canonical_quotes"))
            connection.execute(text("DELETE FROM provider_quotes"))
            connection.execute(text("DELETE FROM pricing_backfill_jobs"))
            connection.execute(text("INSERT INTO instruments(instrument_id) VALUES (:id) ON CONFLICT DO NOTHING"), {"id": self.provider.instrument_id})

    async def ingest(self):
        payload = {"series": [{"key": "silver", "name": "Silver 999",
                                "days": [["1405/07/22", 502340], ["1405/07/23", 517260]]}]}
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
        operational = SimpleNamespace(instrument=AsyncMock(return_value=get_instrument(self.provider.instrument_id)))
        store, budgets, redis = AsyncMock(), AsyncMock(), _Redis()
        store.client = lambda: redis
        budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        queue = PricingBackfillQueue(store=store, budgets=budgets,
                                     persistence=PricingPersistence(store=store), operational=operational)
        with patch("app.pricing.backfill.httpx.AsyncClient", return_value=client):
            return await queue._execute_history_job({"id": 1, "instrument_id": self.provider.instrument_id,
                "range_start": self.start, "range_end": self.end, "attempt_count": 1}, self.provider)

    def instant(self, stamp, price, summary=None):
        quote = CanonicalQuote.create(instrument_id=self.provider.instrument_id, price=Decimal(str(price)),
            status=CanonicalStatus.LIVE, primary_quote_id=None, verification_quote_ids=[],
            source_summary=summary or {"provider_ids": ["owned_instant"], "primary_provider_id": "owned_instant", "derived": False},
            canonical_at=stamp, observed_at=stamp, valid_until=self.end, stale_at=self.end,
            expires_at=self.end, is_persisted=False, decision_reason="owned_instant_fixture")
        PricingPersistence._persist_canonical(quote)
        return quote

    def with_instant_grant(self):
        grants = deepcopy(rights.grants())
        grants["owned_instant"] = deepcopy(grants["gold_api_free_xag"])
        return grants

    def daily(self, stamp, price, provider_id, metadata, instrument_id=None):
        instrument = get_instrument(instrument_id or self.provider.instrument_id)
        quote = ProviderQuote.create(
            instrument_id=instrument.instrument_id, provider_id=provider_id, source_type=SourceType.HTTP,
            price=Decimal(str(price)), currency=instrument.quote_currency, weight_unit=instrument.weight_unit,
            purity=instrument.purity, observed_at=stamp, received_at=self.end,
            parser_version="owned-daily-fixture/1", validation_status=ValidationStatus.ACCEPTED,
            metadata={"quote_role": "backfill", **metadata},
        )
        PricingPersistence._persist_provider_quote(quote)
        canonical = CanonicalQuote.create(
            instrument_id=instrument.instrument_id, price=quote.price, status=CanonicalStatus.CONFIRMED,
            primary_quote_id=quote.id, verification_quote_ids=[],
            source_summary={"provider_ids": [provider_id], "primary_provider_id": provider_id,
                            "derived": False, "historical_backfill": True, **metadata},
            canonical_at=stamp, observed_at=stamp, valid_until=stamp + timedelta(minutes=1),
            stale_at=stamp + timedelta(minutes=5), expires_at=stamp + timedelta(minutes=20),
            is_persisted=False, decision_reason="owned_daily_fixture",
        )
        PricingPersistence._persist_canonical(canonical)
        return canonical

    def daily_grants(self):
        grants = self.with_instant_grant()
        for name in ("owned_utc_daily", "owned_other_daily"):
            grants[name] = deepcopy(grants["gold_api_free_xag"])
            grants[name]["attribution"] = {"label": name, "url": f"https://fixture.example.invalid/{name}"}
        return grants

    def test_utc_daily_storage_and_public_dto_preserve_gregorian_source_day(self):
        from app.schemas import PricePoint

        instrument_id = "SILVER_925_TOMAN_GRAM"
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO instruments(instrument_id) VALUES (:id) ON CONFLICT DO NOTHING"),
                               {"id": instrument_id})
        payload = {"success": True, "result": {"chart": {"data": [{
            "date": "2026-10-14T00:00:00Z", "open": 475000, "low": 465000,
            "high": 480000, "close": 467000,
        }]}}}
        with patch("app.pricing.parsers.wallgold_history.utc_now", return_value=self.end):
            point, = WallgoldSilver925HistoryParser().parse(payload, get_instrument(instrument_id), self.start, self.end)
        with patch.object(rights, "grants", return_value=self.daily_grants()):
            self.daily(point.observed_at, point.price, "owned_utc_daily", point.metadata, instrument_id)
            with self.sessions() as db:
                bookends = _history_supports_bookends(db)
            for use_bookends in ((False, True) if bookends else (False,)):
                with self.subTest(use_bookends=use_bookends):
                    with patch("app.pricing.history._history_supports_bookends", return_value=use_bookends):
                        row, = InternalPriceHistory._query_canonical_history(instrument_id, self.start, self.end, "4 hours")
                    self.assertEqual(row["timestamp"], "2026-10-14T00:00:00+00:00")
                    self.assertEqual(row["source_timezone"], "UTC")
                    self.assertEqual(row["source_calendar"], "gregorian")
                    self.assertEqual(row["source_date"], "2026-10-14")
                    self.assertFalse(row["source_observation_time_known"])
                    public = PricePoint.model_validate({**row, "value_usd": None, "value_toman": row["value"]})
                    self.assertEqual(public.source_calendar, "gregorian")
            provider_row, = InternalPriceHistory._query_provider_history(instrument_id, "owned_utc_daily", self.start, self.end)
            self.assertEqual((provider_row["source_timezone"], provider_row["source_calendar"], provider_row["source_date"]),
                             ("UTC", "gregorian", "2026-10-14"))
            self.assertIsNone(InternalPriceHistory._query_latest_canonical(instrument_id))

    def test_daily_groups_never_mix_timezone_calendar_or_source_date(self):
        stamp = datetime(2026, 10, 14, tzinfo=UTC)
        metadata = {"timestamp_precision": "day", "timestamp_role": "day_bucket_start",
                    "source_observation_time_known": False, "source_timezone": "UTC",
                    "source_calendar": "gregorian", "source_date": "2026-10-14"}
        entries = [
            (400000, "owned_utc_daily", metadata), (410000, "owned_utc_daily", metadata),
            (700000, "owned_other_daily", {**metadata, "source_date": "2026-10-15"}),
            (800000, "owned_other_daily", {**metadata, "source_calendar": "jalali"}),
            (900000, "owned_other_daily", {**metadata, "source_timezone": "Asia/Tehran"}),
        ]
        with self.sessions() as db:
            bookends = _history_supports_bookends(db)
        with patch.object(rights, "grants", return_value=self.daily_grants()):
            for reverse in (False, True):
                with self.engine.begin() as connection:
                    connection.execute(text("DELETE FROM canonical_quotes"))
                    connection.execute(text("DELETE FROM provider_quotes"))
                for price, provider_id, info in (reversed(entries) if reverse else entries):
                    self.daily(stamp, price, provider_id, info)
                for use_bookends in ((False, True) if bookends else (False,)):
                    with self.subTest(reverse=reverse, use_bookends=use_bookends):
                        with patch("app.pricing.history._history_supports_bookends", return_value=use_bookends):
                            row, = InternalPriceHistory._query_canonical_history(self.provider.instrument_id, self.start, self.end, "1 day")
                        self.assertEqual(row["sample_count"], 2)
                        self.assertEqual((row["source_timezone"], row["source_calendar"], row["source_date"]),
                                         ("UTC", "gregorian", "2026-10-14"))
                        self.assertEqual((row["low"], row["high"]), (400000, 410000))
                        self.assertIn(row["value"], (400000, 410000))
                        self.assertEqual(row["attributions"], [self.daily_grants()["owned_utc_daily"]["attribution"]])

    def test_daily_without_source_calendar_never_invents_a_jalali_label(self):
        stamp = datetime(2026, 10, 14, tzinfo=UTC)
        with patch.object(rights, "grants", return_value=self.daily_grants()):
            self.daily(stamp, 400000, "owned_utc_daily", {
                "timestamp_precision": "day", "timestamp_role": "day_bucket_start", "source_date": "2026-10-14",
            })
            row, = InternalPriceHistory._query_canonical_history(self.provider.instrument_id, self.start, self.end, "1 day")
        self.assertIsNone(row["source_timezone"])
        self.assertIsNone(row["source_calendar"])
        self.assertEqual(row["source_date"], "2026-10-14")

    def test_real_storage_and_chart_preserve_daily_label_and_source_attribution(self):
        self.assertEqual(asyncio.run(self.ingest()), 2)
        rows = InternalPriceHistory._query_canonical_history(self.provider.instrument_id, self.start, self.end, "4 hours")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["timestamp"], "2026-10-14T20:30:00+00:00")
        self.assertEqual(rows[-1]["source_date"], "1405/07/23")
        self.assertEqual(rows[-1]["value"], 517260)
        self.assertEqual(rows[-1]["timestamp_precision"], "day")
        self.assertIs(rows[-1]["source_observation_time_known"], False)
        self.assertEqual(rows[-1]["attributions"], [rights.grants()[self.provider.provider_id]["attribution"]])
        sources = InternalPriceHistory._query_provider_history(self.provider.instrument_id, self.provider.provider_id, self.start, self.end)
        self.assertEqual(sources[-1]["source_date"], "1405/07/23")
        self.assertEqual(sources[-1]["timestamp_role"], "day_bucket_start")

    def test_daily_labels_cannot_be_used_as_current_or_instant_baseline(self):
        self.assertEqual(asyncio.run(self.ingest()), 2)
        self.assertIsNone(InternalPriceHistory._query_latest_canonical(self.provider.instrument_id))
        self.assertIsNone(InternalPriceHistory._query_baseline(self.provider.instrument_id, self.end, self.start))
        self.assertEqual(InternalPriceHistory._query_recent_prices(self.provider.instrument_id, 10), [])
        self.assertEqual(InternalPriceHistory._query_latest_sources(self.provider.instrument_id), [])

    def test_source_identity_cannot_be_relabelled_as_a_current_quote(self):
        self.assertEqual(asyncio.run(self.ingest()), 2)
        with self.engine.begin() as connection:
            connection.execute(text("""UPDATE canonical_quotes SET
                source_summary = source_summary - 'historical_backfill' - 'timestamp_precision',
                valid_until = NOW() + interval '1 hour', stale_at = NOW() + interval '2 hours',
                expires_at = NOW() + interval '3 hours'"""))
        self.assertIsNone(InternalPriceHistory._query_latest_canonical(self.provider.instrument_id))

    def test_daily_and_instant_collision_prefers_only_instant_group(self):
        with self.sessions() as db:
            bookends = _history_supports_bookends(db)
        with patch.object(rights, "grants", return_value=self.with_instant_grant()):
            # Both observations fall in the 20:30 UTC fifteen-minute bucket.
            # Exercise either insertion order and each available SQL path.
            for minute, daily_first in ((31, True), (31, False), (30, True), (30, False)):
                with self.engine.begin() as connection:
                    connection.execute(text("DELETE FROM canonical_quotes"))
                    connection.execute(text("DELETE FROM provider_quotes"))
                stamp = datetime(2026, 10, 14, 20, minute, tzinfo=UTC)
                if daily_first:
                    self.assertEqual(asyncio.run(self.ingest()), 2)
                    self.instant(stamp, 600000)
                else:
                    self.instant(stamp, 600000)
                    self.assertEqual(asyncio.run(self.ingest()), 2)
                for use_bookends in ((False, True) if bookends else (False,)):
                    with patch("app.pricing.history._history_supports_bookends", return_value=use_bookends):
                        rows = InternalPriceHistory._query_canonical_history(self.provider.instrument_id, self.start, self.end, "15 minutes")
                    instant = next(row for row in rows if row["value"] == 600000)
                    self.assertNotIn("timestamp_precision", instant)
                    self.assertNotIn("source_date", instant)
                    self.assertEqual(instant["sample_count"], 1)
                    self.assertEqual([instant[key] for key in ("open", "close", "high", "low")], [600000] * 4)
                    self.assertEqual(instant["attributions"], [self.with_instant_grant()["owned_instant"]["attribution"]])
                    self.assertEqual(len([row for row in rows if row["timestamp"] == instant["timestamp"]]), 1)

    def test_recursive_history_dependency_does_not_hide_previous_current_quote(self):
        stamp = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
        grants = self.with_instant_grant()
        grants[self.provider.provider_id]["permissions"].append("derive")
        with patch.object(rights, "grants", return_value=grants):
            older = self.instant(stamp, 600000)
            summaries = [
                {"provider_ids": ["owned_instant"], "primary_provider_id": "owned_instant", "derived": False,
                 "previous_provider_id": self.provider.provider_id},
                {"provider_ids": ["derived:owned"], "primary_provider_id": "derived:owned", "derived": True,
                 "inputs": [{"source_summary": {"provider_ids": [self.provider.provider_id], "primary_provider_id": self.provider.provider_id, "derived": False}}]},
                {"provider_ids": ["owned_instant"], "primary_provider_id": "owned_instant", "derived": False,
                 "timestamp_precision": "day"},
            ]
            for index, summary in enumerate(summaries, 1):
                self.instant(stamp + timedelta(minutes=index), 700000 + index, summary)
                self.assertEqual(InternalPriceHistory._query_latest_canonical(self.provider.instrument_id).id, older.id)

    def test_daily_auto_job_is_durable_across_poll_lock_expiry_with_original_range(self):
        async def check():
            operational = SimpleNamespace(instrument=AsyncMock(return_value=get_instrument(self.provider.instrument_id)),
                                          feature_enabled=AsyncMock(return_value=True))
            queue = PricingBackfillQueue(store=AsyncMock(), operational=operational)
            queue.automatic_locks = SimpleNamespace(acquire=AsyncMock(side_effect=lambda *args: object()), release=AsyncMock())
            with patch.object(queue, "_history_provider", AsyncMock(return_value=self.provider)):
                first = await queue.enqueue_automatic(instrument_id=self.provider.instrument_id,
                    range_start=self.start, range_end=self.end, bucket_seconds=14400)
                # Each call receives a fresh lease, as if the short UI lock expired.
                second = await queue.enqueue_automatic(instrument_id=self.provider.instrument_id,
                    range_start=self.start + timedelta(hours=1), range_end=self.end + timedelta(hours=1), bucket_seconds=14400)
                tomorrow = await queue.enqueue_automatic(instrument_id=self.provider.instrument_id,
                    range_start=self.start + timedelta(days=1), range_end=self.end + timedelta(days=1), bucket_seconds=14400)
                manual = await queue.enqueue(instrument_id=self.provider.instrument_id,
                    range_start=self.start + timedelta(hours=2), range_end=self.end + timedelta(hours=2))
            return first, second, tomorrow, manual
        first, second, tomorrow, manual = asyncio.run(check())
        self.assertEqual(first.database_job_id, second.database_job_id)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertNotEqual(first.database_job_id, tomorrow.database_job_id)
        self.assertNotIn(manual.database_job_id, {first.database_job_id, tomorrow.database_job_id})
        with self.sessions() as db:
            self.assertEqual(db.scalar(text("SELECT COUNT(*) FROM pricing_backfill_jobs")), 3)
            stored = db.get(PricingBackfillJobRecord, first.database_job_id)
            self.assertEqual(stored.range_start, self.start)
            self.assertEqual(stored.range_end, self.end)

    def test_daily_archive_does_not_queue_intraday_poll_requests(self):
        async def check():
            operational = SimpleNamespace(instrument=AsyncMock(return_value=get_instrument(self.provider.instrument_id)),
                                          feature_enabled=AsyncMock(return_value=True))
            queue = PricingBackfillQueue(store=AsyncMock(), operational=operational)
            with patch.object(queue, "_history_provider", AsyncMock(return_value=self.provider)):
                return await queue.enqueue_automatic(instrument_id=self.provider.instrument_id,
                    range_start=self.start, range_end=self.start + timedelta(hours=1), bucket_seconds=60)
        result = asyncio.run(check())
        self.assertEqual(result.status, "unsupported")
        with self.sessions() as db:
            self.assertEqual(db.scalar(text("SELECT COUNT(*) FROM pricing_backfill_jobs")), 0)

    def test_right_revocation_hides_archive_without_erasing_rows(self):
        self.assertEqual(asyncio.run(self.ingest()), 2)
        with patch.object(rights, "grants", return_value={}):
            self.assertEqual(InternalPriceHistory._query_canonical_history(self.provider.instrument_id, self.start, self.end, "1 day"), [])
        with self.sessions() as db:
            self.assertEqual(db.scalar(text("SELECT COUNT(*) FROM canonical_quotes")), 2)
            self.assertEqual(db.scalar(text("SELECT COUNT(*) FROM provider_quotes")), 2)

    def test_replaying_same_source_days_is_idempotent(self):
        self.assertEqual(asyncio.run(self.ingest()), 2)
        self.assertEqual(asyncio.run(self.ingest()), 2)
        with self.sessions() as db:
            self.assertEqual(db.scalar(text("SELECT COUNT(*) FROM canonical_quotes")), 2)
            self.assertEqual(db.scalar(text("SELECT COUNT(*) FROM provider_quotes")), 2)


if __name__ == "__main__":
    unittest.main()
