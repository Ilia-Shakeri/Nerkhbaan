from __future__ import annotations

import os
import re
import threading
import time
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
from app.schemas import ChangePasswordRequest, RefreshRequest
from app.security import hash_refresh_token, hash_client_value


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
        self.selected: list[object] = []
        self.user = User(id=session.user_id, is_active=True)

    def scalar(self, statement):
        self.selected.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        return self.user if entity is User else self.session

    def execute(self, statement):
        self.executed.append(statement)

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commit_count += 1


class RefreshRotationUnitTests(unittest.TestCase):
    def test_refresh_session_locks_owner_before_token_state_check(self) -> None:
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
        self.assertTrue(sql.startswith("SELECT USERS."))
        self.assertIn("SELECT USER_SESSIONS.USER_ID", sql)
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
        self.assertEqual([statement.column_descriptions[0]["entity"] for statement in db.selected], [User, UserSession])
        for statement in db.selected:
            self.assertIn("FOR UPDATE", str(statement.compile(dialect=postgresql.dialect())).upper())
            self.assertTrue(statement.get_execution_options()["populate_existing"])
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

    def test_signout_prefers_explicit_refresh_over_an_unrelated_cookie(self) -> None:
        scope = dict(_request().scope)
        scope["headers"] = list(scope["headers"]) + [
            (b"cookie", f"{auth.settings.auth_refresh_cookie_name}=unrelated-cookie".encode())
        ]
        with patch.object(auth, "_lock_refresh_session", return_value=(None, None)) as locked:
            result = auth.signout(Request(scope), Response(), _LockProbeSession(), RefreshRequest(refresh_token="b" * 32))
        self.assertEqual(result.status_code, 204)
        locked.assert_called_once()
        self.assertEqual(locked.call_args.args[1], hash_refresh_token("b" * 32))


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

    def setUp(self) -> None:
        assert self.test_engine is not None
        with self.test_engine.begin() as connection:
            for table in (SecurityEvent.__table__, UserSession.__table__, User.__table__):
                connection.execute(table.delete())

    def _seed_family(self) -> tuple[str, str, str]:
        assert self.test_engine is not None
        old_token = "previous-refresh-token-for-race-proof"
        active_token = "active-refresh-token-for-race-proof"
        family = str(uuid.uuid4())
        now = datetime.now(UTC)
        with Session(self.test_engine) as db:
            db.add(User(id=7, username="revoke_race_user", full_name="Revoke Race User",
                        email="revoke-race@example.com", password_hash="current-password-hash",
                        is_active=True, security_version=1))
            db.flush()
            db.add_all([
                UserSession(id="previous", user_id=7, token_family=family,
                            refresh_token_hash=hash_refresh_token(old_token),
                            created_at=now, last_used_at=now, expires_at=now + timedelta(days=1),
                            revoked_at=now - timedelta(seconds=20), replaced_by_session_id="active"),
                UserSession(id="active", user_id=7, token_family=family,
                            refresh_token_hash=hash_refresh_token(active_token),
                            created_at=now, last_used_at=now, expires_at=now + timedelta(days=1)),
            ])
            db.commit()
        return old_token, active_token, family

    def _assert_revocation_waits_for_rotation(self, operation: str) -> None:
        assert self.test_engine is not None
        old_token, active_token, family = self._seed_family()
        rotation_inserted = threading.Event()
        release_rotation = threading.Event()
        revocation_lock_attempted = threading.Event()
        revocation_backend: dict[str, int] = {}
        real_issue_session = auth._issue_session

        class ObservedSession(Session):
            def scalar(inner_self, statement, *args, **kwargs):
                if (inner_self.info.get("revoking")
                        and statement.column_descriptions[0]["entity"] is User
                        and statement._for_update_arg is not None):
                    revocation_backend["pid"] = inner_self.connection().exec_driver_sql(
                        "SELECT pg_backend_pid()"
                    ).scalar_one()
                    revocation_lock_attempted.set()
                return super().scalar(statement, *args, **kwargs)

        def pause_after_insert(*args, **kwargs):
            result = real_issue_session(*args, **kwargs)
            rotation_inserted.set()
            if not release_rotation.wait(timeout=10):
                raise TimeoutError("Rotation coordinator did not release the transaction")
            return result

        def rotate():
            with ObservedSession(self.test_engine) as db:
                return auth.refresh_session(_request(), Response(), RefreshRequest(refresh_token=active_token), db)

        def revoke():
            with ObservedSession(self.test_engine, info={"revoking": True}) as db:
                if operation == "signout":
                    return auth.signout(_request(), Response(), db, RefreshRequest(refresh_token=old_token)).status_code
                if operation == "terminate":
                    return auth.terminate_session("previous", db.get(User, 7), db).status_code
                if operation == "password":
                    return auth.change_password(
                        ChangePasswordRequest(current_password="CurrentPassword12!", new_password="NextPasswordSafe12!"),
                        _request(), Response(), db.get(User, 7), db,
                    )["message"]
                try:
                    auth.refresh_session(_request(), Response(), RefreshRequest(refresh_token=old_token), db)
                except HTTPException as exc:
                    return exc.status_code
                raise AssertionError("A replayed token was accepted")

        with patch.object(auth, "_issue_session", side_effect=pause_after_insert), \
                patch.object(auth, "_enforce_request_limit"), patch.object(auth, "_account_limit"), \
                patch.object(auth, "_password_policy"), patch.object(auth, "revoke_admin_sessions"), \
                patch.object(auth, "verify_password", return_value=True), patch.object(auth, "hash_password", return_value="new-password-hash"):
            with ThreadPoolExecutor(max_workers=2) as executor:
                rotating = executor.submit(rotate)
                revoking = None
                try:
                    self.assertTrue(rotation_inserted.wait(timeout=5), "Rotation did not insert its child")
                    revoking = executor.submit(revoke)
                    self.assertTrue(revocation_lock_attempted.wait(timeout=5), "Revocation did not lock the owner first")
                    deadline = time.monotonic() + 3
                    waiting = False
                    with self.test_engine.connect() as observer:
                        while time.monotonic() < deadline:
                            waiting = observer.execute(
                                text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"),
                                {"pid": revocation_backend["pid"]},
                            ).scalar() is True
                            observer.commit()
                            if waiting:
                                break
                            threading.Event().wait(0.01)
                    self.assertTrue(waiting, "PostgreSQL did not block revocation on the owner lock")
                    self.assertFalse(revoking.done(), "Revocation passed the uncommitted rotation")
                finally:
                    release_rotation.set()
                rotating.result(timeout=10)
                result = revoking.result(timeout=10) if revoking is not None else None
        self.assertEqual(result, "Password changed successfully" if operation == "password" else 401 if operation == "replay" else 204)
        with Session(self.test_engine) as db:
            members = db.scalars(select(UserSession).where(UserSession.token_family == family)).all()
            self.assertEqual(len(members), 3)
            self.assertTrue(all(row.revoked_at is not None for row in members))
            if operation == "replay":
                child = next(row for row in members if row.id not in {"previous", "active"})
                self.assertIsNotNone(child.compromised_at)
            if operation == "password":
                self.assertEqual(db.get(User, 7).security_version, 2)

    def test_signout_old_token_revokes_a_concurrent_rotated_child(self) -> None:
        self._assert_revocation_waits_for_rotation("signout")

    def test_terminate_rotated_session_revokes_a_concurrent_child(self) -> None:
        self._assert_revocation_waits_for_rotation("terminate")

    def test_replay_revokes_a_concurrent_rotated_child(self) -> None:
        self._assert_revocation_waits_for_rotation("replay")

    def test_password_change_revokes_a_concurrent_rotated_child(self) -> None:
        self._assert_revocation_waits_for_rotation("password")

    def test_password_change_reloads_a_previously_read_password(self) -> None:
        assert self.test_engine is not None
        self._seed_family()
        with Session(self.test_engine) as stale, Session(self.test_engine) as writer:
            user = stale.get(User, 7)
            current = writer.get(User, 7)
            current.password_hash = "changed-elsewhere"
            writer.commit()
            with patch.object(auth, "_enforce_request_limit"), patch.object(auth, "_account_limit"), \
                    patch.object(auth, "verify_password", return_value=False) as verify:
                with self.assertRaises(HTTPException) as caught:
                    auth.change_password(
                        ChangePasswordRequest(current_password="CurrentPassword12!", new_password="NextPasswordSafe12!"),
                        _request(), Response(), user, stale,
                    )
            self.assertEqual(caught.exception.status_code, 400)
            verify.assert_called_once_with("CurrentPassword12!", "changed-elsewhere")

    def test_concurrent_rotation_allows_one_success_without_revoking_replacement(self) -> None:
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
                    email="refresh-race@example.com",
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
                    ip_hash=hash_client_value("198.51.100.20"),
                    user_agent_hash=hash_client_value("refresh-rotation-test"),
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
        self.assertEqual(results.count(("rejected", 409)), 1)
        self.assertEqual(issue_count, 1)

        with session_factory() as db:
            family_sessions = db.scalars(
                select(UserSession).where(UserSession.token_family == family)
            ).all()
            events = db.scalars(
                select(SecurityEvent).where(SecurityEvent.user_id == 7)
            ).all()

        self.assertEqual(len(family_sessions), 2)
        self.assertEqual(sum(session.revoked_at is None for session in family_sessions), 1)
        replacement = next(
            session for session in family_sessions if session.id != original_session_id
        )
        self.assertIsNone(replacement.compromised_at)
        self.assertEqual(
            sorted((event.event_type, event.result) for event in events),
            [("refresh", "success"), ("refresh_duplicate", "ignored")],
        )


if __name__ == "__main__":
    unittest.main()
