from __future__ import annotations

import copy
import json
import os
import unittest
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import INSTRUMENTS
from app.pricing.parsers.base import ParserError
from app.pricing.reference_rates import (
    HISTORY_PROVIDER_ID, REFERENCE_IDS, SNAPSHOT_PROVIDER_ID,
    build_reference_history, build_reference_snapshot, reference_definitions,
    validate_reference_record,
)


NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
GOLD, BTC, USDT = REFERENCE_IDS


def snapshot():
    return {"date": "1405/07/25", "time": "15:30", "rates": {
        "gold24": 35_000_000, "bitcoin": 20_000_000_000,
        "tether": 275_000, "dollar": 250_000,
    }}


def archive():
    return {"updated": "1405/07/24", "series": [
        {"key": "gold24", "name": "Gold24", "days": [
            ["1405/07/22", 32_000_000], ["1405/07/23", 33_000_000], ["1405/07/24", 34_000_000]]},
        {"key": "dollar", "name": "USD/Toman", "days": [
            ["1405/07/22", 200_000], ["1405/07/24", 250_000]]},
        {"key": "bitcoin", "name": "BTC/Toman", "days": [
            ["1405/07/22", 16_000_000_000], ["1405/07/23", 18_000_000_000],
            ["1405/07/24", 20_000_000_000]]},
        {"key": "tether", "name": "USDT/Toman", "days": [
            ["1405/07/22", 220_000], ["1405/07/23", 240_000], ["1405/07/24", 275_000]]},
    ]}


