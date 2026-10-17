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
from app.pricing.parsers.base import ParserError
from app.pricing.parsers.nerkhsanj_history import NerkhsanjDailyHistoryParser


NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
START = NOW - timedelta(days=365)
INSTRUMENT = get_instrument("SILVER_999_TOMAN_GRAM")


def payload(*days):
    return {"series": [{"key": "silver", "name": "نقره", "days": list(days)}]}


class NerkhsanjDailyHistoryParserTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch("app.pricing.parsers.nerkhsanj_history.utc_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.parser = NerkhsanjDailyHistoryParser()

    def parse(self, source, *, instrument=INSTRUMENT, start=START, end=NOW):
        return self.parser.parse(source, instrument, start, end)

    def test_source_reported_close_has_day_bucket_metadata_without_close_hour(self):
        point, = self.parse(payload(["1405/07/23", 517260]))
        self.assertEqual(point.observed_at, datetime(2026, 10, 14, 20, 30, tzinfo=UTC))
        self.assertEqual(point.price, Decimal("517260"))
        self.assertIsNone(point.volume)
        self.assertEqual(point.metadata, {
            "source_calendar": "jalali",
            "source_date": "1405/07/23",
            "source_timezone": "Asia/Tehran",
            "timestamp_precision": "day",
            "timestamp_role": "day_bucket_start",
            "source_observation_time_known": False,
            "history_point_kind": "source_reported_daily_close",
        })

    def test_known_nowruz_and_leap_boundaries(self):
        anchors = {
            "1300/01/01": datetime(1921, 3, 21, tzinfo=UTC),
            "1399/01/01": datetime(2020, 3, 20, tzinfo=UTC),
            "1399/12/30": datetime(2021, 3, 20, tzinfo=UTC),
            "1400/01/01": datetime(2021, 3, 21, tzinfo=UTC),
            "1403/01/01": datetime(2024, 3, 20, tzinfo=UTC),
            "1403/12/30": datetime(2025, 3, 20, tzinfo=UTC),
            "1404/01/01": datetime(2025, 3, 21, tzinfo=UTC),
            "1405/01/01": datetime(2026, 3, 21, tzinfo=UTC),
            "1500/01/01": datetime(2121, 3, 21, tzinfo=UTC),
        }
        from zoneinfo import ZoneInfo
        for source_date, expected_day in anchors.items():
            with self.subTest(source_date=source_date):
                expected = expected_day.replace(tzinfo=ZoneInfo("Asia/Tehran")).astimezone(UTC)
                with patch("app.pricing.parsers.nerkhsanj_history.utc_now",
                           return_value=datetime(2200, 1, 1, tzinfo=UTC)):
                    point, = self.parse(payload([source_date, 5000]),
                                        start=expected, end=expected + timedelta(days=1))
                self.assertEqual(point.observed_at, expected)

    def test_tehran_day_boundary_excludes_current_day_even_before_utc_midnight(self):
        with patch("app.pricing.parsers.nerkhsanj_history.utc_now",
                   return_value=datetime(2026, 10, 16, 21, tzinfo=UTC)):
            points = self.parse(payload(["1405/07/24", 5000], ["1405/07/25", 6000]))
        self.assertEqual([p.metadata["source_date"] for p in points], ["1405/07/24"])

    def test_current_and_future_days_are_not_final(self):
        self.assertEqual(self.parse(payload(["1405/07/25", 5000], ["1405/07/26", 6000])), [])

    def test_sorts_source_days_and_keeps_holiday_gaps(self):
        points = self.parse(payload(["1405/07/23", "۵۱۷۲۶۰"], ["1405/07/21", 510000]))
        self.assertEqual([p.metadata["source_date"] for p in points], ["1405/07/21", "1405/07/23"])
        self.assertEqual(len(points), 2)

    def test_range_is_inclusive_at_bucket_boundary(self):
        expected = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
        source = payload(["1405/07/23", 5000])
        self.assertEqual(len(self.parse(source, start=expected, end=expected)), 1)
        self.assertEqual(self.parse(source, start=expected + timedelta(microseconds=1)), [])

    def test_other_documented_series_is_ignored(self):
        source = payload(["1405/07/23", 5000])
        source["series"].insert(0, {"key": "gold24", "name": "طلای ۲۴", "days": [["bad", 2]]})
        self.assertEqual(len(self.parse(source)), 1)

    def test_empty_selected_series_does_not_create_rows(self):
        self.assertEqual(self.parse(payload()), [])

    def test_rejects_duplicate_matching_series(self):
        source = payload(["1405/07/23", 5000])
        source["series"].append(dict(source["series"][0]))
        self.assert_error("duplicate_series", source)

    def test_rejects_duplicate_dates_even_outside_requested_range(self):
        self.assert_error("duplicate_date", payload(["1399/08/10", 5000], ["1399/08/10", 6000]))

    def test_rejects_bad_calendar_dates(self):
        for source_date in ("1404/12/30", "1400/12/30", "1405/07/31", "1405/13/01",
                            "1405/00/01", "1405/01/00", "1405/01/32", "1299/12/29",
                            "1501/01/01", "1405/7/23", "1405-07-23", "۱۴۰۵/۰۷/۲۳",
                            True, 14050723, None):
            with self.subTest(source_date=source_date):
                self.assert_error("invalid_source_date", payload([source_date, 5000]))

    def test_rejects_invalid_prices(self):
        for value in (True, False, None, 0, -1, "NaN", Decimal("NaN"), float("nan"),
                      float("inf"), "Infinity", {}, [], "1e4", "9" * 129):
            with self.subTest(value=repr(value)):
                self.assert_error("invalid_number", payload(["1405/07/23", value]))

    def test_rejects_prices_outside_current_instrument_sanity_bounds(self):
        for value in (999, 10000001):
            with self.subTest(value=value):
                self.assert_error("outside_sanity_bounds", payload(["1405/07/23", value]))

    def test_rejects_huge_integer_before_decimal_conversion(self):
        self.assert_error("invalid_number", payload(["1405/07/23", 10 ** 5000]))

    def test_old_sanity_outliers_do_not_override_requested_recent_history(self):
        point, = self.parse(payload(["1400/05/19", 800], ["1400/06/07", 820],
                                   ["1405/07/23", 5000]))
        self.assertEqual(point.price, Decimal("5000"))

    def test_old_sanity_outliers_are_rejected_if_their_range_is_requested(self):
        for source_date, value in (("1400/05/19", 800), ("1400/06/07", 820)):
            with self.subTest(source_date=source_date):
                with self.assertRaises(ParserError) as caught:
                    self.parse(payload([source_date, value]),
                               start=datetime(2021, 8, 1, tzinfo=UTC),
                               end=datetime(2021, 9, 1, tzinfo=UTC))
                self.assertEqual(caught.exception.code, "outside_sanity_bounds")

    def test_invalid_numbers_outside_requested_range_are_still_rejected(self):
        self.assert_error("invalid_number", payload(["1400/05/19", True], ["1405/07/23", 5000]))

    def test_rejects_wrong_instrument_and_units(self):
        for instrument in (get_instrument("SILVER_925_TOMAN_GRAM"),
                           replace(INSTRUMENT, quote_currency=Currency.USD),
                           replace(INSTRUMENT, weight_unit=WeightUnit.TROY_OUNCE),
                           replace(INSTRUMENT, purity=Decimal("0.925")),
                           replace(INSTRUMENT, base_asset="XAU")):
            with self.subTest(instrument=instrument):
                with self.assertRaises(ParserError):
                    self.parse(payload(["1405/07/23", 5000]), instrument=instrument)

    def test_rejects_unsupported_parser_symbol(self):
        with self.assertRaises(ParserError):
            NerkhsanjDailyHistoryParser(symbol="gold").parse(payload(), INSTRUMENT, START, NOW)

    def test_rejects_missing_silver_and_malformed_root(self):
        for source in ([], None, {}, {"series": {}}, {"series": []},
                       {"series": [{"key": "gold", "name": "طلا", "days": []}]}):
            with self.subTest(source=source):
                with self.assertRaises(ParserError):
                    self.parse(source)

    def test_rejects_malformed_series_and_days(self):
        for series in (None, {}, {"key": "silver", "days": []},
                       {"key": "silver", "name": "", "days": []},
                       {"key": "silver", "name": "نقره", "days": {}},
                       {"key": "silver", "name": "نقره", "days": [["1405/07/23"]]},
                       {"key": "silver", "name": "نقره", "days": [["1405/07/23", 5000, 1]]}):
            with self.subTest(series=series):
                with self.assertRaises(ParserError):
                    self.parse({"series": [series]})

    def test_rejects_oversize_series_and_selected_days(self):
        source = payload()
        source["series"] *= 65
        self.assert_error("history_too_large", source)
        self.assert_error("history_too_large", payload(*([["1405/07/23", 5000]] * 20001)))

    def test_rejects_naive_inverted_and_oversize_ranges(self):
        for start, end in ((NOW.replace(tzinfo=None), NOW), (START, NOW.replace(tzinfo=None)),
                           (NOW, START), (NOW - timedelta(days=366, microseconds=1), NOW)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ParserError) as caught:
                    self.parse(payload(), start=start, end=end)
                self.assertEqual(caught.exception.code, "invalid_history_range")

    def assert_error(self, code, source):
        with self.assertRaises(ParserError) as caught:
            self.parse(source)
        self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
