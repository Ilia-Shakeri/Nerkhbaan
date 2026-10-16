from __future__ import annotations

import asyncio
import os
import re
import threading
import unittest
import uuid
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request
from sqlalchemy import MetaData, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")

from app.models import Alert, AlertDeliveryJob, AlertTriggerEvent, User
from app.admin.routers.health_jobs import cancel_delivery_job
from app.admin.schemas import DangerousConfirmation
from app.routers.alerts import create_alert, delete_alert
from app.schemas import AlertCreate
from app.services.alert_engine import Alert as DeliveryAlert, AlertEngine, PermanentDeliveryError
from app.services.dlq_worker import DLQWorker


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not set")
class AlertConsistencyPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        url = make_url(TEST_DATABASE_URL)
        name_parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or name_parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("A PostgreSQL test or CI database is required")
        cls.schema = "alert_consistency_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url)
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        metadata = MetaData()
        for table in (User.__table__, Alert.__table__, AlertTriggerEvent.__table__, AlertDeliveryJob.__table__):
            table.to_metadata(metadata, schema=cls.schema)
        metadata.create_all(cls.admin_engine)
        cls.engine = create_engine(url, connect_args={"options": f"-csearch_path={cls.schema},public -clock_timeout=5000 -cstatement_timeout=10000"})
        cls.session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        try:
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
        finally:
            cls.admin_engine.dispose()

    def setUp(self) -> None:
        with self.engine.begin() as connection:
            for table in (AlertDeliveryJob.__table__, AlertTriggerEvent.__table__, Alert.__table__, User.__table__):
                connection.execute(table.delete())
        with self.session() as db:
            db.add(User(id=1, username="alert_owner", email="alert-owner@example.invalid", full_name="Test owner", password_hash="test", is_active=True))
            db.commit()

    @staticmethod
    def _alert(**changes) -> Alert:
        values = dict(user_id=1, asset="btc", target_price=100, condition="above", currency_mode="usd", notify_app=False, notify_email=False, notify_webhook=True, webhook_url="https://old.example.invalid/hook", mode="recurring", is_active=True)
        return Alert(**(values | changes))

    def test_pending_occurrence_keeps_original_condition_and_webhook_after_edit(self) -> None:
        engine = AlertEngine()
        prices = {"assets": [{"asset": "btc", "price_usd": 150}]}
        occurred_at = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
        with self.session() as db:
            alert = self._alert()
            db.add(alert)
            db.flush()
            engine._queue_trigger(db, alert, prices, occurred_at, preferences=None, push_available=False)
            db.commit()
            job = db.scalar(select(AlertDeliveryJob))
            job.status, job.attempt_count = "processing", 1
            alert.asset, alert.target_price, alert.condition = "gold", 1000, "below"
            alert.currency_mode, alert.price_source_mode = "toman", "reference"
            alert.webhook_url = "https://new.example.invalid/hook"
            db.commit()
            job_id = job.id
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        delivered, snapshot = engine._send_webhook.await_args.args
        self.assertEqual((delivered.asset_id, delivered.target_price, delivered.condition, delivered.currency, delivered.price_source_mode), ("btc", 100, "above", "usd", "ordinary"))
        self.assertEqual(delivered.webhook_url, "https://old.example.invalid/hook")
        self.assertIn("above target 100.00 USD", engine._alert_summary(delivered, snapshot)[1])
        self.assertEqual(engine._current_price(delivered, snapshot), 150)
        self.assertEqual(snapshot["triggered_at"], occurred_at.isoformat())

    def test_pending_formula_keeps_original_expression_after_edit(self) -> None:
        engine = AlertEngine()
        with self.session() as db:
            alert = self._alert(asset="formula", alert_type="formula", formula="btc > x")
            db.add(alert)
            db.flush()
            engine._queue_trigger(db, alert, {"assets": [{"asset": "btc", "price_usd": 150}]}, datetime.now(UTC), preferences=None, push_available=False)
            db.commit()
            job = db.scalar(select(AlertDeliveryJob))
            job.status, job.attempt_count = "processing", 1
            event = db.get(AlertTriggerEvent, job.trigger_event_id)
            original = dict(event.condition_snapshot)
            original.pop("triggered_at", None)
            event.condition_snapshot = original
            expected_time = event.created_at.isoformat()
            alert.formula = "gold < x"
            db.commit()
            job_id = job.id
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        delivered, snapshot = engine._send_webhook.await_args.args
        self.assertEqual(delivered.formula, "btc > x")
        self.assertIn("btc > x", engine._alert_summary(delivered, snapshot)[1])
        self.assertEqual(snapshot["triggered_at"], expected_time)

    def _legacy_job(self, channel: str) -> int:
        with self.session() as db:
            alert = self._alert(asset="gold", target_price=1000, formula="gold < x", notify_app=True)
            db.add(alert)
            db.flush()
            event = AlertTriggerEvent(alert_id=alert.id, instrument_id="BTC_USD", price=150, condition_snapshot={"assets": [{"asset": "btc", "price_usd": 150}]}, status="queued", idempotency_key=uuid.uuid4().hex)
            db.add(event)
            db.flush()
            job = AlertDeliveryJob(alert_id=alert.id, trigger_event_id=event.id, channel=channel, destination_reference="test", status="processing", attempt_count=1, idempotency_key=uuid.uuid4().hex)
            db.add(job)
            db.commit()
            return job.id

    def test_legacy_occurrence_uses_only_stored_facts_without_current_condition(self) -> None:
        job_id = self._legacy_job("push")
        engine = AlertEngine()
        engine._send_push_notification = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        alert, snapshot = engine._send_push_notification.await_args.args
        title, body = engine._alert_summary(alert, snapshot)
        self.assertIn("150.00", body)
        self.assertIn("Original condition unavailable", body)
        for edited in ("GOLD", "1,000", "gold < x"):
            self.assertNotIn(edited, title + body)

    def test_legacy_webhook_without_original_destination_fails_without_sending(self) -> None:
        job_id = self._legacy_job("webhook")
        engine = AlertEngine()
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        engine._send_webhook.assert_not_awaited()
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob, job_id).status, "processing")

    def test_disabled_owner_cannot_receive_queued_delivery(self) -> None:
        job_id = self._legacy_job("push")
        with self.session() as db:
            db.get(User, 1).is_active = False
            db.commit()
        engine = AlertEngine()
        engine._send_push_notification = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        engine._send_push_notification.assert_not_awaited()

    def test_current_webhook_opt_out_blocks_immutable_queued_destination(self) -> None:
        engine = AlertEngine()
        with self.session() as db:
            alert = self._alert()
            db.add(alert)
            db.flush()
            engine._queue_trigger(db, alert, {"assets": [{"asset": "btc", "price_usd": 150}]}, datetime.now(UTC), preferences=None, push_available=False)
            db.commit()
            job = db.scalar(select(AlertDeliveryJob))
            job.status, job.attempt_count = "processing", 1
            alert.notify_webhook, alert.webhook_url = False, None
            db.commit()
            job_id = job.id
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        engine._send_webhook.assert_not_awaited()

    def test_cleared_current_webhook_blocks_old_destination_even_with_flag_enabled(self) -> None:
        engine = AlertEngine()
        with self.session() as db:
            alert = self._alert()
            db.add(alert)
            db.flush()
            engine._queue_trigger(db, alert, {"assets": [{"asset": "btc", "price_usd": 150}]}, datetime.now(UTC), preferences=None, push_available=False)
            db.commit()
            job = db.scalar(select(AlertDeliveryJob))
            job.status, job.attempt_count = "processing", 1
            alert.webhook_url = None
            db.commit()
            job_id = job.id
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        engine._send_webhook.assert_not_awaited()

    def test_automatically_closed_one_time_alert_still_delivers_its_occurrence(self) -> None:
        engine = AlertEngine()
        with self.session() as db:
            alert = self._alert(mode="one_time")
            db.add(alert)
            db.flush()
            engine._queue_trigger(db, alert, {"assets": [{"asset": "btc", "price_usd": 150}]}, datetime.now(UTC), preferences=None, push_available=False)
            db.commit()
            job = db.scalar(select(AlertDeliveryJob))
            job.status, job.attempt_count = "processing", 1
            alert.is_active = False
            db.commit()
            job_id = job.id
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        engine._send_webhook.assert_awaited_once()

    def test_explicit_delete_withdraws_delivery_for_already_triggered_one_time_alert(self) -> None:
        engine = AlertEngine()
        with self.session() as db:
            alert = self._alert(mode="one_time")
            db.add(alert)
            db.flush()
            engine._queue_trigger(db, alert, {"assets": [{"asset": "btc", "price_usd": 150}]}, datetime.now(UTC), preferences=None, push_available=False)
            db.commit()
            job = db.scalar(select(AlertDeliveryJob))
            job.status, job.attempt_count = "processing", 1
            alert.is_active = False
            db.commit()
            job_id = job.id
            delete_alert(alert.id, current_user=User(id=1), db=db)
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(engine.deliver_job(job_id, expected_attempt=1))
        engine._send_webhook.assert_not_awaited()
        with self.session() as db:
            alert = db.get(Alert, db.get(AlertDeliveryJob, job_id).alert_id)
            self.assertFalse(any(getattr(alert, flag) for flag in ("notify_app", "notify_email", "notify_webhook", "notify_telegram", "notify_sms")))

    def test_two_creates_at_49_active_alerts_allow_only_one(self) -> None:
        with self.session() as db:
            db.add_all([self._alert(notify_webhook=False) for _ in range(49)])
            db.commit()
        first_read, release_first, second_done = threading.Event(), threading.Event(), threading.Event()

        class PausedCountSession(Session):
            def scalar(inner, statement, *args, **kwargs):
                result = super().scalar(statement, *args, **kwargs)
                if inner.info.get("hold") and "count(alerts.id)" in str(statement):
                    first_read.set()
                    if not release_first.wait(4):
                        raise AssertionError("First create was not released")
                return result

        factory = sessionmaker(bind=self.engine, class_=PausedCountSession, expire_on_commit=False)

        def create(hold: bool) -> int:
            try:
                with factory(info={"hold": hold}) as db:
                    try:
                        create_alert(AlertCreate(asset="btc", target_price=100), current_user=User(id=1), db=db)
                        return 201
                    except HTTPException as exc:
                        return exc.status_code
            finally:
                if not hold:
                    second_done.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(create, True)
            try:
                self.assertTrue(first_read.wait(3))
                second = executor.submit(create, False)
                second_done.wait(0.5)
            finally:
                release_first.set()
            results = sorted([first.result(timeout=6), second.result(timeout=6)])
        with self.session() as db:
            active = db.scalar(select(func.count(Alert.id)).where(Alert.is_active.is_(True)))
        self.assertEqual((results, active), ([201, 409], 50))

    def test_cancelling_last_channel_finishes_event_and_keeps_success(self) -> None:
        for peer_status, expected in (("delivered", "delivered"), ("cancelled", "cancelled"), ("failed", "delivery_failed")):
            with self.subTest(peer_status=peer_status):
                self.setUp()
                job_id = self._legacy_job("push")
                with self.session() as db:
                    job = db.get(AlertDeliveryJob, job_id)
                    job.status = "pending"
                    event = db.get(AlertTriggerEvent, job.trigger_event_id)
                    event.status = "delivery_failed" if peer_status == "failed" else "queued"
                    db.add(AlertDeliveryJob(alert_id=job.alert_id, trigger_event_id=event.id, channel="email", destination_reference="test", status=peer_status, idempotency_key=uuid.uuid4().hex))
                    db.commit()
                    event_id = event.id
                principal = SimpleNamespace(user=SimpleNamespace(id=1), session=SimpleNamespace(reauthenticated_at=datetime.now(UTC)))
                request = Request({"type": "http", "method": "POST", "path": "/test", "headers": []})
                with self.session() as db, patch("app.admin.routers.health_jobs.add_audit_event"):
                    cancel_delivery_job(str(job_id), DangerousConfirmation(confirmation=f"CANCEL DELIVERY {job_id}"), request, principal, db)
                with self.session() as db:
                    self.assertEqual(db.get(AlertDeliveryJob, job_id).status, "cancelled")
                    self.assertEqual(db.get(AlertTriggerEvent, event_id).status, expected)

    def test_parallel_channel_completion_finishes_occurrence_in_both_orders(self) -> None:
        for peer_action, reverse in (("deliver", False), ("deliver", True), ("cancel", False), ("cancel", True)):
            with self.subTest(peer_action=peer_action, reverse=reverse):
                self.setUp()
                with self.session() as db:
                    alert = self._alert()
                    db.add(alert)
                    db.flush()
                    event = AlertTriggerEvent(alert_id=alert.id, condition_snapshot={"assets": []}, status="queued", idempotency_key=uuid.uuid4().hex)
                    db.add(event)
                    db.flush()
                    jobs = [AlertDeliveryJob(alert_id=alert.id, trigger_event_id=event.id, channel=channel, destination_reference="test", status="sending", attempt_count=1, idempotency_key=uuid.uuid4().hex) for channel in ("push", "webhook")]
                    if peer_action == "cancel":
                        jobs[1].status = "pending"
                    db.add_all(jobs)
                    db.commit()
                    job_ids, event_id = [job.id for job in jobs], event.id
                    cancel_id = jobs[1].id if peer_action == "cancel" else None
                if reverse:
                    job_ids.reverse()
                first_read, release_first, second_done = threading.Event(), threading.Event(), threading.Event()

                class PausedFinalizeSession(Session):
                    def scalars(inner, statement, *args, **kwargs):
                        result = super().scalars(statement, *args, **kwargs)
                        if threading.current_thread().name.endswith("_0") and "SELECT alert_delivery_jobs.status" in str(statement):
                            first_read.set()
                            if not release_first.wait(4):
                                raise AssertionError("First completion was not released")
                        return result

                factory = sessionmaker(bind=self.engine, class_=PausedFinalizeSession, expire_on_commit=False)
                worker = DLQWorker(AlertEngine())

                def finish(job_id: int, second: bool = False) -> None:
                    try:
                        if job_id == cancel_id:
                            principal = SimpleNamespace(user=SimpleNamespace(id=1), session=SimpleNamespace(reauthenticated_at=datetime.now(UTC)))
                            request = Request({"type": "http", "method": "POST", "path": "/test", "headers": []})
                            with factory() as db:
                                cancel_delivery_job(str(job_id), DangerousConfirmation(confirmation=f"CANCEL DELIVERY {job_id}"), request, principal, db)
                        else:
                            worker._mark_delivered(job_id, {"accepted": True}, 1)
                    finally:
                        if second:
                            second_done.set()

                with patch("app.services.dlq_worker.SessionLocal", factory), patch("app.admin.routers.health_jobs.add_audit_event"), ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(finish, job_ids[0])
                    try:
                        self.assertTrue(first_read.wait(3))
                        second = executor.submit(finish, job_ids[1], True)
                        second_done.wait(0.5)
                    finally:
                        release_first.set()
                    first.result(timeout=6)
                    second.result(timeout=6)
                with self.session() as db:
                    expected = ["cancelled", "delivered"] if peer_action == "cancel" else ["delivered", "delivered"]
                    self.assertEqual(sorted(db.scalars(select(AlertDeliveryJob.status))), expected)
                    self.assertEqual(db.get(AlertTriggerEvent, event_id).status, "delivered")


class AlertMailTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_retries_keep_identical_body_and_occurrence_timestamp(self) -> None:
        calls = []

        class FakeResponse:
            status_code = 200
            extensions = {"network_stream": SimpleNamespace(get_extra_info=lambda _key: ("8.8.8.8", 443))}

            def raise_for_status(self):
                pass

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                pass

            def stream(self, method, url, *, json, headers):
                calls.append((method, url, json, headers))
                return FakeStream()

        class FakeStream:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, *_args):
                pass

        alert = DeliveryAlert(id=1, user_id=1, asset_id="btc", target_price=100, condition="above", currency="usd", active=True, in_app_enabled=False, email_enabled=False, webhook_enabled=True, webhook_url="https://example.invalid/hook")
        alert.delivery_key = "same-occurrence-webhook"
        snapshot = {"triggered_at": "2026-10-16T10:00:00+00:00", "assets": [{"asset": "btc", "price_usd": 150}]}
        with patch("app.services.alert_engine.validate_webhook_url", return_value={"8.8.8.8"}), patch("app.services.alert_engine.PinnedWebhookTransport"), patch("app.services.alert_engine.httpx.AsyncClient", return_value=FakeClient()):
            await AlertEngine()._send_webhook(alert, snapshot)
            await AlertEngine()._send_webhook(alert, snapshot)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0][2]["triggered_at"], snapshot["triggered_at"])
        self.assertEqual(calls[0][3], {"Idempotency-Key": "same-occurrence-webhook"})

    async def test_shared_transport_gets_settings_and_propagates_failure_to_retry(self) -> None:
        alert = DeliveryAlert(id=1, user_id=1, asset_id="btc", target_price=100, condition="above", currency="usd", active=True, in_app_enabled=False, email_enabled=True, webhook_enabled=False, webhook_url=None)
        session = MagicMock()
        session.scalar.return_value = SimpleNamespace(email_enabled=True, email_verified=True, email_address="test@example.invalid")
        configured = SimpleNamespace(smtp_host="smtp.example.invalid", smtp_from="test@example.invalid")
        with patch("app.services.alert_engine.SessionLocal", return_value=session), patch("app.services.alert_engine.settings", configured), patch("app.services.alert_engine.send_smtp_message", side_effect=OSError("test mail offline")) as sender:
            with self.assertRaises(OSError):
                await AlertEngine()._send_email(alert, {"assets": [{"asset": "btc", "price_usd": 150}]})
        sender.assert_called_once()
        self.assertIs(sender.call_args.kwargs["smtp_settings"], configured)
        self.assertEqual(sender.call_args.kwargs["timeout"], 15)
