from __future__ import annotations

import hashlib
import hmac
import os
import ssl
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app import security
from app.routers import insights as insight_routes
from app.routers import pricing_worker
from app.services.insights import MarketInsightEngine, ProviderConfig


class EmailTransportRegressionTests(unittest.TestCase):
    def settings(self, port=465, use_tls=True):
        return SimpleNamespace(smtp_host="mail.fixture.invalid", smtp_port=port,
                               smtp_username="fixture-user", smtp_password="fixture-password",
                               smtp_from="alerts@fixture.invalid", smtp_use_tls=use_tls, debug=False)

    def test_implicit_tls_port_never_opens_plain_connection(self):
        for enabled in (True, False):
            with self.subTest(use_tls=enabled), patch.object(security, "settings", self.settings(use_tls=enabled)), \
                    patch.object(security.smtplib, "SMTP") as plain, \
                    patch.object(security.smtplib, "SMTP_SSL") as encrypted:
                self.assertTrue(security.send_email("user@fixture.invalid", "Verify", "Code: fixture"))
                plain.assert_not_called()
                encrypted.assert_called_once()
                context = encrypted.call_args.kwargs["context"]
                self.assertTrue(context.check_hostname)
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                client = encrypted.return_value.__enter__.return_value
                client.starttls.assert_not_called()
                client.login.assert_called_once_with("fixture-user", "fixture-password")
                client.send_message.assert_called_once()

    def test_starttls_precedes_login_and_send(self):
        with patch.object(security, "settings", self.settings(port=587)), \
                patch.object(security.smtplib, "SMTP") as plain, \
                patch.object(security.smtplib, "SMTP_SSL") as encrypted:
            self.assertTrue(security.send_email("user@fixture.invalid", "Reset", "Code: fixture"))
        encrypted.assert_not_called()
        client = plain.return_value.__enter__.return_value
        self.assertEqual([call[0] for call in client.mock_calls],
                         ["ehlo", "starttls", "ehlo", "login", "send_message"])
        self.assertEqual(client.starttls.call_args.kwargs["context"].verify_mode, ssl.CERT_REQUIRED)

    def test_transport_failure_is_reported_without_sending(self):
        with patch.object(security, "settings", self.settings()), \
                patch.object(security.smtplib, "SMTP") as plain, \
                patch.object(security.smtplib, "SMTP_SSL", side_effect=OSError("fixture unreachable")):
            self.assertFalse(security.send_email("user@fixture.invalid", "Verify", "Code: fixture"))
        plain.assert_not_called()

    def test_starttls_certificate_failure_never_logs_in_or_sends(self):
        with patch.object(security, "settings", self.settings(port=587)), \
                patch.object(security.smtplib, "SMTP") as plain:
            client = plain.return_value.__enter__.return_value
            client.starttls.side_effect = ssl.SSLCertVerificationError("fixture bad certificate")
            self.assertFalse(security.send_email("user@fixture.invalid", "Reset", "Code: fixture"))
        client.login.assert_not_called()
        client.send_message.assert_not_called()


class WorkerAuthenticationRegressionTests(unittest.IsolatedAsyncioTestCase):
    secret = "fixture-worker-secret-" * 3
    body = b'{"quotes":[]}'
    now = 1_700_000_000

    def request(self, timestamp, signature=None):
        signature = signature if signature is not None else hmac.new(
            self.secret.encode(), timestamp.encode() + b"." + self.body, hashlib.sha256
        ).hexdigest()
        return SimpleNamespace(headers={"X-Pricing-Worker-Timestamp": timestamp,
                                        "X-Pricing-Worker-Signature": signature})

    async def test_malformed_nonascii_signature_or_timestamp_returns_401_without_store(self):
        requests = [self.request(str(self.now), "ت" * 64), self.request("۱۷۰۰۰۰۰۰۰۰", "0" * 64)]
        for request in requests:
            with self.subTest(headers=request.headers), \
                    patch.object(pricing_worker.settings, "pricing_worker_shared_secret", self.secret), \
                    patch.object(pricing_worker.time, "time", return_value=self.now), \
                    patch.object(pricing_worker.pricing_redis, "client") as store:
                with self.assertRaises(HTTPException) as raised:
                    await pricing_worker._authenticate(request, self.body)
                self.assertEqual(raised.exception.status_code, 401)
                store.assert_not_called()

    async def test_future_clock_request_cannot_replay_until_its_acceptance_window_ends(self):
        for offset, elapsed in ((299, 301), (300, 600)):
            now = [float(self.now)]
            expiry = {}

            async def claim(key, value, *, ex, nx):
                if expiry.get(key, 0) > now[0]:
                    return False
                expiry[key] = now[0] + ex
                return True

            request = self.request(str(self.now + offset))
            store = SimpleNamespace(set=AsyncMock(side_effect=claim))
            with self.subTest(offset=offset), \
                    patch.object(pricing_worker.settings, "pricing_worker_shared_secret", self.secret), \
                    patch.object(pricing_worker.time, "time", side_effect=lambda: now[0]), \
                    patch.object(pricing_worker.pricing_redis, "client", return_value=store):
                await pricing_worker._authenticate(request, self.body)
                now[0] += elapsed
                with self.assertRaises(HTTPException) as raised:
                    await pricing_worker._authenticate(request, self.body)
                self.assertEqual(raised.exception.status_code, 409)

    def test_raw_nonascii_http_signature_is_401_and_never_reaches_ingest(self):
        app = FastAPI()
        app.include_router(pricing_worker.router)
        with patch.object(pricing_worker.settings, "pricing_worker_shared_secret", self.secret), \
                patch.object(pricing_worker.time, "time", return_value=self.now), \
                patch.object(pricing_worker.pricing_redis, "client") as store, \
                patch.object(pricing_worker.instrument_pricing_service, "ingest_worker_quote") as ingest:
            with TestClient(app, raise_server_exceptions=False) as client:
                result = client.post("/api/internal/pricing-worker/ingest", content=self.body, headers=[
                    (b"X-Pricing-Worker-Timestamp", str(self.now).encode()),
                    (b"X-Pricing-Worker-Signature", b"\xff" * 64),
                ])
        self.assertEqual(result.status_code, 401)
        store.assert_not_called()
        ingest.assert_not_called()


class ProviderResponseRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_content_type_uses_the_next_provider(self):
        for malformed in (123, ["not text"], {"text": "not a completion"}, True):
            post = AsyncMock(side_effect=[
                httpx.Response(200, json={"choices": [{"message": {"content": malformed}}]},
                               request=httpx.Request("POST", "https://primary.fixture.invalid")),
                httpx.Response(200, json={"choices": [{"message": {"content": "Fallback works"}}]},
                               request=httpx.Request("POST", "https://secondary.fixture.invalid")),
            ])
            client = MagicMock()
            client.__aenter__ = AsyncMock(return_value=SimpleNamespace(post=post))
            client.__aexit__ = AsyncMock(return_value=None)
            providers = [ProviderConfig("https://primary.fixture.invalid", "model-a", "fixture-a"),
                         ProviderConfig("https://secondary.fixture.invalid", "model-b", "fixture-b")]
            with self.subTest(malformed=malformed), \
                    patch("app.services.insights.httpx.AsyncClient", return_value=client):
                answer = await MarketInsightEngine()._complete(
                    [{"role": "user", "content": "Market view"}], temperature=0.4, providers=providers
                )
                self.assertEqual(answer, "Fallback works")
                self.assertEqual(post.await_count, 2)

    async def test_long_answer_with_disclaimer_round_trips_through_chat_schema(self):
        engine = MarketInsightEngine()
        with patch.object(engine, "_complete", AsyncMock(return_value="پ" * 9000)), \
                patch.object(engine, "_check_quota"):
            reply = await engine.chat([{"role": "user", "content": "Market view"}], "fa", "fixture-1")
        self.assertLessEqual(len(reply), 4000)
        self.assertTrue(reply.endswith("توصیه سرمایه‌گذاری شخصی محسوب نمی‌شود."))
        model = insight_routes.ChatMessage(role="assistant", content=reply)
        self.assertEqual(model.content, reply)

    async def test_successful_long_chat_is_persisted_and_can_be_reopened(self):
        engine = MarketInsightEngine()
        payload = insight_routes.ChatRequest(
            messages=[{"role": "user", "content": "Market view"}],
            processing_consent=True, policy_version="2026-09-19.2",
        )
        db = MagicMock()
        session = SimpleNamespace(id=42, title="Fixture", created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        with patch.object(engine, "_complete", AsyncMock(return_value="پ" * 9000)), \
                patch.object(engine, "_check_quota"), \
                patch.object(insight_routes, "insight_engine", engine), \
                patch.object(insight_routes, "_enforce_rate_limit"), \
                patch.object(insight_routes, "AssistantChatSession", return_value=session):
            response = await insight_routes.chat(payload, SimpleNamespace(id=7), db)
        messages = [call.args[0] for call in db.add.call_args_list if hasattr(call.args[0], "role")]
        self.assertEqual([row.role for row in messages], ["user", "assistant"])
        self.assertEqual(messages[-1].content, response.reply)
        self.assertLessEqual(len(response.reply), 4000)
        db.scalars.return_value.all.return_value = messages
        with patch.object(insight_routes, "_owned_session", return_value=session):
            detail = insight_routes.get_chat_session(42, SimpleNamespace(id=7), db)
        self.assertEqual(detail.messages[-1].content, response.reply)

    def test_legacy_long_stored_answer_can_be_loaded_and_used_in_next_request(self):
        now = datetime.now(UTC)
        session = SimpleNamespace(id=42, user_id=7, title="Fixture", created_at=now, updated_at=now)
        stored = SimpleNamespace(role="assistant", content="پ" * 9000)
        db = MagicMock()
        db.scalars.return_value.all.return_value = [stored]
        with patch.object(insight_routes, "_owned_session", return_value=session):
            detail = insight_routes.get_chat_session(42, SimpleNamespace(id=7), db)
        self.assertLessEqual(len(detail.messages[0].content), 4000)
        self.assertEqual(stored.content, "پ" * 9000)
        continuation = insight_routes.ChatRequest(
            messages=[*detail.messages, insight_routes.ChatMessage(role="user", content="Next question")],
            processing_consent=True, policy_version="2026-09-19.2",
        )
        self.assertEqual(continuation.messages[-1].content, "Next question")
