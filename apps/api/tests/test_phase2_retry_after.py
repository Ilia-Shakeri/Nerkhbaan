from __future__ import annotations

import os
import time
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import patch

import httpx

os.environ["DEBUG"] = "false"

from app.pricing.models import ProviderRuntimeState
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import PROVIDERS


FROZEN_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class _RuntimeStore:
    def __init__(self) -> None:
        self.runtime = None

    async def set_provider_runtime(self, runtime) -> None:
        self.runtime = runtime


class _RuntimePersistence:
    async def record_runtime_event(self, **_values) -> None:
        return None


class RetryAfterTests(unittest.IsolatedAsyncioTestCase):
    def test_integer_and_http_date_are_bounded(self) -> None:
        self.assertEqual(
            ProviderQuoteCollector._parse_retry_after("120", now=FROZEN_NOW),
            120,
        )
        date_value = format_datetime(FROZEN_NOW + timedelta(seconds=75), usegmt=True)
        self.assertEqual(
            ProviderQuoteCollector._parse_retry_after(date_value, now=FROZEN_NOW),
            75,
        )
        self.assertEqual(
            ProviderQuoteCollector._parse_retry_after("999999", now=FROZEN_NOW),
            86400,
        )
        self.assertEqual(
            ProviderQuoteCollector._parse_retry_after("9" * 5000, now=FROZEN_NOW),
            86400,
        )
        self.assertIsNone(
            ProviderQuoteCollector._parse_retry_after("bad-value", now=FROZEN_NOW)
        )

    async def test_429_response_carries_retry_after_without_sleep(self) -> None:
        provider = PROVIDERS["coinbase_btc_usd"]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"Retry-After": "180", "content-type": "application/json"},
                json={"error": "rate limit"},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ProviderCallFailure) as raised:
                await ProviderQuoteCollector()._request_payload(client, provider)

        self.assertEqual(raised.exception.retry_after_seconds, 180)

    async def test_rate_limit_cooldown_uses_greater_retry_after(self) -> None:
        provider = PROVIDERS["coinbase_btc_usd"]
        store = _RuntimeStore()
        collector = ProviderQuoteCollector(
            store=store,
            budgets=object(),
            locks=object(),
            persistence=_RuntimePersistence(),
        )
        runtime = ProviderRuntimeState(
            provider_id=provider.provider_id,
            instrument_id=provider.instrument_id,
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            await collector._record_failure(
                provider,
                runtime,
                "rate_limited",
                429,
                time.monotonic(),
                retry_after_seconds=900,
            )

        self.assertEqual(
            runtime.cooldown_until,
            FROZEN_NOW + timedelta(seconds=900),
        )


if __name__ == "__main__":
    unittest.main()
