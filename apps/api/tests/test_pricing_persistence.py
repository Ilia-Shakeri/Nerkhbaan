from __future__ import annotations

import asyncio
import sys
import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "pricing-persistence-test-key-0123456789")

config_module = sys.modules.get("app.config")
if config_module is not None:
    config_module.settings.database_url = (
        "postgresql+psycopg://test:test@localhost:5432/test"
    )
    config_module.settings.redis_url = None

from app.pricing.db_models import (
    InstrumentRecord,
    InstrumentProviderConfigRecord,
    PricingProviderRecord,
)
from app.pricing.instruments import INSTRUMENTS
from app.pricing.persistence import PricingPersistence
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.history import InternalPriceHistory, _canonical_from_row
from app.pricing.registry import PROVIDERS


class _CatalogSession:
    def __init__(self) -> None:
        self.added_instruments: list[InstrumentRecord] = []
        self.added_providers: list[PricingProviderRecord] = []
        self.added_configs: list[InstrumentProviderConfigRecord] = []
        self.locked = False
        self.parents_flushed = False
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def get(self, model, _key):
        return None

    def add(self, record) -> None:
        if isinstance(record, InstrumentRecord):
            self.added_instruments.append(record)
            return
        if isinstance(record, PricingProviderRecord):
            self.added_providers.append(record)
            return
        if isinstance(record, InstrumentProviderConfigRecord):
            if not self.parents_flushed:
                raise AssertionError("Provider configs were added before providers were flushed")
            self.added_configs.append(record)

    def execute(self, query, parameters):
        self.locked = "pg_advisory_xact_lock" in str(query)
        self.asserted_lock_id = parameters["lock_id"]

    def flush(self) -> None:
        self.parents_flushed = True

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class PricingPersistenceCatalogTests(unittest.TestCase):
    def test_catalog_flushes_provider_parents_before_configs(self) -> None:
        session = _CatalogSession()

        with patch("app.pricing.persistence.SessionLocal", return_value=session):
            PricingPersistence._sync_provider_catalog()

        self.assertEqual(len(session.added_providers), len(PROVIDERS))
        self.assertEqual(len(session.added_instruments), len(INSTRUMENTS))
        self.assertEqual(len(session.added_configs), len(PROVIDERS))
        self.assertTrue(session.locked)
        self.assertGreater(session.asserted_lock_id, 0)
        self.assertTrue(session.parents_flushed)
        self.assertTrue(session.committed)
        self.assertFalse(session.rolled_back)
        self.assertTrue(session.closed)


class _HistoryRows:
    def mappings(self):
        return self

    def all(self):
        return []


class _HistorySession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def execute(self, query, parameters):
        self.calls.append((str(query), parameters))
        return _HistoryRows()

    def close(self) -> None:
        return None


class InternalPriceHistoryQueryTests(unittest.TestCase):
    def test_latest_row_accepts_negative_percentage_change(self) -> None:
        now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
        quote = _canonical_from_row(
            {
                "id": 1,
                "instrument_id": "BTC_USD",
                "price": Decimal("100000"),
                "status": "live",
                "primary_quote_id": None,
                "verification_quote_ids": [],
                "source_summary": {},
                "candidate_price": None,
                "candidate_provider_id": None,
                "observed_at": now,
                "canonical_at": now,
                "valid_until": now + timedelta(minutes=1),
                "stale_at": now + timedelta(minutes=2),
                "expires_at": now + timedelta(minutes=3),
                "is_persisted": True,
                "decision_reason": "test",
                "verification_status": "not_required",
                "change_1h": Decimal("-1.25"),
                "change_24h": Decimal("0.50"),
                "change_7d": None,
                "change_30d": None,
                "idempotency_key": "test",
                "sequence_number": 1,
            }
        )

        self.assertEqual(quote.change_1h, Decimal("-1.25"))
        self.assertEqual(quote.change_24h, Decimal("0.50"))

    def test_latest_all_skips_one_malformed_row(self) -> None:
        valid = MagicMock(instrument_id="BTC_USD")
        with (
            patch.object(
                InternalPriceHistory,
                "_query_latest_rows",
                return_value=[{"instrument_id": "BROKEN"}, {"instrument_id": "BTC_USD"}],
            ),
            patch(
                "app.pricing.history._canonical_from_row",
                side_effect=[ValueError("bad row"), valid],
            ),
        ):
            quotes = InternalPriceHistory._query_latest_all()

        self.assertEqual(quotes, {"BTC_USD": valid})

    def test_latest_all_uses_no_untyped_null_parameter(self) -> None:
        session = _HistorySession()

        with patch("app.pricing.history.SessionLocal", return_value=session):
            rows = InternalPriceHistory._query_latest_rows(None)

        self.assertEqual(rows, [])
        self.assertEqual(session.calls[0][1], {})
        self.assertNotIn(":instrument_id", session.calls[0][0])

    def test_latest_instrument_keeps_typed_column_comparison(self) -> None:
        session = _HistorySession()

        with patch("app.pricing.history.SessionLocal", return_value=session):
            rows = InternalPriceHistory._query_latest_rows("BTC_USD")

        self.assertEqual(rows, [])
        self.assertEqual(session.calls[0][1], {"instrument_id": "BTC_USD"})
        self.assertIn("instrument_id = :instrument_id", session.calls[0][0])


class _BackfillOperational:
    async def feature_enabled(self, _key: str) -> bool:
        return True

    async def providers_for(self, _instrument_id: str):
        return ()


class PricingBackfillQueueTests(unittest.TestCase):
    def test_enqueue_skips_instruments_without_a_history_route(self) -> None:
        now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
        queue = PricingBackfillQueue(operational=_BackfillOperational())

        with patch.object(PricingBackfillQueue, "_insert_job") as insert_job:
            result = asyncio.run(
                queue.enqueue(
                    instrument_id="XAU_USD_OZ",
                    range_start=now - timedelta(hours=1),
                    range_end=now,
                )
            )

        self.assertEqual(result.status, "unsupported")
        insert_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
