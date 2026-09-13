from __future__ import annotations

import hashlib
import hmac
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from fastapi import HTTPException

from app.routers.pricing_worker import _WORKER_ROUTES, _authenticate
from app.schemas import PricingWorkerIngestRequest


class PricingWorkerAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def test_worker_contract_allows_only_exact_metal_route(self) -> None:
        payload = PricingWorkerIngestRequest.model_validate(
            {
                "quotes": [
                    {
                        "instrument_id": "XAG_USD_OZ",
                        "provider_id": "gold_api_free_xag",
                        "price": "64.6",
                        "observed_at": "2026-09-13T08:00:00Z",
                    }
                ]
            }
        )
        quote = payload.quotes[0]
        self.assertEqual(_WORKER_ROUTES[quote.provider_id], quote.instrument_id)

    async def test_valid_signature_claims_one_replay_slot(self) -> None:
        secret = "x" * 48
        body = b'{"quotes":[]}'
        timestamp = "1700000000"
        signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        request = SimpleNamespace(headers={"X-Pricing-Worker-Timestamp": timestamp, "X-Pricing-Worker-Signature": signature})
        client = MagicMock()
        client.set = AsyncMock(return_value=True)
        with patch("app.routers.pricing_worker.time.time", return_value=1_700_000_000), patch(
            "app.routers.pricing_worker.settings.pricing_worker_shared_secret", secret
        ), patch("app.routers.pricing_worker.pricing_redis.client", return_value=client):
            await _authenticate(request, body)
        client.set.assert_awaited_once_with(f"pricing:worker:replay:{signature}", "1", ex=300, nx=True)

    async def test_bad_signature_never_touches_replay_store(self) -> None:
        request = SimpleNamespace(headers={"X-Pricing-Worker-Timestamp": "1700000000", "X-Pricing-Worker-Signature": "bad"})
        with patch("app.routers.pricing_worker.time.time", return_value=1_700_000_000), patch(
            "app.routers.pricing_worker.settings.pricing_worker_shared_secret", "x" * 48
        ), patch("app.routers.pricing_worker.pricing_redis.client") as client:
            with self.assertRaises(HTTPException) as raised:
                await _authenticate(request, b"{}")
        self.assertEqual(raised.exception.status_code, 401)
        client.assert_not_called()
