from __future__ import annotations

import copy
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.models import Currency, SourceSemantic, WeightUnit
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.parsers.history import build_history_parser
from app.pricing.registry import PROVIDERS, RETIRED_PROVIDERS


RECEIVED = datetime(2026, 10, 17, 8, 23, 7, 347762, tzinfo=UTC)
# Captured by one public GET on 2026-10-17; tests never contact the provider.
PUBLIC_BTC = {
    "currency": "USD", "currencySymbol": "$", "exchangeRate": 1.0,
    "name": "Bitcoin", "price": 81627.648438, "symbol": "BTC",
    "updatedAt": "2026-10-17T08:22:42Z", "updatedAtReadable": "a few seconds ago",
}
LOCAL_QUOTES = (
    ("btc", "BTC_RLS", "BTC_TOMAN", "80000000000"),
    ("usdt", "USDT_RLS", "USDT_TOMAN", "1000000"),
)


def context(instrument_id="BTC_USD"):
    return ParserContext(get_instrument(instrument_id), RECEIVED, 120, 30)


def local_row(symbol, value):
    return {"code": symbol, "quoteUnit": "RLS", "value": value,
            "businessTime": RECEIVED.isoformat()}


class PublicBitcoinContractTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser("gold_api_free_btc_v1")

    def test_captured_public_response_replays_exact_usd_price_and_source_time(self):
        parsed = self.parser.parse(PUBLIC_BTC, context())
        self.assertEqual(parsed.price, Decimal("81627.648438"))
        self.assertEqual(parsed.currency, Currency.USD)
        self.assertEqual(parsed.weight_unit, WeightUnit.UNIT)
        self.assertIsNone(parsed.purity)
        self.assertEqual(parsed.observed_at, datetime(2026, 10, 17, 8, 22, 42, tzinfo=UTC))
        self.assertEqual(parsed.metadata["asset_symbol"], "BTC")

    def test_symbol_is_required_and_exact(self):
        for value in (None, "", "XAU", "USDT", "btc", True):
            with self.subTest(symbol=value), self.assertRaises(ParserError):
                self.parser.parse({**PUBLIC_BTC, "symbol": value}, context())
        payload = dict(PUBLIC_BTC)
        del payload["symbol"]
        with self.assertRaises(ParserError):
            self.parser.parse(payload, context())

    def test_currency_must_explicitly_be_usd(self):
        for value in (None, "", "USDT", "TOMAN", "usd", True):
            with self.subTest(currency=value), self.assertRaises(ParserError):
                self.parser.parse({**PUBLIC_BTC, "currency": value}, context())

    def test_cross_instrument_and_metal_contexts_are_rejected(self):
        for instrument_id in ("USDT_USD", "BTC_TOMAN", "XAU_USD_OZ"):
            with self.subTest(instrument=instrument_id), self.assertRaises(ParserError):
                self.parser.parse(PUBLIC_BTC, context(instrument_id))

    def test_btc_cannot_be_relabelled_with_ounce_or_purity(self):
        for instrument in (replace(get_instrument("BTC_USD"), weight_unit=WeightUnit.TROY_OUNCE),
                           replace(get_instrument("BTC_USD"), purity=Decimal("0.9999"))):
            with self.subTest(instrument=instrument), self.assertRaises(ParserError):
                self.parser.parse(PUBLIC_BTC, replace(context(), instrument=instrument))

    def test_source_time_is_required_aware_iso_text(self):
        for value in (None, "", "bad", True, 1792224000, "2026-10-17T08:22:42"):
            with self.subTest(timestamp=value), self.assertRaises(ParserError):
                self.parser.parse({**PUBLIC_BTC, "updatedAt": value}, context())

    def test_numeric_timestamp_does_not_replace_missing_documented_updated_at(self):
        payload = {key: value for key, value in PUBLIC_BTC.items() if key != "updatedAt"}
        payload["timestamp"] = RECEIVED.timestamp()
        with self.assertRaises(ParserError):
            self.parser.parse(payload, context())

    def test_old_and_future_prices_keep_existing_age_guards(self):
        for timestamp in (RECEIVED-timedelta(seconds=121), RECEIVED+timedelta(seconds=31)):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                self.parser.parse({**PUBLIC_BTC, "updatedAt": timestamp.isoformat()}, context())

    def test_nonpositive_nonfinite_and_out_of_bounds_prices_are_rejected(self):
        for price in (0, -1, True, "NaN", "Infinity", "1000001", None):
            with self.subTest(price=price), self.assertRaises(ParserError):
                self.parser.parse({**PUBLIC_BTC, "price": price}, context())

    def test_response_and_readable_age_are_not_mutated_or_used_as_source_time(self):
        payload = copy.deepcopy(PUBLIC_BTC)
        payload["updatedAtReadable"] = "now"
        before = copy.deepcopy(payload)
        self.assertEqual(self.parser.parse(payload, context()).observed_at,
                         datetime(2026, 10, 17, 8, 22, 42, tzinfo=UTC))
        self.assertEqual(payload, before)


