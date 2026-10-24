from __future__ import annotations

import copy
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import os
import re
import unittest
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import BigInteger, Integer, MetaData, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")

from app.admin.communication_storage import DEFAULT_POLICY
from app.admin.models import AdminAuditLog, AdminSecret, CommunicationEvent, CommunicationRecipient, OperationalSetting
from app.models import Alert, AlertDeliveryJob, AlertTriggerEvent, NotificationPreference, User
from app.services import communication_delivery as d
from app.services.alert_engine import AlertEngine
from app.services.communication_transport import TransportResult
from app.services.dlq_worker import DLQWorker


class CommunicationWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        metadata = MetaData()
        for model in (User, Alert, NotificationPreference, AlertTriggerEvent, AlertDeliveryJob, CommunicationRecipient, CommunicationEvent, OperationalSetting):
            table = model.__table__.to_metadata(metadata)
            for column in table.columns:
                if isinstance(column.type, BigInteger): column.type = Integer()
        metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        self.alert_engine = AlertEngine()
        self.worker = DLQWorker(self.alert_engine)
        self.policy = {**copy.deepcopy(DEFAULT_POLICY), "enabled": True, "persist_seconds": 0}
        self.policy["quiet_hours"]["enabled"] = False
        self.provider = {"enabled": True, "ready": True, "provider_id": "kavenegar", "config": {"sender": "1000123"}}
        self.prices = {"assets": [{"asset": "btc", "price_usd": 150, "usd_status": "live", "usd_live_eligible": True,
            "usd_is_persisted": True, "usd_persistence_status": "persisted", "usd_is_suspicious": False,
            "usd_expired": False, "usd_source_semantic": "exchange_trade", "usd_derivation_depth": 0}]}
        patches = [patch("app.services.communication_delivery.SessionLocal", self.session),
            patch("app.services.alert_engine.SessionLocal", self.session), patch("app.services.dlq_worker.SessionLocal", self.session),
            patch("app.services.communication_delivery.read_provider", side_effect=lambda _db, _channel: self.provider),
            patch("app.services.communication_delivery.read_policy", side_effect=lambda _db: copy.deepcopy(self.policy)),
            patch("app.services.communication_delivery.encryption_ready", return_value=True),
            patch("app.services.communication_delivery.read_secret", return_value={"api_key": "ownedfixturekey"}),
            patch("app.services.communication_delivery.decrypt_value", return_value="+989120000000"),
            patch("app.services.communication_delivery.read_fresh_prices", new_callable=AsyncMock, side_effect=lambda: copy.deepcopy(self.prices)),
            patch("app.services.alert_engine.rights.enforced", return_value=False),
            patch("app.services.communication_delivery.send_transport", return_value=TransportResult("accepted", "safe-hash", provider_id="kavenegar")),
            patch("socket.socket.connect", side_effect=AssertionError("real_network_forbidden")),
            patch("socket.create_connection", side_effect=AssertionError("real_network_forbidden"))]
        self.mocks = [item.start() for item in patches]
        for item in patches: self.addCleanup(item.stop)
        self.send = self.mocks[10]
        self.read_secret = self.mocks[6]
        with self.session() as db:
            db.add(User(id=1, username="owned", full_name="Owned", email="owned@example.invalid", password_hash="test"))
            db.add(User(id=2, username="other", full_name="Other", email="other@example.invalid", password_hash="test"))
            db.add(NotificationPreference(id=1, user_id=1, sms_enabled=True, sms_verified=True, sms_phone="+989120000000"))
            db.add(CommunicationRecipient(id=1, owner_user_id=1, label="Owned", phone_ciphertext="opaque-fixture", phone_masked="***0000", consented=True))
            db.commit()
        self.addCleanup(self.engine.dispose)

    def seed_job(self, channel="voip", **changes):
        with self.session() as db:
            alert = Alert(id=1, user_id=1, asset="btc", target_price=100, condition="above", currency_mode="usd", mode="recurring",
                notify_app=False, notify_sms=channel == "sms", notify_voip=channel == "voip", priority="critical", is_active=True)
            for key, value in changes.items(): setattr(alert, key, value)
            db.add(alert); db.flush()
            context = vars(self.alert_engine._delivery_alert(alert))
            db.add(AlertTriggerEvent(id=1, alert_id=1, condition_snapshot={"assets": self.prices["assets"], "delivery_alert": context},
                idempotency_key="owned-occurrence", status="queued")); db.flush()
            db.add(AlertDeliveryJob(id=1, alert_id=1, trigger_event_id=1, channel=channel,
                destination_reference=d.destination_reference(1, channel, "+989120000000"), status="processing", attempt_count=1,
                idempotency_key="owned-occurrence:" + channel)); db.commit()

    def seed_manual(self, **changes):
        values = dict(id=1, owner_user_id=1, recipient_id=1, channel="sms", status="queued", dry_run=False,
            client_request_id="owned-request", delivery_key="owned-manual-key", provider_response_summary={"phone_masked": "***0000", "recipient_label": "Owned"})
        values.update(changes)
        with self.session() as db: db.add(CommunicationEvent(**values)); db.commit()

    async def test_dry_run_never_reads_secret_or_calls_transport(self):
        self.seed_manual(dry_run=True)
        result = await d.dispatch_manual_event(1)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["network_called"])
        self.read_secret.assert_not_called(); self.send.assert_not_called()

    async def test_manual_accepted_is_not_delivered_and_labels_stay_masked(self):
        self.seed_manual()
        await d.dispatch_manual_event(1)
        await d.dispatch_manual_event(1)
        self.assertEqual(self.send.call_count, 1)
        with self.session() as db:
            row = db.get(CommunicationEvent, 1)
            self.assertEqual(row.status, "accepted")
            self.assertEqual(row.provider_response_summary["phone_masked"], "***0000")
            self.assertFalse(row.provider_response_summary["delivered"])
            self.assertNotIn("+989120000000", str(row.provider_response_summary))

    async def test_manual_cross_owner_or_revoked_consent_cancelled(self):
        self.seed_manual(owner_user_id=2)
        self.assertEqual((await d.dispatch_manual_event(1))["status"], "cancelled")
        self.send.assert_not_called()

    async def test_manual_unknown_is_not_reclaimed_or_retried(self):
        self.seed_manual()
        self.send.return_value = TransportResult("unknown", error_code="provider_result_unknown")
        await d.dispatch_manual_event(1)
        self.assertEqual(d._claim_manual(10), [])
        await d.dispatch_manual_event(1)
        self.assertEqual(self.send.call_count, 1)
        with self.session() as db: self.assertEqual(db.get(CommunicationEvent, 1).status, "unknown")

    async def test_manual_stale_sending_becomes_unknown_never_queued(self):
        self.seed_manual(status="sending", updated_at=datetime.now(UTC) - timedelta(minutes=6))
        self.assertEqual(d._claim_manual(10), [])
        with self.session() as db: self.assertEqual(db.get(CommunicationEvent, 1).status, "unknown")
        self.send.assert_not_called()

    async def test_actual_sms_alert_is_queued_and_provider_accepted(self):
        self.seed_job("sms")
        await self.worker._process_job(1, 1)
        with self.session() as db:
            row = db.get(AlertDeliveryJob, 1)
            self.assertEqual(row.status, "accepted")
            self.assertIsNone(row.delivered_at)
            self.assertFalse(row.provider_response_summary["delivered"])
        self.assertEqual(self.send.call_count, 1)

    async def test_paid_acceptance_before_push_completion_finalizes_mixed_event(self):
        self.seed_job("sms")
        with self.session() as db:
            db.add(AlertDeliveryJob(id=2, alert_id=1, trigger_event_id=1, channel="push", status="sending",
                attempt_count=1, destination_reference="app:1", idempotency_key="owned-occurrence:push"))
            db.commit()
        await self.worker._process_job(1, 1)
        self.worker._mark_delivered(2, {"channel": "push", "accepted": True}, 1)
        with self.session() as db:
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "accepted")
            self.assertIsNone(db.get(AlertDeliveryJob, 1).delivered_at)
        self.assertEqual(self.send.call_count, 1)

    async def test_push_completion_before_paid_acceptance_has_same_mixed_result(self):
        self.seed_job("sms")
        with self.session() as db:
            db.add(AlertDeliveryJob(id=2, alert_id=1, trigger_event_id=1, channel="push", status="sending",
                attempt_count=1, destination_reference="app:1", idempotency_key="owned-occurrence:push"))
            db.commit()
        self.worker._mark_delivered(2, {"channel": "push", "accepted": True}, 1)
        await self.worker._process_job(1, 1)
        with self.session() as db:
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "accepted")

    async def test_unknown_or_failed_paid_result_is_not_erased_by_push_completion(self):
        self.seed_job("sms")
        with self.session() as db:
            db.add(AlertDeliveryJob(id=2, alert_id=1, trigger_event_id=1, channel="push", status="sending",
                attempt_count=1, destination_reference="app:1", idempotency_key="owned-occurrence:push"))
            db.commit()
        for status, expected in (("failed", "delivery_failed"), ("unknown", "delivery_unknown")):
            with self.subTest(status=status):
                with self.session() as db:
                    db.get(AlertDeliveryJob, 1).status = "processing"
                    db.get(AlertDeliveryJob, 2).status = "sending"
                    db.get(AlertTriggerEvent, 1).status = "queued"
                    db.commit()
                self.send.return_value = TransportResult(status, error_code="provider_rejected")
                await self.worker._process_job(1, 1)
                self.worker._mark_delivered(2, {"channel": "push", "accepted": True}, 1)
                with self.session() as db:
                    self.assertEqual(db.get(AlertTriggerEvent, 1).status, expected)

    async def test_cancelled_paid_job_finalizes_as_cancelled_without_false_failure(self):
        self.seed_job("sms")
        self.provider["enabled"] = self.provider["ready"] = False
        await self.worker._process_job(1, 1)
        with self.session() as db:
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "cancelled")
        self.send.assert_not_called()

    async def test_actual_critical_voip_condition_met_calls(self):
        self.seed_job()
        await self.worker._process_job(1, 1)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.send.call_args.args[0], "voip")

    async def test_normal_priority_does_not_call_under_critical_policy(self):
        self.seed_job(priority="normal")
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db: self.assertEqual(db.get(AlertDeliveryJob, 1).last_error, "critical_alert_required")

    async def test_cleared_condition_or_stale_price_cancels_before_call(self):
        self.seed_job()
        self.prices["assets"][0]["price_usd"] = 50
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db: self.assertEqual(db.get(AlertDeliveryJob, 1).status, "cancelled")

    async def test_stale_quote_is_not_a_critical_signal(self):
        self.seed_job()
        self.prices["assets"][0]["usd_expired"] = True
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_provider_disable_and_phone_revocation_block_queued_send(self):
        self.seed_job("sms")
        self.provider["ready"] = False
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_changed_alert_condition_does_not_repurpose_old_job(self):
        self.seed_job()
        with self.session() as db: db.get(Alert, 1).target_price = 120; db.commit()
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_persistence_waits_and_gap_resets_instead_of_blind_delayed_call(self):
        self.seed_job()
        self.policy["persist_seconds"] = 60
        now = datetime.now(UTC)
        with self.session() as db:
            db.get(AlertDeliveryJob, 1).provider_response_summary = {"condition_since": (now-timedelta(seconds=100)).isoformat(),
                "condition_last_seen": (now-timedelta(seconds=16)).isoformat()}; db.commit()
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db:
            row = db.get(AlertDeliveryJob, 1)
            self.assertEqual(row.status, "pending")
            self.assertGreater(datetime.fromisoformat(row.provider_response_summary["condition_since"]), now-timedelta(seconds=1))

    async def test_persistence_with_recent_continuous_observations_calls(self):
        self.seed_job()
        self.policy["persist_seconds"] = 60
        now = datetime.now(UTC)
        with self.session() as db:
            db.get(AlertDeliveryJob, 1).provider_response_summary = {"condition_since": (now-timedelta(seconds=61)).isoformat(),
                "condition_last_seen": (now-timedelta(seconds=1)).isoformat()}; db.commit()
        await self.worker._process_job(1, 1)
        self.assertEqual(self.send.call_count, 1)

    async def test_manual_calls_share_actual_alert_daily_cap(self):
        self.seed_job()
        self.seed_manual(channel="voip", status="accepted", provider_response_summary={"send_started_at": datetime.now(UTC).isoformat()})
        self.policy["max_calls_per_day"] = 1
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db: self.assertEqual(db.get(AlertDeliveryJob, 1).last_error, "daily_call_cap")

    async def test_quiet_hours_and_critical_bypass_are_server_rules(self):
        policy = copy.deepcopy(self.policy)
        policy["quiet_hours"] = {"enabled": True, "start": "22:00", "end": "08:00", "timezone": "UTC", "critical_bypass": False}
        now = datetime(2026, 10, 21, 23, tzinfo=UTC)
        self.assertTrue(d.quiet_now(policy, now, critical=True))
        policy["quiet_hours"]["critical_bypass"] = True
        self.assertFalse(d.quiet_now(policy, now, critical=True))
        self.assertTrue(d.quiet_now(policy, now, critical=False))

    async def test_alert_unknown_after_timeout_or_crash_never_goes_to_dlq_retry(self):
        self.seed_job(enable_dlq=True)
        self.send.side_effect = TimeoutError("private-provider-response")
        await self.worker._process_job(1, 1)
        with self.session() as db:
            row = db.get(AlertDeliveryJob, 1)
            self.assertEqual(row.status, "unknown")
            self.assertIsNone(row.next_retry_at)
            self.assertNotIn("private-provider-response", row.last_error or "")
        self.assertEqual(self.worker._claim_jobs(10), [])
        self.assertEqual(self.send.call_count, 1)

    async def test_crash_after_sending_durable_boundary_becomes_unknown(self):
        self.seed_job()
        with self.session() as db:
            row = db.get(AlertDeliveryJob, 1); row.status = "sending"; row.updated_at = datetime.now(UTC)-timedelta(minutes=6); db.commit()
        self.assertEqual(self.worker._claim_jobs(10), [])
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob, 1).status, "unknown")
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "delivery_unknown")
        self.send.assert_not_called()

    async def test_real_alert_flags_queue_only_verified_opted_in_phone(self):
        self.seed_job()
        with self.session() as db:
            alert, prefs = db.get(Alert, 1), db.get(NotificationPreference, 1)
            self.assertEqual(d.queued_channels(db, alert, prefs)[0][0], "voip")
            prefs.sms_verified = False
            self.assertEqual(d.queued_channels(db, alert, prefs), [])

    async def test_corrupt_quiet_hours_or_policy_fail_closed(self):
        self.seed_job()
        self.policy["quiet_hours"] = {"enabled": True, "start": "broken", "end": "08:00", "timezone": "invalid-zone"}
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db: self.assertEqual(db.get(AlertDeliveryJob, 1).last_error, "call_policy_invalid")

    async def test_phone_replaced_after_queue_cancels_original_job(self):
        self.seed_job()
        with self.session() as db: db.get(NotificationPreference, 1).sms_phone = "+989120000001"; db.commit()
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_phone_permission_shutdown_revokes_voip_too(self):
        self.seed_job()
        with self.session() as db: db.get(NotificationPreference, 1).sms_enabled = False; db.commit()
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_held_call_policy_after_queue_cancels(self):
        self.seed_job()
        self.policy["enabled"] = False
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_manual_and_alert_calls_share_owner_cooldown(self):
        self.seed_job()
        self.seed_manual(channel="voip", status="accepted", provider_response_summary={"send_started_at": datetime.now(UTC).isoformat()})
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db: self.assertEqual(db.get(AlertDeliveryJob, 1).last_error, "call_cooldown")

    async def test_corrupt_recipient_cipher_fails_without_send_or_retry(self):
        self.seed_manual()
        with patch.object(d, "decrypt_value", side_effect=ValueError("opaque-private-fixture")):
            result = await d.dispatch_manual_event(1)
        self.assertEqual(result, {"status": "failed", "error_code": "delivery_preflight_failed"})
        self.send.assert_not_called()
        self.assertEqual(d._claim_manual(10), [])

    async def test_rights_revocation_before_call_cancels(self):
        self.seed_job()
        with patch("app.services.alert_engine.source_rights_snapshot_allowed", return_value=False):
            await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_cancelled_job_never_calls_transport(self):
        self.seed_job()
        with self.session() as db: db.get(AlertDeliveryJob, 1).status = "cancelled"; db.commit()
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()

    async def test_provider_rejected_all_paid_jobs_finalizes_failure_and_safe_error(self):
        self.seed_job("sms")
        self.send.return_value = TransportResult("failed", error_code="provider_rejected", provider_id="kavenegar")
        await self.worker._process_job(1, 1)
        with self.session() as db:
            row = db.get(AlertDeliveryJob, 1)
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.last_error, "provider_rejected")
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "delivery_failed")

    async def test_provider_unknown_has_safe_error_in_history(self):
        self.seed_job("sms")
        self.send.return_value = TransportResult("unknown", error_code="provider_result_unknown", provider_id="kavenegar")
        await self.worker._process_job(1, 1)
        with self.session() as db:
            row = db.get(AlertDeliveryJob, 1)
            self.assertEqual(row.last_error, "provider_result_unknown")
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "delivery_unknown")

    async def test_multiple_attempt_policy_is_not_supported_or_silently_accepted(self):
        self.seed_job()
        self.policy["max_attempts"] = 2
        await self.worker._process_job(1, 1)
        self.send.assert_not_called()
        with self.session() as db: self.assertEqual(db.get(AlertDeliveryJob, 1).last_error, "call_policy_invalid")


