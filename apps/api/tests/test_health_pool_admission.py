import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "owned-health-pool-test-000000000000000000000")
from app import health
from app import db
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool


class HealthPoolAdmissionTests(unittest.TestCase):
    def test_history_pool_exhaustion_does_not_block_health_connection(self):
        if db.request_engine is db.engine:
            self.skipTest("Configured budget has no reserved request connection")
        background = create_engine("sqlite://", poolclass=QueuePool, pool_size=1,
            max_overflow=0, pool_timeout=0.05)
        reserved = create_engine("sqlite://", poolclass=QueuePool, pool_size=1,
            max_overflow=0, pool_timeout=0.05)
        self.addCleanup(background.dispose)
        self.addCleanup(reserved.dispose)
        selected = {db.engine: background, db.request_engine: reserved}[health.engine]
        with background.connect():
            with patch.object(health, "engine", selected), patch.object(
                health, "migration_state", return_value={"current": True}
            ), patch.object(health, "_backlog_counts", return_value={}):
                self.assertEqual(health._database_health()["status"], "connected")
            self.assertEqual(background.pool.checkedout(), 1)
            self.assertEqual(reserved.pool.checkedout(), 0)

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
