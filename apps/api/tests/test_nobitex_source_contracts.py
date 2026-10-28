from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.models import Currency, WeightUnit
from app.pricing.parsers.base import ParserContext, ParserError
from app.pricing.parsers.history import NobitexUdfHistoryParser
from app.pricing.parsers.nobitex import NobitexOrderBookParser


NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def book(symbol="USDTIRT"):
    bids, asks = (("2631100", "2635130") if symbol == "USDTIRT"
                  else ("214000000000", "214200000000"))
    return {"status": "ok", "lastUpdate": int(NOW.timestamp() * 1000),
            "bids": [[bids, "1"]], "asks": [[asks, "2"]]}


def candles(start=None, count=3):
    start = NOW - timedelta(hours=2) if start is None else start
    return {"s": "ok", "t": [int((start + timedelta(hours=index)).timestamp()) for index in range(count)],
            "o": ["263000"] * count, "h": ["264000"] * count,
            "l": ["262000"] * count, "c": ["263400"] * count, "v": ["0"] * count}


class NobitexOrderBookSourceTests(unittest.TestCase):
    def test_multi_market_route_uses_only_requested_market_clock_and_units(self):
        from app.pricing.registry import PROVIDERS

        self.assertTrue(PROVIDERS["nobitex_orderbook_usdt"].url.endswith("/v3/orderbook/all"))
        source = {"status": "ok", "BTCIRT": book("BTCIRT"), "USDTIRT": book()}
        value = self.parse(source)
        self.assertEqual(value.price, Decimal("263311.5"))
        source["USDTIRT"]["lastUpdate"] = int((NOW - timedelta(minutes=2)).timestamp() * 1000)
        with self.assertRaises(ParserError):
            self.parse(source)
        del source["USDTIRT"]
        with self.assertRaises(ParserError):
            self.parse(source)

    def parse(self, payload, symbol="USDTIRT", instrument=None):
        instrument = instrument or get_instrument("USDT_TOMAN" if symbol == "USDTIRT" else "BTC_TOMAN")
        return NobitexOrderBookParser(symbol).parse(payload, ParserContext(instrument, NOW, 60))

    def test_documented_single_market_shape_normalizes_rial_exactly_once(self):
        for symbol, instrument in (("USDTIRT", "USDT_TOMAN"), ("BTCIRT", "BTC_TOMAN")):
            source = book(symbol)
            with self.subTest(symbol=symbol):
                parsed = self.parse(source, symbol, get_instrument(instrument))
                self.assertEqual(parsed.bid, Decimal(source["bids"][0][0]) / 10)
                self.assertEqual(parsed.ask, Decimal(source["asks"][0][0]) / 10)
                self.assertEqual(parsed.price, (parsed.bid + parsed.ask) / 2)
                self.assertEqual(parsed.observed_at, NOW)
                self.assertEqual(parsed.metadata["source_currency"], "RIAL")
                self.assertEqual(parsed.metadata["timestamp_basis"], "lastUpdate")

    def test_legacy_all_market_shape_keeps_its_own_timestamp(self):
        payload = {"USDTIRT": book(), "BTCIRT": book("BTCIRT"), "lastUpdate": int((NOW + timedelta(days=1)).timestamp() * 1000)}
        self.assertEqual(self.parse(payload).observed_at, NOW)

    def test_missing_clock_never_uses_updated_at_receive_time_or_global_clock(self):
        for payload in (book(), {"USDTIRT": book(), "lastUpdate": int(NOW.timestamp() * 1000)}):
            selected = payload.get("USDTIRT", payload)
            del selected["lastUpdate"]
            selected["updated_at"] = NOW.isoformat()
            with self.subTest(payload=payload), self.assertRaises(ParserError) as raised:
                self.parse(payload)
            self.assertEqual(raised.exception.code, "missing_timestamp")

    def test_malformed_source_clocks_are_rejected(self):
        for stamp in (True, False, "", " ", "2026-10-17T12:00:00Z", int(NOW.timestamp()), 1.0, [], {}, "9" * 100):
            source = {**book(), "lastUpdate": stamp}
            with self.subTest(stamp=stamp), self.assertRaises(ParserError) as raised:
                self.parse(source)
            self.assertEqual(raised.exception.code, "invalid_timestamp")

    def test_stale_and_future_clocks_remain_rejected(self):
        for offset in (-61, 31):
            source = {**book(), "lastUpdate": int((NOW + timedelta(seconds=offset)).timestamp() * 1000)}
            with self.subTest(offset=offset), self.assertRaises(ParserError) as raised:
                self.parse(source)
            self.assertEqual(raised.exception.code, "stale_timestamp")

    def test_explicit_symbol_and_instrument_cannot_be_relabelled(self):
        for symbol in ("BTCIRT", "USDTUSDT", [], True):
            source = {**book(), "symbol": symbol}
            with self.subTest(symbol=symbol), self.assertRaises(ParserError):
                self.parse(source)
        with self.assertRaises(ParserError):
            self.parse(book(), instrument=get_instrument("BTC_TOMAN"))
        with self.assertRaises(ParserError):
            self.parse(book(), symbol="USDTUSD", instrument=get_instrument("USDT_USD"))

    def test_mismatched_currency_unit_purity_and_base_are_rejected(self):
        original = get_instrument("USDT_TOMAN")
        for changes in ({"quote_currency": Currency.USD}, {"weight_unit": WeightUnit.GRAM},
                        {"purity": Decimal("0.999")}, {"base_asset": "USD"}):
            with self.subTest(changes=changes), self.assertRaises(ParserError):
                self.parse(book(), instrument=replace(original, **changes))

    def test_empty_crossed_and_out_of_bounds_sides_are_rejected(self):
        for changes in ({"bids": []}, {"asks": []}, {"bids": [["2640000", "1"]]},
                        {"bids": [["1", "1"]]}, {"asks": [["10000001", "1"]]}):
            with self.subTest(changes=changes), self.assertRaises(ParserError):
                self.parse({**book(), **changes})

    def test_status_and_ambiguous_shapes_are_rejected(self):
        for source in ({**book(), "status": "failed"}, {**book(), "USDTIRT": book()}):
            with self.subTest(source=source), self.assertRaises(ParserError):
                self.parse(source)

    def test_missing_zero_and_malformed_top_quantities_are_rejected(self):
        for level in (["2631100"], ["2631100", "0"], ["2631100", "-1"],
                      ["2631100", True], ["2631100", "NaN"], {"price": "2631100"}):
            with self.subTest(level=level), self.assertRaises(ParserError):
                self.parse({**book(), "bids": [level]})