class ServixLocalCryptoContractTests(unittest.TestCase):
    def test_current_rial_values_convert_once_to_toman(self):
        for name, symbol, instrument, value in LOCAL_QUOTES:
            with self.subTest(symbol=symbol):
                parsed = build_parser(f"servix_{name}_toman_v1").parse(
                    {"data": [local_row(symbol, value)]}, context(instrument))
                self.assertEqual(parsed.price, Decimal(value)*Decimal("0.1"))
                self.assertEqual(parsed.currency, Currency.TOMAN)
                self.assertEqual(parsed.weight_unit, WeightUnit.UNIT)
                self.assertIsNone(parsed.purity)
                self.assertEqual(parsed.observed_at, RECEIVED)
                self.assertEqual(parsed.metadata["conversion_factor"], "0.1")
                self.assertEqual(parsed.metadata["source_code"], symbol)

    def test_current_quotes_require_exact_rls_unit(self):
        for name, symbol, instrument, value in LOCAL_QUOTES:
            for unit in (None, "", "TOMAN", "IRR", "USD", "USDT"):
                with self.subTest(symbol=symbol, unit=unit), self.assertRaises(ParserError):
                    build_parser(f"servix_{name}_toman_v1").parse(
                        {**local_row(symbol, value), "quoteUnit": unit}, context(instrument))

    def test_current_quotes_reject_wrong_code_duplicate_and_context(self):
        for name, symbol, instrument, value in LOCAL_QUOTES:
            parser = build_parser(f"servix_{name}_toman_v1")
            row = local_row(symbol, value)
            for payload in ({**row, "code": "BTC_USD"}, [row, row]):
                with self.subTest(symbol=symbol, payload=payload), self.assertRaises(ParserError):
                    parser.parse(payload, context(instrument))
            with self.assertRaises(ParserError):
                parser.parse(row, context("USDT_USD"))

    def test_current_quotes_reject_missing_naive_stale_and_future_time(self):
        for name, symbol, instrument, value in LOCAL_QUOTES:
            for timestamp in (None, "", "2026-10-17T08:23:07", False,
                              (RECEIVED-timedelta(seconds=121)).isoformat(),
                              (RECEIVED+timedelta(seconds=31)).isoformat()):
                with self.subTest(symbol=symbol, timestamp=timestamp), self.assertRaises(ParserError):
                    build_parser(f"servix_{name}_toman_v1").parse(
                        {**local_row(symbol, value), "businessTime": timestamp}, context(instrument))

    def test_history_preserves_gaps_source_time_and_exact_normalisation(self):
        for name, symbol, instrument, value in LOCAL_QUOTES:
            rows = [local_row(symbol, value),
                    {**local_row(symbol, value), "businessTime": (RECEIVED-timedelta(days=3)).isoformat()}]
            with self.subTest(symbol=symbol):
                points = build_history_parser(f"servix_{name}_toman_history_v1").parse(
                    rows, get_instrument(instrument), RECEIVED-timedelta(days=4), RECEIVED)
                self.assertEqual([point.observed_at for point in points],
                                 [RECEIVED-timedelta(days=3), RECEIVED])
                self.assertTrue(all(point.price == Decimal(value)*Decimal("0.1") for point in points))
                self.assertTrue(all(point.volume is None for point in points))

    def test_history_rejects_code_unit_duplicate_and_time_contract_drift(self):
        for name, symbol, instrument, value in LOCAL_QUOTES:
            parser = build_history_parser(f"servix_{name}_toman_history_v1")
            row = local_row(symbol, value)
            for rows in ([{**row, "code": "BTC_USD"}], [{**row, "quoteUnit": "TOMAN"}],
                         [row, row], [{**row, "businessTime": None}],
                         [{**row, "businessTime": "2026-10-17T08:23:07"}]):
                with self.subTest(symbol=symbol, rows=rows), self.assertRaises(ParserError):
                    parser.parse(rows, get_instrument(instrument), RECEIVED-timedelta(days=1), RECEIVED)

    def test_history_rejects_cross_instrument_use(self):
        for name, symbol, _instrument, value in LOCAL_QUOTES:
            with self.subTest(symbol=symbol), self.assertRaises(ParserError):
                build_history_parser(f"servix_{name}_toman_history_v1").parse(
                    [local_row(symbol, value)], get_instrument("USDT_USD"), RECEIVED-timedelta(days=1), RECEIVED)


