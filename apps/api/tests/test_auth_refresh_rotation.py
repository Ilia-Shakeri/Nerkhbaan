from __future__ import annotations

import os
import re
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException, Request, Response
from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models import SecurityEvent, User, UserSession
from app.routers import auth
from app.schemas import RefreshRequest
from app.security import hash_refresh_token


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/auth/refresh",
            "raw_path": b"/api/auth/refresh",
            "query_string": b"",
            "headers": [(b"user-agent", b"refresh-rotation-test")],
            "client": ("198.51.100.20", 42000),
            "server": ("example.test", 443),
        }
    )


class _LockProbeSession:
    def __init__(self) -> None:
        self.statement = None

    def scalar(self, statement):
        self.statement = statement
        return None


class _ReuseProbeSession:
    def __init__(self, session: UserSession) -> None:
        self.session = session
        self.executed: list[object] = []
        self.added: list[object] = []
        self.commit_count = 0

    def scalar(self, _statement):
        return self.session

    def execute(self, statement):
        self.executed.append(statement)

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commit_count += 1


class RefreshRotationUnitTests(unittest.TestCase):
    def test_refresh_session_locks_token_row_before_state_check(self) -> None:
        db = _LockProbeSession()

        with self.assertRaises(HTTPException) as caught:
            auth.refresh_session(
                _request(),
                Response(),
                RefreshRequest(refresh_token="r" * 32),
                db,
            )

        self.assertEqual(caught.exception.status_code, 401)
        self.assertIsNotNone(db.statement)
        sql = str(db.statement.compile(dialect=postgresql.dialect())).upper()
        self.assertIn("FOR UPDATE", sql)

    def test_reused_rotated_token_marks_active_family_compromised(self) -> None:
        now = datetime.now(UTC)
        session = UserSession(
            id=str(uuid.uuid4()),
            user_id=7,
            token_family=str(uuid.uuid4()),
            refresh_token_hash=hash_refresh_token("r" * 32),
            replaced_by_session_id=str(uuid.uuid4()),
            created_at=now - timedelta(minutes=2),
            last_used_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=1),
            revoked_at=now - timedelta(seconds=1),
        )
        db = _ReuseProbeSession(session)

        with self.assertRaises(HTTPException) as caught:
            auth.refresh_session(
                _request(),
                Response(),
                RefreshRequest(refresh_token="r" * 32),
                db,
            )

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Refresh token was revoked")
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(len(db.executed), 1)
        sql = str(db.executed[0].compile(dialect=postgresql.dialect())).upper()
        self.assertIn("USER_SESSIONS.TOKEN_FAMILY", sql)
        self.assertIn("USER_SESSIONS.REVOKED_AT IS NULL", sql)
        self.assertIn("COMPROMISED_AT", sql)
        self.assertEqual(len(db.added), 1)
        event = db.added[0]
        self.assertIsInstance(event, SecurityEvent)
        self.assertEqual(event.event_type, "refresh_reuse")
        self.assertEqual(event.result, "blocked")