def _owned_postgres_url(value):
    url = make_url(value)
    markers = set(re.split(r"[_-]+", (url.database or "").lower()))
    if (url.drivername not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}
            or url.host != "127.0.0.1" or url.port is None or not 1 <= url.port <= 65535
            or markers.isdisjoint({"test", "ci"}) or url.query):
        raise unittest.SkipTest("Explicit synchronous loopback PostgreSQL test/CI database without URL overrides is required")
    return url


def _communication_fixture_metadata(schema):
    # Automatic column labels include the long run-owned schema. PostgreSQL's
    # 63-byte limit then reduces names to a short digest that can collide.
    # Table/column names are already unique inside each isolated schema.
    metadata = MetaData(naming_convention={"ix": "ix_%(table_name)s_%(column_0_name)s"})
    for model in (User, Alert, AlertTriggerEvent, AlertDeliveryJob, CommunicationRecipient,
                  CommunicationEvent, OperationalSetting, AdminSecret, AdminAuditLog):
        model.__table__.to_metadata(metadata, schema=schema)
    return metadata


class CommunicationDatabaseGuardTests(unittest.TestCase):
    def test_long_owned_schema_keeps_all_postgres_index_names_distinct(self):
        from sqlalchemy.dialects import postgresql
        dialect = postgresql.dialect()
        schemas = ("communication_worker_0d08380c56634278a74c422e643dec7c",
                   "communication_worker_" + "f" * 32,
                   "communication_worker_" + "0" * 32)
        for schema in schemas:
            with self.subTest(schema=schema):
                metadata = _communication_fixture_metadata(schema)
                names = [dialect.identifier_preparer.format_index(index)
                         for table in metadata.tables.values() for index in table.indexes]
                self.assertGreater(len(names), 20)
                self.assertEqual(len(names), len(set(names)))
                self.assertTrue(all(len(name.encode("utf-8")) <= 63 for name in names))
                self.assertTrue(all(table.schema == schema for table in metadata.tables.values()))

    def test_fixture_naming_does_not_change_application_metadata(self):
        models = (User, AlertDeliveryJob, AdminAuditLog)
        before = [(model.__table__.schema, sorted(str(index.name) for index in model.__table__.indexes)) for model in models]
        _communication_fixture_metadata("communication_worker_" + "a" * 32)
        after = [(model.__table__.schema, sorted(str(index.name) for index in model.__table__.indexes)) for model in models]
        self.assertEqual(after, before)

    def test_ci_port_and_database_name_are_allowed_without_shared_data_access(self):
        url = _owned_postgres_url("postgresql+psycopg://owned@127.0.0.1:5433/nerkhbaan_history_ci")
        self.assertEqual(url.port, 5433)
        self.assertEqual(url.database, "nerkhbaan_history_ci")

    def test_nonlocal_production_async_and_query_overrides_are_rejected(self):
        values = ("postgresql+psycopg://owned@external.invalid:5433/owned_ci",
                  "postgresql+psycopg://owned@127.0.0.1:5433/production",
                  "postgresql+psycopg://owned@127.0.0.1:5433/contest",
                  "postgresql+asyncpg://owned@127.0.0.1:5433/owned_ci",
                  "postgresql+psycopg://owned@127.0.0.1/owned_ci",
                  "postgresql+psycopg://owned@127.0.0.1:5433/owned_ci?host=external.invalid",
                  "postgresql+psycopg://owned@127.0.0.1:5433/owned_ci?dbname=production",
                  "postgresql+psycopg://owned@127.0.0.1:5433/owned_ci?options=overrides")
        for value in values:
            with self.subTest(value=value), self.assertRaises(unittest.SkipTest): _owned_postgres_url(value)


