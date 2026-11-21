import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "owned-health-pool-test-000000000000000000000")
from app import health


class HealthPoolAdmissionTests(unittest.TestCase):
    def test_probe_never_holds_a_connection_while_verifying_migrations(self):
        occupied = []
        connection = MagicMock()

        @contextmanager
        def connect():
            self.assertFalse(occupied, "Nested acquisition starves a bounded pool")
            occupied.append(True)
            try:
                yield connection
            finally:
                occupied.pop()

        engine = MagicMock()
        engine.connect.side_effect = connect

        def migration(selected):
            self.assertIs(selected, engine)
            with selected.connect():
                return {"current": True}

        with patch.object(health, "engine", engine), patch.object(
            health, "migration_state", side_effect=migration
        ), patch.object(health, "_backlog_counts", return_value={}):
            self.assertEqual(health._database_health()["status"], "connected")
        self.assertEqual(engine.connect.call_count, 2)
        self.assertFalse(occupied)
