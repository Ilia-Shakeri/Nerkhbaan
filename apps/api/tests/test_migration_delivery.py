from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")
os.environ.setdefault("PRICING_REQUIRE_PROVIDER_KEYS", "false")

from app.migrations import runner, state


class MigrationDeliveryTests(unittest.TestCase):
    def test_connect_preserves_tls_query(self):
        configuration = SimpleNamespace(database_url="postgresql+psycopg://user:password@db:5432/test?sslmode=verify-full&sslrootcert=%2Fcerts%2Fca.pem", migration_connect_timeout_seconds=7)
        with patch.object(runner, "settings", configuration), patch.object(runner.psycopg, "connect") as connect:
            runner._connect()
        self.assertEqual(connect.call_args.kwargs["sslmode"], "verify-full")
        self.assertEqual(connect.call_args.kwargs["sslrootcert"], "/certs/ca.pem")
        self.assertEqual(connect.call_args.kwargs["connect_timeout"], 7)

    def test_lock_has_deadline(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (False,)
        configuration = SimpleNamespace(migration_statement_timeout_seconds=1, migration_advisory_lock_id=1)
        with patch.object(runner, "settings", configuration), patch.object(runner.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                runner._acquire_advisory_lock(connection)
        self.assertIn("pg_try_advisory_lock", cursor.execute.call_args.args[0])

    def test_newer_database_is_not_current(self):
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value.execute.return_value.mappings.return_value.all.return_value = [
            {"version": "known.sql", "checksum": "known", "applied_at": None},
            {"version": "future.sql", "checksum": "future", "applied_at": None},
        ]
        with patch.object(state, "expected_migrations", return_value={"known.sql": "known"}):
            result = state.migration_state(engine)
        self.assertFalse(result["current"])
        self.assertEqual(result["unknown"], ["future.sql"])


if __name__ == "__main__":
    unittest.main()
