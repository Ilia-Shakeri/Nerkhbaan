from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
import re
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.pricing.history import (
    InternalPriceHistory, _ACCEPTED_STATUSES, _canonical_history_sql,
    _history_supports_bookends,
)


TEST_URL = os.getenv("TEST_DATABASE_URL")
BACKEND = os.getenv("TEST_HISTORY_BACKEND")
START = datetime(2026, 10, 11, tzinfo=UTC)
END = START+timedelta(hours=1)


@unittest.skipUnless(TEST_URL and BACKEND in {"plain", "timescale"},
                     "Set TEST_DATABASE_URL and TEST_HISTORY_BACKEND=plain|timescale")
class HistoryBackendAggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("History fixture requires an explicitly named test/CI PostgreSQL database")
        cls.schema = "pricing_history_"+uuid.uuid4().hex
        cls.admin_engine = create_engine(url, pool_pre_ping=True)
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        try:
            cls.engine = create_engine(url, pool_pre_ping=True,
                                      connect_args={"options": f"-csearch_path={cls.schema},public"})
            cls.sessions = sessionmaker(bind=cls.engine)
            with cls.engine.begin() as connection:
                connection.execute(text("""CREATE TABLE canonical_quotes (
                    id BIGINT PRIMARY KEY, instrument_id TEXT NOT NULL,
                    canonical_at TIMESTAMPTZ NOT NULL, price NUMERIC(24,8) NOT NULL,
                    status TEXT NOT NULL, source_summary JSONB NOT NULL)"""))
                direct = {"derived": False, "primary_provider_id": "owned-direct-fixture"}
                rows = [
                    (1, "GOLD_18K_TOMAN_GRAM", START+timedelta(minutes=2), 110, "live", direct),
                    (2, "GOLD_18K_TOMAN_GRAM", START, 100, "confirmed", direct),
                    (3, "GOLD_18K_TOMAN_GRAM", START+timedelta(minutes=14), 90, "fresh_cache", direct),
                    (4, "GOLD_18K_TOMAN_GRAM", START+timedelta(minutes=35), 150, "unpersisted", direct),
                    (5, "GOLD_18K_TOMAN_GRAM", START+timedelta(minutes=45), 120, "live", direct),
                    (6, "GOLD_18K_TOMAN_GRAM", START+timedelta(minutes=45), 120, "live", direct),
                    (7, "GOLD_18K_TOMAN_GRAM", END, 160, "live", direct),
                    (8, "GOLD_18K_TOMAN_GRAM", START-timedelta(microseconds=1), 999, "live", direct),
                    (9, "GOLD_18K_TOMAN_GRAM", END+timedelta(microseconds=1), 999, "live", direct),
                    (10, "GOLD_18K_TOMAN_GRAM", START, 999, "suspicious", direct),
                    (11, "GOLD_18K_TOMAN_GRAM", START, 999, "derived_fallback", direct),
                    (12, "GOLD_18K_TOMAN_GRAM", START, 999, "live", {"derived": True}),
                    (13, "GOLD_18K_TOMAN_GRAM", START, 999, "live", {"primary_provider_id": "derived:gold"}),
                    (14, "GOLD_18K_TOMAN_GRAM", START, 999, "live", {"primary_provider_id": "persian_toolbox_gold24"}),
                    (15, "GOLD_18K_TOMAN_GRAM", START, 999, "live", {"provider_ids": ["persian_toolbox_gold24"]}),
                    (16, "GOLD_24K_TOMAN_GRAM", START, 180, "live", direct),
                    (17, "GOLD_24K_TOMAN_GRAM", START, 999, "confirmed", {"provider_ids": ["persian_toolbox_gold24"]}),
                    (20, "BTC_USD", START, 10, "live", direct),
                    (21, "BTC_USD", START, 15, "live", direct),
                    (22, "BTC_USD", START+timedelta(minutes=1), 20, "live", direct),
                    (23, "BTC_USD", END, 30, "live", direct),
                    (24, "BTC_USD", END, 31, "live", direct),
                ]
                connection.execute(text("""INSERT INTO canonical_quotes VALUES
                    (:id, :instrument, :stamp, :price, :status, CAST(:summary AS jsonb))"""),
                    [{"id": identifier, "instrument": instrument, "stamp": stamp,
                      "price": price, "status": status, "summary": json.dumps(summary)}
                     for identifier, instrument, stamp, price, status, summary in rows])
            cls.capability_queries = 0
            @event.listens_for(cls.engine, "before_cursor_execute")
            def count(_connection, _cursor, statement, _parameters, _context, _many):
                if "FROM pg_extension e" in statement:
                    cls.capability_queries += 1
            with cls.sessions() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                cls.supported = _history_supports_bookends(session)
            if cls.supported != (BACKEND == "timescale"):
                raise AssertionError("Actual extension/functions do not match the explicitly requested backend")
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        try:
            if not re.fullmatch(r"pricing_history_[0-9a-f]{32}", cls.schema):
                raise AssertionError("Refusing cleanup outside owned schema")
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
        finally:
            cls.admin_engine.dispose()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def raw(self, instrument, *, fast=False, bucket="15 minutes"):
        with self.sessions() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            return [dict(row) for row in session.execute(_canonical_history_sql(fast), {
                "instrument_id": instrument, "start": START, "end": END,
                "bucket": bucket, "statuses": list(_ACCEPTED_STATUSES),
            }).mappings().all()]

    def test_actual_ohlc_status_range_bucket_and_direct_gold_filters_match_original(self):
        old = self.raw("GOLD_18K_TOMAN_GRAM")
        if self.supported:
            self.assertEqual(self.raw("GOLD_18K_TOMAN_GRAM", fast=True), old)
        self.assertEqual([int(row["sample_count"]) for row in old], [3, 1, 2, 1])
        self.assertEqual((old[0]["open"], old[0]["close"], old[0]["high"], old[0]["low"]), (100, 90, 110, 90))
        self.assertEqual(old[-1]["bucket"], END)
        with patch("app.pricing.history.SessionLocal", self.sessions):
            actual = InternalPriceHistory._query_canonical_history("GOLD_18K_TOMAN_GRAM", START, END, "15 minutes")
        self.assertEqual([item["sample_count"] for item in actual], [3, 1, 2, 1])
        self.assertEqual(actual[0]["open"], 100)
        self.assertEqual(actual[0]["close"], 90)
        self.assertEqual(actual[-1]["timestamp"], END.isoformat())

    def test_timestamp_ties_and_gold24_exclusion_have_actual_backend_equivalence(self):
        for instrument in ("BTC_USD", "GOLD_24K_TOMAN_GRAM"):
            old = self.raw(instrument, bucket="1 hour")
            if self.supported:
                self.assertEqual(self.raw(instrument, fast=True, bucket="1 hour"), old)
        gold = self.raw("GOLD_24K_TOMAN_GRAM")
        self.assertEqual(len(gold), 1)
        self.assertEqual(gold[0]["sample_count"], 1)
        self.assertEqual(gold[0]["close"], 180)

    def test_backend_capability_is_once_for_all_fresh_canonical_queries(self):
        with patch("app.pricing.history.SessionLocal", self.sessions):
            for _index in range(3):
                InternalPriceHistory._query_canonical_history("GOLD_18K_TOMAN_GRAM", START, END, "15 minutes")
        self.assertEqual(self.capability_queries, 1)


if __name__ == "__main__":
    unittest.main()