_POSTGRES_TEST_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(_POSTGRES_TEST_URL, "TEST_DATABASE_URL is not set")
class RefreshRotationPostgresTests(unittest.TestCase):
    admin_engine = None
    test_engine = None
    schema_name = ""

    @classmethod
    def _drop_test_schema(cls) -> None:
        if cls.admin_engine is None or not cls.schema_name:
            return
        quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema_name)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"))

    @classmethod
    def setUpClass(cls) -> None:
        assert _POSTGRES_TEST_URL is not None
        database_url = make_url(_POSTGRES_TEST_URL)
        database_name = (database_url.database or "").lower()
        if database_url.get_backend_name() != "postgresql":
            raise unittest.SkipTest("TEST_DATABASE_URL is not PostgreSQL")
        database_name_parts = set(re.split(r"[_-]+", database_name))
        if database_name_parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("TEST_DATABASE_URL must name a test or CI database")
        if database_url.drivername.endswith("+asyncpg"):
            raise unittest.SkipTest("TEST_DATABASE_URL must use a synchronous driver")

        cls.schema_name = f"refresh_rotation_{uuid.uuid4().hex}"
        try:
            cls.admin_engine = create_engine(database_url, pool_pre_ping=True)
            quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema_name)
            with cls.admin_engine.begin() as connection:
                connection.execute(text("SELECT 1"))
                connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))

            metadata = MetaData()
            for table in (User.__table__, UserSession.__table__, SecurityEvent.__table__):
                table.to_metadata(metadata, schema=cls.schema_name)
            metadata.create_all(cls.admin_engine)
            cls.test_engine = create_engine(
                database_url,
                pool_pre_ping=True,
                connect_args={"options": f"-csearch_path={cls.schema_name},public"},
            )
        except (ImportError, SQLAlchemyError) as exc:
            if cls.admin_engine is not None:
                try:
                    cls._drop_test_schema()
                except SQLAlchemyError:
                    pass
                cls.admin_engine.dispose()
            raise unittest.SkipTest(
                f"PostgreSQL test schema is unavailable: {type(exc).__name__}"
            ) from exc

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.test_engine is not None:
            cls.test_engine.dispose()
        if cls.admin_engine is not None and cls.schema_name:
            try:
                cls._drop_test_schema()
            finally:
                cls.admin_engine.dispose()

    def test_concurrent_rotation_allows_one_success_then_revokes_family(self) -> None:
        assert self.test_engine is not None
        raw_refresh_token = "refresh-token-for-postgres-race-proof"
        family = str(uuid.uuid4())
        original_session_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        session_factory = sessionmaker(bind=self.test_engine, class_=Session)
        with session_factory() as db:
            db.add(
                User(
                    id=7,
                    username="refresh_race_user",
                    full_name="Refresh Race User",
                    email="refresh-race@example.test",
                    password_hash="unused-in-refresh-test",
                    is_active=True,
                    must_change_password=False,
                    failed_login_count=0,
                    security_version=1,
                    created_at=now,
                )
            )
            db.add(
                UserSession(
                    id=original_session_id,
                    user_id=7,
                    token_family=family,
                    refresh_token_hash=hash_refresh_token(raw_refresh_token),
                    created_at=now,
                    last_used_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
            db.commit()

        start = threading.Barrier(3)
        issue_lock = threading.Lock()
        second_issue_entered = threading.Event()
        issue_count = 0
        real_issue_session = auth._issue_session

        def coordinated_issue_session(*args, **kwargs):
            nonlocal issue_count
            with issue_lock:
                issue_count += 1
                position = issue_count
            if position == 1:
                second_issue_entered.wait(timeout=1.0)
            else:
                second_issue_entered.set()
            return real_issue_session(*args, **kwargs)

        def rotate() -> tuple[str, int | None]:
            with session_factory() as db:
                start.wait(timeout=5)
                try:
                    auth.refresh_session(
                        _request(),
                        Response(),
                        RefreshRequest(refresh_token=raw_refresh_token),
                        db,
                    )
                except HTTPException as exc:
                    return "rejected", exc.status_code
                return "success", None

        with patch.object(auth, "_issue_session", side_effect=coordinated_issue_session):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(rotate) for _ in range(2)]
                start.wait(timeout=5)
                results = [future.result(timeout=10) for future in futures]

        self.assertEqual(results.count(("success", None)), 1)
        self.assertEqual(results.count(("rejected", 401)), 1)
        self.assertEqual(issue_count, 1)

        with session_factory() as db:
            family_sessions = db.scalars(
                select(UserSession).where(UserSession.token_family == family)
            ).all()
            events = db.scalars(
                select(SecurityEvent).where(SecurityEvent.user_id == 7)
            ).all()

        self.assertEqual(len(family_sessions), 2)
        self.assertFalse(any(session.revoked_at is None for session in family_sessions))
        replacement = next(
            session for session in family_sessions if session.id != original_session_id
        )
        self.assertIsNotNone(replacement.compromised_at)
        self.assertEqual(
            sorted((event.event_type, event.result) for event in events),
            [("refresh", "success"), ("refresh_reuse", "blocked")],
        )


if __name__ == "__main__":
    unittest.main()