class IranianReferenceSnapshotTests(unittest.TestCase):
    def parse(self, payload=None, *, received_at=NOW, now=NOW):
        return {item["instrument_id"]: item for item in build_reference_snapshot(
            payload if payload is not None else snapshot(), received_at=received_at, now=now)}

    def test_published_gold_and_actual_fx_ratios_are_separate_reference_contracts(self):
        values = self.parse()
        self.assertEqual(set(values), set(REFERENCE_IDS))
        self.assertEqual([values[key]["price"] for key in REFERENCE_IDS], [35_000_000, 80_000, 1.1])
        self.assertEqual(values[GOLD]["method"], "published_reference")
        self.assertEqual(values[BTC]["method"], "iran_fx_ratio")
        self.assertEqual(values[USDT]["price_decimal"], "1.1")
        for item in values.values():
            self.assertEqual(item["market"], "reference")
            self.assertEqual(item["region"], "iran")
            self.assertEqual(item["source_provider_id"], SNAPSHOT_PROVIDER_ID)
            self.assertFalse(item["physical_purity_confirmed"])
            self.assertFalse(item["source_trade_time_known"])
            self.assertFalse(item["source_observation_time_known"])

    def test_native_gold24_is_used_without_gold18_conversion_or_physical_claim(self):
        payload = snapshot()
        payload["rates"]["gold"] = 1
        values = self.parse(payload)
        self.assertEqual(values[GOLD]["price"], 35_000_000)
        self.assertIsNone(values[GOLD]["purity"])
        self.assertEqual(values[GOLD]["nominal_karat"], 24)
        self.assertEqual(values[GOLD]["inputs"][0]["instrument_id"], GOLD)
        self.assertNotIn("GOLD_24K_TOMAN_GRAM", json.dumps(values))
        self.assertEqual(INSTRUMENTS["GOLD_24K_TOMAN_GRAM"].purity, Decimal("0.9999"))
        self.assertTrue(set(REFERENCE_IDS).isdisjoint(INSTRUMENTS))

    def test_ratio_has_both_actual_parent_prices_and_no_usdt_peg(self):
        item = self.parse()[USDT]
        self.assertEqual([parent["source_key"] for parent in item["inputs"]], ["tether", "dollar"])
        self.assertEqual([parent["price"] for parent in item["inputs"]], [275_000, 250_000])
        self.assertEqual({parent["currency"] for parent in item["inputs"]}, {"TOMAN"})
        self.assertIn("جهانی", item["disclaimer_fa"])
        self.assertNotEqual(item["price"], 1)

    def test_original_clocks_and_last_change_scope_survive_cached_reuse(self):
        received = NOW + timedelta(seconds=5)
        item = self.parse(received_at=received, now=NOW + timedelta(seconds=120))[BTC]
        self.assertEqual(item["received_at"], received.isoformat())
        self.assertEqual(item["observed_at"], NOW.isoformat())
        self.assertEqual(item["age_seconds"], 120)
        self.assertEqual(item["source_timestamp_scope"], "source_rates_last_change")
        self.assertEqual(item["status"], "delayed_reference")
        self.assertEqual(item["inputs"][0]["as_of"], NOW.isoformat())

    def test_fresh_reference_limits_do_not_relax_parent_operational_ttls(self):
        definitions = {item["instrument_id"]: item for item in reference_definitions()}
        self.assertEqual(definitions[GOLD]["freshness_limit_seconds"], 300)
        self.assertEqual(definitions[BTC]["freshness_limit_seconds"], 20)
        self.assertEqual(definitions[USDT]["freshness_limit_seconds"], 20)
        for seconds, expected in ((20, "fresh_reference"), (20.001, "delayed_reference")):
            self.assertEqual(self.parse(now=NOW + timedelta(seconds=seconds))[BTC]["status"], expected)
        self.assertEqual(self.parse(now=NOW + timedelta(seconds=300))[GOLD]["status"], "fresh_reference")
        self.assertEqual(self.parse(now=NOW + timedelta(seconds=301))[GOLD]["status"], "delayed_reference")

    def test_37_minute_reference_retains_value_with_an_explicit_delayed_status(self):
        values = self.parse(now=NOW + timedelta(minutes=37))
        self.assertTrue(all(item["status"] == "delayed_reference" for item in values.values()))
        self.assertTrue(all(item["price"] is not None and item["age_seconds"] == 2220 for item in values.values()))

    def test_24_hour_boundary_then_unavailable_without_a_new_receipt(self):
        for seconds, expected in ((86400, "delayed_reference"), (86400.001, "unavailable_reference")):
            with self.subTest(seconds=seconds):
                values = self.parse(now=NOW + timedelta(seconds=seconds))
                self.assertTrue(all(item["status"] == expected for item in values.values()))
                for item in values.values():
                    self.assertEqual(item["received_at"], NOW.isoformat())
                    self.assertEqual(item["maximum_reference_age_seconds"], 86400)
                    if seconds > 86400:
                        self.assertIsNone(item["price"])
                        self.assertIsNone(item["price_decimal"])
                        self.assertEqual(item["unavailable_reason"], "source_older_than_24_hours")

    def test_missing_or_bad_parent_withholds_only_affected_references(self):
        for key, affected in (("gold24", {GOLD}), ("bitcoin", {BTC}), ("tether", {USDT}), ("dollar", {BTC, USDT})):
            with self.subTest(key=key):
                payload = snapshot()
                del payload["rates"][key]
                values = self.parse(payload)
                for instrument, item in values.items():
                    self.assertEqual(item["status"], "unavailable_reference" if instrument in affected else "fresh_reference")

    def test_nonfinite_boolean_zero_negative_and_unbounded_money_is_not_a_price(self):
        for value in (None, True, 0, -1, "NaN", float("nan"), float("inf"), Decimal("NaN"),
                      Decimal("1e-100000"), 10**100, "1" * 129, [], {}):
            with self.subTest(value=value):
                payload = snapshot()
                payload["rates"]["tether"] = value
                values = self.parse(payload)
                self.assertIsNone(values[USDT]["price"])
                self.assertEqual(values[USDT]["status"], "unavailable_reference")
                self.assertEqual(values[BTC]["status"], "fresh_reference")

    def test_bounded_parent_values_cannot_produce_an_unbounded_ratio(self):
        payload = snapshot()
        payload["rates"]["bitcoin"] = Decimal("1e18")
        payload["rates"]["dollar"] = Decimal("1e-12")
        item = self.parse(payload)[BTC]
        self.assertIsNone(item["price"])
        self.assertEqual(item["unavailable_reason"], "outside_sanity_bounds")

    def test_missing_closed_market_clock_is_unavailable_and_never_uses_receive_time(self):
        for clock in (None, ""):
            payload = snapshot()
            payload["time"] = clock
            for item in self.parse(payload).values():
                self.assertEqual(item["status"], "unavailable_reference")
                self.assertIsNone(item["observed_at"])
                self.assertIsNone(item["age_seconds"])
                self.assertEqual(item["unavailable_reason"], "source_clock_unavailable")

    def test_invalid_or_future_source_clocks_fail_without_current_quote_fallback(self):
        for changes in ({"date": "1405/07/26"}, {"time": "15:31"}, {"time": "24:00"},
                        {"time": "15:30:00"}, {"date": "1405/99/01"}):
            with self.subTest(changes=changes):
                payload = snapshot()
                payload.update(changes)
                with self.assertRaises(ParserError):
                    self.parse(payload)

    def test_clock_inputs_require_timezones_and_future_receipt_is_rejected(self):
        for received, now in ((NOW.replace(tzinfo=None), NOW), (NOW, NOW.replace(tzinfo=None)),
                              (NOW + timedelta(seconds=31), NOW)):
            with self.subTest(received=received, now=now), self.assertRaises(ParserError):
                self.parse(received_at=received, now=now)
        offset = timezone(timedelta(hours=3, minutes=30))
        item = self.parse(received_at=NOW.astimezone(offset), now=NOW.astimezone(offset))[BTC]
        self.assertEqual(item["received_at"], NOW.isoformat())

    def test_global_payload_unit_shape_and_key_count_are_bounded(self):
        for payload in ([], {**snapshot(), "unit": "usd"}, {**snapshot(), "rates": []},
                        {**snapshot(), "rates": {str(index): 1 for index in range(65)}}):
            with self.subTest(payload=type(payload).__name__), self.assertRaises(ParserError):
                self.parse(payload)

    def test_decimal_precision_json_and_definition_copy_are_stable(self):
        payload = snapshot()
        payload["rates"].update(bitcoin=1, dollar=3)
        item = self.parse(payload)[BTC]
        self.assertEqual(item["price_decimal"], "0.3333333333333333333333333333")
        json.dumps(self.parse(payload), allow_nan=False)
        definitions = reference_definitions()
        definitions[0]["attribution"]["label"] = "changed"
        self.assertEqual(reference_definitions()[0]["attribution"]["label"], "نرخ‌سنج")


class IranianReferenceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("app.pricing.reference_rates.utc_now", return_value=NOW))

    def parse(self, payload=None, *, start=NOW - timedelta(days=7), end=NOW):
        return build_reference_history(payload if payload is not None else archive(), range_start=start, range_end=end)

    def test_daily_ratios_inner_join_the_exact_published_day_without_gap_fill(self):
        history = self.parse()
        self.assertEqual(len(history[GOLD]), 3)
        for instrument in (BTC, USDT):
            self.assertEqual([point["source_date"] for point in history[instrument]], ["1405/07/22", "1405/07/24"])
            self.assertEqual([point["price"] for point in history[instrument]], [80000, 80000] if instrument == BTC else [1.1, 1.1])
            for point in history[instrument]:
                self.assertTrue(all(parent["source_date"] == point["source_date"] for parent in point["inputs"]))
                self.assertEqual(len(point["inputs"]), 2)

    def test_gold_daily_uses_published_gold24_and_never_18k_or_9999_relabels(self):
        history = self.parse()
        self.assertEqual([point["price"] for point in history[GOLD]], [32_000_000, 33_000_000, 34_000_000])
        for point in history[GOLD]:
            self.assertEqual(point["method"], "published_reference")
            self.assertEqual(point["inputs"][0]["source_key"], "gold24")
            self.assertIsNone(point["purity"])
        self.assertNotIn("GOLD_24K_TOMAN_GRAM", json.dumps(history))

    def test_daily_bucket_has_tehran_midnight_and_unknown_true_observation_clock(self):
        point = self.parse()[GOLD][-1]
        self.assertEqual(point["timestamp"], "2026-10-15T20:30:00+00:00")
        self.assertEqual(point["source_date"], "1405/07/24")
        self.assertEqual(point["source_timezone"], "Asia/Tehran")
        self.assertEqual(point["source_calendar"], "jalali")
        self.assertEqual(point["timestamp_precision"], "day")
        self.assertEqual(point["timestamp_role"], "day_bucket_start")
        self.assertFalse(point["source_observation_time_known"])
        self.assertIsNone(point["source_time"])
        self.assertEqual(point["source_provider_id"], HISTORY_PROVIDER_ID)

    def test_daily_output_is_json_safe_and_does_not_mutate_source_rows(self):
        payload = archive()
        saved = copy.deepcopy(payload)
        json.dumps(self.parse(payload), allow_nan=False)
        self.assertEqual(payload, saved)

    def test_missing_daily_parents_create_empty_references_not_cross_date_fallbacks(self):
        for missing, empty in (("dollar", {BTC, USDT}), ("gold24", {GOLD}), ("bitcoin", {BTC})):
            payload = archive()
            payload["series"] = [item for item in payload["series"] if item["key"] != missing]
            result = self.parse(payload)
            for instrument in REFERENCE_IDS:
                self.assertEqual(result[instrument] == [], instrument in empty)

    def test_duplicate_series_and_duplicate_days_fail_even_outside_requested_window(self):
        duplicate_series = archive()
        duplicate_series["series"].append(copy.deepcopy(duplicate_series["series"][0]))
        duplicate_day = archive()
        duplicate_day["series"][0]["days"].append(["1405/07/22", 1])
        for payload in (duplicate_series, duplicate_day):
            with self.subTest(kind=len(payload["series"])), self.assertRaises(ParserError):
                self.parse(payload, start=NOW - timedelta(days=1))

    def test_invalid_date_money_or_row_shape_is_rejected(self):
        for row in (["1405/13/01", 1], ["1405/07/24", 0], ["1405/07/24", True],
                    ["1405/07/24", float("nan")], ["1405/07/24", 10**100], ["1405/07/24"], {}):
            payload = archive()
            payload["series"][0]["days"] = [row]
            with self.subTest(row=row), self.assertRaises(ParserError):
                self.parse(payload)

    def test_open_today_is_excluded_without_faking_a_completed_daily_price(self):
        payload = archive()
        payload["updated"] = "1405/07/25"
        payload["series"][0]["days"].append(["1405/07/25", 36_000_000])
        self.assertEqual(len(self.parse(payload)[GOLD]), 3)

    def test_future_source_day_or_future_archive_date_is_rejected(self):
        for updated, day in (("1405/07/26", "1405/07/24"), ("1405/07/25", "1405/07/26"),
                             ("1405/07/23", "1405/07/24")):
            payload = archive()
            payload["updated"] = updated
            payload["series"][0]["days"] = [[day, 35_000_000]]
            with self.subTest(updated=updated, day=day), self.assertRaises(ParserError):
                self.parse(payload)

    def test_requested_end_cannot_include_an_unfinished_day_at_that_time(self):
        history = self.parse(end=datetime(2026, 10, 16, 18, tzinfo=UTC))
        self.assertEqual([point["source_date"] for point in history[GOLD]], ["1405/07/22", "1405/07/23"])

    def test_range_limits_naive_clocks_and_wrong_currency_fail(self):
        for start, end in ((NOW, NOW - timedelta(days=1)), (NOW - timedelta(days=367), NOW),
                           (NOW.replace(tzinfo=None), NOW)):
            with self.subTest(start=start, end=end), self.assertRaises(ParserError):
                self.parse(start=start, end=end)
        with self.assertRaises(ParserError):
            self.parse({**archive(), "unit": "usd"})

    def test_history_series_names_rows_and_counts_are_bounded(self):
        too_many = {"series": [archive()["series"][0]] * 65}
        bad_name = archive()
        bad_name["series"][0]["name"] = "x" * 201
        too_many_rows = archive()
        too_many_rows["series"][0]["days"] = [["1405/07/24", 1]] * 20_001
        for payload in (too_many, bad_name, too_many_rows, {"series": {}}, []):
            with self.subTest(kind=type(payload).__name__), self.assertRaises(ParserError):
                self.parse(payload)

    def test_unordered_days_are_sorted_and_range_bounds_are_preserved(self):
        payload = archive()
        payload["series"][0]["days"].reverse()
        history = self.parse(payload, start=datetime(2026, 10, 14, 20, 30, tzinfo=UTC))
        self.assertEqual([point["source_date"] for point in history[GOLD]], ["1405/07/23", "1405/07/24"])


class IranianReferenceRecordValidationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("app.pricing.reference_rates.utc_now", return_value=NOW))
        self.current = build_reference_snapshot(snapshot(), received_at=NOW, now=NOW)
        self.history = build_reference_history(archive(), range_start=NOW - timedelta(days=7), range_end=NOW)

    def assert_invalid(self, item, kind, path, value):
        changed = copy.deepcopy(item)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with self.subTest(kind=kind, path=path, value=value), self.assertRaises(ParserError):
            validate_reference_record(changed, kind)

    def test_generated_contracts_validate_and_old_status_can_be_reaged(self):
        for item in self.current:
            validate_reference_record(item, "snapshot")
            validate_reference_record(item, "snapshot", now=NOW + timedelta(days=2))
        for points in self.history.values():
            for item in points:
                validate_reference_record(item, "history")
        payload = snapshot()
        payload["rates"].update(bitcoin=1, dollar=3)
        item = build_reference_snapshot(payload, received_at=NOW, now=NOW)[1]
        validate_reference_record(item, "snapshot")

    def test_each_named_contract_rejects_another_currency_method_or_source_identity(self):
        for index, item in enumerate(self.current):
            for key, value in (("currency", "USD" if index == 0 else "TOMAN"),
                               ("weight_unit", "unit" if index == 0 else "gram"),
                               ("method", "iran_fx_ratio" if index == 0 else "published_reference"),
                               ("is_derived", index == 0), ("nominal_karat", None if index == 0 else 24),
                               ("purity", "0.9999"), ("physical_purity_confirmed", True),
                               ("source_provider_id", HISTORY_PROVIDER_ID), ("source_keys", ["gold"]),
                               ("market", "spot"), ("region", "global")):
                self.assert_invalid(item, "snapshot", (key,), value)

    def test_parent_contracts_and_arithmetic_reject_tampering(self):
        for kind, item in (("snapshot", self.current[1]), ("history", self.history[BTC][0])):
            for path, value in ((("inputs",), []), (("inputs", 0, "source_key"), "tether"),
                                (("inputs", 0, "instrument_id"), "BTC_USD"),
                                (("inputs", 1, "currency"), "USD"),
                                (("inputs", 1, "source_date"), "1405/07/21"),
                                (("inputs", 0, "price"), 1), (("price",), 1),
                                (("inputs", 0, "price_decimal"), "1"), (("price_decimal",), "1")):
                self.assert_invalid(item, kind, path, value)
            changed = copy.deepcopy(item)
            changed["inputs"][0].update(price=1, price_decimal="1")
            with self.assertRaises(ParserError):
                validate_reference_record(changed, kind)
        self.assert_invalid(self.current[0], "snapshot", ("inputs", 0, "instrument_id"), "GOLD_24K_TOMAN_GRAM")

    def test_decimal_strings_and_matching_finite_bounded_numbers_are_required(self):
        for value in (None, 1, True, "NaN", "Infinity", "0", "-1", "1e-13", "1e19", "1" * 129):
            self.assert_invalid(self.current[1], "snapshot", ("price_decimal",), value)
            self.assert_invalid(self.current[1], "snapshot", ("inputs", 0, "price_decimal"), value)
        for value in (True, float("nan"), float("inf"), "80000"):
            self.assert_invalid(self.current[1], "snapshot", ("price",), value)

    def test_snapshot_requires_exact_original_tehran_clock_and_parent_clock(self):
        item = self.current[1]
        for path, value in ((("observed_at",), NOW.replace(tzinfo=None).isoformat()),
                            (("received_at",), NOW.replace(tzinfo=None).isoformat()),
                            (("source_date",), "1405/07/24"), (("source_time",), "15:30:00"),
                            (("source_time",), None), (("source_timestamp_precision",), "instant"),
                            (("source_timestamp_scope",), "publication_snapshot"),
                            (("source_timezone",), "UTC"), (("source_calendar",), "gregorian"),
                            (("source_observation_time_known",), True), (("source_trade_time_known",), True),
                            (("inputs", 0, "as_of"), (NOW - timedelta(minutes=1)).isoformat()),
                            (("inputs", 0, "timestamp_precision"), "day"),
                            (("inputs", 0, "timestamp_role"), "day_bucket_start")):
            self.assert_invalid(item, "snapshot", path, value)
        self.assert_invalid(item, "snapshot", ("received_at",), (NOW - timedelta(seconds=31)).isoformat())
        self.assert_invalid(item, "snapshot", ("received_at",), (NOW + timedelta(seconds=31)).isoformat())
        with self.assertRaises(ParserError):
            validate_reference_record(item, "snapshot", now=NOW - timedelta(seconds=31))

    def test_history_requires_exact_closed_tehran_day_and_daily_parent_metadata(self):
        item = self.history[BTC][-1]
        for path, value in ((("timestamp",), (NOW - timedelta(days=1)).isoformat()),
                            (("source_time",), "00:00"), (("source_timestamp_scope",), "source_rates_last_change"),
                            (("timestamp_precision",), "minute"), (("timestamp_role",), "observation"),
                            (("history_point_kind",), "published_reference_daily_close"),
                            (("source_provider_id",), SNAPSHOT_PROVIDER_ID),
                            (("inputs", 0, "timestamp_precision"), "minute"),
                            (("inputs", 0, "timestamp_role"), "source_rates_last_change")):
            self.assert_invalid(item, "history", path, value)
        with self.assertRaises(ParserError):
            validate_reference_record(item, "history", now=datetime(2026, 10, 16, 18, tzinfo=UTC))

    def test_unknown_contract_or_record_kind_fails_with_parser_error(self):
        self.assert_invalid(self.current[0], "snapshot", ("instrument_id",), "GOLD_24K_TOMAN_GRAM")
        with self.assertRaises(ParserError):
            validate_reference_record(self.current[0], "native")


if __name__ == "__main__":
    unittest.main()
