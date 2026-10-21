from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-only-migration-key-not-for-runtime-00000000")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.admin import models as admin_models  # Register administrative tables.
from app.db import Base
from app.migrations import runner
from app.migrations.state import migration_checksum


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "An isolated PostgreSQL fixture is required")
class CommunicationsMigrationTests(unittest.TestCase):
    def test_exact_upgrade_and_idempotency_rollback_to_empty_fixture(self):
        url = make_url(os.environ["TEST_DATABASE_URL"])
        if (url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost"}
                or "communications_test" not in (url.database or "")):
            self.skipTest("The dedicated local communications fixture is required")
        engine = create_engine(url, connect_args={"connect_timeout": 3})
        path = Path(__file__).resolve().parents[1] / "db" / "migrations" / "20261021_001_communications.sql"
        try:
            with engine.connect() as connection:
                count = connection.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar_one()
                if count:
                    self.skipTest("Public fixture must initially be empty")
                # All DDL remains in this outer transaction, including nested applier commits.
                try:
                    Base.metadata.create_all(connection)
                    connection.exec_driver_sql("DROP TABLE public.communication_events, public.communication_recipients, public.admin_secrets")
                    connection.exec_driver_sql("ALTER TABLE public.alerts DROP COLUMN notify_voip, DROP COLUMN priority")
                    connection.exec_driver_sql("ALTER TABLE public.alert_delivery_jobs DROP CONSTRAINT ck_alert_delivery_status")
                    connection.exec_driver_sql("ALTER TABLE public.alert_delivery_jobs ADD CONSTRAINT ck_alert_delivery_status CHECK(status IN ('pending','processing','sending','delivered','retrying','failed','dead','cancelled'))")
                    connection.exec_driver_sql(runner.MIGRATION_TABLE_SQL)
                    raw = connection.connection.driver_connection
                    runner._apply_file(raw, path)
                    runner._apply_file(raw, path)
                    rows = connection.execute(text("SELECT version,checksum FROM public.schema_migrations")).all()
                    self.assertEqual(rows, [(path.name, migration_checksum(path))])
                    fields = set(connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='alerts'")).scalars())
                    self.assertTrue({"notify_voip", "priority"} <= fields)
                    tables = set(connection.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")).scalars())
                    self.assertTrue({"admin_secrets", "communication_recipients", "communication_events"} <= tables)
                    check = connection.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_alert_delivery_status' AND conrelid='public.alert_delivery_jobs'::regclass")).scalar_one()
                    self.assertIn("accepted", check)
                    self.assertIn("unknown", check)
                    self.assertEqual(admin_models.CommunicationEvent.__table__.c.channel.type.length, 16)
                finally:
                    connection.rollback()
                self.assertEqual(connection.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar_one(), 0)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