class NobitexHourlyChartSourceTests(unittest.TestCase):
    def setUp(self):
        clock = patch("app.pricing.parsers.history.utc_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def parse(self, payload, symbol="USDTIRT", instrument=None, start=None, end=None):
        return NobitexUdfHistoryParser(symbol).parse(
            payload, instrument or get_instrument("USDT_TOMAN"),
            NOW - timedelta(days=1) if start is None else start, NOW if end is None else end)

    def test_closed_hourly_bars_preserve_udf_toman_without_orderbook_division(self):
        points = self.parse(candles())
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].price, Decimal("263400"))
        self.assertEqual(points[0].volume, Decimal(0))
        self.assertEqual(points[0].observed_at, NOW - timedelta(hours=2))

    def test_unclosed_current_bar_is_never_a_final_close(self):
        self.assertEqual(self.parse(candles(NOW, 1)), [])
        self.assertEqual(self.parse(candles(NOW - timedelta(minutes=30), 1)), [])
        self.assertEqual(len(self.parse(candles(NOW - timedelta(hours=1), 1))), 1)

    def test_range_end_also_must_allow_the_whole_hour_to_close(self):
        self.assertEqual(len(self.parse(candles(count=2), end=NOW - timedelta(minutes=30))), 1)

    def test_future_range_end_cannot_accept_an_open_bar(self):
        self.assertEqual(self.parse(candles(NOW, 1), end=NOW + timedelta(hours=2)), [])

    def test_history_and_no_data_still_require_exact_supported_instrument(self):
        for source in (candles(), {"s": "no_data"}):
            for instrument in ("BTC_TOMAN", "USDT_USD", "SILVER_999_TOMAN_GRAM"):
                with self.subTest(source=source.get("s"), instrument=instrument), self.assertRaises(ParserError):
                    self.parse(source, instrument=get_instrument(instrument))
            with self.assertRaises(ParserError):
                self.parse(source, symbol="USDTUSD", instrument=get_instrument("USDT_USD"))

    def test_matching_btc_chart_keeps_its_own_native_toman_values(self):
        source = candles(count=1)
        source.update(o=["8000000000"], h=["8100000000"], l=["7900000000"], c=["8050000000"])
        point, = self.parse(source, symbol="BTCIRT", instrument=get_instrument("BTC_TOMAN"))
        self.assertEqual(point.price, Decimal("8050000000"))

    def test_explicit_response_symbol_and_instrument_contract_rejected(self):
        with self.assertRaises(ParserError):
            self.parse({**candles(), "symbol": "BTCIRT"})
        original = get_instrument("USDT_TOMAN")
        for changes in ({"quote_currency": Currency.USD}, {"weight_unit": WeightUnit.GRAM},
                        {"purity": Decimal("0.999")}, {"base_asset": "USD"}):
            with self.subTest(changes=changes), self.assertRaises(ParserError):
                self.parse(candles(), instrument=replace(original, **changes))

    def test_aware_ordered_bounded_range_is_required(self):
        for bounds in ({"start": NOW.replace(tzinfo=None)}, {"end": NOW.replace(tzinfo=None)},
                       {"start": NOW + timedelta(seconds=1)}, {"start": NOW - timedelta(days=367)}):
            with self.subTest(bounds=bounds), self.assertRaises(ParserError) as raised:
                self.parse(candles(), **bounds)
            self.assertEqual(raised.exception.code, "invalid_history_range")

    def test_all_ohlcv_arrays_must_exist_and_match(self):
        for key in ("t", "o", "h", "l", "c", "v"):
            source = candles()
            del source[key]
            with self.subTest(missing=key), self.assertRaises(ParserError):
                self.parse(source)
            source = candles()
            source[key] = source[key][:-1]
            with self.subTest(length=key), self.assertRaises(ParserError):
                self.parse(source)

    def test_bad_ohlc_bounds_and_every_numeric_field_are_rejected(self):
        for key, value in (("o", "264001"), ("h", "263399"), ("l", "263001"),
                           ("c", "264001"), ("v", "-1"), ("v", None), ("o", "NaN"),
                           ("h", 1000001), ("l", 999), ("c", True)):
            source = candles(count=1)
            source[key][0] = value
            with self.subTest(key=key, value=value), self.assertRaises(ParserError):
                self.parse(source)

    def test_timestamps_need_integer_seconds_and_never_boolean_or_milliseconds(self):
        for stamp in (True, False, 1.5, "1.5", "not-a-time", int(NOW.timestamp() * 1000), {}, [], "9" * 100):
            source = candles(count=1)
            source["t"][0] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ParserError) as raised:
                self.parse(source)
            self.assertEqual(raised.exception.code, "invalid_timestamp")

    def test_duplicate_and_reverse_times_rejected_even_before_requested_range(self):
        source = candles(NOW - timedelta(days=2), 2)
        for timestamps in ([source["t"][0]] * 2, list(reversed(source["t"]))):
            with self.subTest(timestamps=timestamps), self.assertRaises(ParserError) as raised:
                self.parse({**source, "t": timestamps})
            self.assertEqual(raised.exception.code, "history_order")

    def test_500_candle_page_limit_is_enforced(self):
        source = candles(NOW - timedelta(hours=501), 501)
        with self.assertRaises(ParserError) as raised:
            self.parse(source, start=NOW - timedelta(days=30))
        self.assertEqual(raised.exception.code, "history_too_large")

    def test_no_data_remains_empty_and_errors_remain_errors(self):
        self.assertEqual(self.parse({"s": "no_data"}), [])
        for status in (None, "error", "", True):
            with self.subTest(status=status), self.assertRaises(ParserError) as raised:
                self.parse({"s": status})
            self.assertEqual(raised.exception.code, "history_status")


if __name__ == "__main__":
    unittest.main()
