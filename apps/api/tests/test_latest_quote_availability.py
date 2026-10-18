from __future__ import annotations

import os
import asyncio
import re
import time
import unittest
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "latest-read-test-key-000000000000000000000000")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.pricing import history, rights


TEST_URL = os.getenv("TEST_DATABASE_URL")
TABLE_SQL = """CREATE TABLE canonical_quotes (
    id BIGINT PRIMARY KEY, instrument_id TEXT NOT NULL, price NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'live', primary_quote_id BIGINT,
    verification_quote_ids JSONB DEFAULT '[]', source_summary JSONB NOT NULL,
    candidate_price NUMERIC, candidate_provider_id TEXT, observed_at TIMESTAMPTZ NOT NULL,
    canonical_at TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ, stale_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ, is_persisted BOOLEAN DEFAULT TRUE, decision_reason TEXT,
    verification_status TEXT DEFAULT 'not_required', change_1h NUMERIC, change_24h NUMERIC,
    change_7d NUMERIC, change_30d NUMERIC, idempotency_key TEXT, sequence_number BIGINT)"""


@unittest.skipUnless(TEST_URL, "Requires an explicitly owned test PostgreSQL database")
class LatestQuoteAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        if (url.get_backend_name() != "postgresql"
                or set(re.split(r"[_-]+", (url.database or "").lower())).isdisjoint({"test", "ci"})):
            raise unittest.SkipTest("Only a named test/CI PostgreSQL database is permitted")
        cls.schema = "pricing_latest_" + uuid.uuid4().hex
        cls.admin = create_engine(url, hide_parameters=True)
        with cls.admin.begin() as connection:
            cls.public_table = connection.scalar(text("SELECT to_regclass('public.canonical_quotes')::text"))
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(url, hide_parameters=True,
            connect_args={"options": f"-csearch_path={cls.schema},public"}, pool_size=2, max_overflow=0)
        cls.sessions = sessionmaker(bind=cls.engine)
        try:
            with cls.engine.begin() as connection:
                cls.assert_owned(connection)
                connection.execute(text(TABLE_SQL))
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def assert_owned(cls, connection):
        if connection.scalar(text("SELECT current_schema()")) != cls.schema:
            raise AssertionError("Refusing SQL outside the owned latest-read schema")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        if not re.fullmatch(r"pricing_latest_[0-9a-f]{32}", cls.schema):
            raise AssertionError("Refusing cleanup outside the owned schema")
        with cls.admin.begin() as connection:
            if connection.scalar(text("SELECT to_regclass('public.canonical_quotes')::text")) != cls.public_table:
                raise AssertionError("Public canonical table identity changed")
            connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin.dispose()

    def setUp(self):
        with self.engine.begin() as connection:
            self.assert_owned(connection)
            connection.execute(text("DELETE FROM canonical_quotes"))
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        now = datetime.now(UTC)
        grant = {"permissions": ["collect", "store", "display", "history", "derive"],
                 "checked_at": (now - timedelta(days=1)).isoformat(),
                 "expires_at": (now + timedelta(days=1)).isoformat(),
                 "evidence_ref": "https://fixture.example.invalid/terms"}
        self.grants = {"approved": deepcopy(grant)}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.enterContext(patch.object(history, "SessionLocal", self.sessions))

    def insert(self, identifier, *, instrument="BTC_USD", summary=None, candidate=None, status="live", age=0, price=None):
        import json
        stamp = datetime.now(UTC) - timedelta(days=age, seconds=100 - identifier)
        summary = {"provider_ids": ["approved"], "primary_provider_id": "approved", "derived": False} if summary is None else summary
        with self.engine.begin() as connection:
            self.assert_owned(connection)
            connection.execute(text("""INSERT INTO canonical_quotes
                (id,instrument_id,price,status,source_summary,candidate_provider_id,observed_at,canonical_at,
                 valid_until,stale_at,expires_at,primary_quote_id,idempotency_key)
                VALUES (:id,:instrument,:price,:status,CAST(:summary AS jsonb),:candidate,:stamp,:stamp,
                 :until,:until,:until,1,:key)"""),
                {"id": identifier, "instrument": instrument, "price": 100 + identifier if price is None else price,
                 "status": status, "summary": json.dumps(summary), "candidate": candidate,
                 "stamp": stamp, "until": datetime.now(UTC) + timedelta(hours=1), "key": str(identifier)})

    def settings(self, session):
        return dict(session.execute(text("""SELECT name, setting FROM pg_settings
            WHERE name IN ('statement_timeout','lock_timeout','jit','transaction_read_only')""")).all())

    def test_transaction_budgets_are_local_read_only_and_disable_jit(self):
        with self.sessions() as db:
            before = self.settings(db)
            db.rollback()
            history._latest_read_budget(db)
            during = self.settings(db)
            self.assertEqual(during["statement_timeout"], str(min(int(before["statement_timeout"]) or 1500, 1500)))
            self.assertEqual(during["lock_timeout"], str(min(int(before["lock_timeout"]) or 250, 250)))
            self.assertEqual(during["jit"], "off")
            self.assertEqual(during["transaction_read_only"], "on")
        with self.sessions() as db:
            self.assertEqual(self.settings(db), before)

    def test_existing_stricter_and_mixed_timeouts_are_preserved(self):
        for statement, lock, expected in (("500ms", "100ms", ("500", "100")),
                                           ("2s", "50ms", ("1500", "50")),
                                           ("0", "0", ("1500", "250"))):
            with self.sessions() as db:
                db.execute(text("SELECT set_config('statement_timeout',:statement,true), set_config('lock_timeout',:lock,true)"), {"statement": statement, "lock": lock})
                history._latest_read_budget(db)
                actual = self.settings(db)
                self.assertEqual((actual["statement_timeout"], actual["lock_timeout"]), expected)

    def test_stricter_connection_defaults_survive_timeout_and_pool_return(self):
        strict_engine = create_engine(self.engine.url, hide_parameters=True, pool_size=1, max_overflow=0,
            connect_args={"options": f"-csearch_path={self.schema},public -cstatement_timeout=500 -clock_timeout=100 -cjit=on"})
        strict_sessions = sessionmaker(bind=strict_engine)
        try:
            with strict_sessions() as db:
                before = self.settings(db)
            with strict_sessions() as db:
                history._latest_read_budget(db)
                active = self.settings(db)
                self.assertEqual((active["statement_timeout"], active["lock_timeout"]), ("500", "100"))
                self.assertEqual(active["jit"], "off")
                started = time.monotonic()
                with self.assertRaises(DBAPIError) as caught:
                    db.execute(text("SELECT pg_sleep(5)"))
                self.assertEqual(getattr(caught.exception.orig, "sqlstate", None), "57014")
                self.assertLess(time.monotonic() - started, 1.5)
            with strict_sessions() as db:
                self.assertEqual(self.settings(db), before)
        finally:
            strict_engine.dispose()

    def test_statement_timeout_bubbles_and_session_closes_without_empty_success(self):
        with self.sessions() as probe:
            before = self.settings(probe)
        session = self.sessions()
        original = session.close
        closed = []
        def close():
            closed.append(True)
            original()
        session.close = close
        started = time.monotonic()
        with patch.object(history, "SessionLocal", return_value=session), patch.object(
                history, "_latest_rows_sql", return_value=(text("SELECT pg_sleep(10)"), {})):
            with self.assertRaises(DBAPIError) as caught:
                history.InternalPriceHistory._query_latest_rows(None)
        self.assertEqual(getattr(caught.exception.orig, "sqlstate", None), "57014")
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(closed, [True])
        with self.sessions() as db:
            self.assertEqual(self.settings(db), before)

    def test_lock_timeout_bubbles_before_statement_deadline(self):
        with self.engine.connect() as blocker:
            transaction = blocker.begin()
            self.assert_owned(blocker)
            blocker.execute(text("LOCK TABLE canonical_quotes IN ACCESS EXCLUSIVE MODE"))
            started = time.monotonic()
            try:
                with self.assertRaises(DBAPIError) as caught:
                    history.InternalPriceHistory._query_latest_rows(None)
                self.assertEqual(getattr(caught.exception.orig, "sqlstate", None), "55P03")
                self.assertLess(time.monotonic() - started, 1.3)
            finally:
                transaction.rollback()

    def test_full_rights_and_daily_lineage_keep_older_eligible_rows(self):
        self.insert(1, age=4000)
        self.insert(2, summary={"provider_ids": ["restricted"], "primary_provider_id": "restricted"})
        self.insert(3, summary={"provider_ids": ["approved"], "primary_provider_id": "approved", "timestamp_precision": "day"})
        self.insert(4, candidate="restricted")
        self.insert(5, summary={"provider_ids": ["approved"], "primary_provider_id": "approved", "historical_backfill": True})
        self.insert(6, summary={"provider_ids": ["derived:owned"], "primary_provider_id": "derived:owned", "derived": True, "inputs": [{"source_summary": {"provider_ids": ["restricted"], "primary_provider_id": "restricted"}}]})
        self.insert(7, summary={"provider_ids": ["derived:owned"], "primary_provider_id": "derived:owned", "derived": True, "inputs": [{"source_summary": {"provider_ids": ["approved"], "primary_provider_id": "approved", "timestamp_precision": "day"}}]})
        self.assertEqual([row["id"] for row in history.InternalPriceHistory._query_latest_rows(None)], [1])
        self.assertEqual([row["id"] for row in history.InternalPriceHistory._query_latest_rows("BTC_USD")], [1])
        self.grants.clear()
        self.assertEqual(history.InternalPriceHistory._query_latest_rows(None), [])

    def test_derived_approved_parent_survives_root_prefilter_and_revocation(self):
        self.insert(1, age=4000)
        self.insert(2, status="derived_fallback", summary={"provider_ids": ["derived:owned"],
            "primary_provider_id": "derived:owned", "derived": True,
            "inputs": [{"source_summary": {"provider_ids": ["approved"],
                "primary_provider_id": "approved", "derived": False}}]})
        self.assertEqual([row["id"] for row in history.InternalPriceHistory._query_latest_rows(None)], [2])
        self.grants["approved"]["permissions"].remove("derive")
        self.assertEqual([row["id"] for row in history.InternalPriceHistory._query_latest_rows(None)], [1])

    def test_gold_purity_and_ties_stay_exact(self):
        self.insert(1, instrument="GOLD_18K_TOMAN_GRAM", age=4000)
        self.insert(2, instrument="GOLD_18K_TOMAN_GRAM", status="derived_fallback")
        self.insert(3, instrument="GOLD_24K_TOMAN_GRAM")
        self.insert(4, instrument="GOLD_24K_TOMAN_GRAM", summary={"provider_ids": ["approved"], "primary_provider_id": "approved", "derived": True})
        self.assertEqual([row["id"] for row in history.InternalPriceHistory._query_latest_rows(None)], [1, 3])
        self.insert(5)
        self.insert(6)
        with self.engine.begin() as connection:
            self.assert_owned(connection)
            connection.execute(text("UPDATE canonical_quotes SET observed_at = TIMESTAMPTZ '2026-10-17', canonical_at = TIMESTAMPTZ '2026-10-17' WHERE id IN(5,6)"))
        self.assertEqual([row["id"] for row in history.InternalPriceHistory._query_latest_rows("BTC_USD")], [6])

    def test_actual_sql_timeout_keeps_existing_eligible_cache_fallback(self):
        from app.pricing.instruments import get_instrument
        from app.pricing.service import InstrumentPricingService
        self.insert(1, price=50000)
        quote = history.InternalPriceHistory._query_latest_canonical("BTC_USD")
        self.assertIsNotNone(quote)
        service = InstrumentPricingService(store=AsyncMock(get_all_canonical=AsyncMock(return_value={"BTC_USD": quote})),
                                          history=history.InternalPriceHistory())
        with patch.object(history, "_latest_rows_sql", return_value=(text("SELECT pg_sleep(10)"), {})):
            started = time.monotonic()
            with self.assertLogs("app.pricing.service", level="ERROR"):
                result = asyncio.run(service._read_canonical_snapshot({"BTC_USD": get_instrument("BTC_USD")}))
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(result["BTC_USD"].id, quote.id)
            self.grants.clear()
            with self.assertLogs("app.pricing.service", level="ERROR"):
                self.assertEqual(asyncio.run(service._read_canonical_snapshot({"BTC_USD": get_instrument("BTC_USD")})), {})

    def test_prefilter_matches_complete_query_with_and_without_rights_enforcement(self):
        direct = {"provider_ids": ["approved"], "primary_provider_id": "approved", "derived": False}
        derived = {"provider_ids": ["derived:owned"], "primary_provider_id": "derived:owned",
                   "derived": True, "inputs": [{"source_summary": direct}]}
        variants = [direct, derived, {}, {"provider_ids": "approved"},
                    {**direct, "provider_ids": []}, {**direct, "primary_provider_id": "restricted"},
                    {**direct, "candidate_provider_id": "restricted"},
                    {**direct, "previous_provider_id": "restricted"},
                    {**direct, "timestamp_precision": "day"},
                    {**direct, "historical_backfill": True},
                    {**direct, "provider_ids": ["servix_btc_usd"]},
                    {**derived, "inputs": [{"source_summary": {**direct, "timestamp_precision": "day"}}]},
                    {**derived, "inputs": [{"source_summary": {}}]},
                    {**derived, "inputs": derived["inputs"] * 17}]
        for identifier, summary in enumerate(variants, 1):
            for offset, instrument in ((0, "BTC_USD"), (100, "GOLD_18K_TOMAN_GRAM")):
                self.insert(identifier + offset, instrument=instrument, summary=summary)
        for enabled in (True, False):
            with patch.object(settings, "pricing_rights_enforced", enabled):
                permitted, parameters = history._canonical_permissions("display")
                query = text(f"""SELECT DISTINCT ON(instrument_id) id
                    FROM canonical_quotes WHERE {history._DIRECT_GOLD_SQL} AND {permitted}
                    AND COALESCE(source_summary->>'historical_backfill','false') <> 'true'
                    ORDER BY instrument_id, observed_at DESC, canonical_at DESC, id DESC""")
                with self.sessions() as db:
                    expected = list(db.execute(query, parameters).scalars())
                actual = history.InternalPriceHistory._query_latest_rows(None)
                self.assertEqual([row["id"] for row in actual], expected)


if __name__ == "__main__":
    unittest.main()
