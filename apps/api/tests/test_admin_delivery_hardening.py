from __future__ import annotations

import asyncio
import base64
import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-with-32-characters")

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Alert, AlertDeliveryJob, AlertTriggerEvent, SupportTicket, User
from app.admin.bootstrap import ensure_admin_catalog
from app.admin.deps import rotate_csrf_token, token_digest
from app.admin.mfa import backup_digest, encrypt_secret, totp_code, verify_mfa
from app.admin.models import AdminJob, AdminMfaProfile, AdminPermission, AdminRole, AdminRolePermission, AdminSession, AdminUserRole, OperationalSetting, UserSecurityProfile
from app.admin.jobs import complete_admin_job, fail_admin_job
from app.admin.redaction import sanitize_error
from app.admin.routers import access, health_jobs, providers, settings, support
from app.admin.schemas import AdminRoleAssignmentRequest, AdminRoleUpdate, DangerousConfirmation, OperationalSettingUpdate, SupportTicketUpdate, UserStateUpdate
from app.admin.session_security import revoke_admin_sessions
from app.admin.worker import AdminOperationsWorker


def request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/admin/test", "headers": [], "client": ("127.0.0.1", 123), "server": ("localhost", 8000), "scheme": "http"})


class AdminRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.now = datetime.now(UTC)
        self.db.add_all([User(id=index, username=f"user{index}", email=f"user{index}@example.test", full_name=f"User {index}", password_hash="test-placeholder", is_active=True) for index in range(1, 5)])
        self.db.flush()
        ensure_admin_catalog(self.db)
        self.db.add_all([UserSecurityProfile(user_id=1, is_active=True), UserSecurityProfile(user_id=2, is_active=True)])
        self.db.commit()
        self.principal = SimpleNamespace(user=self.db.get(User, 1), permissions=frozenset(permission.key for permission in self.db.scalars(select(AdminPermission)).all()), session=SimpleNamespace(reauthenticated_at=self.now), roles=frozenset({"super_admin"}))

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def admin_session(self, user_id: int, identifier: str = "test-session") -> AdminSession:
        row = AdminSession(id=identifier, user_id=user_id, token_hash=token_digest(identifier), csrf_token_hash="unused", ip_address="127.0.0.1", user_agent_hash="test", created_at=self.now - timedelta(minutes=1), last_seen_at=self.now, expires_at=self.now + timedelta(minutes=20))
        self.db.add(row)
        self.db.commit()
        return row

    def assign(self, user_id: int, role_name: str) -> None:
        role = self.db.scalar(select(AdminRole).where(AdminRole.name == role_name))
        self.db.add(AdminUserRole(user_id=user_id, role_id=role.id, is_active=True))
        self.db.commit()

    def delivery(self, status: str = "pending", identifier: int = 1) -> AlertDeliveryJob:
        if self.db.get(Alert, 1) is None:
            self.db.add(Alert(id=1, user_id=3, asset="Bitcoin", target_price=100, condition="above"))
            self.db.add(AlertTriggerEvent(id=1, alert_id=1, idempotency_key="trigger-test", condition_snapshot={}))
            self.db.flush()
        row = AlertDeliveryJob(id=identifier, alert_id=1, trigger_event_id=1, channel="email", destination_reference=f"target-{identifier}", status=status, idempotency_key=f"delivery-test-{identifier}", created_at=self.now - timedelta(seconds=identifier))
        self.db.add(row)
        self.db.commit()
        return row

    def test_csrf_is_stable_for_two_tabs_and_distinct_between_sessions(self) -> None:
        row = self.admin_session(1)
        first = rotate_csrf_token(row)
        self.assertEqual(first, rotate_csrf_token(row))
        self.assertEqual(row.csrf_token_hash, token_digest(first))
        self.assertNotEqual(first, rotate_csrf_token(self.admin_session(1, "second-session")))

    def test_disabled_user_without_security_profile_is_not_active(self) -> None:
        self.db.get(User, 3).is_active = False
        self.db.commit()
        active = access.list_users(search="", active=True, limit=50, offset=0, principal=self.principal, db=self.db)
        inactive = access.list_users(search="", active=False, limit=50, offset=0, principal=self.principal, db=self.db)
        self.assertNotIn(3, [row["id"] for row in active["items"]])
        self.assertIn(3, [row["id"] for row in inactive["items"]])

    def test_system_role_catalog_removes_obsolete_permission(self) -> None:
        role = self.db.scalar(select(AdminRole).where(AdminRole.name == "operator"))
        permission = self.db.scalar(select(AdminPermission).where(AdminPermission.key == "admin.roles.manage"))
        self.db.add(AdminRolePermission(role_id=role.id, permission_id=permission.id))
        self.db.commit()
        ensure_admin_catalog(self.db)
        self.db.commit()
        self.assertIsNone(self.db.scalar(select(AdminRolePermission).where(AdminRolePermission.role_id == role.id, AdminRolePermission.permission_id == permission.id)))

    def test_revoke_all_roles_closes_admin_sessions(self) -> None:
        self.assign(2, "viewer")
        row = self.admin_session(2)
        access.assign_admin_roles(2, AdminRoleAssignmentRequest(roles=[], confirmation="SET ADMIN ROLES 2"), request(), self.principal, self.db)
        self.db.refresh(row)
        self.assertIsNotNone(row.revoked_at)
        self.assertFalse(self.db.scalar(select(AdminUserRole).where(AdminUserRole.user_id == 2)).is_active)

    def test_last_super_administrator_cannot_be_disabled_or_removed(self) -> None:
        self.assign(1, "super_admin")
        with self.assertRaises(HTTPException) as disable:
            access.set_user_state(1, UserStateUpdate(is_active=False, reason="test reason", confirmation="DISABLE USER 1"), request(), self.principal, self.db)
        self.assertEqual(disable.exception.status_code, 409)
        with self.assertRaises(HTTPException) as remove:
            access.assign_admin_roles(1, AdminRoleAssignmentRequest(roles=[], confirmation="SET ADMIN ROLES 1"), request(), self.principal, self.db)
        self.assertEqual(remove.exception.status_code, 409)

    def test_custom_role_policy_changes_revoke_affected_sessions(self) -> None:
        body = AdminRoleUpdate(name="custom_reader", description="Test role", permissions=["admin.pricing.read"], confirmation="CREATE ROLE custom_reader")
        created = access.create_custom_role(body, request(), self.principal, self.db)
        self.assign(2, "custom_reader")
        row = self.admin_session(2)
        update = body.model_copy(update={"is_active": False, "confirmation": f"UPDATE ROLE {created['id']}"})
        access.update_custom_role(created["id"], update, request(), self.principal, self.db)
        self.db.refresh(row)
        self.assertIsNotNone(row.revoked_at)

    def test_password_transaction_revokes_admin_and_updates_cutoff(self) -> None:
        row = self.admin_session(2)
        revoke_admin_sessions(self.db, 2, "password_reset", now=self.now)
        self.db.commit()
        self.db.refresh(row)
        self.assertIsNotNone(row.revoked_at)
        self.assertIsNotNone(self.db.get(UserSecurityProfile, 2).sessions_revoked_before)

    def test_support_rejects_regular_assignee_and_allows_unassign(self) -> None:
        ticket = SupportTicket(id=1, user_id=3, subject="Test", status="open", last_message="test")
        self.db.add(ticket)
        self.db.commit()
        with self.assertRaises(HTTPException) as ordinary:
            support.update_ticket(1, SupportTicketUpdate(assigned_admin_id=3), request(), self.principal, self.db)
        self.assertEqual(ordinary.exception.status_code, 422)
        self.assign(2, "support_agent")
        response = support.update_ticket(1, SupportTicketUpdate(assigned_admin_id=2), request(), self.principal, self.db)
        self.assertEqual(response["ticket"]["assigned_admin_id"], 2)
        response = support.update_ticket(1, SupportTicketUpdate(assigned_admin_id=None), request(), self.principal, self.db)
        self.assertIsNone(response["ticket"]["assigned_admin_id"])

    def test_dlq_filters_before_limit_and_paginates(self) -> None:
        self.delivery("pending", 1)
        self.delivery("dead", 2)
        response = health_jobs.list_dlq(limit=1, offset=0, principal=self.principal, db=self.db)
        self.assertEqual(response["total"], 1)
        self.assertEqual(response["items"][0]["id"], 2)

    def test_cancel_claimed_delivery_but_not_sending(self) -> None:
        claimed = self.delivery("processing", 1)
        health_jobs.cancel_delivery_job("1", DangerousConfirmation(confirmation="CANCEL DELIVERY 1"), request(), self.principal, self.db)
        self.db.refresh(claimed)
        self.assertEqual(claimed.status, "cancelled")
        self.delivery("sending", 2)
        with self.assertRaises(HTTPException) as sending:
            health_jobs.cancel_delivery_job("2", DangerousConfirmation(confirmation="CANCEL DELIVERY 2"), request(), self.principal, self.db)
        self.assertEqual(sending.exception.status_code, 409)

    def test_operational_setting_conflict_and_reset(self) -> None:
        initial = OperationalSettingUpdate(key="comparison_visible", value=False, expected_version=0)
        first = settings.update_operational_setting(initial, request(), self.principal, self.db)
        self.assertEqual(first["version"], 1)
        changed = initial.model_copy(update={"value": True, "expected_version": 1})
        settings.update_operational_setting(changed, request(), self.principal, self.db)
        with self.assertRaises(HTTPException) as conflict:
            settings.update_operational_setting(changed, request(), self.principal, self.db)
        self.assertEqual(conflict.exception.status_code, 409)
        reset = initial.model_copy(update={"expected_version": 2, "confirmation": "RESET SETTING comparison_visible:global"})
        settings.reset_operational_setting(reset, request(), self.principal, self.db)
        self.assertIsNone(self.db.scalar(select(OperationalSetting).where(OperationalSetting.key == "comparison_visible")))

    def test_totp_matches_known_vector_and_rejects_replay(self) -> None:
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(totp_code(secret, 1), "287082")
        self.db.add(AdminMfaProfile(user_id=2, totp_enabled=True, encrypted_totp_secret=encrypt_secret(secret), backup_code_digests=[backup_digest("TEST-RECOVERY-CODE")]))
        self.db.commit()
        with patch("app.admin.mfa.time.time", return_value=59):
            verify_mfa(self.db, 2, "287082")
            self.db.commit()
            with self.assertRaises(HTTPException):
                verify_mfa(self.db, 2, "287082")
        verify_mfa(self.db, 2, "TEST-RECOVERY-CODE")
        self.db.commit()
        with self.assertRaises(HTTPException):
            verify_mfa(self.db, 2, "TEST-RECOVERY-CODE")

    def test_error_text_does_not_leak_credentials(self) -> None:
        clean = sanitize_error("connect postgres://test:test@db/test failed token=private-value Bearer another-private-value")
        self.assertNotIn("test:test", clean)
        self.assertNotIn("private-value", clean)

    def test_mfa_lock_refreshes_preloaded_profile_before_replay_check(self) -> None:
        secret = base64.b32encode(b"12345678901234567890").decode()
        profile = AdminMfaProfile(user_id=2, totp_enabled=True, encrypted_totp_secret=encrypt_secret(secret), backup_code_digests=[])
        self.db.add(profile)
        self.db.commit()
        self.assertIsNone(profile.last_totp_step)
        self.db.connection().execute(AdminMfaProfile.__table__.update().where(AdminMfaProfile.user_id == 2).values(last_totp_step=1))
        self.assertIsNone(profile.last_totp_step)
        with patch("app.admin.mfa.time.time", return_value=59):
            with self.assertRaises(HTTPException) as replay:
                verify_mfa(self.db, 2, "287082")
        self.assertEqual(replay.exception.status_code, 401)
        self.assertEqual(profile.last_totp_step, 1)

    def test_parser_preview_uses_worker_contract(self) -> None:
        from app.models import TelegramSource
        from app.admin.schemas import TelegramParserPreview
        self.db.add(TelegramSource(id=1, channel_id="-100123", display_name="Test", parser_type="strict_explicit", parser_version="strict-explicit-3", allowed_instruments=["USDT_TOMAN"], minimum_confidence=Decimal("0.8"), expected_patterns={}))
        self.db.commit()
        preview = providers.preview_telegram_parser(1, TelegramParserPreview(text="USDT 1000000 ریال"), self.principal, self.db)
        self.assertEqual(preview["items"][0]["price"], Decimal("100000"))

    def test_support_null_status_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SupportTicketUpdate(status=None)

    def test_stale_provider_draft_cannot_overwrite_new_policy(self) -> None:
        from app.admin.models import AdminProviderConfigDraft
        self.db.add(AdminProviderConfigDraft(id=1, provider_id="test-provider", before_data={"priority": 1, "config_version": 0}, proposed_data={"priority": 4}, impact_preview={}, status="draft"))
        self.db.commit()
        with patch.object(providers, "_provider", return_value={"priority": 2, "config_version": 1}):
            with self.assertRaises(HTTPException) as conflict:
                providers.apply_provider_draft(1, DangerousConfirmation(confirmation="APPLY PROVIDER test-provider"), request(), self.principal, self.db)
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(self.db.get(AdminProviderConfigDraft, 1).status, "draft")

    def test_latest_canonical_query_picks_newest_per_instrument(self) -> None:
        from app.pricing.db_models import CanonicalQuoteRecord
        from app.admin.routers import pricing
        for identifier, price, observed in [(1, 100, self.now - timedelta(hours=1)), (2, 200, self.now)]:
            self.db.add(CanonicalQuoteRecord(id=identifier, instrument_id="BTC_USD", canonical_at=observed, price=price, status="live", source_summary={}, observed_at=observed, valid_until=observed + timedelta(minutes=1), stale_at=observed + timedelta(minutes=2), expires_at=observed + timedelta(minutes=3), decision_reason="test", verification_status="not_required", idempotency_key=f"quote-{identifier}"))
        self.db.commit()
        with patch.object(pricing, "safe_rows", return_value=[{"instrument_id": "BTC_USD", "enabled": True}]):
            rows = pricing.list_instruments(self.principal, self.db)["items"]
        self.assertEqual(Decimal(str(rows[0]["latest_canonical"]["price"])), Decimal("200"))

    def test_stale_worker_cannot_complete_or_fail_new_claim(self) -> None:
        job = AdminJob(job_type="instrument_refresh", resource_type="instrument", resource_id="BTC_USD", payload={}, status="processing", attempt_count=2)
        self.db.add(job)
        self.db.commit()
        complete_admin_job(self.db, job, expected_attempt=1)
        self.assertEqual(job.status, "processing")
        fail_admin_job(self.db, job, "old attempt failed", expected_attempt=1)
        self.assertEqual(job.status, "processing")
        self.assertIsNone(job.last_error)
        complete_admin_job(self.db, job, expected_attempt=2)
        self.assertEqual(job.status, "completed")

    def test_derived_override_cannot_bypass_recent_reauthentication(self) -> None:
        self.principal.session.reauthenticated_at = self.now - timedelta(hours=1)
        payload = OperationalSettingUpdate(key="derived_fallback_enabled", scope_id="global", value=True, expected_version=0)
        with self.assertRaises(HTTPException) as rejected:
            settings.update_operational_setting(payload, request(), self.principal, self.db)
        self.assertEqual(rejected.exception.status_code, 403)
        self.assertIsNone(self.db.scalar(select(OperationalSetting)))

    def test_telegram_sources_have_independent_permission_catalog_and_paging(self) -> None:
        from app.models import TelegramSource
        for identifier in (1, 2):
            self.db.add(TelegramSource(id=identifier, channel_id=f"-10012345678{identifier}", display_name=f"Source {identifier}", source_type="channel", role="compare", allowed_instruments=["BTC_USD"], parser_type="strict_explicit", parser_version="strict-explicit-3"))
        self.db.commit()
        result = providers.list_telegram_sources(limit=1, offset=1, principal=self.principal, db=self.db)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("BTC_USD", result["instrument_ids"])
        self.assertEqual(result["items"][0]["id"], 1)

    def test_security_history_includes_account_events_and_excludes_other_users(self) -> None:
        from app.models import SecurityEvent
        self.db.add_all([SecurityEvent(id=1, user_id=2, event_type="signin", result="failed", detail={}), SecurityEvent(id=2, user_id=3, event_type="password_reset", result="success", detail={})])
        self.db.commit()
        history = access.user_security_history(2, limit=1, offset=0, principal=self.principal, db=self.db)
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["kind"], "account")
        self.assertEqual(history["items"][0]["action"], "signin")


class AdminHttpRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.db import get_db
        from app.admin.config import get_admin_config
        from app.admin.router import router
        from app.security import hash_password, rate_limit_clear
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.password = "TestAdminPassword!2026"
        with Session(self.engine) as db:
            ensure_admin_catalog(db)
            db.add(User(id=1, username="http_admin", full_name="HTTP Admin", email="http-admin@example.test", password_hash=hash_password(self.password), is_active=True))
            db.add(UserSecurityProfile(user_id=1, is_active=True, must_change_password=False))
            db.flush()
            role = db.scalar(select(AdminRole).where(AdminRole.name == "super_admin"))
            db.add(AdminUserRole(user_id=1, role_id=role.id, is_active=True))
            db.commit()
        def database():
            with Session(self.engine) as db:
                yield db
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app, base_url="https://testserver", client=("127.0.0.1", 1234))
        self.headers = {"Origin": get_admin_config().frontend_origin}
        rate_limit_clear("admin-signin-failure", "127.0.0.1:http_admin")
        rate_limit_clear("admin-signin-account", "1")
        rate_limit_clear("admin-signin-ip", "127.0.0.1")
        rate_limit_clear("admin-sensitive-account", "1")
        rate_limit_clear("admin-sensitive-ip", "127.0.0.1")

    def tearDown(self) -> None:
        self.client.close()
        self.engine.dispose()

    def login(self) -> str:
        response = self.client.post("/api/admin/auth/signin", json={"identifier": "http_admin", "password": self.password}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return response.json()["csrf_token"]

    def test_missing_csrf_and_origin_block_mutations(self) -> None:
        self.login()
        no_csrf = self.client.post("/api/admin/auth/reauthenticate", json={"password": self.password}, headers={"Origin": self.headers["Origin"]})
        self.assertEqual(no_csrf.status_code, 403)
        no_origin = self.client.post("/api/admin/auth/reauthenticate", json={"password": self.password}, headers={"X-CSRF-Token": self.headers["X-CSRF-Token"]})
        self.assertEqual(no_origin.status_code, 403)
        valid = self.client.post("/api/admin/auth/reauthenticate", json={"password": self.password}, headers=self.headers)
        self.assertEqual(valid.status_code, 200)

    def test_mfa_enroll_confirm_and_login_requires_code(self) -> None:
        self.login()
        self.assertEqual(self.client.post("/api/admin/auth/reauthenticate", json={"password": self.password}, headers=self.headers).status_code, 200)
        enrollment = self.client.post("/api/admin/auth/mfa/enroll", headers=self.headers)
        self.assertEqual(enrollment.status_code, 200)
        secret = enrollment.json()["secret"]
        import time
        code = totp_code(secret, int(time.time()) // 30)
        confirmed = self.client.post("/api/admin/auth/mfa/confirm", json={"code": code}, headers=self.headers)
        self.assertEqual(confirmed.status_code, 200)
        recovery = confirmed.json()["backup_codes"][0]
        self.assertEqual(self.client.post("/api/admin/auth/signout", headers=self.headers).status_code, 204)
        denied = self.client.post("/api/admin/auth/signin", json={"identifier": "http_admin", "password": self.password}, headers=self.headers)
        self.assertEqual(denied.status_code, 401)
        admitted = self.client.post("/api/admin/auth/signin", json={"identifier": "http_admin", "password": self.password, "mfa_code": recovery}, headers=self.headers)
        self.assertEqual(admitted.status_code, 200)
        self.assertTrue(admitted.json()["admin"]["mfa_enabled"])
        replay = self.client.post("/api/admin/auth/signin", json={"identifier": "http_admin", "password": self.password, "mfa_code": recovery}, headers=self.headers)
        self.assertEqual(replay.status_code, 401)

    def test_sensitive_password_endpoint_limits_attempts(self) -> None:
        self.login()
        statuses = [self.client.post("/api/admin/auth/reauthenticate", json={"password": "wrong-test-password"}, headers=self.headers).status_code for _ in range(11)]
        self.assertEqual(statuses[-1], 429)


class AdminWorkerRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_claim_failure_does_not_kill_loop(self) -> None:
        worker = AdminOperationsWorker(poll_seconds=0.005)
        with patch.object(worker, "_claim", side_effect=[OSError("test outage"), None, None, None, None, None, None]):
            await worker.start()
            await asyncio.sleep(0.02)
            self.assertTrue(worker._running)
            self.assertFalse(worker._task.done())
            self.assertIsNotNone(worker.last_heartbeat_at)
            await worker.stop()


if __name__ == "__main__":
    unittest.main()
