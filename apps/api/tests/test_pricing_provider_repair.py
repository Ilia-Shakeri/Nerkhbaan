from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.derived import derived_price_engine
from app.pricing.backfill import PricingBackfillQueue, _history_request_options
from app.pricing.instruments import INSTRUMENTS
from app.pricing.models import (
    CanonicalQuote,
    CanonicalStatus,
    ProviderRole,
    SourceSemantic,
    SourceType,
)
from app.pricing.operational import OperationalPricingSettings
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.parsers.history import build_history_parser
from app.pricing.registry import PROVIDERS, PROVIDERS_BY_INSTRUMENT


def _context(instrument_id: str) -> ParserContext:
    return ParserContext(
        instrument=INSTRUMENTS[instrument_id],
        received_at=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
        maximum_timestamp_age_seconds=3600,
    )


def _canonical(instrument_id: str, price: str, provenance: list[str] | None = None) -> CanonicalQuote:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    return CanonicalQuote.create(
        instrument_id=instrument_id,
        price=Decimal(price),
        status=CanonicalStatus.LIVE,
        primary_quote_id=1,
        verification_quote_ids=[],
        source_summary={
            "derived": False,
            "derivation_depth": 0,
            "confidence_score": "1",
            "provenance": provenance or [instrument_id],
        },
        observed_at=now,
        canonical_at=now,
        valid_until=now.replace(hour=12, minute=5),
        stale_at=now.replace(hour=12, minute=10),
        expires_at=now.replace(hour=12, minute=15),
        is_persisted=True,
        decision_reason="test",
    )


