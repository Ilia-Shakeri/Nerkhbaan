from __future__ import annotations

import copy
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.models import Currency, WeightUnit
from app.pricing.parsers.base import ParserError
from app.pricing.parsers.wallgold_history import WallgoldSilver925HistoryParser


NOW = datetime(2026, 10, 17, 11, 56, tzinfo=UTC)
INSTRUMENT = get_instrument("SILVER_925_TOMAN_GRAM")


def candle(stamp="2026-10-16T00:00:00Z", **kwargs):
    return {"date": stamp, "open": "475000", "low": "465000", "high": "480000", "close": "467000", **kwargs}


def payload(*rows):
    return {"success": True, "result": {"chart": {"data": list(rows)},
            "metaData": [{"symbol": "GOLD_OUNCE", "price": "4166.39", "currency": "DOLLAR"}]}}


class WallgoldSilver925HistoryTests(unittest.TestCase):
    def setUp(self):
        clock = patch("app.pricing.parsers.wallgold_history.utc_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def parse(self, source=None, period="day", instrument=INSTRUMENT, start=None, end=NOW):
        return WallgoldSilver925HistoryParser(period).parse(
            payload(candle()) if source is None else source,
            instrument, start or NOW - timedelta(days=365), end)

    def test_published_daily_close_keeps_utc_gregorian_bucket_semantics(self):
        point, = self.parse()
        self.assertEqual(point.price, Decimal("467000"))
        self.assertEqual(point.observed_at, datetime(2026, 10, 16, tzinfo=UTC))
        self.assertIsNone(point.volume)
        self.assertEqual(point.metadata["timestamp_precision"], "day")
        self.assertEqual(point.metadata["timestamp_role"], "day_bucket_start")
        self.assertEqual(point.metadata["source_timezone"], "UTC")
        self.assertEqual(point.metadata["source_calendar"], "gregorian")
        self.assertEqual(point.metadata["source_date"], "2026-10-16")
        self.assertIs(point.metadata["source_observation_time_known"], False)
        self.assertEqual(point.metadata["source_candle_interval_seconds"], 86400)

    def test_hourly_route_keeps_candle_boundary_without_invented_trade_time(self):
        point, = self.parse(payload(candle("2026-10-17T10:00:00Z")), period="hour")
        self.assertEqual(point.observed_at, datetime(2026, 10, 17, 10, tzinfo=UTC))
        self.assertEqual(point.metadata["source_candle_interval_seconds"], 3600)
        self.assertEqual(point.metadata["source_candle_time_role"], "period_start")
        self.assertIs(point.metadata["source_trade_time_known"], False)
        self.assertNotIn("timestamp_role", point.metadata)
        self.assertNotIn("timestamp_precision", point.metadata)

    def test_current_and_future_periods_cannot_be_final_closes(self):
        source = payload(candle("2026-10-17T00:00:00Z"), candle("2026-10-18T00:00:00Z"))
        self.assertEqual(self.parse(source), [])
        self.assertEqual(self.parse(payload(candle("2026-10-17T11:00:00Z")), period="hour"), [])

    def test_exact_end_of_period_is_closed(self):
        with patch("app.pricing.parsers.wallgold_history.utc_now", return_value=datetime(2026, 10, 17, tzinfo=UTC)):
            self.assertEqual(len(self.parse()), 1)
        with patch("app.pricing.parsers.wallgold_history.utc_now", return_value=datetime(2026, 10, 17, 11, tzinfo=UTC)):
            self.assertEqual(len(self.parse(payload(candle("2026-10-17T10:00:00Z")), period="hour")), 1)

    def test_sorting_does_not_fill_market_history_before_inception_or_missing_days(self):
        source = payload(candle("2026-10-16T00:00:00Z"), candle("2026-08-18T00:00:00Z"),
                         candle("2026-10-14T00:00:00Z"))
        points = self.parse(source)
        self.assertEqual([p.metadata["source_date"] for p in points], ["2026-08-18", "2026-10-14", "2026-10-16"])

    def test_range_includes_only_requested_candle_starts(self):
        stamp = datetime(2026, 10, 16, tzinfo=UTC)
        self.assertEqual(len(self.parse(start=stamp, end=stamp)), 1)
        self.assertEqual(self.parse(start=stamp + timedelta(microseconds=1)), [])

    def test_cannot_relabel_gold_999_or_dollar_payload_to_silver925(self):
        for key in ("SILVER_999_TOMAN_GRAM", "GOLD_18K_TOMAN_GRAM", "XAG_USD_OZ"):
            with self.subTest(key=key), self.assertRaises(ParserError) as raised:
                self.parse(instrument=get_instrument(key))
            self.assertEqual(raised.exception.code, "unsupported_symbol")

    def test_instrument_currency_unit_purity_and_asset_are_strict(self):
        for field, value, code in (("quote_currency", Currency.USD, "currency_mismatch"),
                ("weight_unit", WeightUnit.TROY_OUNCE, "unit_mismatch"),
                ("purity", Decimal("0.999"), "purity_mismatch"),
                ("base_asset", "XAU", "purity_mismatch")):
            with self.subTest(field=field), self.assertRaises(ParserError) as raised:
                self.parse(instrument=replace(INSTRUMENT, **{field: value}))
            self.assertEqual(raised.exception.code, code)

    def test_rejects_unsupported_period_and_unbounded_range(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(period="week")
        self.assertEqual(raised.exception.code, "unsupported_period")
        for start, end in ((NOW.replace(tzinfo=None), NOW), (NOW - timedelta(days=367), NOW),
                           (NOW + timedelta(days=1), NOW)):
            with self.subTest(start=start), self.assertRaises(ParserError) as raised:
                self.parse(start=start, end=end)
            self.assertEqual(raised.exception.code, "invalid_history_range")

    def test_rejects_invalid_response_shapes_and_failure_flag(self):
        for source in (None, [], {"success": False}, {"success": True, "result": []},
                       {"success": True, "result": {"chart": {"data": {}}}}):
            with self.subTest(source=source), self.assertRaises(ParserError):
                # Pass through directly so None is not the helper's valid default.
                WallgoldSilver925HistoryParser().parse(source, INSTRUMENT, NOW - timedelta(days=1), NOW)

    def test_rejects_duplicates_even_outside_requested_range(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(payload(candle("2020-01-01T00:00:00Z"), candle("2020-01-01T00:00:00Z")))
        self.assertEqual(raised.exception.code, "duplicate_timestamp")

    def test_rejects_oversized_daily_and_hourly_bodies(self):
        for period, count in (("day", 367), ("hour", 745)):
            with self.subTest(period=period), self.assertRaises(ParserError) as raised:
                self.parse(payload(*([candle()] * count)), period=period)
            self.assertEqual(raised.exception.code, "history_too_large")

    def test_rejects_non_utc_naive_or_unaligned_candle_starts(self):
        for stamp in (None, 12345, "bad", "2026-10-16T00:00:00", "2026-10-16T00:00:00+03:30",
                      "2026-10-16T00:01:00Z", "2026-10-16T00:00:01Z", "2026-10-16T00:00:00.1Z",
                      "2026-10-16T10:00:00Z"):
            with self.subTest(stamp=stamp), self.assertRaises(ParserError) as raised:
                self.parse(payload(candle(stamp)))
            self.assertEqual(raised.exception.code, "invalid_timestamp")

    def test_rejects_missing_invalid_or_excessive_numbers(self):
        for value in (None, True, 0, -1, "NaN", "Infinity", "x", "1" * 129, 10**100):
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ParserError):
                self.parse(payload(candle(close=value)))

    def test_rejects_contradictory_ohlc(self):
        for kwargs in ({"low": "490000"}, {"high": "460000"}, {"open": "500000"}, {"close": "450000"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ParserError) as raised:
                self.parse(payload(candle(**kwargs)))
            self.assertEqual(raised.exception.code, "invalid_ohlc")

    def test_checks_all_returned_ohlc_values_against_instrument_bounds(self):
        source = payload(candle(open="500", low="500", high="470000", close="467000"))
        with self.assertRaises(ParserError) as raised:
            self.parse(source)
        self.assertEqual(raised.exception.code, "outside_sanity_bounds")

    def test_unrelated_metadata_asset_does_not_supply_a_fake_price_or_volume(self):
        source = payload()
        self.assertEqual(self.parse(source), [])
        source = payload(candle())
        copied = copy.deepcopy(source)
        point, = self.parse(source)
        self.assertEqual(point.price, Decimal("467000"))
        self.assertEqual(source, copied)
        self.assertIsNone(point.volume)


if __name__ == "__main__":
    unittest.main()
