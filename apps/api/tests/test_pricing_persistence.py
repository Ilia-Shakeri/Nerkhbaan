from __future__ import annotations

import sys
import os
import unittest
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
from app.pricing.history import InternalPriceHistory
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


if __name__ == "__main__":
    unittest.main()
