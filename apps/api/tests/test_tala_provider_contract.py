from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.pricing.instruments import get_instrument
from app.pricing.parsers.base import ParserContext, ParserError
from app.pricing.parsers.local_reference import TalaRatesParser


NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


class TalaProviderContractTests(unittest.TestCase):
    """Official response shape with fixed local sample values."""

    def setUp(self) -> None:
        self.parser = TalaRatesParser("geram24k")
        self.context = ParserContext(get_instrument("GOLD_24K_TOMAN_GRAM"), NOW, 300)
        self.row = {
            "key": "geram24k",
            "title": "گرم 24 عیار",
            "value": "8000000",
            "unit": "تومان",
            "source_key": "geram24k",
            "updated_at": "2026-10-17T13:29:30+03:30",
            "status": "ok",
        }

    def payload(self, **updates: object) -> dict:
        row = deepcopy(self.row)
        row.update(updates)
        return {
            "success": True,
            "generated_at": NOW.isoformat(),
            "count": 1,
            "rates": [row],
            "meta": {"max_keys": 10, "includes_prices": True},
        }

    def assert_rejected(self, payload: object, code: str) -> None:
        with self.assertRaises(ParserError) as raised:
            self.parser.parse(payload, self.context)
        self.assertEqual(raised.exception.code, code)

    def test_official_rates_wrapper_preserves_source_time_and_toman_price(self) -> None:
        parsed = self.parser.parse(self.payload(), self.context)
        self.assertEqual(parsed.price, Decimal("8000000"))
        self.assertEqual(parsed.observed_at, NOW - timedelta(seconds=30))
        self.assertEqual(parsed.metadata["source_currency"], "TOMAN")
        self.assertEqual(parsed.metadata["conversion_factor"], "1")
        self.assertEqual(parsed.metadata["normalization"], "none")
        self.assertIsNone(parsed.bid)
        self.assertIsNone(parsed.ask)

    def test_parser_version_changes_with_contract(self) -> None:
        self.assertEqual(self.parser.parser_version, "tala-rates/1.1.0")

    def test_rial_is_converted_exactly_once_from_explicit_unit(self) -> None:
        for unit in ("RIAL", "IRR", "RLS", "ریال"):
            with self.subTest(unit=unit):
                parsed = self.parser.parse(self.payload(unit=unit, value="80000000"), self.context)
                self.assertEqual(parsed.price, Decimal("8000000.0"))
                self.assertEqual(parsed.metadata["source_currency"], "RIAL")
                self.assertEqual(parsed.metadata["original_value"], "80000000")
                self.assertEqual(parsed.metadata["normalization"], "rial_to_toman")

    def test_foreign_currency_does_not_become_toman(self) -> None:
        for unit in ("USD", "USDT"):
            with self.subTest(unit=unit):
                self.assert_rejected(self.payload(unit=unit), "currency_mismatch")

    def test_unknown_or_missing_unit_is_rejected(self) -> None:
        for unit in (None, "", "gold", "دلار", True):
            with self.subTest(unit=unit):
                self.assert_rejected(self.payload(unit=unit), "unknown_unit")
        payload = self.payload()
        del payload["rates"][0]["unit"]
        self.assert_rejected(payload, "unknown_unit")

    def test_explicit_failed_response_cannot_supply_a_price(self) -> None:
        payload = self.payload()
        payload["success"] = False
        self.assert_rejected(payload, "provider_disabled")

    def test_malformed_success_flag_is_rejected(self) -> None:
        for success in ("false", "true", 0, 1, None):
            with self.subTest(success=success):
                payload = self.payload()
                payload["success"] = success
                self.assert_rejected(payload, "provider_disabled")

    def test_only_explicit_usable_statuses_are_accepted(self) -> None:
        for status in ("ok", "active", "live", " OK "):
            with self.subTest(status=status):
                parsed = self.parser.parse(self.payload(status=status), self.context)
                self.assertEqual(parsed.price, Decimal("8000000"))

    def test_inactive_unknown_or_missing_status_is_rejected(self) -> None:
        for status in ("error", "inactive", "disabled", "", None, True):
            with self.subTest(status=status):
                self.assert_rejected(self.payload(status=status), "provider_disabled")
        payload = self.payload()
        del payload["rates"][0]["status"]
        self.assert_rejected(payload, "provider_disabled")

    def test_missing_source_time_cannot_use_response_or_receive_time(self) -> None:
        payload = self.payload()
        del payload["rates"][0]["updated_at"]
        self.assert_rejected(payload, "invalid_timestamp")

    def test_source_time_requires_explicit_timezone(self) -> None:
        for value in ("2026-10-17T09:59:30", "2026-10-17 09:59:30", "2026-10-17"):
            with self.subTest(value=value):
                self.assert_rejected(self.payload(updated_at=value), "invalid_timestamp")

    def test_source_time_requires_valid_iso_text(self) -> None:
        for value in (None, "", "bad-time", 1792223970, True, "2026-10-17T09:59:30+25:00"):
            with self.subTest(value=value):
                self.assert_rejected(self.payload(updated_at=value), "invalid_timestamp")

    def test_utc_source_time_is_accepted(self) -> None:
        parsed = self.parser.parse(self.payload(updated_at="2026-10-17T09:59:30Z"), self.context)
        self.assertEqual(parsed.observed_at, NOW - timedelta(seconds=30))

    def test_fresh_response_does_not_hide_stale_source_time(self) -> None:
        self.assert_rejected(
            self.payload(updated_at=(NOW - timedelta(seconds=301)).isoformat()), "stale_timestamp"
        )

    def test_future_source_time_is_rejected(self) -> None:
        self.assert_rejected(
            self.payload(updated_at=(NOW + timedelta(hours=1)).isoformat()), "stale_timestamp"
        )

    def test_duplicate_selected_keys_are_rejected_even_with_equal_prices(self) -> None:
        payload = self.payload()
        payload["rates"].append({**self.row, "key": "GERAM24K"})
        self.assert_rejected(payload, "ambiguous_symbol")

    def test_duplicate_selected_keys_in_dictionary_are_rejected(self) -> None:
        payload = self.payload()
        payload["rates"] = {"geram24k": self.row, "other": {**self.row, "key": "GERAM24K"}}
        self.assert_rejected(payload, "ambiguous_symbol")

    def test_dictionary_key_cannot_override_embedded_wrong_symbol(self) -> None:
        payload = self.payload()
        payload["rates"] = {"geram24k": {**self.row, "key": "geram18k"}}
        self.assert_rejected(payload, "unsupported_symbol")

    def test_embedded_selected_symbol_cannot_hide_wrong_dictionary_key(self) -> None:
        payload = self.payload()
        payload["rates"] = {"geram18k": self.row}
        self.assert_rejected(payload, "unsupported_symbol")

    def test_matching_dictionary_and_legacy_wrapper_are_accepted(self) -> None:
        for field in ("rates", "data", "result"):
            with self.subTest(field=field):
                parsed = self.parser.parse({field: {"geram24k": self.row}}, self.context)
                self.assertEqual(parsed.price, Decimal("8000000"))

    def test_selected_rate_does_not_use_another_symbol(self) -> None:
        payload = self.payload()
        payload["rates"].insert(0, {**self.row, "key": "geram18k", "value": "6000000"})
        parsed = self.parser.parse(payload, self.context)
        self.assertEqual(parsed.price, Decimal("8000000"))

    def test_empty_official_rates_does_not_fall_back_to_other_wrapper(self) -> None:
        payload = self.payload()
        payload["rates"] = []
        payload["data"] = [self.row]
        self.assert_rejected(payload, "unsupported_symbol")

    def test_missing_selected_rate_is_rejected(self) -> None:
        self.assert_rejected(self.payload(key="geram18k"), "unsupported_symbol")

    def test_invalid_price_cannot_use_other_fields(self) -> None:
        for value in (None, False, 0, -1, "NaN", "Infinity", "bad-price"):
            with self.subTest(value=value):
                self.assert_rejected(self.payload(value=value, price="8000000"), "invalid_number")

    def test_missing_value_does_not_use_other_price_field(self) -> None:
        payload = self.payload(price="8000000")
        del payload["rates"][0]["value"]
        self.assert_rejected(payload, "missing_field")

    def test_catalog_without_prices_is_rejected(self) -> None:
        self.assert_rejected({"success": True, "references": [self.row]}, "invalid_shape")


if __name__ == "__main__":
    unittest.main()
