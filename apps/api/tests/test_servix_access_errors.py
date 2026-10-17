from __future__ import annotations

import os
import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.budgets import BudgetDecision
from app.pricing.models import ProviderRuntimeState, RequestPurpose
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import RETIRED_PROVIDERS


class ServixAccessErrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.provider = RETIRED_PROVIDERS["servix_btc_usd"]
        self.payload = {"status": 403, "code": "EMAIL_VERIFICATION_REQUIRED",
                        "message": "Verify private-account@example.test using secret-value",
                        "email": "private-account@example.test", "requestId": "private-request-id"}
        self.key = patch("app.pricing.providers.settings.servix_api_key", "test-private-key")
        self.allowed = patch("app.pricing.providers.rights.provider_allowed", return_value=True)
        self.endpoint = patch("app.pricing.providers.rights.endpoint_allowed", return_value=True)
        for mocked in (self.key, self.allowed, self.endpoint):
            mocked.start()
            self.addCleanup(mocked.stop)

    async def request_failure(self, provider=None, payload=None, status=403):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(status, json=self.payload if payload is None else payload)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch("app.pricing.providers.settings.pricing_provider_max_retries", 3):
                with self.assertRaises(ProviderCallFailure) as raised:
                    await ProviderQuoteCollector()._request_payload(client, provider or self.provider)
        return raised.exception, calls

    async def test_exact_account_verification_error_is_actionable_and_not_retried(self):
        failure, calls = await self.request_failure()
        self.assertEqual(failure.code, "email_verification_required")
        self.assertEqual(failure.http_status, 403)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].headers["X-API-Key"], "test-private-key")
        self.assertNotIn("authorization", calls[0].headers)
        self.assertEqual(failure.payload, {"status": 403, "code": "EMAIL_VERIFICATION_REQUIRED"})
        self.assertNotIn("private-account", str(failure))
        self.assertNotIn("secret-value", str(failure.payload))

    async def test_unrelated_403_keeps_generic_classification(self):
        for payload in ({"code": "ACCESS_DENIED"}, {"code": "email_verification_required"},
                        {"message": "EMAIL_VERIFICATION_REQUIRED"}, {"code": ["EMAIL_VERIFICATION_REQUIRED"]}):
            with self.subTest(payload=payload):
                failure, calls = await self.request_failure(payload=payload)
                self.assertEqual(failure.code, "http_error")
                self.assertEqual(len(calls), 1)

    async def test_other_family_does_not_trust_servix_error_code(self):
        failure, calls = await self.request_failure(provider=replace(self.provider, source_family="another_family"))
        self.assertEqual(failure.code, "http_error")
        self.assertEqual(len(calls), 1)

    async def test_verification_marker_on_different_status_is_not_reclassified(self):
        failure, calls = await self.request_failure(status=401)
        self.assertEqual(failure.code, "http_error")
        self.assertEqual(len(calls), 1)

    async def test_known_denial_remains_sanitized_in_runtime_and_rejection(self):
        store, persistence, budgets = AsyncMock(), AsyncMock(), AsyncMock()
        budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        persistence.store_raw_payload.return_value = "owned-rejection-proof"
        collector = ProviderQuoteCollector(store=store, persistence=persistence, budgets=budgets)
        runtime = ProviderRuntimeState(self.provider.provider_id, self.provider.instrument_id)
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json=self.payload))) as client:
            result = await collector._call_and_parse(
                self.provider, RequestPurpose.FALLBACK, runtime, client,
                get_instrument(self.provider.instrument_id))
        self.assertEqual(result.failure_reason, "email_verification_required")
        self.assertFalse(result.usable)
        self.assertIsNone(result.quote.price)
        self.assertEqual(result.quote.rejection_reason, "email_verification_required")
        self.assertEqual(result.quote.validation_status.value, "rejected")
        self.assertEqual(runtime.last_error_code, "email_verification_required")
        self.assertEqual(persistence.record_runtime_event.await_args.kwargs["sanitized_error"],
                         "email_verification_required")
        raw_record = persistence.store_raw_payload.await_args.kwargs["sanitized_text"]
        self.assertEqual(json.loads(raw_record), {"status": 403, "code": "EMAIL_VERIFICATION_REQUIRED"})
        self.assertNotIn("private-account", result.sanitized_payload)
        self.assertNotIn("private-request-id", result.sanitized_payload)
        self.assertNotIn("secret-value", result.sanitized_payload)
        persistence.persist_provider_quote.assert_awaited_once_with(result.quote)
        store.set_provider_quote.assert_not_awaited()

    async def test_missing_source_right_still_blocks_before_transport(self):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(403, json=self.payload)

        with patch("app.pricing.providers.rights.provider_allowed", return_value=False):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with self.assertRaises(ProviderCallFailure) as raised:
                    await ProviderQuoteCollector()._request_payload(client, self.provider)
        self.assertEqual(raised.exception.code, "provider_rights_denied")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
