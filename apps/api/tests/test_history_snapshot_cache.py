from __future__ import annotations

import asyncio
import os
import re
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "history-cache-tests-only-0000000000000000000000")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.pricing import history, rights
from tests import test_pricing_rights_postgres as fixtures
from tests.test_latest_quote_availability import TABLE_SQL


@unittest.skipUnless(fixtures.TEST_URL, "Requires an explicitly owned test database")
class SnapshotCachePostgresTests(fixtures._OwnedPostgresFixture, unittest.TestCase):
    owned_table_names = ("canonical_quotes", "canonical_quote_read_index", "canonical_history_versions",
                         "canonical_history_bucket_versions")

    @classmethod
    def setUpClass(cls):
        url = make_url(fixtures.TEST_URL)
        if url.get_backend_name() != "postgresql" or not set(re.split("[_-]+", url.database or "")) & {"test", "ci"}:
            raise unittest.SkipTest("Only a named test database is permitted")
        cls.schema = "history_snapshot_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, hide_parameters=True)
        cls.public_fingerprint = cls._public_fingerprint()
        with cls.admin_engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(url, hide_parameters=True,
            connect_args={"options": f"-csearch_path={cls.schema},public"})
        cls.sessions = sessionmaker(bind=cls.engine)
        with cls.engine.begin() as db:
            assert db.scalar(text("SELECT current_schema()")) == cls.schema
            db.execute(text(TABLE_SQL))
            migrations = Path(__file__).resolve().parents[1] / "db/migrations"
            for name in ("20261115_001_canonical_read_index.sql", "20261121_004_history_versions.sql",
                         "20261121_005_history_bucket_versions.sql"):
                db.connection.driver_connection.execute((migrations / name).read_text().replace("public.", f'"{cls.schema}".'))
        cls._install_ownership_guard()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        assert re.fullmatch("history_snapshot_[0-9a-f]{32}", cls.schema)
        assert cls._public_fingerprint() == cls.public_fingerprint
        with cls.admin_engine.begin() as db:
            db.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        cls.admin_engine.dispose()

    def setUp(self):
        with self.engine.begin() as db:
            db.execute(text("TRUNCATE canonical_quotes"))
            db.execute(text("TRUNCATE canonical_quote_read_index"))
        self.enterContext(patch.object(settings, "pricing_history_snapshot_cache_seconds", 30))
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        self.enterContext(patch.object(history, "SessionLocal", self.sessions))
        self.enterContext(patch.object(history, "RequestSessionLocal", self.sessions))
        now = datetime.now(UTC)
        self.grants = {"approved": {"permissions": ["store", "display", "history", "derive"],
            "checked_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(), "evidence_ref": "https://fixture.invalid/terms"}}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.reader = history.InternalPriceHistory()
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO canonical_quotes
                (id,instrument_id,price,status,source_summary,observed_at,canonical_at)
                VALUES(1,'BTC_USD',100,'live',
                    jsonb_build_object('provider_ids',jsonb_build_array('approved'),
                        'derived',false),now(),now())"""))

    def read(self):
        return asyncio.run(self.reader.canonical_history("BTC_USD", "1y"))

    def test_reuses_exact_snapshot_but_caller_cannot_mutate_saved_chart(self):
        with patch.object(self.reader, "_query_canonical_history", wraps=self.reader._query_canonical_history) as query:
            first = self.read()
            first.points[0]["close"] = 999
            second = self.read()
            self.assertEqual(query.call_count, 1)
            self.assertEqual(second.points[0]["close"], 100)
            self.assertEqual(first.range_end, second.range_end)

    def test_old_tick_update_and_delete_invalidate_immediately(self):
        self.assertEqual(self.read().points[0]["close"], 100)
        with self.engine.begin() as db:
            db.execute(text("UPDATE canonical_quotes SET price=200 WHERE id=1"))
        self.assertEqual(self.read().points[0]["close"], 200)
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM canonical_quotes WHERE id=1"))
        self.assertEqual(self.read().points, [])

    def test_correction_in_a_complete_old_hour_invalidates_the_saved_chart(self):
        with self.engine.begin() as db:
            db.execute(text("UPDATE canonical_quotes SET canonical_at=now()-interval '2 days'"))
        self.assertEqual(self.read().points[0]["close"], 100)
        with self.engine.begin() as db:
            db.execute(text("UPDATE canonical_quotes SET price=400"))
        self.assertEqual(self.read().points[0]["close"], 400)
        with self.engine.begin() as db:
            db.execute(text("UPDATE canonical_quotes SET canonical_at=now()+interval '1 minute'"))
        self.assertEqual(self.read().points, [])

    def test_bucket_and_boundary_fingerprint_do_not_depend_on_session_timezone(self):
        with self.engine.begin() as db:
            db.execute(text("SET LOCAL TIME ZONE 'Asia/Tehran'"))
            db.execute(text("UPDATE canonical_quotes SET canonical_at=now()-interval '2 days'"))
        now = datetime.now(UTC)
        results = []
        for zone in ("UTC", "Asia/Tehran"):
            def session():
                db = self.sessions()
                db.execute(text("SET LOCAL TIME ZONE '" + zone + "'"))
                return db
            with patch.object(history, "RequestSessionLocal", side_effect=session):
                results.append(self.reader._query_history_fingerprint("BTC_USD", now-timedelta(days=365), now))
        self.assertEqual(results[0], results[1])

    def test_insert_and_instrument_move_invalidate_both_instrument_generations(self):
        self.assertTrue(self.read().points)
        old = self.reader._query_history_generation("BTC_USD")
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO canonical_quotes
                (id,instrument_id,price,status,source_summary,observed_at,canonical_at)
                SELECT 2,instrument_id,500,status,source_summary,observed_at,canonical_at
                FROM canonical_quotes WHERE id=1"""))
        self.assertGreater(self.reader._query_history_generation("BTC_USD"), old)
        self.assertEqual(self.read().points[0]["high"], 500)
        with self.engine.begin() as db:
            db.execute(text("UPDATE canonical_quotes SET instrument_id='BTC_TOMAN'"))
        self.assertEqual(self.read().points, [])
        self.assertGreater(self.reader._query_history_generation("BTC_TOMAN"), 0)

    def test_legacy_history_without_enforced_rights_is_never_cached(self):
        with patch.object(settings, "pricing_rights_enforced", False), patch.object(
                self.reader, "_query_history_generation", side_effect=AssertionError("Legacy cache forbidden")):
            self.assertTrue(self.read().points)
            self.assertEqual(self.reader._history_snapshots, {})

    def test_future_insert_reuses_original_range_without_extending_snapshot_lifetime(self):
        with patch.object(self.reader, "_query_canonical_history", wraps=self.reader._query_canonical_history) as query:
            first = self.read()
            deadline = next(iter(self.reader._history_snapshots.values()))[0]
            with self.engine.begin() as db:
                db.execute(text("""INSERT INTO canonical_quotes
                    (id,instrument_id,price,status,source_summary,observed_at,canonical_at)
                    SELECT 2,instrument_id,500,status,source_summary,now(),now()
                    FROM canonical_quotes WHERE id=1"""))
            second = self.read()
            self.assertEqual(query.call_count, 1)
            self.assertEqual(second.range_end, first.range_end)
            self.assertEqual(second.points, first.points)
            self.assertEqual(next(iter(self.reader._history_snapshots.values()))[0], deadline)

    def test_future_insert_during_cold_read_does_not_duplicate_the_expensive_query(self):
        self._concurrent_change(in_range=False)

    def test_many_instruments_keep_a_bounded_snapshot_set(self):
        for instrument in history.INSTRUMENTS:
            asyncio.run(self.reader.canonical_history(instrument, "1y"))
            self.assertLessEqual(len(self.reader._history_snapshots), 8)

    def test_new_caller_after_in_range_edit_does_not_join_an_obsolete_result(self):
        self._concurrent_change(in_range=True)

    def _concurrent_change(self, *, in_range):
        started, release, newer = Event(), Event(), Event()
        self.addCleanup(release.set)
        original = self.reader._query_canonical_history
        version_reader = self.reader._query_history_generation
        version = version_reader("BTC_USD")
        calls = []
        def read(*args):
            result = original(*args)
            calls.append(True)
            if len(calls) == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError("Missing fixture release")
            return result
        def generation(instrument):
            result = version_reader(instrument)
            if result > version:
                newer.set()
            return result
        async def scenario():
            first = asyncio.create_task(self.reader.canonical_history("BTC_USD", "1y"))
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            with self.engine.begin() as db:
                if in_range:
                    db.execute(text("UPDATE canonical_quotes SET price=200 WHERE id=1"))
                else:
                    db.execute(text("""INSERT INTO canonical_quotes
                        (id,instrument_id,price,status,source_summary,observed_at,canonical_at)
                        SELECT 2,instrument_id,500,status,source_summary,now(),now()
                        FROM canonical_quotes WHERE id=1"""))
            second = asyncio.create_task(self.reader.canonical_history("BTC_USD", "1y"))
            self.assertTrue(await asyncio.to_thread(newer.wait, 5))
            release.set()
            return await asyncio.gather(first, second)
        with patch.object(self.reader, "_query_canonical_history", side_effect=read), patch.object(
                self.reader, "_query_history_generation", side_effect=generation):
            first, second = asyncio.run(scenario())
        self.assertEqual(first.points[0]["close"], 100)
        self.assertEqual(second.points[0]["close"], 200 if in_range else 100)
        self.assertEqual(len(calls), 2 if in_range else 1)

    def test_truncate_invalidates_and_rollback_does_not_publish_a_new_version(self):
        self.assertTrue(self.read().points)
        version = self.reader._query_history_generation("BTC_USD")
        with self.engine.connect() as db:
            transaction = db.begin()
            db.execute(text("UPDATE canonical_quotes SET price=900 WHERE id=1"))
            transaction.rollback()
        self.assertEqual(self.reader._query_history_generation("BTC_USD"), version)
        self.assertEqual(self.read().points[0]["close"], 100)
        with self.engine.begin() as db:
            db.execute(text("TRUNCATE canonical_quotes"))
        self.assertEqual(self.read().points, [])

    def test_permission_revocation_never_reuses_a_completed_snapshot(self):
        self.assertTrue(self.read().points)
        self.grants.clear()
        self.assertEqual(self.read().points, [])

    def test_mutation_during_read_prevents_saving_a_completed_snapshot(self):
        original = self.reader._query_canonical_history
        def concurrent_edit(*args):
            rows = original(*args)
            with self.engine.begin() as db:
                db.execute(text("UPDATE canonical_quotes SET price=300 WHERE id=1"))
            return rows
        with patch.object(self.reader, "_query_canonical_history", side_effect=concurrent_edit):
            self.assertEqual(self.read().points[0]["close"], 100)
        self.assertEqual(self.reader._history_snapshots, {})
        self.assertEqual(self.read().points[0]["close"], 300)

    def test_expiry_and_missing_invalidation_state_fail_closed(self):
        self.assertTrue(self.read().points)
        with patch("app.pricing.history.time.monotonic", return_value=10**12):
            with patch.object(self.reader, "_query_canonical_history", wraps=self.reader._query_canonical_history) as query:
                self.read()
                self.assertEqual(query.call_count, 1)
        with patch.object(self.reader, "_query_history_generation", side_effect=RuntimeError("version read unavailable")):
            with self.assertRaisesRegex(RuntimeError, "version read unavailable"):
                self.read()


if __name__ == "__main__":
    unittest.main()
