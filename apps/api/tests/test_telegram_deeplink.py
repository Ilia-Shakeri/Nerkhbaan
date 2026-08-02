from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-that-is-long-enough"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-only-bot-token"
os.environ["DEBUG"] = "false"

from app.routers import notifications
from app.services.alert_engine import AlertEngine


FROZEN_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
BOT_TOKEN = "test-only-bot-token"
BOT_USERNAME = "NerkhbaanTestBot"
WEBHOOK_SECRET = "test-only-webhook-secret"


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_NOW.replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)


class _Result:
    def __init__(self, value=None, rowcount: int = 0) -> None:
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def first(self):
        return self.value

    def all(self):
        return [] if self.value is None else [self.value]

    def scalars(self):
        return self


class _Session:
    def __init__(self, preferences) -> None:
        self.preferences = preferences
        self.challenge = None
        self.commit_count = 0
        self.rollback_count = 0
        self.atomic_consume_seen = False
        self.added: list[object] = []

    def add(self, value) -> None:
        self.added.append(value)
        if hasattr(value, "expires_at") and hasattr(value, "used"):
            if getattr(value, "used", None) is None:
                value.used = False
            if getattr(value, "created_at", None) is None:
                value.created_at = FROZEN_NOW
            if getattr(value, "id", None) is None:
                value.id = 1
            self.challenge = value

    def flush(self) -> None:
        return None

    def refresh(self, _value) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def _challenge_for(self, statement):
        sql = str(statement).lower()
        if "otp_verifications" not in sql and "telegram_deep_link_tokens" not in sql:
            return None
        challenge = self.challenge
        if challenge is None or bool(getattr(challenge, "used", False)):
            return None
        expires_at = getattr(challenge, "expires_at", None)
        if "expires_at" in sql and expires_at is not None and expires_at <= FROZEN_NOW:
            return None
        return challenge

    def scalar(self, statement):
        sql = str(statement).lower()
        if sql.lstrip().startswith("update"):
            return self._consume(statement).value
        challenge = self._challenge_for(statement)
        if challenge is not None:
            if getattr(statement, "_for_update_arg", None) is not None:
                self.atomic_consume_seen = True
            return challenge
        if "notification_preferences" in sql:
            return self.preferences
        return None

    def scalars(self, statement):
        return _Result(self.scalar(statement))

    def execute(self, statement):
        sql = str(statement).lower()
        if sql.lstrip().startswith("update") and (
            "otp_verifications" in sql or "telegram_deep_link_tokens" in sql
        ):
            return self._consume(statement)
        return _Result()

    def _consume(self, statement) -> _Result:
        sql = str(statement).lower()
        has_unused_guard = "used is false" in sql or "used = false" in sql
        has_expiry_guard = "expires_at" in sql
        if has_unused_guard and has_expiry_guard:
            self.atomic_consume_seen = True
        challenge = self._challenge_for(statement)
        if challenge is None:
            return _Result(rowcount=0)
        challenge.used = True
        return _Result(challenge, rowcount=1)


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
        "telegram_id": None,
        "telegram_verified": False,
        "silent_mode": False,
        "aggressive_alerts": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _settings(**overrides):
    values = {
        "telegram_alert_delivery_enabled": True,
        "telegram_bot_token": BOT_TOKEN,
        "telegram_bot_username": BOT_USERNAME,
        "telegram_deeplink_enabled": True,
        "telegram_deeplink_ttl_seconds": 600,
        "telegram_deeplink_signing_secret": "test-only-link-signing-secret",
        "telegram_webhook_secret": WEBHOOK_SECRET,
        "vapid_public_key": None,
        "vapid_private_key": None,
        "smtp_host": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _telegram_update(token: str, *, chat_type: str = "private", chat_id: int = 987654321):
    return {
        "update_id": 1001,
        "message": {
            "message_id": 77,
            "date": int(FROZEN_NOW.timestamp()),
            "chat": {"id": chat_id, "type": chat_type},
            "text": f"/start {token}",
        },
    }


class TelegramDeepLinkContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=42)
        self.preferences = _preferences()
        self.db = _Session(self.preferences)
        app = FastAPI()
        app.include_router(notifications.router)
        app.dependency_overrides[notifications.get_current_user] = lambda: self.user
        app.dependency_overrides[notifications.get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def _post_link(self, **setting_overrides):
        with patch.object(notifications, "settings", _settings(**setting_overrides)), patch.object(
            notifications, "datetime", _FrozenDateTime
        ), patch.object(
            notifications,
            "_send_telegram_verification",
            side_effect=AssertionError("deep-link creation must not call Telegram"),
        ):
            return self.client.post("/api/notifications/telegram/deep-link")

    def _post_update(self, token: str, *, secret=WEBHOOK_SECRET, chat_type="private", **settings):
        headers = {}
        if secret is not None:
            headers["X-Telegram-Bot-Api-Secret-Token"] = secret
        with patch.object(notifications, "settings", _settings(**settings)), patch.object(
            notifications, "datetime", _FrozenDateTime
        ), patch.object(
            notifications, "_prefs_for", return_value=self.preferences
        ):
            return self.client.post(
                "/api/notifications/telegram/webhook",
                headers=headers,
                json=_telegram_update(token, chat_type=chat_type),
            )

    def _create_token(self) -> tuple[str, dict]:
        response = self._post_link()
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        query = parse_qs(urlsplit(payload["url"]).query)
        return query["start"][0], payload

    def _state(self):
        return (
            self.preferences.telegram_id,
            self.preferences.telegram_enabled,
            self.preferences.telegram_verified,
            bool(self.db.challenge and self.db.challenge.used),
            self.db.commit_count,
        )

    def test_routes_have_expected_names_and_auth_boundary(self) -> None:
        routes = {
            (route.path, method): route
            for route in notifications.router.routes
            for method in getattr(route, "methods", set())
        }
        create_key = ("/api/notifications/telegram/deep-link", "POST")
        webhook_key = ("/api/notifications/telegram/webhook", "POST")
        self.assertIn(create_key, routes)
        self.assertIn(webhook_key, routes)
        create = routes[create_key]
        webhook = routes[webhook_key]

        self.assertEqual(create.endpoint.__name__, "create_telegram_deep_link")
        self.assertEqual(webhook.endpoint.__name__, "handle_telegram_start")
        self.assertIn(
            notifications.get_current_user,
            [dependency.call for dependency in create.dependant.dependencies],
        )
        self.assertNotIn(
            notifications.get_current_user,
            [dependency.call for dependency in webhook.dependant.dependencies],
        )

    def test_authenticated_user_gets_short_lived_signed_bot_url_without_bot_token(self) -> None:
        token, payload = self._create_token()
        parsed = urlsplit(payload["url"])
        expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "t.me")
        self.assertEqual(parsed.path, f"/{BOT_USERNAME}")
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(expires_at, FROZEN_NOW + timedelta(seconds=600))
        self.assertNotIn(BOT_TOKEN, json.dumps(payload, sort_keys=True))
        self.assertNotIn("bot_token", payload)
        self.assertIsNotNone(self.db.challenge)

    def test_valid_private_start_atomically_consumes_token_and_verifies_numeric_chat(self) -> None:
        token, _payload = self._create_token()
        before_commits = self.db.commit_count
        self.db.atomic_consume_seen = False

        response = self._post_update(token)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["accepted"])
        self.assertTrue(self.db.atomic_consume_seen)
        self.assertTrue(self.db.challenge.used)
        self.assertEqual(self.preferences.telegram_id, "987654321")
        self.assertTrue(self.preferences.telegram_verified)
        self.assertTrue(self.preferences.telegram_enabled)
        self.assertEqual(self.db.commit_count, before_commits + 1)

    def test_replay_is_rejected_without_second_mutation(self) -> None:
        token, _payload = self._create_token()
        first = self._post_update(token)
        self.assertEqual(first.status_code, 200, first.text)
        state = self._state()

        replay = self._post_update(token)

        self.assertEqual(replay.status_code, 400, replay.text)
        self.assertEqual(self._state(), state)

    def test_disabling_telegram_invalidates_pending_deep_link(self) -> None:
        token, _payload = self._create_token()
        with patch.object(notifications, "settings", _settings()):
            disabled = self.client.delete("/api/notifications/telegram")
        self.assertEqual(disabled.status_code, 200, disabled.text)
        state = self._state()

        response = self._post_update(token)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._state(), state)

    def test_expired_token_is_rejected_without_mutation(self) -> None:
        token, _payload = self._create_token()
        self.db.challenge.expires_at = FROZEN_NOW - timedelta(seconds=1)
        state = self._state()

        response = self._post_update(token)

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._state(), state)

    def test_tampered_signature_is_rejected_without_mutation(self) -> None:
        token, _payload = self._create_token()
        replacement = "A" if token[-1] != "A" else "B"
        state = self._state()

        response = self._post_update(f"{token[:-1]}{replacement}")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._state(), state)

    def test_webhook_requires_secret_header_and_private_chat(self) -> None:
        for secret, chat_type, expected_status in (
            (None, "private", 403),
            ("wrong-secret", "private", 403),
            (WEBHOOK_SECRET, "group", 400),
        ):
            with self.subTest(secret=secret, chat_type=chat_type):
                token, _payload = self._create_token()
                state = self._state()

                response = self._post_update(token, secret=secret, chat_type=chat_type)

                self.assertEqual(response.status_code, expected_status, response.text)
                self.assertEqual(self._state(), state)
                self.db.challenge = None

    def test_disabled_or_unconfigured_feature_returns_stable_503(self) -> None:
        cases = (
            {"telegram_deeplink_enabled": False},
            {"telegram_bot_username": None},
            {"telegram_deeplink_signing_secret": None},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                response = self._post_link(**overrides)
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(
                    response.json()["detail"]["code"],
                    "telegram_deeplink_unavailable",
                )
                self.assertIsNone(self.db.challenge)
                self.assertEqual(self.db.commit_count, 0)

        response = self._post_update("invalid", telegram_webhook_secret=None)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "telegram_deeplink_unavailable",
        )

    def test_existing_verified_numeric_chat_id_remains_valid(self) -> None:
        preferences = _preferences(
            telegram_id="123456789",
            telegram_enabled=True,
            telegram_verified=True,
        )
        with patch.object(
            notifications,
            "settings",
            _settings(telegram_deeplink_enabled=False),
        ):
            response = notifications._to_response(preferences)

        self.assertEqual(response.telegram_id, "123456789")
        self.assertTrue(response.telegram_enabled)
        self.assertTrue(response.telegram_verified)
        self.assertEqual(AlertEngine._telegram_destination(preferences), "123456789")

    def test_preferences_report_deep_link_availability_separately(self) -> None:
        preferences = _preferences()
        with patch.object(notifications, "settings", _settings()):
            enabled = notifications._to_response(preferences)
        with patch.object(
            notifications,
            "settings",
            _settings(telegram_deeplink_enabled=False),
        ):
            disabled = notifications._to_response(preferences)

        self.assertTrue(enabled.telegram_available)
        self.assertTrue(enabled.telegram_deeplink_available)
        self.assertTrue(disabled.telegram_available)
        self.assertFalse(disabled.telegram_deeplink_available)


if __name__ == "__main__":
    unittest.main()
