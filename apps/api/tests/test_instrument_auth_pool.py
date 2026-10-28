from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.routers.instruments import optional_current_user


class InstrumentAuthPoolTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=QueuePool,
                                    pool_size=1, max_overflow=0, pool_timeout=0.1)
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        self.users = Table("owned_auth_pool_fixture", metadata,
                           Column("id", Integer, primary_key=True))
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.execute(self.users.insert().values(id=1))
        self.db = Session(self.engine)
        self.addCleanup(self.db.close)
        self.request = Request({"type": "http", "headers": []})
        self.credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test")

    def test_authenticated_pricing_read_does_not_hold_only_connection(self):
        def resolve(*_args):
            self.assertEqual(self.db.scalar(select(self.users.c.id)), 1)
            return object()

        with patch("app.routers.instruments.get_current_user", side_effect=resolve):
            user = optional_current_user(self.request, self.credentials, self.db)
        self.assertIsNotNone(user)
        # An independent logout/pricing transaction must enter while the read
        # route still holds the resolved identity and awaits its pricing work.
        with self.engine.connect() as other:
            self.assertEqual(other.scalar(select(self.users.c.id)), 1)
        self.assertEqual(self.engine.pool.checkedout(), 0)

    def test_revoked_identity_releases_connection_without_becoming_anonymous(self):
        def revoked(*_args):
            self.db.scalar(select(self.users.c.id))
            raise HTTPException(status_code=401, detail="Session revoked")

        with patch("app.routers.instruments.get_current_user", side_effect=revoked):
            with self.assertRaises(HTTPException) as caught:
                optional_current_user(self.request, self.credentials, self.db)
        self.assertEqual(caught.exception.status_code, 401)
        with self.engine.connect() as other:
            self.assertEqual(other.scalar(select(self.users.c.id)), 1)

    def test_public_read_does_not_resolve_an_identity(self):
        with patch("app.routers.instruments.get_current_user") as resolve:
            self.assertIsNone(optional_current_user(self.request, None, self.db))
        resolve.assert_not_called()
        self.assertEqual(self.engine.pool.checkedout(), 0)
