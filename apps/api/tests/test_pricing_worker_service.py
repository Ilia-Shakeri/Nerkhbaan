from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.service import InstrumentPricingService, _WORKER_PARSER_VERSION


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
