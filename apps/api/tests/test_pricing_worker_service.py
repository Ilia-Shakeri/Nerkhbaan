from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.service import InstrumentPricingService, _WORKER_PARSER_VERSION
from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.instruments import get_instrument
from app.pricing.models import (
    Currency,
    PersistenceStatus,
    ProviderQuote,
    ValidationStatus,
    WeightUnit,
)


class PricingWorkerServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_worker_parser_version_fits_production_column(self) -> None:
        self.assertLessEqual(len(_WORKER_PARSER_VERSION), 32)

    async def test_rejects_stale_live_quote_before_storage(self) -> None:
        service = InstrumentPricingService()
        now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)

        with patch("app.pricing.service.utc_now", return_value=now):
            with self.assertRaisesRegex(ValueError, "too old"):
                await service.ingest_worker_quote(
                    instrument_id="XAG_USD_OZ",
                    provider_id="gold_api_free_xag",
                    price=Decimal("64.6"),
                    observed_at=now - timedelta(hours=3),
                    historical=False,
                )

    def test_relay_quote_starts_bounded_live_window_at_receive_time(self) -> None:
        now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
        quote = ProviderQuote.create(
            instrument_id="USDT_USD",
            provider_id="coingecko_usdt",
            source_type="http",
            price=Decimal("0.999"),
            currency=Currency.USD,
            weight_unit=WeightUnit.UNIT,
            purity=None,
            observed_at=now - timedelta(minutes=2),
            received_at=now,
            parser_version=_WORKER_PARSER_VERSION,
            validation_status=ValidationStatus.ACCEPTED,
            persistence_status=PersistenceStatus.PERSISTED,
            metadata={
                "provider_live_ttl_seconds": 360,
                "maximum_source_age_seconds": 600,
                "anchor_live_window_at_receive_time": True,
            },
        )

        decision = CanonicalPricePolicy().select(
            instrument=get_instrument("USDT_USD"),
            primary=quote,
            previous=None,
            assessment=None,
            verifier_quotes=[],
            now=now,
        )

        self.assertEqual(decision.canonical.observed_at, now - timedelta(minutes=2))
        self.assertEqual(decision.canonical.valid_until, now + timedelta(minutes=6))

    async def test_rejects_future_live_quote_before_storage(self) -> None:
        service = InstrumentPricingService()
        now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)

        with patch("app.pricing.service.utc_now", return_value=now):
            with self.assertRaisesRegex(ValueError, "future"):
                await service.ingest_worker_quote(
                    instrument_id="XAG_USD_OZ",
                    provider_id="gold_api_free_xag",
                    price=Decimal("64.6"),
                    observed_at=now + timedelta(minutes=6),
                    historical=False,
                )

    async def test_rejects_unsupported_silver_history(self) -> None:
        service = InstrumentPricingService()
        now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)

        with patch("app.pricing.service.utc_now", return_value=now):
            with self.assertRaisesRegex(ValueError, "does not support historical"):
                await service.ingest_worker_quote(
                    instrument_id="XAG_USD_OZ",
                    provider_id="gold_api_free_xag",
                    price=Decimal("64.6"),
                    observed_at=now,
                    historical=True,
                )
