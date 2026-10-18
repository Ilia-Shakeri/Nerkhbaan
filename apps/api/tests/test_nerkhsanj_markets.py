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
from app.pricing.parsers.base import ParserContext, ParserError
from app.pricing.parsers.nerkhsanj_markets import (
    NERKHSANJ_MARKETS, NerkhsanjIntradayHistoryParser,
    NerkhsanjMarketDailyHistoryParser, NerkhsanjSnapshotParser,
)
from app.pricing.registry import PROVIDERS


NOW = datetime(2026, 10, 17, 11, 47, 18, tzinfo=UTC)
SOURCE = {
    "date": "1405/07/25", "time": "15:16",
    "rates": {"dollar": 263800, "gold": 26236700, "silver": 504840,
              "tether": 263235, "bitcoin": 21476622300},
    "usd": {"ounce": 4166.39, "silver-ounce": 56.99},
}


class NerkhsanjSnapshotTests(unittest.TestCase):
    def parse(self, symbol="dollar", source=None, instrument=None, age=180):
        instrument = instrument or get_instrument(NERKHSANJ_MARKETS[symbol].instrument_id)
        return NerkhsanjSnapshotParser(symbol).parse(
            SOURCE if source is None else source,
            ParserContext(instrument, NOW, age),
        )

    def test_documented_keys_use_published_currency_without_ratio(self):
        for symbol, market in NERKHSANJ_MARKETS.items():
            with self.subTest(symbol=symbol):
                parsed = self.parse(symbol)
                original = SOURCE["usd" if market.currency is Currency.USD else "rates"][symbol]
                self.assertEqual(parsed.price, Decimal(str(original)))
                self.assertEqual(parsed.currency, market.currency)
                self.assertEqual(parsed.metadata["conversion_factor"], "1")

    def test_clock_is_tehran_source_rate_change_minute_not_reception_or_trade(self):
        parsed = self.parse()
        self.assertEqual(parsed.observed_at, datetime(2026, 10, 17, 11, 46, tzinfo=UTC))
        self.assertEqual(parsed.metadata["source_timestamp_scope"], "source_rates_last_change")
        self.assertEqual(parsed.metadata["source_timestamp_precision"], "minute")
        self.assertIs(parsed.metadata["source_observation_time_known"], False)
        self.assertIs(parsed.metadata["source_trade_time_known"], False)
        self.assertEqual(NerkhsanjSnapshotParser("dollar").parser_version, "nerkhsanj-snapshot/1.1.0")
        self.assertTrue(all(provider.parser_version == "nerkhsanj-snapshot/1.1.0"
                            for provider in PROVIDERS.values()
                            if provider.source_family == "nerkhsanj" and not provider.history_only))

    def test_blank_closed_market_clock_does_not_become_current(self):
        for clock in (None, "", "  "):
            source = {**SOURCE, "time": clock}
            with self.subTest(clock=clock), self.assertRaises(ParserError) as raised:
                self.parse(source=source)
            self.assertEqual(raised.exception.code, "missing_timestamp")

    def test_stale_publication_is_rejected_using_callers_actual_limit(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(age=60)
        self.assertEqual(raised.exception.code, "stale_timestamp")

    def test_recorded_old_source_change_stays_rejected_for_all_current_routes(self):
        received = datetime(2026, 10, 17, 13, 23, 5, 390705, tzinfo=UTC)
        recorded = {
            "date": "1405/07/25", "time": "16:16",
            "rates": {"dollar": 264010, "gold": 26237300, "silver": 511280,
                      "tether": 263685, "bitcoin": 21497010400},
            "usd": {"ounce": 4166.39, "silver-ounce": 56.99},
        }
        for symbol, market in NERKHSANJ_MARKETS.items():
            instrument = get_instrument(market.instrument_id)
            context = ParserContext(instrument, received,
                                    min(instrument.stale_after_seconds, instrument.expire_after_seconds))
            with self.subTest(symbol=symbol), self.assertRaises(ParserError) as raised:
                NerkhsanjSnapshotParser(symbol).parse(recorded, context)
            self.assertEqual(raised.exception.code, "stale_timestamp")

    def test_future_publication_rejected(self):
        with self.assertRaises(ParserError) as raised:
            self.parse(source={**SOURCE, "time": "15:25"})
        self.assertEqual(raised.exception.code, "stale_timestamp")

    def test_no_implicit_tether_usd_or_bitcoin_usd(self):
        for symbol, instrument in (("tether", "USDT_USD"), ("bitcoin", "BTC_USD")):
            with self.subTest(symbol=symbol), self.assertRaises(ParserError) as raised:
                self.parse(symbol, instrument=get_instrument(instrument))
            self.assertEqual(raised.exception.code, "unsupported_symbol")

    def test_24k_label_and_925_are_not_inferred(self):
        for symbol, instrument in (("gold24", "GOLD_24K_TOMAN_GRAM"), ("silver925", "SILVER_925_TOMAN_GRAM")):
            with self.subTest(symbol=symbol), self.assertRaises(ParserError) as raised:
                self.parse(symbol, instrument=get_instrument(instrument))
            self.assertEqual(raised.exception.code, "unsupported_symbol")

    def test_instrument_contract_currency_weight_purity_and_base_are_checked(self):
        original = get_instrument("SILVER_999_TOMAN_GRAM")
        for field, value, code in (
            ("quote_currency", Currency.USD, "currency_mismatch"),
            ("weight_unit", WeightUnit.TROY_OUNCE, "unit_mismatch"),
            ("purity", Decimal("0.925"), "purity_mismatch"),
            ("base_asset", "XAU", "purity_mismatch"),
        ):
            with self.subTest(field=field), self.assertRaises(ParserError) as raised:
                self.parse("silver", instrument=replace(original, **{field: value}))
            self.assertEqual(raised.exception.code, code)

    def test_invalid_dates_and_clocks_rejected(self):
        for field, value in (("date", "1404/12/30"), ("time", "24:00"), ("time", "15:60"), ("time", "15:16:00")):
            with self.subTest(field=field, value=value), self.assertRaises(ParserError):
                self.parse(source={**SOURCE, field: value})

    def test_missing_and_invalid_number_do_not_fall_back_to_other_fields(self):
        for value in (None, True, 0, -1, "NaN", "9" * 129, 10**100):
            source = copy.deepcopy(SOURCE)
            source["rates"]["dollar"] = value
            with self.subTest(value=repr(value)[:40]), self.assertRaises(ParserError):
                self.parse(source=source)
        source = copy.deepcopy(SOURCE)
        del source["usd"]["ounce"]
        source["ounce"] = 4166
        with self.assertRaises(ParserError):
            self.parse("ounce", source)

    def test_outside_instrument_sanity_bounds_rejected(self):
        source = copy.deepcopy(SOURCE)
        source["rates"]["dollar"] = 10
        with self.assertRaises(ParserError) as raised:
            self.parse(source=source)
        self.assertEqual(raised.exception.code, "outside_sanity_bounds")


class NerkhsanjExtendedHistoryTests(unittest.TestCase):
    def setUp(self):
        clock = patch("app.pricing.parsers.nerkhsanj_markets.utc_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def daily(self, symbol="dollar", rows=None, unit=None, **kwargs):
        source = {"series": [{"key": symbol, "name": "Published source", "days":
                              rows if rows is not None else [["1405/07/23", 263800]]}]}
        if unit is not None:
            source["unit"] = unit
        instrument = get_instrument(NERKHSANJ_MARKETS[symbol].instrument_id)
        return NerkhsanjMarketDailyHistoryParser(symbol).parse(source, instrument,
            kwargs.get("start", NOW - timedelta(days=365)), kwargs.get("end", NOW))

    def test_daily_toman_and_usd_archives_keep_currency_and_day_precision(self):
        for symbol, price, unit in (("dollar", 263800, None), ("gold", 26236700, None),
                ("tether", 263235, None), ("bitcoin", 21476622300, None),
                ("silver", 504840, None), ("ounce", 4166.39, "usd"), ("silver-ounce", 56.99, "usd")):
            with self.subTest(symbol=symbol):
                point, = self.daily(symbol, [["1405/07/23", price]], unit)
                self.assertEqual(point.price, Decimal(str(price)))
                self.assertEqual(point.observed_at, datetime(2026, 10, 14, 20, 30, tzinfo=UTC))
                self.assertEqual(point.metadata["timestamp_precision"], "day")
                self.assertIs(point.metadata["source_observation_time_known"], False)

    def test_dollar_archive_requires_explicit_usd_currency(self):
        for unit in (None, "IRT", "USD", "toman"):
            with self.subTest(unit=unit), self.assertRaises(ParserError) as raised:
                self.daily("ounce", [["1405/07/23", 4166]], unit)
            self.assertEqual(raised.exception.code, "currency_mismatch")

    def test_toman_archive_rejects_usd_unit(self):
        with self.assertRaises(ParserError) as raised:
            self.daily(unit="usd")
        self.assertEqual(raised.exception.code, "currency_mismatch")

    def test_current_and_future_daily_dates_excluded_without_filling_gaps(self):
        points = self.daily(rows=[["1405/07/21", 263000], ["1405/07/23", 264000],
                                  ["1405/07/25", 265000], ["1405/07/26", 266000]])
        self.assertEqual([p.metadata["source_date"] for p in points], ["1405/07/21", "1405/07/23"])

    def test_daily_duplicate_and_malformed_rows_rejected_even_outside_range(self):
        for rows in ([["1399/08/10", 20000], ["1399/08/10", 21000]],
                     [["1405/07/23", 260000, 1]], [["1404/12/30", 260000]]):
            with self.subTest(rows=rows), self.assertRaises(ParserError):
                self.daily(rows=rows)

    def test_daily_source_selection_is_unique_and_bounded(self):
        parser = NerkhsanjMarketDailyHistoryParser("dollar")
        instrument = get_instrument("USD_TOMAN")
        row = {"key": "dollar", "name": "USD", "days": []}
        for source, code in (({"series": [row, row]}, "duplicate_series"),
                             ({"series": []}, "missing_series"),
                             ({"series": [row] * 65}, "history_too_large"),
                             ({"series": [{**row, "days": [["1405/07/23", 263000]] * 20001}]}, "history_too_large")):
            with self.subTest(code=code), self.assertRaises(ParserError) as raised:
                parser.parse(source, instrument, NOW - timedelta(days=30), NOW)
            self.assertEqual(raised.exception.code, code)

    def test_daily_range_needs_timezone_and_maximum_366_days(self):
        for kwargs in ({"start": NOW.replace(tzinfo=None)}, {"start": NOW - timedelta(days=367)},
                       {"start": NOW + timedelta(days=1)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ParserError) as raised:
                self.daily(**kwargs)
            self.assertEqual(raised.exception.code, "invalid_history_range")

    def intraday(self, rows=None, **kwargs):
        source = {"date": "1405/07/25", "time": "15:16", "series": {
            "dollar": {"low": 263000, "high": 264000,
                       "points": rows if rows is not None else [["15:10", 263800], ["15:00", 263500]]}}}
        return NerkhsanjIntradayHistoryParser("dollar").parse(
            kwargs.get("source", source), get_instrument("USD_TOMAN"),
            kwargs.get("start", NOW - timedelta(days=1)), kwargs.get("end", NOW))

    def test_intraday_uses_published_ten_minute_points_without_interpolation(self):
        points = self.intraday()
        self.assertEqual([p.observed_at for p in points], [datetime(2026, 10, 17, 11, 30, tzinfo=UTC),
                                                          datetime(2026, 10, 17, 11, 40, tzinfo=UTC)])
        self.assertEqual(points[-1].metadata["source_timestamp_scope"], "publication_snapshot")
        self.assertEqual(points[-1].metadata["source_sample_interval_seconds"], 600)
        self.assertIs(points[-1].metadata["source_trade_time_known"], False)

    def test_intraday_filters_range(self):
        points = self.intraday(start=datetime(2026, 10, 17, 11, 35, tzinfo=UTC))
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].price, Decimal("263800"))

    def test_closed_market_blank_global_clock_preserves_actual_point_clocks(self):
        source = {"date": "1405/07/24", "time": "", "series": {
            "dollar": {"points": [["15:10", 263800], ["14:20", 263500]]}}}
        points = self.intraday(source=source, start=NOW - timedelta(days=2))
        self.assertEqual([point.observed_at for point in points], [
            datetime(2026, 10, 16, 10, 50, tzinfo=UTC),
            datetime(2026, 10, 16, 11, 40, tzinfo=UTC)])
        self.assertIs(points[-1].metadata["source_publication_clock_known"], False)
        self.assertEqual(points[-1].metadata["source_time"], "15:10")
        self.assertEqual(points[-1].metadata["source_sample_interval_scope"],
                         "publisher_declared_nominal_cadence")

    def test_blank_global_clock_still_rejects_future_point_and_bad_source_day(self):
        for source in (
            {"date": "1405/07/25", "time": "", "series": {"dollar": {"points": [["15:20", 263800]]}}},
            {"date": "bad", "time": "", "series": {}},
            {"date": "1405/07/26", "time": "", "series": {}},
        ):
            with self.subTest(source=source), self.assertRaises(ParserError):
                self.intraday(source=source)

    def test_intraday_rejects_duplicate_future_and_overfull_points(self):
        for rows in ([["15:10", 263000], ["15:10", 264000]], [["15:20", 263000]],
                     [["15:00", 263000]] * 145, [["24:00", 263000]]):
            with self.subTest(rows=str(rows)[:100]), self.assertRaises(ParserError):
                self.intraday(rows)

    def test_intraday_has_no_usd_leg(self):
        with self.assertRaises(ParserError) as raised:
            NerkhsanjIntradayHistoryParser("ounce").parse(
                {"date": "1405/07/25", "time": "15:16", "series": {"ounce": {"points": []}}},
                get_instrument("XAU_USD_OZ"), NOW - timedelta(days=1), NOW)
        self.assertEqual(raised.exception.code, "unsupported_symbol")

    def test_intraday_rejects_future_publication_and_bad_price(self):
        with self.assertRaises(ParserError):
            self.intraday(source={"date": "1405/07/26", "time": "15:16", "series": {}})
        with self.assertRaises(ParserError) as raised:
            self.intraday([["15:10", 10]])
        self.assertEqual(raised.exception.code, "outside_sanity_bounds")


if __name__ == "__main__":
    unittest.main()
