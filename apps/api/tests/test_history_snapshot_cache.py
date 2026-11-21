from __future__ import annotations

import asyncio
import os
import re
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    owned_table_names = ("canonical_quotes", "canonical_history_versions")

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
            migration = Path(__file__).resolve().parents[1] / "db/migrations/20261121_004_history_versions.sql"
            db.connection.driver_connection.execute(migration.read_text().replace("public.", f'"{cls.schema}".'))
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