class ReplacementRegistryTests(unittest.TestCase):
    def test_public_btc_contract_metadata_matches_parser(self):
        provider = PROVIDERS["gold_api_free_btc"]
        self.assertEqual(provider.instrument_id, "BTC_USD")
        self.assertTrue(provider.url.endswith("/price/BTC"))
        self.assertEqual(provider.source_family, "gold_api_free")
        self.assertEqual(provider.source_semantic, SourceSemantic.REFERENCE_RATE)
        self.assertEqual(provider.parser_version, build_parser(provider.parser_id).parser_version)
        self.assertIsNone(provider.api_key_setting)
        self.assertIsNone(provider.history_url)
        self.assertTrue(provider.requires_https)

    def test_local_crypto_routes_stay_disabled_and_keyed(self):
        for name, symbol, instrument, _value in LOCAL_QUOTES:
            with self.subTest(symbol=symbol):
                provider = RETIRED_PROVIDERS[f"servix_{name}_toman"]
                self.assertFalse(provider.enabled)
                self.assertFalse(provider.configured(SimpleNamespace()))
                self.assertEqual(provider.api_key_header, "X-API-Key")
                self.assertEqual(provider.api_key_setting, "servix_api_key")
                self.assertTrue(provider.requires_https)
                self.assertEqual(provider.instrument_id, instrument)
                self.assertEqual(provider.symbol_or_pair, symbol)
                self.assertEqual(provider.parser_version, build_parser(provider.parser_id).parser_version)
                self.assertTrue(provider.history_url.endswith(f"/{symbol}/history"))
                self.assertFalse(provider.history_requires_live_quote)

    def test_nine_default_servix_routes_fit_forty_eight_catalogue_calls(self):
        routes = list(RETIRED_PROVIDERS.values())
        self.assertEqual(len(routes), 9)
        self.assertEqual(sum(provider.budget.requests_per_day for provider in routes), 48)
        for name, _symbol, _instrument, _value in LOCAL_QUOTES:
            provider = RETIRED_PROVIDERS[f"servix_{name}_toman"]
            self.assertEqual(provider.budget.requests_per_day, 3)
            self.assertGreaterEqual(provider.budget.minimum_interval_seconds, 28800)


if __name__ == "__main__":
    unittest.main()
