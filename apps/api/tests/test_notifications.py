from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

os.environ["DEBUG"] = "false"

from app.routers import notifications


FROZEN_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_NOW.replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)


class _Session:
    def __init__(self, verification=None) -> None:
        self.verification = verification
        self.commit_count = 0
        self.refreshed: list[object] = []
        self.scalar_count = 0

    def scalar(self, _statement):
        self.scalar_count += 1
        if self.verification is None or self.verification.used:
            return None
        return self.verification

    def commit(self) -> None:
        self.commit_count += 1

    def refresh(self, value) -> None:
        self.refreshed.append(value)


def _preferences(**overrides):
    values = {
        "push_app": True,
        "sms_enabled": False,
        "sms_phone": None,
        "sms_verified": False,
        "email_enabled": False,
        "email_address": None,
        "email_verified": False,
        "telegram_enabled": False,
        "telegram_id": "123456789",
        "telegram_verified": False,
        "silent_mode": False,
        "aggressive_alerts": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _verification(*, expires_at=None):
    return SimpleNamespace(
        expires_at=expires_at or FROZEN_NOW + timedelta(minutes=5),
        code_hash="local-test-hash",
        used=False,
    )


class NotificationPreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=42)

    @staticmethod
    def _settings(
        *,
        telegram_enabled: bool = True,
        telegram_token: str | None = "local-test-token",
        vapid_public_key: str | None = None,
        vapid_private_key: str | None = None,
    ) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(
            patch.object(
                notifications.settings,
                "telegram_alert_delivery_enabled",
                telegram_enabled,
            )
        )
        stack.enter_context(
            patch.object(notifications.settings, "telegram_bot_token", telegram_token)
        )
        stack.enter_context(
            patch.object(notifications.settings, "vapid_public_key", vapid_public_key)
        )
        stack.enter_context(
            patch.object(notifications.settings, "vapid_private_key", vapid_private_key)
        )
        stack.enter_context(patch.object(notifications.settings, "smtp_host", None))
        return stack

    def _confirm(
        self,
        *,
        db: _Session,
        prefs,
        code_valid: bool = True,
        blocked: bool = False,
        telegram_enabled: bool = True,
        telegram_token: str | None = "local-test-token",
    ):
        rate_state = SimpleNamespace(
            blocked=blocked,
            retry_after=37 if blocked else 0,
        )
        with self._settings(
            telegram_enabled=telegram_enabled,
            telegram_token=telegram_token,
        ), patch.object(notifications, "datetime", _FrozenDateTime), patch.object(
            notifications, "_prefs_for", return_value=prefs
        ), patch.object(
            notifications, "rate_limit_hit", return_value=rate_state
        ), patch.object(
            notifications, "rate_limit_clear"
        ) as rate_limit_clear, patch.object(
            notifications, "verify_password", return_value=code_valid
        ):
            result = notifications.confirm_telegram(
                notifications.TelegramConfirmRequest(code="123456"),
                current_user=self.user,
                db=db,
            )
        return result, rate_limit_clear

    def test_telegram_confirmation_success(self) -> None:
        prefs = _preferences()
        verification = _verification()
        db = _Session(verification)

        result, rate_limit_clear = self._confirm(db=db, prefs=prefs)

        self.assertTrue(verification.used)
        self.assertTrue(prefs.telegram_enabled)
        self.assertTrue(prefs.telegram_verified)
        self.assertTrue(result.telegram_enabled)
        self.assertTrue(result.telegram_verified)
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(db.refreshed, [prefs])
        rate_limit_clear.assert_called_once_with(
            "notification-telegram-confirm",
            f"{self.user.id}:{prefs.telegram_id}",
        )

    def test_telegram_confirmation_requires_started_verification(self) -> None:
        prefs = _preferences(telegram_id=None)

        with self.assertRaises(HTTPException) as raised:
            self._confirm(db=_Session(), prefs=prefs)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(
            raised.exception.detail,
            "Telegram verification was not started",
        )

    def test_telegram_confirmation_rejects_invalid_code(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._confirm(
                db=_Session(_verification()),
                prefs=_preferences(),
                code_valid=False,
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.detail,
            "Invalid or expired verification code",
        )

    def test_telegram_confirmation_rejects_expired_code(self) -> None:
        expired = _verification(expires_at=FROZEN_NOW - timedelta(seconds=1))

        with self.assertRaises(HTTPException) as raised:
            self._confirm(db=_Session(expired), prefs=_preferences())

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(expired.used)

    def test_telegram_confirmation_rejects_replayed_code(self) -> None:
        prefs = _preferences()
        verification = _verification()
        db = _Session(verification)
        self._confirm(db=db, prefs=prefs)

        with self.assertRaises(HTTPException) as raised:
            self._confirm(db=db, prefs=prefs)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(db.commit_count, 1)

    def test_telegram_confirmation_rate_limit(self) -> None:
        db = _Session(_verification())

        with self.assertRaises(HTTPException) as raised:
            self._confirm(db=db, prefs=_preferences(), blocked=True)

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers, {"Retry-After": "37"})
        self.assertEqual(db.scalar_count, 0)

    def test_telegram_confirmation_rejects_disabled_delivery(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._confirm(
                db=_Session(_verification()),
                prefs=_preferences(),
                telegram_enabled=False,
                telegram_token=None,
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(
            raised.exception.detail,
            "Telegram alert delivery is not configured.",
        )

    def test_push_enable_requires_vapid_with_stable_error_code(self) -> None:
        prefs = _preferences(push_app=False)
        db = _Session()

        with self._settings(), patch.object(
            notifications, "_prefs_for", return_value=prefs
        ), self.assertRaises(HTTPException) as raised:
            notifications.set_basic_preference(
                "push_app",
                notifications.BasicPreferenceRequest(enabled=True),
                current_user=self.user,
                db=db,
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIsInstance(raised.exception.detail, dict)
        self.assertEqual(raised.exception.detail.get("code"), "push_unavailable")
        self.assertFalse(prefs.push_app)
        self.assertEqual(db.commit_count, 0)

    def test_push_disable_allowed_without_vapid(self) -> None:
        prefs = _preferences(push_app=True)
        db = _Session()

        with self._settings(), patch.object(
            notifications, "_prefs_for", return_value=prefs
        ):
            result = notifications.set_basic_preference(
                "push_app",
                notifications.BasicPreferenceRequest(enabled=False),
                current_user=self.user,
                db=db,
            )

        self.assertFalse(prefs.push_app)
        self.assertFalse(result.push_app)
        self.assertFalse(result.push_available)
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(db.refreshed, [prefs])


if __name__ == "__main__":
    unittest.main()
