from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")
os.environ.setdefault("PRICING_REQUIRE_PROVIDER_KEYS", "false")

from app.models import Alert, AlertDeliveryJob, AlertTriggerEvent, User
from app.services.alert_engine import AlertEngine
from app.services.dlq_worker import DLQWorker


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRATION = Path(__file__).resolve().parents[1] / "db" / "migrations" / "20261011_002_notification_sending_state.sql"
LEGACY_STATES = ("pending", "processing", "delivered", "retrying", "failed", "dead", "cancelled")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not set")
class AlertDeliveryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert TEST_DATABASE_URL is not None
        url = make_url(TEST_DATABASE_URL)
        name_parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or name_parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("TEST_DATABASE_URL must name a PostgreSQL test or CI database")
        if url.drivername.endswith("+asyncpg"):
            raise unittest.SkipTest("TEST_DATABASE_URL must use a synchronous driver")
        cls.schema = "delivery_state_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, pool_pre_ping=True)
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        try:
            metadata = MetaData()
            for table in (User.__table__, Alert.__table__, AlertTriggerEvent.__table__, AlertDeliveryJob.__table__):
                table.to_metadata(metadata, schema=cls.schema)
            metadata.create_all(cls.admin_engine)
            cls.engine = create_engine(url, pool_pre_ping=True, connect_args={"options": f"-csearch_path={cls.schema},public"})
            cls.session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        except Exception:
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
            cls.admin_engine.dispose()
            raise

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
            connection.exec_driver_sql("ALTER TABLE alert_delivery_jobs DROP CONSTRAINT ck_alert_delivery_status")
            states = ",".join("'" + status + "'" for status in LEGACY_STATES)
            connection.exec_driver_sql("ALTER TABLE alert_delivery_jobs ADD CONSTRAINT ck_alert_delivery_status CHECK (status IN (" + states + "))")

    def _apply_migration(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("public.alert_delivery_jobs", sql)
        sql = sql.replace("public.alert_delivery_jobs", self.quoted_schema + ".alert_delivery_jobs")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(sql)

    def _seed(self, status: str = "processing", attempt: int = 1) -> None:
        with self.session() as db:
            db.add(User(id=1, username="owned_delivery", email="owned-delivery@example.invalid", full_name="Owned delivery test", password_hash="test", is_active=True))
            db.flush()
            db.add(Alert(id=1, user_id=1, asset="probe", target_price=1, condition="above", currency_mode="usd", notify_app=True, notify_email=False, notify_webhook=False, is_active=False))
            db.flush()
            db.add(AlertTriggerEvent(id=1, alert_id=1, condition_snapshot={"assets": []}, status="queued", idempotency_key="owned-event"))
            db.flush()
            db.add(AlertDeliveryJob(id=1, alert_id=1, trigger_event_id=1, channel="push", destination_reference="owned-test", status=status, attempt_count=attempt, idempotency_key="owned-job"))
            db.commit()

    def test_upgrade_reproduces_and_repairs_the_network_boundary(self) -> None:
        self._seed()
        with self.assertRaises(IntegrityError) as rejected:
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE alert_delivery_jobs SET status='sending' WHERE id=1"))
        self.assertEqual(rejected.exception.orig.sqlstate, "23514")
        self._apply_migration()
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alert_delivery_jobs SET status='sending' WHERE id=1"))
        with self.session() as db:
            job = db.get(AlertDeliveryJob, 1)
            self.assertEqual((job.status, job.attempt_count, job.idempotency_key), ("sending", 1, "owned-job"))

    def test_migration_keeps_legacy_states_is_idempotent_and_rejects_unknown(self) -> None:
        self._seed()
        self._apply_migration()
        self._apply_migration()
        with self.engine.begin() as connection:
            for status in (*LEGACY_STATES, "sending"):
                connection.execute(text("UPDATE alert_delivery_jobs SET status=:status WHERE id=1"), {"status": status})
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE alert_delivery_jobs SET status='invented' WHERE id=1"))
        with self.session() as db:
            self.assertEqual(db.scalar(select(AlertDeliveryJob.id)), 1)
            self.assertEqual(db.get(AlertDeliveryJob, 1).status, "sending")

    def test_actual_sender_commits_sending_before_transport_then_worker_finishes(self) -> None:
        self._seed()
        self._apply_migration()
        engine = AlertEngine()
        observed = []

        async def observe_network_boundary(*_args):
            with self.session() as db:
                observed.append(db.get(AlertDeliveryJob, 1).status)

        engine._send_push_notification = AsyncMock(side_effect=observe_network_boundary)
        with patch("app.services.alert_engine.SessionLocal", self.session):
            summary = asyncio.run(engine.deliver_job(1, expected_attempt=1))
        self.assertEqual(observed, ["sending"])
        self.assertEqual(summary, {"channel": "push", "accepted": True})
        worker = DLQWorker(engine)
        with patch("app.services.dlq_worker.SessionLocal", self.session):
            worker._mark_delivered(1, summary, 1)
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob, 1).status, "delivered")
            self.assertEqual(db.get(AlertTriggerEvent, 1).status, "delivered")
            self.assertIsNotNone(db.get(AlertDeliveryJob, 1).delivered_at)

    def test_cancel_and_stale_attempt_keep_their_database_state(self) -> None:
        self._seed(status="cancelled", attempt=2)
        self._apply_migration()
        engine = AlertEngine()
        engine._send_push_notification = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal", self.session):
            summary = asyncio.run(engine.deliver_job(1, expected_attempt=2))
        self.assertTrue(summary["skipped"])
        engine._send_push_notification.assert_not_awaited()
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE alert_delivery_jobs SET status='sending' WHERE id=1"))
        worker = DLQWorker(engine)
        with patch("app.services.dlq_worker.SessionLocal", self.session):
            worker._mark_delivered(1, {"accepted": True}, 1)
            worker._mark_failed(1, RuntimeError("old attempt"), 1)
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob, 1).status, "sending")


if __name__ == "__main__":
    unittest.main()
