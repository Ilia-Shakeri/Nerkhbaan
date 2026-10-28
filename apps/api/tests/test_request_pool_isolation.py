from contextlib import ExitStack
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app import db


class RequestPoolIsolationTests(unittest.TestCase):
    def test_split_keeps_configured_budget_for_small_and_large_pools(self):
        for size in range(1, 10):
            for overflow in range(0, 5):
                background, extra, reserved = db.sync_pool_plan(size, overflow)
                self.assertEqual(background + extra + reserved, size + overflow)
                self.assertGreaterEqual(background, 1)
                self.assertLessEqual(reserved, 2)
        self.assertEqual(db.sync_pool_plan(5, 3), (5, 1, 2))
        self.assertEqual(db.sync_pool_plan(1, 0), (1, 0, 0))
        for size, overflow in ((0, 3), (5, -1)):
            with self.assertRaises(ValueError):
                db.sync_pool_plan(size, overflow)

    def test_exhausted_background_pool_cannot_block_request_transaction(self):
        background_size, overflow, reserved = db.sync_pool_plan(5, 3)
        common = dict(poolclass=QueuePool, pool_timeout=0.05)
        background = create_engine("sqlite://", pool_size=background_size,
                                   max_overflow=overflow, **common)
        request = create_engine("sqlite://", pool_size=reserved, max_overflow=0, **common)
        self.addCleanup(background.dispose)
        self.addCleanup(request.dispose)
        with ExitStack() as held:
            for _ in range(background_size + overflow):
                held.enter_context(background.connect())
            self.assertEqual(background.pool.checkedout(), 6)
            with patch.object(db, "RequestSessionLocal", sessionmaker(bind=request)):
                dependency = db.get_db()
                session = next(dependency)
                self.assertEqual(session.scalar(text("SELECT 1")), 1)
                dependency.close()
            self.assertEqual(request.pool.checkedout(), 0)
            self.assertEqual(background.pool.checkedout(), 6)

    def test_failed_request_rolls_back_and_releases_its_reserved_connection(self):
        request = create_engine("sqlite://", poolclass=QueuePool,
                                pool_size=1, max_overflow=0, pool_timeout=0.05)
        self.addCleanup(request.dispose)
        with patch.object(db, "RequestSessionLocal", sessionmaker(bind=request)):
            dependency = db.get_db()
            self.assertEqual(next(dependency).scalar(text("SELECT 1")), 1)
            with self.assertRaisesRegex(RuntimeError, "owned fixture failure"):
                dependency.throw(RuntimeError("owned fixture failure"))
        self.assertEqual(request.pool.checkedout(), 0)
