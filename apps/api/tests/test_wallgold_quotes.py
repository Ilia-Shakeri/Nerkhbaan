from __future__ import annotations

import copy
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.models import Currency, WeightUnit
from app.pricing.parsers.base import ParserContext, ParserError
from app.pricing.parsers.wallgold_quotes import WallgoldPublicQuoteParser


NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
SILVER = get_instrument("SILVER_925_TOMAN_GRAM")


def quote(symbol="SLV_925TMN", side="buy", **kwargs):
    return {"symbol": symbol, "side": side, "price": "464000",
            "currentTime": "2026-10-17T12:00:00Z",
            "priceExpiresAt": "2026-10-18T11:59:00Z", "ttl": 86340, **kwargs}


def payload(*rows):
    return {"success": True, "result": list(rows)}


class WallgoldPublicQuoteParserTests(unittest.TestCase):
    def parse(self, source=None, symbol="SLV_925TMN", side="buy", instrument=SILVER, now=NOW, age=120):
        return WallgoldPublicQuoteParser(symbol, side).parse(
            payload(quote()) if source is None else source,
            ParserContext(instrument, now, age))

    def test_published_925_quote_preserves_toman_gram_and_explicit_side(self):
        parsed = self.parse()
        self.assertEqual(parsed.price, Decimal("464000"))
        self.assertEqual(parsed.currency, Currency.TOMAN)
        self.assertEqual(parsed.weight_unit, WeightUnit.GRAM)
        self.assertEqual(parsed.purity, Decimal("0.925"))
        self.assertIsNone(parsed.bid)
        self.assertIsNone(parsed.ask)
        self.assertEqual(parsed.metadata["source_selected_side"], "buy")
        self.assertEqual(parsed.metadata["source_price_semantic"], "published_side_reference_quote")

    def test_gold18_uses_only_its_published_750_market(self):
        point = self.parse(payload(quote("GLD_18C_750TMN", price="26008000")),
            symbol="GLD_18C_750TMN", instrument=get_instrument("GOLD_18K_TOMAN_GRAM"))
        self.assertEqual(point.price, Decimal("26008000"))
        self.assertEqual(point.purity, Decimal("0.750"))

    def test_clock_is_response_quote_snapshot_not_a_trade_claim(self):
        parsed = self.parse()
        self.assertEqual(parsed.observed_at, NOW)
        self.assertEqual(parsed.metadata["timestamp_basis"], "provider_response_clock")
        self.assertEqual(parsed.metadata["source_timestamp_scope"], "response_quote_snapshot")
        self.assertIs(parsed.metadata["source_trade_time_known"], False)
        self.assertIs(parsed.metadata["source_observation_time_known"], False)

    def test_selects_one_exact_market_and_side_without_averaging(self):
        source = payload(quote(side="sell", price="462000"), quote("GLD_18C_750TMN", price="26008000"), quote())
        self.assertEqual(self.parse(source).price, Decimal("464000"))
        self.assertEqual(self.parse(source, side="sell").price, Decimal("462000"))

    def test_one_day_remote_expiry_cannot_extend_local_freshness(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(now=NOW + timedelta(seconds=121), age=120)
        self.assertEqual(raised.exception.code, "stale_timestamp")

    def test_expiry_does_not_replace_missing_or_old_response_clock(self):
        for value in (None, "", "2026-10-17T10:00:00Z"):
            with self.subTest(value=value), self.assertRaises(ParserError):
                self.parse(payload(quote(currentTime=value)))

    def test_future_response_clock_rejected_by_existing_skew_limit(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(payload(quote(currentTime="2026-10-17T13:00:00Z")))
        self.assertEqual(raised.exception.code, "stale_timestamp")

    def test_timezone_required_for_both_clocks(self):
        for field in ("currentTime", "priceExpiresAt"):
            for value in (None, 12345, "bad", "2026-10-17T12:00:00", "2026-10-17", "x" * 81):
                with self.subTest(field=field, value=value), self.assertRaises(ParserError) as raised:
                    self.parse(payload(quote(**{field: value})))
                self.assertEqual(raised.exception.code, "invalid_timestamp")

    def test_equivalent_explicit_timezone_converts_without_changing_clock(self):
        parsed = self.parse(payload(quote(currentTime="2026-10-17T15:30:00+03:30")))
        self.assertEqual(parsed.observed_at, NOW)

    def test_expired_reversed_and_unbounded_validity_rejected(self):
        for kwargs in ({"priceExpiresAt": "2026-10-17T12:00:00Z", "ttl": 1},
                {"priceExpiresAt": "2026-10-17T11:59:59Z", "ttl": 1},
                {"priceExpiresAt": "2026-11-17T12:00:00Z", "ttl": 86400},
                {"ttl": 86401}, {"ttl": 30}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ParserError) as raised:
                self.parse(payload(quote(**kwargs)))
            self.assertEqual(raised.exception.code, "invalid_quote_validity")

    def test_ttl_requires_finite_bounded_positive_number(self):
        for value in (None, False, 0, -1, "NaN", "Infinity", "x", "9" * 129):
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ParserError):
                self.parse(payload(quote(ttl=value)))

    def test_duplicate_or_absent_selected_side_rejected(self):
        for source in (payload(), payload(quote(side="sell")), payload(quote(), quote())):
            with self.subTest(source=source), self.assertRaises(ParserError) as raised:
                self.parse(source)
            self.assertEqual(raised.exception.code, "unsupported_symbol")

    def test_invalid_shapes_or_provider_error_rejected(self):
        for source in (None, [], {"success": False}, {"success": True, "result": {}}, payload(None)):
            with self.subTest(source=source), self.assertRaises(ParserError):
                WallgoldPublicQuoteParser("SLV_925TMN").parse(source, ParserContext(SILVER, NOW, 120))

    def test_oversized_market_side_list_rejected(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(payload(*([quote()] * 65)))
        self.assertEqual(raised.exception.code, "payload_too_large")

    def test_cannot_relabel_other_purity_instrument_or_side(self):
        for symbol, instrument, side, code in (
                ("GLD_24K_9999TMN", get_instrument("GOLD_24K_TOMAN_GRAM"), "buy", "unsupported_symbol"),
                ("SLV_925TMN", get_instrument("SILVER_999_TOMAN_GRAM"), "buy", "unsupported_symbol"),
                ("SLV_925TMN", SILVER, "last", "unsupported_side")):
            with self.subTest(symbol=symbol, side=side), self.assertRaises(ParserError) as raised:
                self.parse(symbol=symbol, instrument=instrument, side=side)
            self.assertEqual(raised.exception.code, code)

    def test_checks_instrument_currency_weight_purity_and_asset(self):
        for field, value, code in (("quote_currency", Currency.USD, "currency_mismatch"),
                ("weight_unit", WeightUnit.TROY_OUNCE, "unit_mismatch"),
                ("purity", Decimal("0.999"), "purity_mismatch"),
                ("base_asset", "XAU", "purity_mismatch")):
            with self.subTest(field=field), self.assertRaises(ParserError) as raised:
                self.parse(instrument=replace(SILVER, **{field: value}))
            self.assertEqual(raised.exception.code, code)

    def test_invalid_and_out_of_sanity_price_rejected(self):
        for value in (None, True, 0, -1, "NaN", "9" * 129, 500, 10000001):
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ParserError):
                self.parse(payload(quote(price=value)))

    def test_does_not_modify_source_or_use_unrelated_stats(self):
        source = payload(quote())
        source["result"][0]["lastPrice"] = "1"
        original = copy.deepcopy(source)
        self.assertEqual(self.parse(source).price, Decimal("464000"))
        self.assertEqual(source, original)


if __name__ == "__main__":
    unittest.main()
