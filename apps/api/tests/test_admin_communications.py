from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-with-32-characters")

from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.admin import models as admin_models
from app.admin.communication_schemas import CallPolicyUpdate, ChannelUpdate, QuietHours, TestEventCreate, TestRecipientCreate
from app.admin.communication_storage import decrypt_value, normalize_phone, read_provider, read_secret
from app.admin.deps import require_permission
from app.admin.bootstrap import ensure_admin_catalog
from app.admin.config import get_admin_config
from app.admin.deps import new_admin_session
from app.admin.models import AdminAuditLog, AdminSecret, CommunicationEvent, OperationalSetting
from app.admin.models import AdminRole, AdminUserRole, UserSecurityProfile
from app.admin.permissions import AdminPermissionKey
from app.admin.routers import communications
from app.models import Alert, AlertDeliveryJob, AlertTriggerEvent, NotificationPreference, OtpVerification, User
from app.routers import alerts, notifications
from app.schemas import AlertCreate
from app.services.communication_transport import TransportResult


def request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/admin/communications", "headers": [],
        "client": ("127.0.0.1", 123), "server": ("localhost", 8000), "scheme": "http"})


class CommunicationsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(id=index, username=f"user{index}", full_name=f"User {index}", email=f"user{index}@example.test", password_hash="unused", is_active=True) for index in (1, 2)])
        self.db.commit()
        self.principal = SimpleNamespace(user=self.db.get(User, 1), permissions=frozenset(item.value for item in AdminPermissionKey),
            security=SimpleNamespace(must_change_password=False), session=SimpleNamespace(reauthenticated_at=datetime.now(UTC)))
        self.key = patch.object(settings, "communications_encryption_key", SecretStr(Fernet.generate_key().decode()))
        self.key.start()

    def tearDown(self):
        self.key.stop()
        self.db.close()
        self.engine.dispose()

    def channel(self, **overrides):
        value = {"expected_version": 0, "provider_id": "kavenegar", "enabled": True,
            "config": {"sender": "1000001"}, "secret_action": "replace",
            "secret_value": {"api_key": "PrivateTestKey012345"}, "confirmation": "ENABLE SMS"}
        value.update(overrides)
        return communications.update_channel("sms", ChannelUpdate(**value), request(), self.principal, self.db)

    def recipient(self):
        return communications.create_recipient(TestRecipientCreate(label="Test owner", phone="09123456789", consent_confirmed=True),
            request(), self.principal, self.db)

    def event(self, recipient_id, **overrides):
        value = {"channel": "sms", "recipient_id": recipient_id, "client_request_id": uuid4()}
        value.update(overrides)
        return communications.create_test_event(TestEventCreate(**value), request(), self.principal, self.db)

    def authenticated_client(self, role_name):
        self.enterContext(patch.object(settings, "admin_frontend_enabled", True))
        self.enterContext(patch.object(settings, "admin_private_network_only", False))
        self.enterContext(patch.object(settings, "admin_ip_allowlist", ""))
        self.enterContext(patch.object(settings, "admin_mfa_required", False))
        self.enterContext(patch.dict(os.environ, {"ADMIN_SESSION_BIND_IP": "false", "ADMIN_SESSION_BIND_USER_AGENT": "true"}))
        get_admin_config.cache_clear()
        self.addCleanup(get_admin_config.cache_clear)
        ensure_admin_catalog(self.db)
        role = self.db.scalar(select(AdminRole).where(AdminRole.name == role_name))
        self.db.add(AdminUserRole(user_id=1, role_id=role.id, is_active=True))
        self.db.add(UserSecurityProfile(user_id=1, is_active=True, must_change_password=False))
        req = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"user-agent", b"testclient")],
            "client": ("127.0.0.1", 123), "server": ("localhost", 8000), "scheme": "https"})
        session, token, csrf = new_admin_session(self.db, self.principal.user, req)
        self.db.commit()
        app = FastAPI()
        app.include_router(communications.router, prefix="/api/admin")
        app.dependency_overrides[get_db] = lambda: self.db
        client = self.enterContext(TestClient(app, base_url="https://admin.example.test", client=("127.0.0.1", 50000)))
        client.cookies.set(get_admin_config().cookie_name, token)
        self.enterContext(patch("app.services.communication_transport._request", side_effect=AssertionError("paid network forbidden")))
        self.enterContext(patch("app.services.communication_transport.resolve_addresses", side_effect=AssertionError("provider DNS forbidden")))
        headers = {"Origin": get_admin_config().frontend_origin, "X-CSRF-Token": csrf, "User-Agent": "testclient"}
        return client, session, headers

    def test_real_http_session_origin_csrf_and_viewer_role_protect_channel_write(self):
        client, session, headers = self.authenticated_client("viewer")
        body = {"expected_version": 0, "provider_id": "kavenegar", "enabled": False, "config": {"sender": "100"},
            "secret_action": "replace", "secret_value": {"api_key": "SensitiveWireKey01234"}}
        self.assertEqual(client.get("/api/admin/communications", headers=headers).status_code, 200)
        for denied in ({"X-CSRF-Token": headers["X-CSRF-Token"]}, {"Origin": headers["Origin"], "X-CSRF-Token": "wrong"}, headers):
            result = client.put("/api/admin/communications/channels/sms", json=body, headers=denied)
            self.assertEqual(result.status_code, 403)
            self.assertNotIn("SensitiveWireKey01234", result.text)
        self.assertIsNone(self.db.scalar(select(AdminSecret)))
        session.revoked_at = datetime.now(UTC)
        self.db.commit()
        self.assertEqual(client.get("/api/admin/communications", headers=headers).status_code, 401)

    def test_real_http_admin_requires_reauthentication_and_mfa_policy(self):
        client, session, headers = self.authenticated_client("super_admin")
        body = {"expected_version": 0, "provider_id": "kavenegar", "enabled": False, "config": {"sender": "100"},
            "secret_action": "replace", "secret_value": {"api_key": "SensitiveWireKey01234"}}
        self.assertEqual(client.put("/api/admin/communications/channels/sms", json=body, headers=headers).status_code, 403)
        session.reauthenticated_at = datetime.now(UTC)
        self.db.commit()
        result = client.put("/api/admin/communications/channels/sms", json=body, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("SensitiveWireKey01234", result.text)
        self.assertTrue(result.json()["credentials"]["configured"])
        with patch.object(settings, "admin_mfa_required", True):
            self.assertEqual(client.get("/api/admin/communications", headers=headers).status_code, 403)

    def test_snapshot_catalog_has_only_public_form_fields(self):
        result = communications.snapshot(self.principal, self.db)
        self.assertEqual(set(result), {"version", "encryption_ready", "channels", "call_policy", "provider_catalog", "test_recipients"})
        self.assertFalse(result["channels"]["sms"]["ready"])
        self.assertTrue(result["encryption_ready"])
        self.assertEqual({item["id"] for item in result["provider_catalog"]}, {"kavenegar", "asterisk_ari"})

    def test_credentials_encrypted_and_get_and_audit_do_not_leak(self):
        result = self.channel()
        self.assertTrue(result["ready"])
        secret = self.db.scalar(select(AdminSecret))
        self.assertNotIn("PrivateTestKey012345", secret.ciphertext)
        self.assertEqual(read_secret(self.db, "sms"), {"api_key": "PrivateTestKey012345"})
        self.assertNotIn("PrivateTestKey012345", json.dumps(result))
        self.assertNotIn("PrivateTestKey012345", json.dumps(self.db.scalar(select(OperationalSetting)).value))
        audit = self.db.scalars(select(AdminAuditLog)).all()
        self.assertNotIn("PrivateTestKey012345", str([(row.before_data, row.after_data) for row in audit]))

    def test_blank_replace_preserves_credential(self):
        self.channel()
        self.channel(expected_version=1, secret_value={"api_key": "  "}, confirmation=None)
        self.assertEqual(read_secret(self.db, "sms")["api_key"], "PrivateTestKey012345")

    def test_stale_write_rejected(self):
        self.channel()
        with self.assertRaises(HTTPException) as caught:
            self.channel()
        self.assertEqual(caught.exception.status_code, 409)

    def test_enable_requires_confirmation_and_recent_reauth(self):
        with self.assertRaises(HTTPException) as caught:
            self.channel(confirmation=None)
        self.assertEqual(caught.exception.status_code, 400)
        self.principal.session.reauthenticated_at = None
        with self.assertRaises(HTTPException) as caught:
            self.channel()
        self.assertEqual(caught.exception.status_code, 403)

    def test_disable_works_when_key_missing_and_reauth_expired(self):
        self.channel()
        self.principal.session.reauthenticated_at = None
        with patch.object(settings, "communications_encryption_key", None):
            result = self.channel(expected_version=1, enabled=False, secret_action="keep", secret_value=None, confirmation=None)
        self.assertFalse(result["enabled"])

    def test_missing_or_rotated_key_fail_closed(self):
        self.channel()
        with patch.object(settings, "communications_encryption_key", None):
            self.assertFalse(read_provider(self.db, "sms")["ready"])
        with patch.object(settings, "communications_encryption_key", SecretStr(Fernet.generate_key().decode())):
            self.assertFalse(read_provider(self.db, "sms")["ready"])
            with self.assertRaises(HTTPException):
                read_secret(self.db, "sms")

    def test_clear_requires_disabled_and_typed_confirmation(self):
        self.channel()
        with self.assertRaises(HTTPException):
            self.channel(expected_version=1, secret_action="clear", confirmation="CLEAR SMS SECRET")
        self.db.rollback()
        result = self.channel(expected_version=1, enabled=False, secret_action="clear", confirmation="CLEAR SMS SECRET")
        self.assertFalse(result["secret_configured"])

    def test_channel_provider_mismatch_and_raw_config_rejected(self):
        for value in ({"provider_id": "asterisk_ari"}, {"config": {"sender": "100", "api_key": "do-not-return"}}, {"config": ["bad"]}):
            with self.subTest(value=value), self.assertRaises(HTTPException) as caught:
                self.channel(**value)
            self.assertEqual(caught.exception.status_code, 422)
            self.assertNotIn("do-not-return", str(caught.exception.detail))

    def test_invalid_credential_shape_never_echoes_input_on_wire(self):
        app = FastAPI()
        app.include_router(communications.router)
        app.dependency_overrides[get_db] = lambda: self.db
        for route in communications.router.routes:
            for dependency in route.dependant.dependencies:
                if dependency.name == "principal":
                    app.dependency_overrides[dependency.call] = lambda: self.principal
        with TestClient(app) as client:
            response = client.put("/communications/channels/sms", json={"expected_version": 0, "provider_id": "kavenegar", "enabled": False,
                "config": {"sender": "100"}, "secret_action": "replace", "secret_value": {"api_key": ["never-echo-secret"]}})
            missing = client.put("/communications/channels/sms", json={"secret_value": {"api_key": "never-echo-secret"}})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("never-echo-secret", response.text)
        self.assertEqual(missing.status_code, 422)
        self.assertNotIn("never-echo-secret", missing.text)

    def test_permission_dependency_denies_viewer_write(self):
        self.principal.permissions = frozenset({AdminPermissionKey.SETTINGS_READ.value})
        with self.assertRaises(HTTPException) as caught:
            require_permission(AdminPermissionKey.SETTINGS_MANAGE)(self.principal, self.db)
        self.assertEqual(caught.exception.status_code, 403)

    def test_policy_bounds_and_provider_gate(self):
        for key, value in (("persist_seconds", 3601), ("max_attempts", 2), ("cooldown_seconds", 29), ("max_calls_per_day", 101)):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                CallPolicyUpdate(expected_version=0, **{key: value})
        with self.assertRaises(HTTPException):
            communications.update_call_policy(CallPolicyUpdate(expected_version=0, enabled=True, confirmation="ENABLE VOIP POLICY"), request(), self.principal, self.db)
        with self.assertRaises(ValidationError):
            QuietHours(enabled=True, start="08:00", end="08:00")

    def test_recipient_encrypted_masked_consent_owned(self):
        with self.assertRaises(HTTPException):
            communications.create_recipient(TestRecipientCreate(label="Test", phone="09123456789"), request(), self.principal, self.db)
        result = self.recipient()
        row = self.db.get(admin_models.CommunicationRecipient, result["id"])
        self.assertEqual(decrypt_value(row.phone_ciphertext), "+989123456789")
        self.assertEqual(result["phone_masked"], "***6789")
        other = SimpleNamespace(**vars(self.principal))
        other.user = self.db.get(User, 2)
        with self.assertRaises(HTTPException) as caught:
            communications.delete_recipient(row.id, request(), other, self.db)
        self.assertEqual(caught.exception.status_code, 404)

    def test_persian_arabic_and_latin_digits_share_one_phone_identity(self):
        for value in ("۰۹۱۲۳۴۵۶۷۸۹", "٠٩١٢٣٤٥٦٧٨٩", "09123456789", "+۹۸۹۱۲۳۴۵۶۷۸۹", "00989123456789"):
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), "+989123456789")
        with self.assertRaises(HTTPException):
            normalize_phone("09123456\u200b789")

    def test_dry_run_needs_no_provider_and_never_calls_network(self):
        row = self.recipient()
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), patch("app.services.communication_transport.send_transport", side_effect=AssertionError("send forbidden")):
            result = self.event(row["id"])
        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["blocked_reasons"], ["provider_not_ready"])
        history = communications.list_deliveries(50, 0, self.principal, self.db)
        self.assertEqual(history["items"][0]["blocked_reasons"], ["provider_not_ready"])

    def test_provider_disable_cancels_queued_manual_event(self):
        self.channel()
        row = self.recipient()
        result = self.event(row["id"], mode="send", confirmation="SEND TEST")
        self.channel(expected_version=1, enabled=False, secret_action="keep", secret_value=None)
        self.assertEqual(self.db.get(CommunicationEvent, result["event_id"]).status, "cancelled")

    def test_history_merges_actual_jobs_and_masks_destination(self):
        alert = Alert(user_id=2, asset="btc", target_price=100, condition="above")
        self.db.add(alert)
        self.db.flush()
        self.db.add(AlertTriggerEvent(id=1, alert_id=alert.id, idempotency_key="history-trigger", condition_snapshot={}))
        self.db.flush()
        self.db.add(AlertDeliveryJob(id=1, alert_id=alert.id, trigger_event_id=1, channel="voip", status="accepted",
            destination_reference="must-not-be-returned", idempotency_key="history-job"))
        self.db.commit()
        result = communications.list_deliveries(50, 0, self.principal, self.db)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], "alert:1")
        self.assertEqual(result["items"][0]["status"], "accepted")
        self.assertNotIn("must-not-be-returned", str(result))
        self.assertEqual(communications.delivery_detail("alert:1", self.principal, self.db)["phone_masked"], "***")

    def test_late_history_page_only_loads_and_formats_the_requested_page(self):
        start = datetime(2026, 10, 21, tzinfo=UTC)
        self.db.add_all([CommunicationEvent(owner_user_id=1, channel="sms", status="dry_run", dry_run=True,
            client_request_id=str(uuid4()), delivery_key=f"history-page-{index}", created_at=start + timedelta(seconds=index))
            for index in range(100)])
        self.db.add(CommunicationEvent(owner_user_id=2, channel="sms", status="dry_run", dry_run=True,
            client_request_id=str(uuid4()), delivery_key="other-owner-private-event", created_at=start + timedelta(days=1)))
        self.db.commit()
        with Session(self.engine) as fresh, patch.object(communications, "_manual_event", wraps=communications._manual_event) as convert:
            result = communications.list_deliveries(5, 80, self.principal, fresh)
        self.assertEqual(result["total"], 100)
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(convert.call_count, 5)
        self.assertEqual([row["id"] for row in result["items"]], [f"manual:{identifier}" for identifier in range(20, 15, -1)])

    def test_mixed_history_page_has_stable_ties_and_global_total(self):
        stamp = datetime(2026, 10, 21, tzinfo=UTC)
        self.db.add(Alert(id=1, user_id=2, asset="btc", target_price=100, condition="above"))
        self.db.flush()
        self.db.add(AlertTriggerEvent(id=1, alert_id=1, idempotency_key="paging-trigger", condition_snapshot={}))
        self.db.flush()
        for identifier in (1, 2):
            self.db.add(AlertDeliveryJob(id=identifier, alert_id=1, trigger_event_id=1, channel="sms", status="accepted",
                destination_reference=f"hidden-{identifier}", idempotency_key=f"paging-job-{identifier}", created_at=stamp))
            self.db.add(CommunicationEvent(id=identifier, owner_user_id=1, channel="sms", status="dry_run", dry_run=True,
                client_request_id=str(uuid4()), delivery_key=f"paging-test-{identifier}", created_at=stamp))
        self.db.commit()
        result = communications.list_deliveries(2, 1, self.principal, self.db)
        self.assertEqual(result["total"], 4)
        self.assertEqual([row["id"] for row in result["items"]], ["alert:1", "manual:2"])

    def test_test_event_idempotency_and_conflicting_reuse(self):
        row = self.recipient()
        identifier = uuid4()
        first = self.event(row["id"], client_request_id=identifier)
        second = self.event(row["id"], client_request_id=identifier)
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.scalars(select(CommunicationEvent)).all()), 1)
        with self.assertRaises(HTTPException) as caught:
            self.event(row["id"], client_request_id=identifier, channel="voip")
        self.assertEqual(caught.exception.status_code, 409)

    def test_real_send_requires_confirmation_and_only_queues(self):
        self.channel()
        row = self.recipient()
        with self.assertRaises(HTTPException):
            self.event(row["id"], mode="send")
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            result = self.event(row["id"], mode="send", confirmation="SEND TEST")
        self.assertEqual(result["status"], "queued")

    def test_paid_test_budget_counts_failed_attempts_and_rejects_more(self):
        self.channel()
        recipient = self.recipient()
        for _ in range(5):
            result = self.event(recipient["id"], mode="send", confirmation="SEND TEST")
            self.db.get(CommunicationEvent, result["event_id"]).status = "failed"
            self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self.event(recipient["id"], mode="send", confirmation="SEND TEST")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], "3600")

    def test_delete_recipient_cancels_only_unsent_jobs(self):
        self.channel()
        row = self.recipient()
        queued = self.event(row["id"], mode="send", confirmation="SEND TEST")
        accepted = self.event(row["id"], mode="send", confirmation="SEND TEST")
        self.db.get(CommunicationEvent, accepted["event_id"]).status = "accepted"
        self.db.commit()
        communications.delete_recipient(row["id"], request(), self.principal, self.db)
        self.assertEqual(self.db.get(CommunicationEvent, queued["event_id"]).status, "cancelled")
        self.assertEqual(self.db.get(CommunicationEvent, accepted["event_id"]).status, "accepted")

    def test_paid_alert_gate_needs_actual_otp_verification(self):
        self.channel()
        payload = AlertCreate(asset="btc", target_price=100, condition="above", notify_sms=True)
        with self.assertRaises(HTTPException):
            alerts.create_alert(payload, self.principal.user, self.db)
        self.db.add(NotificationPreference(user_id=1, sms_phone="+989123456789", sms_enabled=True, sms_verified=True))
        self.db.commit()
        row = alerts.create_alert(payload, self.principal.user, self.db)
        self.assertTrue(row.notify_sms)
        self.assertFalse(row.notify_voip)

    def test_voip_availability_and_critical_policy_match_alert_api(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")):
            communications.update_channel("voip", ChannelUpdate(expected_version=0, provider_id="asterisk_ari", enabled=True,
                config={"endpoint": "https://pbx.example.test/ari", "trunk": "test_trunk", "ari_app": "test_app"},
                secret_action="replace", secret_value={"username": "test_operator", "password": "test-password-123"},
                confirmation="ENABLE VOIP"), request(), self.principal, self.db)
            communications.update_call_policy(CallPolicyUpdate(expected_version=0, enabled=True, confirmation="ENABLE VOIP POLICY"),
                request(), self.principal, self.db)
            prefs = NotificationPreference(user_id=1, sms_phone="+989123456789", sms_enabled=True, sms_verified=True)
            self.db.add(prefs)
            self.db.commit()
            response = notifications._to_response(prefs, self.db)
            self.assertTrue(response.voip_available)
            self.assertTrue(response.voip_critical_only)
            with self.assertRaises(HTTPException) as caught:
                alerts.create_alert(AlertCreate(asset="btc", target_price=100, notify_voip=True), self.principal.user, self.db)
            self.assertEqual(caught.exception.status_code, 422)
            self.assertIn("critical", caught.exception.detail)
            row = alerts.create_alert(AlertCreate(asset="btc", target_price=100, notify_voip=True, priority="critical"),
                self.principal.user, self.db)
            self.assertTrue(row.notify_voip)

    def test_explicit_delete_cancels_pending_paid_jobs_but_not_sending(self):
        alert = Alert(user_id=1, asset="btc", target_price=100, condition="above", notify_sms=True, notify_voip=True, is_active=False)
        self.db.add(alert)
        self.db.flush()
        trigger = AlertTriggerEvent(id=1, alert_id=alert.id, idempotency_key="test-trigger", condition_snapshot={})
        self.db.add(trigger)
        self.db.flush()
        for index, state in enumerate(("pending", "processing", "sending", "accepted", "unknown")):
            self.db.add(AlertDeliveryJob(id=index + 1, alert_id=alert.id, trigger_event_id=trigger.id, channel="sms", status=state,
                destination_reference=f"test-{index}", idempotency_key=f"job-{index}"))
        self.db.commit()
        alerts.delete_alert(alert.id, self.principal.user, self.db)
        self.assertFalse(alert.notify_voip)
        self.assertEqual([row.status for row in self.db.scalars(select(AlertDeliveryJob).order_by(AlertDeliveryJob.id)).all()],
            ["cancelled", "cancelled", "sending", "accepted", "unknown"])

    def test_otp_accepted_does_not_verify_until_owned_code_confirmed(self):
        self.channel()
        state = SimpleNamespace(blocked=False, retry_after=0)
        accepted = TransportResult("accepted", provider_id="kavenegar")
        with patch.object(notifications, "rate_limit_hit", return_value=state), patch.object(notifications, "send_transport", return_value=accepted) as send, patch.object(notifications.secrets, "randbelow", return_value=123456):
            notifications.start_otp(notifications.OtpStartRequest(channel="sms", destination="09123456789"), self.principal.user, self.db)
            self.assertIsNone(self.db.scalar(select(NotificationPreference)))
            self.assertEqual(send.call_args.kwargs["template_token"], "123456")
            other = self.db.get(User, 2)
            with self.assertRaises(HTTPException):
                notifications.confirm_otp(notifications.OtpConfirmRequest(channel="sms", destination="09123456789", code="123456"), other, self.db)
            with patch.object(notifications, "rate_limit_clear"):
                response = notifications.confirm_otp(notifications.OtpConfirmRequest(channel="sms", destination="09123456789", code="123456"), self.principal.user, self.db)
            self.assertTrue(response.sms_verified)
            self.assertTrue(response.sms_available)
            with self.assertRaises(HTTPException):
                notifications.confirm_otp(notifications.OtpConfirmRequest(channel="sms", destination="09123456789", code="123456"), self.principal.user, self.db)

    def test_unknown_otp_never_retries_or_leaves_usable_challenge(self):
        self.channel()
        with patch.object(notifications, "rate_limit_hit", return_value=SimpleNamespace(blocked=False, retry_after=0)), patch.object(notifications, "send_transport", return_value=TransportResult("unknown", provider_id="kavenegar")) as send:
            with self.assertRaises(HTTPException) as caught:
                notifications.start_otp(notifications.OtpStartRequest(channel="sms", destination="09123456789"), self.principal.user, self.db)
        self.assertEqual(caught.exception.status_code, 503)
        send.assert_called_once()
        self.assertIsNone(self.db.scalar(select(OtpVerification)))
        self.assertIsNone(self.db.scalar(select(NotificationPreference)))
        receipt = self.db.scalar(select(CommunicationEvent))
        self.assertEqual(receipt.status, "unknown")
        self.assertNotIn("+989123456789", str(receipt.provider_response_summary))

    def test_otp_unexpected_transport_error_has_unknown_receipt_without_retry(self):
        self.channel()
        with patch.object(notifications, "rate_limit_hit", return_value=SimpleNamespace(blocked=False, retry_after=0)), patch.object(notifications, "send_transport", side_effect=TimeoutError("secret-response-body")) as send:
            with self.assertRaises(HTTPException) as caught:
                notifications.start_otp(notifications.OtpStartRequest(channel="sms", destination="09123456789"), self.principal.user, self.db)
        send.assert_called_once()
        self.assertNotIn("secret-response-body", str(caught.exception.detail))
        self.assertEqual(self.db.scalar(select(CommunicationEvent)).status, "unknown")
        self.assertIsNone(self.db.scalar(select(OtpVerification)))

    def test_sms_code_without_accepted_delivery_cannot_verify(self):
        self.db.add(OtpVerification(user_id=1, channel="sms", destination="+989123456789", code_hash="fixture", expires_at=datetime.now(UTC) + timedelta(minutes=1)))
        self.db.commit()
        with patch.object(notifications, "rate_limit_hit", return_value=SimpleNamespace(blocked=False)), patch.object(notifications, "verify_password", return_value=True):
            with self.assertRaises(HTTPException):
                notifications.confirm_otp(notifications.OtpConfirmRequest(channel="sms", destination="09123456789", code="123456"), self.principal.user, self.db)
        self.assertIsNone(self.db.scalar(select(NotificationPreference)))

    def test_otp_rate_and_expiry_are_enforced(self):
        self.channel()
        with patch.object(notifications, "rate_limit_hit", return_value=SimpleNamespace(blocked=True, retry_after=60)), patch.object(notifications, "send_transport") as send:
            with self.assertRaises(HTTPException) as caught:
                notifications.start_otp(notifications.OtpStartRequest(channel="sms", destination="09123456789"), self.principal.user, self.db)
            self.assertEqual(caught.exception.status_code, 429)
            send.assert_not_called()
        self.db.add(OtpVerification(user_id=1, channel="sms", destination="+989123456789", code_hash="unused", expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        self.db.commit()
        with patch.object(notifications, "rate_limit_hit", return_value=SimpleNamespace(blocked=False, retry_after=0)):
            with self.assertRaises(HTTPException):
                notifications.confirm_otp(notifications.OtpConfirmRequest(channel="sms", destination="09123456789", code="123456"), self.principal.user, self.db)

    def test_otp_expiry_preserves_non_utc_timezone(self):
        now = datetime.now(UTC)
        local = (now - timedelta(seconds=1)).astimezone(timezone(timedelta(hours=3, minutes=30)))
        self.assertLess(notifications._otp_utc(local), now)
        self.assertEqual(notifications._otp_utc(local), local.astimezone(UTC))


if __name__ == "__main__":
    unittest.main()
