from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")
os.environ["DEBUG"] = "false"

from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from scripts.provider_canary import probe_provider


class _ClientContext:
    async def __aenter__(self) -> "_ClientContext":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class ProviderCanaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_canary_requires_successful_parse(self) -> None:
        request = AsyncMock(return_value=({"price": "100000"}, "application/json", 200))
        with patch.object(ProviderQuoteCollector, "_request_payload", request), patch(
            "scripts.provider_canary.httpx.AsyncClient", return_value=_ClientContext()
        ):
            row = await probe_provider("coinbase_btc_usd")

        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["http_status"], 200)
        self.assertNotIn("price", row)

    async def test_canary_fails_auth_response(self) -> None:
        request = AsyncMock(
            side_effect=ProviderCallFailure("http_error", "bad auth", http_status=401)
        )
        with patch.object(ProviderQuoteCollector, "_request_payload", request), patch(
            "scripts.provider_canary.httpx.AsyncClient", return_value=_ClientContext()
        ):
            row = await probe_provider("coinbase_btc_usd")

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["reason"], "http_error")
