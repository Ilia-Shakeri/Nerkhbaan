from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "pricing-refresh-health-test-key-0123456789")

from app.services.background import BackgroundRunner


class PricingRefreshHealthTests(unittest.TestCase):
    def test_initial_state_is_explicit(self) -> None:
        runner = BackgroundRunner(interval=1)

        self.assertEqual(
            runner.refresh_health(),
            {
                "enabled": True,
                "state": "not_started",
                "last_started_at": None,
                "last_completed_at": None,
                "last_error_type": None,
                "result_counts": {},
            },
        )

    def test_zero_usable_results_report_degraded(self) -> None:
        runner = BackgroundRunner(interval=1)
        runner._running = True

        async def run_once() -> None:
            with (
                patch(
                    "app.services.background.instrument_pricing_service.refresh_cycle",
                    new=AsyncMock(return_value={"BTC_USD": "unavailable", "XAU_USD_OZ": "expired"}),
                ),
                patch(
                    "app.services.background.asyncio.sleep",
                    new=AsyncMock(side_effect=asyncio.CancelledError),
                ),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await runner._run_refresh_loop()

        asyncio.run(run_once())
        health = runner.refresh_health()
        self.assertEqual(health["state"], "degraded")
        self.assertEqual(health["result_counts"], {"expired": 1, "unavailable": 1})