class PricingProviderRepairTests(unittest.TestCase):
    def test_catalogue_covers_every_published_chain(self) -> None:
        # A count assertion only proves the number did not change; assert the
        # instruments the product actually publishes are present.
        for instrument_id in (
            "GOLD_18K_TOMAN_GRAM",
            "GOLD_24K_TOMAN_GRAM",
            "SILVER_999_TOMAN_GRAM",
            "SILVER_925_TOMAN_GRAM",
            "XAU_USD_OZ",
            "XAG_USD_OZ",
            "USD_TOMAN",
            "USDT_TOMAN",
            "USDT_USD",
            "BTC_TOMAN",
            "BTC_USD",
        ):
            self.assertIn(instrument_id, INSTRUMENTS)

    def test_every_instrument_can_produce_a_price(self) -> None:
        """No instrument may be published with neither a source nor a formula.

        Silver in Toman shipped with zero providers and no way to notice.
        """
        from app.config import settings
        from app.pricing.registry import instrument_source_coverage

        unservable = [
            instrument_id
            for instrument_id, row in instrument_source_coverage(settings).items()
            if row["unservable"]
        ]
        self.assertEqual(unservable, [])

    def test_every_instrument_is_refreshed(self) -> None:
        from app.pricing.service import _REFRESH_ORDER

        self.assertEqual(set(_REFRESH_ORDER), set(INSTRUMENTS))

    def test_every_provider_host_is_allowlisted(self) -> None:
        """A provider whose host is not allowlisted can never succeed."""
        from urllib.parse import urlparse

        from app.config import settings

        allowed = {
            item.strip().lower()
            for item in settings.pricing_provider_allowed_hosts.split(",")
            if item.strip()
        }
        for provider in PROVIDERS.values():
            host = (urlparse(provider.url).hostname or "").lower()
            self.assertIn(host, allowed, f"{provider.provider_id} host {host}")

    def test_every_provider_parser_is_registered(self) -> None:
        from app.pricing.parsers import build_parser

        for provider in PROVIDERS.values():
            build_parser(provider.parser_id)

    def test_coincap_is_disabled_and_not_primary(self) -> None:
        self.assertFalse(PROVIDERS["coincap_btc"].enabled)
        self.assertFalse(PROVIDERS["coincap_usdt"].enabled)
        btc_primary_ids = [
            provider.provider_id
            for provider in PROVIDERS_BY_INSTRUMENT["BTC_USD"]
            if provider.role.value == "primary"
        ]
        self.assertEqual(btc_primary_ids, ["coinbase_btc_usd"])

    def test_persian_toolbox_btc_is_enabled_but_reference_usd_stays_disabled(self) -> None:
        btc = PROVIDERS["persian_toolbox_btc"]
        self.assertTrue(btc.enabled)
        self.assertEqual(btc.maximum_source_age_seconds, 300)
        self.assertTrue(btc.anchor_live_window_at_receive_time)
        self.assertFalse(PROVIDERS["persian_toolbox_usd_toman"].enabled)

    def test_gold_24k_derivation_uses_decimal_metadata(self) -> None:
        quote = derived_price_engine.derive(
            "GOLD_24K_TOMAN_GRAM",
            {
                "XAU_USD_OZ": _canonical("XAU_USD_OZ", "2400"),
                "USDT_TOMAN": _canonical("USDT_TOMAN", "60000"),
                "USDT_USD": _canonical("USDT_USD", "1.00"),
            },
            now=datetime(2026, 8, 8, 12, 1, tzinfo=UTC),
        )

        expected = Decimal("2400") * Decimal("60000") / Decimal("31.1034768")
        self.assertEqual(quote.price, expected)
        self.assertIsInstance(quote.metadata["inputs"][0]["price"], str)
        self.assertEqual(quote.source_type, SourceType.DERIVED)
        self.assertEqual(quote.source_semantic, SourceSemantic.DERIVED)

    def test_usdt_depeg_blocks_toman_derivation(self) -> None:
        with self.assertRaisesRegex(Exception, "safe range"):
            derived_price_engine.derive(
                "BTC_TOMAN",
                {
                    "BTC_USD": _canonical("BTC_USD", "100000"),
                    "USDT_TOMAN": _canonical("USDT_TOMAN", "60000"),
                    "USDT_USD": _canonical("USDT_USD", "0.80"),
                },
                now=datetime(2026, 8, 8, 12, 1, tzinfo=UTC),
            )

    def test_wallex_and_tala_parsers_accept_contract_shapes(self) -> None:
        wallex = build_parser("wallex_usdt_toman_v1").parse(
            {"result": {"symbols": [{"symbol": "USDTTMN", "lastPrice": "60000", "updatedAt": "2026-08-08T12:00:00Z"}]}},
            _context("USDT_TOMAN"),
        )
        tala = build_parser("tala_gold24_toman_v1").parse(
            {"data": [{"key": "geram24k", "value": "8000000", "unit": "تومان", "status": "active", "updated_at": "2026-08-08T12:00:00Z"}]},
            _context("GOLD_24K_TOMAN_GRAM"),
        )

        self.assertEqual(wallex.price, Decimal("60000"))
        self.assertEqual(tala.price, Decimal("8000000"))

    def test_persian_toolbox_parses_btc_and_reference_usd_with_explicit_units(self) -> None:
        timestamp = int(self._provider_time().timestamp() * 1000)
        payload = {
            "ok": True,
            "data": {
                "timestamp": timestamp,
                "currencies": {
                    "USD": {"code": "USD", "rate": 1},
                    "IRR": {"code": "IRR", "rate": 1420000},
                },
                "crypto": {"BTC": {"symbol": "BTC", "priceUSD": 77000}},
                "units": {
                    "currencyBase": "USD",
                    "iranCurrency": "IRR",
                    "cryptoPrice": "USD",
                },
                "sources": ["exchange-reference", "crypto-reference"],
                "freshness": "cached",
            },
        }

        btc = build_parser("persian_toolbox_btc_usd_v1").parse(
            payload, _context("BTC_USD")
        )
        usd = build_parser("persian_toolbox_usd_toman_v1").parse(
            payload, _context("USD_TOMAN")
        )

        self.assertEqual(btc.price, Decimal("77000"))
        self.assertEqual(usd.price, Decimal("142000"))
        self.assertEqual(usd.metadata["normalization"], "rial_to_toman")

    def test_persian_toolbox_rejects_stale_payload_and_wrong_unit(self) -> None:
        timestamp = int(self._provider_time().timestamp() * 1000)
        base = {
            "ok": True,
            "data": {
                "timestamp": timestamp,
                "crypto": {"BTC": {"symbol": "BTC", "priceUSD": 77000}},
                "units": {"cryptoPrice": "USD"},
                "sources": ["crypto-reference"],
                "freshness": "stale",
            },
        }
        with self.assertRaisesRegex(ParserError, "not fresh"):
            build_parser("persian_toolbox_btc_usd_v1").parse(
                base, _context("BTC_USD")
            )
        base["data"]["freshness"] = "live"
        base["data"]["units"]["cryptoPrice"] = "EUR"
        with self.assertRaisesRegex(ParserError, "must be USD"):
            build_parser("persian_toolbox_btc_usd_v1").parse(
                base, _context("BTC_USD")
            )

    def test_servix_history_parses_usd_and_rial_units(self) -> None:
        start = datetime(2026, 8, 1, tzinfo=UTC)
        end = datetime(2026, 8, 3, tzinfo=UTC)
        btc = build_history_parser("servix_btc_usd_history_v1").parse(
            [
                {
                    "code": "BTC_USD",
                    "quoteUnit": "USD",
                    "value": "77000",
                    "businessTime": "2026-08-02T00:00:00Z",
                }
            ],
            INSTRUMENTS["BTC_USD"],
            start,
            end,
        )
        usd = build_history_parser("servix_usd_rls_history_v1").parse(
            [
                {
                    "code": "USD_RLS",
                    "quoteUnit": "RLS",
                    "value": "1420000",
                    "businessTime": "2026-08-02T00:00:00Z",
                }
            ],
            INSTRUMENTS["USD_TOMAN"],
            start,
            end,
        )

        self.assertEqual(btc[0].price, Decimal("77000"))
        self.assertEqual(usd[0].price, Decimal("142000"))

    def test_servix_history_rejects_wrong_symbol_or_unit(self) -> None:
        parser = build_history_parser("servix_btc_usd_history_v1")
        start = datetime(2026, 8, 1, tzinfo=UTC)
        end = datetime(2026, 8, 3, tzinfo=UTC)
        with self.assertRaises(ParserError):
            parser.parse(
                [
                    {
                        "code": "ETH_USD",
                        "quoteUnit": "EUR",
                        "value": "3000",
                        "businessTime": "2026-08-02T00:00:00Z",
                    }
                ],
                INSTRUMENTS["BTC_USD"],
                start,
                end,
            )

    def test_servix_history_request_uses_bounded_dates_and_secret_header(self) -> None:
        provider = PROVIDERS["servix_btc_usd"]
        parser = build_history_parser("servix_btc_usd_history_v1")
        with patch("app.pricing.backfill.settings.servix_api_key", "test-key"):
            params, headers = _history_request_options(
                provider,
                parser,
                datetime(2026, 8, 1, 12, tzinfo=UTC),
                datetime(2026, 8, 3, 12, tzinfo=UTC),
            )

        self.assertEqual(params, {"from": "2026-08-01", "to": "2026-08-03"})
        self.assertEqual(headers, {"X-API-Key": "test-key"})
        self.assertFalse(provider.history_requires_live_quote)
        self.assertTrue(PROVIDERS["coingecko_btc"].history_requires_live_quote)

    def test_servix_history_can_run_when_live_quote_is_missing(self) -> None:
        providers = (
            PROVIDERS["coingecko_btc"],
            replace(PROVIDERS["servix_btc_usd"], enabled=True),
        )
        operational = AsyncMock()
        operational.providers_for.return_value = providers
        queue = PricingBackfillQueue(operational=operational)
        with patch("app.pricing.backfill.settings.servix_api_key", "test-key"):
            selected = asyncio.run(
                queue._history_provider("BTC_USD", independent_of_live=True)
            )

        self.assertEqual(selected.provider_id, "servix_btc_usd")

    @staticmethod
    def _provider_time() -> datetime:
        return datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

    def test_unknown_unit_rejected(self) -> None:
        with self.assertRaises(ParserError):
            build_parser("tala_usdt_toman_v1").parse(
                {"data": [{"key": "usdt_irt", "value": "60000", "unit": "mystery", "status": "active"}]},
                _context("USDT_TOMAN"),
            )

    def test_navasan_requires_operator_security_gate(self) -> None:
        provider = PROVIDERS["navasan_usdt"]
        self.assertFalse(provider.enabled)
        self.assertFalse(provider.configured(__import__("app.config").config.settings))

    def test_quarantined_routes_stay_disabled_when_database_rows_are_enabled(self) -> None:
        for provider_id in (
            "tetherland_btc",
            "wallex_usdt_toman",
            "wallex_btc_toman",
        ):
            self.assertFalse(PROVIDERS[provider_id].enabled)

        row = {
            "provider_id": "tetherland_btc",
            "role": ProviderRole.FALLBACK.value,
            "priority": 3,
            "trust_score": "0.84",
            "provider_enabled": True,
            "config_enabled": True,
            "operational_ttl_seconds": 60,
            "requests_per_minute": 6,
            "requests_per_hour": 120,
            "requests_per_day": 1500,
            "reserved_anomaly_requests": 0,
            "reserved_fallback_requests": 0,
            "minimum_interval_seconds": 60,
            "cooldown_after_429_seconds": 300,
            "estimated_request_cost": "1",
        }
        with patch(
            "app.pricing.operational.asyncio.to_thread",
            new=AsyncMock(return_value=[row]),
        ):
            providers = asyncio.run(
                OperationalPricingSettings().providers_for("BTC_TOMAN")
            )

        resolved = next(item for item in providers if item.provider_id == "tetherland_btc")
        self.assertFalse(resolved.enabled)


if __name__ == "__main__":
    unittest.main()
