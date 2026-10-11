from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.models import PersistenceStatus, ProviderRole
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.persistence import PersistenceResult
from app.pricing.registry import PROVIDERS
from app.pricing.service import InstrumentPricingService
from app.routers.pricing_worker import _WORKER_ROUTES

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


class _Locks:
    @asynccontextmanager
    async def refresh_lock(self, *_args):
        yield object()


class GoldSourceContractTests(unittest.TestCase):
    def test_gold_feed_exact_spot_pair_and_explicit_usd_timestamp(self):
        self.assertEqual(_WORKER_ROUTES["gold_api_free_xau"], "XAU_USD_OZ")
        parser = build_parser("gold_api_free_xau_v1")
        context = ParserContext(get_instrument("XAU_USD_OZ"), NOW, 600)
        parsed = parser.parse({"symbol": "XAU", "currency": "USD", "price": 4000,
                               "updatedAt": (NOW-timedelta(seconds=20)).isoformat()}, context)
        self.assertEqual(parsed.currency.value, "USD")
        self.assertEqual(parsed.weight_unit.value, "troy_ounce")
        self.assertEqual(parsed.observed_at, NOW-timedelta(seconds=20))

    def test_ambiguous_currency_or_timestamp_never_becomes_usd(self):
        parser = build_parser("gold_api_free_xau_v1")
        context = ParserContext(get_instrument("XAU_USD_OZ"), NOW, 600)
        for wrong in ({"currency": "EUR"}, {"currency": None}, {"symbol": "XAG"}, {"updatedAt": None}):
            with self.assertRaises(ParserError):
                parser.parse({"symbol": "XAU", "currency": "USD", "price": 4000,
                              "updatedAt": NOW.isoformat(), **wrong}, context)


class GoldFallbackIngestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = PROVIDERS["gold_api_free_xau"]
        self.operational, self.persistence, self.store = AsyncMock(), AsyncMock(), AsyncMock()
        self.operational.instrument.return_value = get_instrument("XAU_USD_OZ")
        self.operational.providers_for.return_value = (self.provider,)
        self.store.ping.return_value = True
        self.service = InstrumentPricingService(store=self.store, operational=self.operational,
                                                persistence=self.persistence, locks=_Locks())
        self.service.get_canonical = AsyncMock(return_value=None)
        self.service._assess_candidate = AsyncMock(return_value=None)
        self.service._attach_changes = AsyncMock()
        self.service._commit = AsyncMock()
        async def persist(quote):
            quote.id = 1
            quote.persistence_status = PersistenceStatus.PERSISTED
            return PersistenceResult(True, False, None, None)
        self.persistence.persist_provider_quote.side_effect = persist
        self.args = dict(instrument_id="XAU_USD_OZ", provider_id="gold_api_free_xau",
                         price=Decimal("4000"), observed_at=NOW-timedelta(seconds=20), historical=False)

    async def test_verified_fallback_preserves_source_time_and_reference_semantic(self):
        self.assertEqual(self.provider.role, ProviderRole.FALLBACK)
        with patch("app.pricing.service.utc_now", return_value=NOW):
            self.assertEqual(await self.service.ingest_worker_quote(**self.args), "accepted")
        quote = self.persistence.persist_provider_quote.call_args.args[0]
        self.assertEqual(quote.observed_at, self.args["observed_at"])
        self.assertEqual(quote.source_semantic.value, "reference_rate")
        self.assertFalse(quote.is_derived)
        self.assertEqual(quote.currency.value, "USD")
        self.assertEqual(quote.weight_unit.value, "troy_ounce")
        self.service._assess_candidate.assert_awaited_once()

    async def test_existing_verifier_policy_is_honored_not_promoted(self):
        self.operational.providers_for.return_value = (replace(self.provider, role=ProviderRole.VERIFIER),)
        with patch("app.pricing.service.utc_now", return_value=NOW):
            self.assertEqual(await self.service.ingest_worker_quote(**self.args), "ignored_role")
        self.persistence.persist_provider_quote.assert_not_called()
        self.service._commit.assert_not_called()

    async def test_disabled_provider_never_publishes(self):
        self.operational.providers_for.return_value = (replace(self.provider, enabled=False),)
        with patch("app.pricing.service.utc_now", return_value=NOW):
            self.assertEqual(await self.service.ingest_worker_quote(**self.args), "ignored_disabled")
        self.persistence.persist_provider_quote.assert_not_called()

    async def test_gold_karat_substitution_and_history_are_rejected(self):
        for wrong in ({"instrument_id": "GOLD_24K_TOMAN_GRAM"}, {"historical": True}):
            with patch("app.pricing.service.utc_now", return_value=NOW):
                with self.assertRaises(ValueError):
                    await self.service.ingest_worker_quote(**{**self.args, **wrong})
        self.persistence.persist_provider_quote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
