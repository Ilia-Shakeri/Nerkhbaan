"""Guard and optional real PostgreSQL checks for disposable browser fixtures."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "scripts"))
from browser_fixture_database import cleanup, prepare, validate_database_url


class FixtureGuards(unittest.TestCase):
    def test_explicit_loopback_test_database(self):
        value = "postgresql+psycopg://fixture@127.0.0.1:55969/delivery_test"
        self.assertEqual(validate_database_url(value), value)

    def test_remote_database_rejected(self):
        with self.assertRaises(ValueError):
            validate_database_url("postgresql+psycopg://fixture@db.example/delivery_test")

    def test_runtime_and_system_databases_rejected(self):
        for database in ("production", "postgres", "template1", "contest"):
            with self.subTest(database=database), self.assertRaises(ValueError):
                validate_database_url(f"postgresql+psycopg://fixture@localhost/{database}")

    def test_unsafe_schema_rejected_before_connect(self):
        with self.assertRaises(ValueError):
            cleanup("public")

    @unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Explicit loopback TEST_DATABASE_URL required")
    def test_real_sync_async_schema_ownership_and_cleanup(self):
        schema, engine, async_engine = prepare()
        try:
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT current_schema()")).scalar_one(), schema)
                self.assertIsNone(connection.execute(text("SELECT to_regclass('schema_migrations')")).scalar_one())
                self.assertIsNotNone(connection.execute(text("SELECT to_regclass('users')")).scalar_one())
            from app.db import RequestSessionLocal, request_engine
            with RequestSessionLocal() as request_session:
                self.assertEqual(request_session.execute(text("SELECT current_schema()")).scalar_one(), schema)
                self.assertIsNotNone(request_session.execute(text("SELECT to_regclass('users')")).scalar_one())
            # Syntax/ORM compatibility only. No hypertables, compression, or ledger proof.
            migration = (Path(__file__).resolve().parents[1] / "apps/api/db/migrations/20261011_001_delivery_hardening.sql").read_text()
            from app.pricing.db_models import CanonicalQuoteRecord, ProviderQuoteRecord
            from app.pricing.persistence import PricingPersistence
            PricingPersistence._sync_provider_catalog()
            with engine.begin() as connection:
                connection.execute(text("UPDATE pricing_providers SET role='verifier' WHERE provider_id='gold_api_free_xag'"))
                connection.execute(text("UPDATE instrument_provider_configs SET role='verifier' WHERE provider_id='gold_api_free_xag'"))
            now = datetime.now(UTC)
            with Session(engine) as session:
                for role in ("backfill", "normal"):
                    provider = ProviderQuoteRecord(
                        instrument_id="FIXTURE_ONLY", provider_id="fixture", source_type="worker",
                        price=Decimal("1"), currency="USD", observed_at=now, received_at=now,
                        parser_version="fixture", validation_status="accepted", confidence_score=Decimal("1"),
                        persistence_status="persisted", idempotency_key=f"provider-{role}",
                        quote_role="normal", extra={"quote_role": role},
                    )
                    session.add(provider)
                    session.flush()
                    session.add(CanonicalQuoteRecord(
                        instrument_id="FIXTURE_ONLY", price=Decimal("1"), status="LIVE",
                        primary_quote_id=provider.id, source_summary={"fixture_role": role},
                        observed_at=now, canonical_at=now, valid_until=now + timedelta(seconds=60),
                        stale_at=now + timedelta(seconds=120), expires_at=now + timedelta(seconds=180),
                        decision_reason="fixture", verification_status="not_required", idempotency_key=f"canonical-{role}",
                    ))
                session.commit()
            with engine.begin() as connection:
                connection.exec_driver_sql(migration.replace("public.", f'"{schema}".'))
                self.assertIsNotNone(connection.execute(text("SELECT to_regclass('ix_canonical_quotes_latest_live')")).scalar_one())
                rows = connection.execute(text("SELECT source_summary->>'fixture_role', source_summary->>'historical_backfill' FROM canonical_quotes")).all()
                self.assertEqual(dict(rows), {"backfill": "true", "normal": None})
                self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM canonical_quotes")).scalar_one(), 2)
                self.assertEqual(connection.execute(text("SELECT role FROM pricing_providers WHERE provider_id='gold_api_free_xag'")).scalar_one(), "fallback")
                self.assertEqual(connection.execute(text("SELECT role FROM instrument_provider_configs WHERE provider_id='gold_api_free_xag'")).scalar_one(), "fallback")
                connection.execute(text("UPDATE pricing_providers SET role='verifier' WHERE provider_id='gold_api_free_xag'"))
                connection.execute(text("UPDATE instrument_provider_configs SET role='verifier' WHERE provider_id='gold_api_free_xag'"))
                connection.execute(text("INSERT INTO operational_settings(key,scope_id,value,description,is_sensitive,version) VALUES ('provider.config','gold_api_free_xag',CAST(:value AS jsonb),'fixture',false,1)"), {"value": '{"role":"verifier"}'})
                connection.exec_driver_sql(migration.replace("public.", f'"{schema}".'))
                self.assertEqual(connection.execute(text("SELECT role FROM pricing_providers WHERE provider_id='gold_api_free_xag'")).scalar_one(), "verifier")
                self.assertEqual(connection.execute(text("SELECT role FROM instrument_provider_configs WHERE provider_id='gold_api_free_xag'")).scalar_one(), "verifier")
            from app.pricing.history import InternalPriceHistory
            from app.config import settings
            # This synthetic instrument checks SQL/ORM shape, not provider rights.
            with patch.object(settings, "pricing_rights_enforced", False):
                latest = InternalPriceHistory._query_latest_rows(None)
            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0]["source_summary"]["fixture_role"], "normal")

            async def verify_async():
                async with async_engine.connect() as connection:
                    self.assertEqual((await connection.execute(text("SELECT current_schema()"))).scalar_one(), schema)
                    self.assertIsNotNone((await connection.execute(text("SELECT to_regclass('users')"))).scalar_one())
                await async_engine.dispose()

            asyncio.run(verify_async())
            with engine.begin() as connection:
                connection.execute(text(f'UPDATE "{schema}"._browser_fixture_marker SET run_id = :value'), {"value": "other-run"})
            with self.assertRaises(ValueError):
                cleanup(schema)
            with engine.begin() as connection:
                self.assertIsNotNone(connection.execute(text("SELECT to_regnamespace(:schema)"), {"schema": schema}).scalar_one())
                connection.execute(text(f'UPDATE "{schema}"._browser_fixture_marker SET run_id = :value'), {"value": schema.removeprefix("browser_fixture_")})
        finally:
            cleanup(schema)
        with engine.connect() as connection:
            self.assertIsNone(connection.execute(text("SELECT to_regnamespace(:schema)"), {"schema": schema}).scalar_one())
        engine.dispose()
        request_engine.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