@unittest.skipUnless(os.getenv("COMMUNICATIONS_TEST_DATABASE_URL"), "Owned communications PostgreSQL test database is not selected")
class CommunicationConcurrencyPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = _owned_postgres_url(os.environ["COMMUNICATIONS_TEST_DATABASE_URL"])
        cls.schema = "communication_worker_" + uuid.uuid4().hex
        cls.admin = create_engine(url, connect_args={"connect_timeout": 5, "application_name": cls.schema})
        cls.quoted = cls.admin.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin.begin() as connection: connection.execute(text("CREATE SCHEMA " + cls.quoted))
        try:
            metadata = _communication_fixture_metadata(cls.schema)
            metadata.create_all(cls.admin)
            cls.engine = create_engine(url, connect_args={"connect_timeout": 5, "application_name": cls.schema,
                "options": "-csearch_path=" + cls.schema + " -clock_timeout=5000 -cstatement_timeout=15000"})
            cls.session = sessionmaker(cls.engine, expire_on_commit=False)
        except Exception:
            with cls.admin.begin() as connection: connection.execute(text("DROP SCHEMA " + cls.quoted + " CASCADE"))
            cls.admin.dispose()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        try:
            with cls.admin.begin() as connection: connection.execute(text("DROP SCHEMA " + cls.quoted + " CASCADE"))
        finally:
            cls.admin.dispose()

    def setUp(self):
        from app.admin import communication_storage as storage
        self.storage = storage
        with self.engine.begin() as connection:
            for model in (AdminAuditLog, CommunicationEvent, CommunicationRecipient, AlertDeliveryJob, AlertTriggerEvent, Alert, AdminSecret, OperationalSetting, User):
                connection.execute(model.__table__.delete())
        with self.session() as db:
            db.add(User(id=1, username="owned", full_name="Owned", email="owned@example.invalid", password_hash="fixture")); db.flush()
            db.add(OperationalSetting(id=1, key="communications.provider.sms", scope_id="global", value={"enabled": True, "provider_id": "kavenegar", "config": {"sender": "1000123"}}, version=1))
            db.add(AdminSecret(id=1, key="communications.sms.credentials", ciphertext="opaque-owned-fixture"))
            db.add(CommunicationRecipient(id=1, owner_user_id=1, label="Owned", phone_ciphertext="opaque-owned-phone", phone_masked="***0000", consented=True)); db.flush()
            db.add(CommunicationEvent(id=1, owner_user_id=1, recipient_id=1, channel="sms", status="queued", dry_run=False,
                client_request_id="owned-concurrent", delivery_key="owned-concurrent-key")); db.commit()
            # Each case owns this schema; keep its generated sequence aligned with its empty reset.
            db.execute(text("SELECT setval(pg_get_serial_sequence('communication_events','id'), 1, true)"))
            db.commit()
        patches = [patch.object(d, "SessionLocal", self.session), patch.object(d, "encryption_ready", return_value=True),
            patch.object(storage, "encryption_ready", return_value=True), patch.object(storage, "read_secret", return_value={"api_key": "ownedfixturekey"}),
            patch.object(d, "read_secret", return_value={"api_key": "ownedfixturekey"}),
            patch.object(d, "decrypt_value", return_value="+989120000000"),
            patch.object(d, "send_transport", return_value=TransportResult("accepted", "safe-reference", provider_id="kavenegar"))]
        mocks = [item.start() for item in patches]
        for item in patches: self.addCleanup(item.stop)
        self.send = mocks[-1]

    def test_duplicate_workers_send_one_owned_event_once(self):
        barrier = threading.Barrier(2)
        def dispatch():
            barrier.wait(timeout=5)
            return asyncio.run(d.dispatch_manual_event(1))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(dispatch) for _ in range(2)]
            outcomes = [future.result(timeout=15) for future in futures]
        self.assertEqual(self.send.call_count, 1)
        self.assertTrue(any(result.get("skipped") for result in outcomes))
        with self.session() as db: self.assertEqual(db.get(CommunicationEvent, 1).status, "accepted")

    def test_postgres_mixed_history_pages_before_loading_receipt_bodies(self):
        from app.admin.routers import communications
        stamp = datetime(2026, 10, 21, tzinfo=UTC)
        with self.session() as db:
            db.get(CommunicationEvent, 1).created_at = stamp
            db.add(CommunicationEvent(id=2, owner_user_id=1, recipient_id=1, channel="sms", status="dry_run", dry_run=True,
                client_request_id=str(uuid.uuid4()), delivery_key="owned-paging-test", created_at=stamp))
            db.add(Alert(id=1, user_id=1, asset="btc", target_price=100, condition="above")); db.flush()
            db.add(AlertTriggerEvent(id=1, alert_id=1, idempotency_key="owned-paging-occurrence", condition_snapshot={})); db.flush()
            db.add(AlertDeliveryJob(id=1, alert_id=1, trigger_event_id=1, channel="voip", status="accepted", created_at=stamp,
                destination_reference="must-stay-private", idempotency_key="owned-paging-job"))
            db.commit()
        principal = SimpleNamespace(user=SimpleNamespace(id=1))
        with self.session() as db:
            first = communications.list_deliveries(2, 0, principal, db)
            second = communications.list_deliveries(2, 1, principal, db)
        self.assertEqual(first["total"], 3)
        self.assertEqual([row["id"] for row in first["items"]], ["alert:1", "manual:2"])
        self.assertEqual([row["id"] for row in second["items"]], ["manual:2", "manual:1"])
        self.assertNotIn("must-stay-private", str(first))
        self.send.assert_not_called()

    def test_recipient_revocation_wins_before_sending_boundary(self):
        waiting = threading.Event()
        original_scalar = Session.scalar
        def queried(session, statement, *args, **kwargs):
            if getattr(statement, "_for_update_arg", None) is not None and "communication_recipients" in str(statement):
                waiting.set()
            return original_scalar(session, statement, *args, **kwargs)
        with self.session() as revoke, ThreadPoolExecutor(max_workers=1) as pool:
            recipient = revoke.scalar(select(CommunicationRecipient).where(CommunicationRecipient.id == 1).with_for_update())
            recipient.consented = False
            with patch.object(Session, "scalar", queried):
                future = pool.submit(lambda: asyncio.run(d.dispatch_manual_event(1)))
                # The worker blocks on this owned recipient row. Release only after it started.
                try:
                    self.assertTrue(waiting.wait(timeout=5))
                    self.assertFalse(future.done())
                finally:
                    revoke.commit()
                result = future.result(timeout=15)
        self.assertEqual(result["status"], "cancelled")
        self.send.assert_not_called()

    def test_provider_disable_wins_before_sending_boundary(self):
        entered = threading.Event()
        original_lock = d.lock_setting
        def worker_lock(*args, **kwargs):
            entered.set()
            return original_lock(*args, **kwargs)
        with self.session() as disable, ThreadPoolExecutor(max_workers=1) as pool:
            row = self.storage.lock_setting(disable, "communications.provider.sms")
            row.value = {**row.value, "enabled": False}
            with patch.object(d, "lock_setting", side_effect=worker_lock):
                future = pool.submit(lambda: asyncio.run(d.dispatch_manual_event(1)))
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    self.assertFalse(future.done())
                finally:
                    disable.commit()
                result = future.result(timeout=15)
        self.assertEqual(result["status"], "cancelled")
        self.send.assert_not_called()

    def test_actual_delete_recipient_route_serializes_with_worker_without_send(self):
        from fastapi import Request
        from app.admin.routers import communications
        route_holds_provider = threading.Event()
        resume_route = threading.Event()
        worker_entered = threading.Event()
        owned_recipient = communications._owned_recipient
        original_lock = d.lock_setting
        def pause_route(*args, **kwargs):
            route_holds_provider.set()
            if not resume_route.wait(timeout=5): raise TimeoutError("owned_test_barrier")
            return owned_recipient(*args, **kwargs)
        def worker_lock(*args, **kwargs):
            worker_entered.set()
            return original_lock(*args, **kwargs)
        request = Request({"type": "http", "method": "DELETE", "path": "/communications/test-recipients/1",
                           "headers": [], "client": ("127.0.0.1", 40000), "scheme": "https"})
        principal = SimpleNamespace(user=SimpleNamespace(id=1))
        def delete():
            with self.session() as db:
                return communications.delete_recipient(1, request, principal, db)
        with patch.object(communications, "_owned_recipient", side_effect=pause_route), patch.object(d, "lock_setting", side_effect=worker_lock), ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(delete)
            try:
                self.assertTrue(route_holds_provider.wait(timeout=5))
                dispatch = pool.submit(lambda: asyncio.run(d.dispatch_manual_event(1)))
                self.assertTrue(worker_entered.wait(timeout=5))
                self.assertFalse(dispatch.done())
            finally:
                resume_route.set()
            self.assertEqual(deletion.result(timeout=15), {"deleted": True})
            self.assertTrue(dispatch.result(timeout=15)["skipped"])
        self.send.assert_not_called()
        with self.session() as db:
            self.assertIsNone(db.get(CommunicationRecipient, 1))
            self.assertEqual(db.get(CommunicationEvent, 1).status, "cancelled")
            self.assertIsNone(db.get(CommunicationEvent, 1).recipient_id)
            self.assertEqual(db.scalar(select(AdminAuditLog.action)), "admin.communications.recipient_deleted")

    def test_sms_post_and_voip_worker_share_owner_before_recipient_lock_order(self):
        from fastapi import Request
        from app.admin.communication_schemas import TestEventCreate
        from app.admin.routers import communications
        with self.session() as db:
            db.get(CommunicationEvent, 1).channel = "voip"
            db.add(OperationalSetting(id=2, key="communications.provider.voip", scope_id="global", version=1,
                value={"enabled": True, "provider_id": "asterisk_ari", "config": {"endpoint": "https://pbx.example.invalid/ari",
                    "trunk": "owned", "context": "owned", "extension": "100"}}))
            db.add(AdminSecret(id=2, key="communications.voip.credentials", ciphertext="opaque-owned-fixture"))
            db.commit()
        credentials = lambda _db, channel: ({"api_key": "ownedfixturekey"} if channel == "sms" else {"username": "owned", "password": "owned-fixture"})
        policy = {**copy.deepcopy(DEFAULT_POLICY), "enabled": True, "persist_seconds": 0}
        policy["quiet_hours"]["enabled"] = False
        worker_before_recipient, post_before_owner, post_before_flush = (threading.Event() for _ in range(3))
        resume_worker, resume_post = threading.Event(), threading.Event()
        local = threading.local()
        scalar, flush = Session.scalar, Session.flush
        def queried(session, statement, *args, **kwargs):
            tag = getattr(local, "tag", "")
            if getattr(statement, "_for_update_arg", None) is not None:
                sql = str(statement)
                if tag == "worker" and "communication_recipients" in sql:
                    worker_before_recipient.set()
                    if not resume_worker.wait(timeout=5): raise TimeoutError("owned_worker_barrier")
                if tag == "post" and "FROM users" in sql:
                    post_before_owner.set()
            return scalar(session, statement, *args, **kwargs)
        def flushed(session, *args, **kwargs):
            if getattr(local, "tag", "") == "post" and any(isinstance(row, CommunicationEvent) for row in session.new):
                post_before_flush.set()
                if not resume_post.wait(timeout=5): raise TimeoutError("owned_post_barrier")
            return flush(session, *args, **kwargs)
        request = Request({"type": "http", "method": "POST", "path": "/communications/test-events",
                           "headers": [], "client": ("127.0.0.1", 40000), "scheme": "https"})
        principal = SimpleNamespace(user=SimpleNamespace(id=1), session=SimpleNamespace(reauthenticated_at=datetime.now(UTC)))
        payload = TestEventCreate(channel="sms", recipient_id=1, mode="send", client_request_id=uuid.uuid4(), confirmation="SEND TEST")
        def post():
            local.tag = "post"
            with self.session() as db: return communications.create_test_event(payload, request, principal, db)
        def dispatch():
            local.tag = "worker"
            return asyncio.run(d.dispatch_manual_event(1))
        with patch.object(Session, "scalar", queried), patch.object(Session, "flush", flushed), \
             patch.object(self.storage, "read_secret", side_effect=credentials), patch.object(d, "read_secret", side_effect=credentials), \
             patch.object(d, "read_policy", return_value=policy), ThreadPoolExecutor(max_workers=2) as pool:
            worker = pool.submit(dispatch)
            try:
                self.assertTrue(worker_before_recipient.wait(timeout=5))
                creator = pool.submit(post)
                self.assertTrue(post_before_owner.wait(timeout=5))
                self.assertFalse(post_before_flush.wait(timeout=0.1))
                resume_worker.set()
                self.assertEqual(worker.result(timeout=15)["status"], "accepted")
                self.assertTrue(post_before_flush.wait(timeout=5))
            finally:
                resume_worker.set()
                resume_post.set()
            self.assertEqual(creator.result(timeout=15)["status"], "queued")
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.send.call_args.args[0], "voip")
        with self.session() as db:
            self.assertEqual(db.get(CommunicationEvent, 1).status, "accepted")
            self.assertEqual(len(db.scalars(select(CommunicationEvent)).all()), 2)


if __name__ == "__main__":
    unittest.main()
