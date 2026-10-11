from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from fastapi import HTTPException, Request, Response
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.admin.models import AdminRole, AdminSession, AdminUserRole, UserSecurityProfile
from app.config import settings
from app.db import Base
from app.models import PasswordReset, User, UserSession
from app.routers import auth
from app.schemas import ChangePasswordRequest, ForgotPasswordRequest, RefreshRequest, ResetPasswordRequest, UserSignin
from app import security


@compiles(BigInteger, "sqlite")
def _sqlite_integer(_type, _compiler, **_kwargs):
    # SQLite auto-generates row identifiers only for the exact INTEGER type.
    return "INTEGER"


def request(ip="198.51.100.20"):
    return Request({"type": "http", "method": "POST", "path": "/api/auth/change-password", "headers": [(b"user-agent", b"delivery-test")], "client": (ip, 1000), "scheme": "https", "server": ("test", 443), "query_string": b""})


class AuthDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        security._memory_limits.clear()
        self.local = patch.object(settings, "redis_url", None)
        self.local.start()
        self.user = User(username="delivery", full_name="Delivery", email="delivery@example.com", password_hash=security.hash_password("CurrentPassword12!"))
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.local.stop()
        self.db.close()
        self.engine.dispose()
        security._memory_limits.clear()

    def test_unknown_account_still_checks_dummy_password(self):
        with patch.object(auth, "verify_password", return_value=False) as verify:
            with self.assertRaises(HTTPException):
                auth.signin(UserSignin(username_or_email="absent", password="WrongPassword12"), request(), Response(), self.db)
            verify.assert_called_once_with("WrongPassword12", auth._DUMMY_PASSWORD_HASH)

    def test_desktop_signout_revokes_rotated_family_without_valid_access(self):
        now = datetime.now(UTC)
        token = "desktop-refresh-token-that-is-long-enough-for-validation"
        self.db.add_all([
            UserSession(id="old", user_id=self.user.id, token_family="desktop", refresh_token_hash=security.hash_refresh_token(token), created_at=now, last_used_at=now, expires_at=now+timedelta(days=1), revoked_at=now),
            UserSession(id="replacement", user_id=self.user.id, token_family="desktop", refresh_token_hash="b"*64, created_at=now, last_used_at=now, expires_at=now+timedelta(days=1)),
            UserSession(id="other-device", user_id=self.user.id, token_family="other", refresh_token_hash="c"*64, created_at=now, last_used_at=now, expires_at=now+timedelta(days=1)),
        ])
        self.db.commit()
        response = auth.signout(request(), Response(), self.db, RefreshRequest(refresh_token=token))
        self.assertEqual(response.status_code, 204)
        self.assertIsNotNone(self.db.get(UserSession, "replacement").revoked_at)
        self.assertIsNone(self.db.get(UserSession, "other-device").revoked_at)

    def test_public_password_change_revokes_admin_and_public_sessions(self):
        now = datetime.now(UTC)
        self.db.add_all([
            UserSession(id="public-session", user_id=self.user.id, token_family="family", refresh_token_hash="a"*64, created_at=now, last_used_at=now, expires_at=now+timedelta(days=1)),
            AdminSession(id="admin-session", user_id=self.user.id, token_hash="b"*64, csrf_token_hash="c"*64, ip_address="127.0.0.1", user_agent_hash="d"*64, expires_at=now+timedelta(hours=1)),
            UserSecurityProfile(user_id=self.user.id),
        ])
        self.db.commit()
        auth.change_password(ChangePasswordRequest(current_password="CurrentPassword12!", new_password="NewPasswordSafe12!"), request(), Response(), self.user, self.db)
        self.assertIsNotNone(self.db.get(UserSession, "public-session").revoked_at)
        self.assertEqual(self.db.get(AdminSession, "admin-session").revoke_reason, "password_changed")
        self.assertIsNotNone(self.db.get(UserSecurityProfile, self.user.id).password_changed_at)

    def test_admin_cannot_bypass_strong_policy_through_public_change(self):
        role = AdminRole(name="custom-admin")
        self.db.add(role)
        self.db.flush()
        self.db.add(AdminUserRole(user_id=self.user.id, role_id=role.id))
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            auth.change_password(ChangePasswordRequest(current_password="CurrentPassword12!", new_password="WeakPass123"), request(), Response(), self.user, self.db)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertTrue(security.verify_password("CurrentPassword12!", self.user.password_hash))

    def test_new_recovery_invalidates_old_codes_and_failure_rolls_back(self):
        old = PasswordReset(user_id=self.user.id, code_hash="unused", expires_at=datetime.now(UTC)+timedelta(minutes=15))
        self.db.add(old)
        self.db.commit()
        with patch.object(auth, "send_email", return_value=False):
            auth.forgot_password(ForgotPasswordRequest(email=self.user.email), request(), self.db)
        self.assertFalse(self.db.get(PasswordReset, old.id).used)
        with patch.object(auth, "send_email", return_value=True):
            auth.forgot_password(ForgotPasswordRequest(email=self.user.email), request(), self.db)
        self.assertTrue(self.db.get(PasswordReset, old.id).used)
        self.assertEqual(len(self.db.scalars(select(PasswordReset).where(PasswordReset.used.is_(False))).all()), 1)

    def test_recovery_success_consumes_all_codes_and_clears_forced_change(self):
        self.user.must_change_password = True
        self.db.add_all([PasswordReset(user_id=self.user.id, code_hash=security.hash_password("123456"), expires_at=datetime.now(UTC)+timedelta(minutes=10)) for _ in range(2)])
        self.db.commit()
        payload = ResetPasswordRequest(email=self.user.email, code="123456", new_password="NewPasswordSafe12!")
        auth.reset_password(payload, request(), self.db)
        self.assertFalse(self.user.must_change_password)
        self.assertFalse(self.db.scalars(select(PasswordReset).where(PasswordReset.used.is_(False))).all())
        with self.assertRaises(HTTPException):
            auth.reset_password(payload, request(), self.db)

    def test_distributed_guard_fails_closed_and_local_map_is_bounded(self):
        with patch.object(settings, "redis_url", "redis://unused"), patch.object(settings, "debug", False), patch.object(security, "_shared_rate_store", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                security.rate_limit_hit("login", "person", 5, 60)
            self.assertEqual(caught.exception.status_code, 503)
        with patch.object(security, "_MEMORY_RATE_LIMIT_MAX_KEYS", 2):
            security.rate_limit_hit("login", "one", 5, 60)
            security.rate_limit_hit("login", "two", 5, 60)
            with self.assertRaises(HTTPException): security.rate_limit_hit("login", "three", 5, 60)
            self.assertEqual(len(security._memory_limits), 2)
            security._memory_limits["expired"] = (5, 0)
            security.rate_limit_hit("login", "one", 5, 60)
            self.assertNotIn("expired", security._memory_limits)
