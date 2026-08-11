from __future__ import annotations

import os
import unittest
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlparse
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")
os.environ["DEBUG"] = "false"

from app.pricing.contracts import PENDING_PROVIDER_CANDIDATES, provider_contract_inventory
from app.pricing.health import PricingHealthService
from app.pricing.instruments import INSTRUMENTS
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import PROVIDERS


class ProviderContractInventoryTests(unittest.TestCase):
    def test_every_provider_has_contract_inventory(self) -> None:
        inventory = provider_contract_inventory()

        self.assertEqual(set(inventory["providers"]), set(PROVIDERS))
        for row in inventory["providers"].values():
            self.assertEqual(row["owner"], "pricing-ops")
            self.assertIn("unit_contract", row)
            self.assertIn("license_or_operator_rights_confirmed", row["enabled_acceptance"])

    def test_pending_providers_do_not_enter_active_pricing_domain(self) -> None:
        self.assertIn("BRSAPI/TSETMC equities and funds", PENDING_PROVIDER_CANDIDATES)
        self.assertNotIn("TSETMC", " ".join(INSTRUMENTS))
        inventory = provider_contract_inventory()
        self.assertFalse(
            inventory["separate_domains"]["tsetmc_equities_and_funds"][
                "current_pricing_instruments_allowed"
            ]
        )

    def test_no_provider_url_contains_path_or_query_credentials(self) -> None:
        for provider in PROVIDERS.values():
            parsed = urlparse(provider.url)
            self.assertFalse(parsed.username or parsed.password)
            lowered = parsed.query.lower()
            self.assertNotIn("api_key=", lowered)
            self.assertNotIn("token=", lowered)
            self.assertNotIn("password=", lowered)

    def test_url_secret_guard_rejects_credentials(self) -> None:
        provider = next(iter(PROVIDERS.values()))
        bad_provider = type(provider)(
            **{
                **{
                    field: getattr(provider, field)
                    for field in provider.__dataclass_fields__
                },
                "url": "https://example.com/latest?api_key=secret",
            }
        )

        with self.assertRaises(ProviderCallFailure):
            ProviderQuoteCollector._validate_destination(bad_provider)

    def test_cleartext_key_transport_is_always_blocked(self) -> None:
        provider = PROVIDERS["navasan_usdt"]

        with patch.object(
            __import__("app.pricing.providers", fromlist=["settings"]).settings,
            "navasan_api_key",
            "test-key",
        ):
            with self.assertRaises(ProviderCallFailure) as raised:
                __import__("asyncio").run(
                    ProviderQuoteCollector()._request_payload(SimpleNamespace(), provider)
                )

        self.assertEqual(raised.exception.code, "insecure_http_blocked")

    def test_canaries_are_sanitized_and_owned(self) -> None:
        canaries = PricingHealthService().provider_canaries()

        self.assertTrue(canaries)
        for row in canaries:
            self.assertIn("provider_id", row)
            self.assertIn("owner", row)
            self.assertNotIn("api_key", str(row).lower())
            self.assertIn(
                row["status"],
                {
                    "provider_disabled",
                    "not_configured",
                    "rights_review_required",
                    "eligible_for_live_canary",
                },
            )


class _StreamResponse:
    def __init__(
        self, status_code: int, payload: bytes = b"{}", headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = {"content-type": "application/json", **(headers or {})}

    async def __aenter__(self) -> "_StreamResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def aiter_bytes(self):
        yield self.payload


class _StreamClient:
    def __init__(self, responses: list[_StreamResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def stream(self, *_args: object, **_kwargs: object) -> _StreamResponse:
        response = self.responses[self.calls]
        self.calls += 1
        return response


class ProviderRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_fault_retries_then_returns_payload(self) -> None:
        provider = PROVIDERS["coinbase_btc_usd"]
        client = _StreamClient(
            [_StreamResponse(503), _StreamResponse(200, b'{"price":"100"}')]
        )
        provider_settings = __import__("app.pricing.providers", fromlist=["settings"]).settings

        with patch.object(provider_settings, "pricing_provider_max_retries", 1), patch.object(
            provider_settings, "pricing_provider_backoff_base_seconds", Decimal("0")
        ):
            payload, _content_type, status_code = await ProviderQuoteCollector()._request_payload(
                client, provider
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload, {"price": "100"})
        self.assertEqual(client.calls, 2)

    async def test_auth_fault_does_not_retry(self) -> None:
        provider = PROVIDERS["coinbase_btc_usd"]
        client = _StreamClient([_StreamResponse(401)])
        provider_settings = __import__("app.pricing.providers", fromlist=["settings"]).settings

        with patch.object(provider_settings, "pricing_provider_max_retries", 2):
            with self.assertRaises(ProviderCallFailure) as raised:
                await ProviderQuoteCollector()._request_payload(client, provider)

        self.assertEqual(raised.exception.code, "http_error")
        self.assertEqual(client.calls, 1)

    async def test_rate_limit_does_not_retry(self) -> None:
        provider = PROVIDERS["coinbase_btc_usd"]
        client = _StreamClient([_StreamResponse(429, headers={"retry-after": "30"})])
        provider_settings = __import__("app.pricing.providers", fromlist=["settings"]).settings

        with patch.object(provider_settings, "pricing_provider_max_retries", 2):
            with self.assertRaises(ProviderCallFailure) as raised:
                await ProviderQuoteCollector()._request_payload(client, provider)

        self.assertEqual(raised.exception.code, "rate_limited")
        self.assertEqual(raised.exception.retry_after_seconds, 30)
        self.assertEqual(client.calls, 1)


if __name__ == "__main__":
    unittest.main()
