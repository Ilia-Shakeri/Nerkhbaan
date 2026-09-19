from __future__ import annotations

import os
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.derived import DerivedPriceEngine, DerivedPriceUnavailable
from app.pricing.instruments import get_instrument
from app.pricing.models import CanonicalQuote, CanonicalStatus
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.registry import PROVIDERS
from app.pricing.service import InstrumentPricingService

NOW = datetime(2026, 9, 19, 10, 30, tzinfo=UTC)


def snapshot(instrument: str, summary: dict) -> CanonicalQuote:
    return CanonicalQuote.create(
        instrument_id=instrument, price=Decimal("20000000"),
        status=CanonicalStatus.LIVE, primary_quote_id=1, verification_quote_ids=[],
        source_summary=summary, observed_at=NOW, canonical_at=NOW,
        valid_until=NOW + timedelta(minutes=1), stale_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=3), is_persisted=True, decision_reason="test",
    )


class BitpinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ParserContext(instrument=get_instrument("USDT_TOMAN"), received_at=NOW,
                                     maximum_timestamp_age_seconds=60)
        self.parser = build_parser("bitpin_usdt_toman_v1")
        self.payload = [{"code": "USDT_IRT", "price": "1", "price_info": {"price": "2"},
                         "order_book_info": {"price": "229128", "time": NOW.isoformat()}}]

    def test_reads_exchange_field_without_rial_or_usdt_conversion(self) -> None:
        result = self.parser.parse(self.payload, self.context)
        self.assertEqual(result.price, Decimal("229128"))
        self.assertEqual(result.observed_at, NOW)
        self.assertEqual(result.metadata["conversion_factor"], "1")

    def test_rejects_missing_duplicate_wrong_symbol_or_invalid_price(self) -> None:
        for name in ("missing", "duplicate", "symbol", "timestamp", "stale", "zero", "nan"):
            payload = deepcopy(self.payload)
            if name == "missing": payload = []
            if name == "duplicate": payload *= 2
            if name == "symbol": payload[0]["code"] = "USDT_USD"
            if name == "timestamp": payload[0]["order_book_info"]["time"] = None
            if name == "stale": payload[0]["order_book_info"]["time"] = (NOW - timedelta(minutes=5)).isoformat()
            if name == "zero": payload[0]["order_book_info"]["price"] = "0"
            if name == "nan": payload[0]["order_book_info"]["price"] = "NaN"
            with self.subTest(name=name), self.assertRaises(ParserError):
                self.parser.parse(payload, self.context)

    def test_btc_quote_is_separate_and_mismatched_context_rejected(self) -> None:
        parser = build_parser("bitpin_btc_toman_v1")
        context = ParserContext(instrument=get_instrument("BTC_TOMAN"), received_at=NOW,
                                maximum_timestamp_age_seconds=60)
        result = parser.parse([{"code": "BTC_IRT", "order_book_info": {
            "price": "18636058882", "time": NOW.isoformat()}}], context)
        self.assertEqual(result.price, Decimal("18636058882"))
        with self.assertRaises(ParserError):
            parser.parse(self.payload, self.context)

    def test_bounded_free_providers_registered(self) -> None:
        for provider_id in ("bitpin_usdt_toman", "bitpin_btc_toman"):
            definition = PROVIDERS[provider_id]
            self.assertTrue(definition.enabled)
            self.assertIsNone(definition.api_key_setting)
            self.assertEqual(definition.maximum_payload_bytes, 1048576)
            self.assertGreaterEqual(definition.budget.minimum_interval_seconds, 20)

    def test_new_hosts_join_an_old_operator_allowlist(self) -> None:
        from app.config import Settings

        settings = Settings(_env_file=None, pricing_provider_allowed_hosts="api.nobitex.ir")
        hosts = settings.pricing_provider_allowed_hosts.split(",")
        self.assertIn("api.bitpin.org", hosts)
        self.assertIn("api.wallgold.ir", hosts)
        self.assertIn("apiv2.nobitex.ir", hosts)


class DirectGoldTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_formula_even_with_fresh_inputs(self) -> None:
        for instrument in ("GOLD_18K_TOMAN_GRAM", "GOLD_24K_TOMAN_GRAM"):
            self.assertFalse(get_instrument(instrument).allow_derived_fallback)
            with self.assertRaises(DerivedPriceUnavailable):
                DerivedPriceEngine().derive(instrument, {
                    "GOLD_24K_TOMAN_GRAM": snapshot("GOLD_24K_TOMAN_GRAM", {}),
                    "XAU_USD_OZ": snapshot("XAU_USD_OZ", {}),
                    "USD_TOMAN": snapshot("USD_TOMAN", {}),
                }, now=NOW)

    async def test_cache_and_database_never_revive_calculated_or_ambiguous_gold(self) -> None:
        instrument = "GOLD_24K_TOMAN_GRAM"
        for summary in ({"derived": True}, {"primary_provider_id": "derived:gold"},
                        {"primary_provider_id": "persian_toolbox_gold24"}):
            old = snapshot(instrument, summary)
            store = AsyncMock()
            history = AsyncMock()
            store.get_canonical.return_value = old
            history.latest_canonical.return_value = old
            store.get_all_canonical.return_value = {instrument: old}
            history.latest_all.return_value = {instrument: old}
            service = InstrumentPricingService(store=store, history=history)
            self.assertIsNone(await service.get_canonical(instrument))
            self.assertNotIn(instrument, await service.get_all_canonical())
            direct = snapshot(instrument, {"primary_provider_id": "tala_gold24_toman"})
            history.latest_canonical.return_value = direct
            history.latest_all.return_value = {instrument: direct}
            self.assertEqual(await service.get_canonical(instrument), direct)
            self.assertEqual((await service.get_all_canonical())[instrument], direct)

    async def test_gold_preserves_direct_telegram_source_pipeline(self) -> None:
        repository = AsyncMock()
        repository.latest.return_value = []
        service = InstrumentPricingService(telegram_quotes=repository)
        for instrument in ("GOLD_18K_TOMAN_GRAM", "GOLD_24K_TOMAN_GRAM"):
            self.assertIsNone(await service._try_telegram_fallback(get_instrument(instrument), None))
        self.assertEqual(repository.latest.await_count, 2)


class WallgoldTests(unittest.TestCase):
    def test_each_purity_reads_its_own_price(self) -> None:
        for asset, symbol, instrument, price in (
            ("gold18", "GLD_18C_750TMN", "GOLD_18K_TOMAN_GRAM", "23872000"),
            ("silver925", "SLV_925TMN", "SILVER_925_TOMAN_GRAM", "468000"),
        ):
            parser = build_parser(f"wallgold_{asset}_v1")
            context = ParserContext(get_instrument(instrument), NOW, 60)
            row = {"symbol": symbol, "baseAsset": symbol[:-3], "quoteAsset": "TMN",
                   "IsEnableBuySide": True, "IsEnableSellSide": True,
                   "buyStatus": "enable", "sellStatus": "enable",
                   "marketCap": {"symbol": symbol, "lastPrice": price}}
            payload = {"success": True, "result": [row]}
            result = parser.parse(payload, context)
            self.assertEqual(result.price, Decimal(price))
            self.assertEqual(result.purity, get_instrument(instrument).purity)
            self.assertFalse(result.metadata["provider_timestamp_available"])
            for key, value in (("quoteAsset", "RLS"), ("baseAsset", "GLD_24C_999"),
                               ("IsEnableBuySide", False), ("sellStatus", "disable")):
                bad = deepcopy(payload)
                bad["result"][0][key] = value
                with self.subTest(key=key), self.assertRaises(ParserError):
                    parser.parse(bad, context)
            with self.assertRaises(ParserError):
                parser.parse({"success": True, "result": [row, row]}, context)
            with self.assertRaises(ParserError):
                parser.parse(payload, ParserContext(get_instrument("GOLD_24K_TOMAN_GRAM"), NOW, 60))

    def test_nobitex_irt_book_levels_are_rial_not_toman(self) -> None:
        for symbol, instrument, bid, ask in (
            ("USDTIRT", "USDT_TOMAN", "2290330", "2290770"),
            ("BTCIRT", "BTC_TOMAN", "185000000030", "185410000000"),
        ):
            asset = "usdt" if symbol == "USDTIRT" else "btc"
            result = build_parser(f"nobitex_orderbook_{asset}irt_v1").parse(
                {symbol: {"lastUpdate": int(NOW.timestamp() * 1000),
                          "bids": [[bid, "1"]], "asks": [[ask, "1"]]}},
                ParserContext(get_instrument(instrument), NOW, 60))
            self.assertEqual(result.bid, Decimal(bid) / 10)
            self.assertEqual(result.ask, Decimal(ask) / 10)
            self.assertEqual(result.price, (Decimal(bid) + Decimal(ask)) / 20)
