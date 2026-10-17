from __future__ import annotations

import copy
import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import INSTRUMENTS
from app.pricing.models import Currency, WeightUnit
from app.pricing.parsers.base import ParserContext, ParserError
from app.pricing.parsers.gta_silver import GtaSilver925Parser


# Selected public fields from the bounded 2026-10-17 source sample.
SAMPLED_PAYLOAD = {
    "ok": True,
    "source": "GTA Silver",
    "source_url": "https://gtasilver.com/silver-price",
    "currency": "IRT",
    "updated_at": "2026-10-17T13:10:01+03:30",
    "prices": {
        "gram_990": 481750,
        "gram_925": 450120,
        "mesghal_990": 2220000,
        "troy_ounce_usd": 57.3,
    },
    "items": [
        {"title": "ساچمه ایرانی", "purity": 990, "buy_toman": 2140000, "sell_toman": 2220000},
        {"title": "نقره عیار 925", "purity": 925, "buy_toman": 433900, "sell_toman": 450120},
    ],
}


def context(instrument_id: str = "SILVER_925_TOMAN_GRAM") -> ParserContext:
    return ParserContext(
        instrument=INSTRUMENTS[instrument_id],
        received_at=datetime(2026, 10, 17, 11, 49, 18, tzinfo=UTC),
        maximum_timestamp_age_seconds=360,
    )


def fresh_payload() -> dict[str, object]:
    payload = copy.deepcopy(SAMPLED_PAYLOAD)
    payload["updated_at"] = "2026-10-17T15:19:00+03:30"
    return payload


class GtaSilver925ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = GtaSilver925Parser()

    def assert_rejected(self, payload: object, code: str | None = None) -> None:
        with self.assertRaises(ParserError) as caught:
            self.parser.parse(payload, context())
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def test_native_toman_925_gram_preserves_sell_and_buy(self) -> None:
        parsed = self.parser.parse(fresh_payload(), context())
        self.assertEqual(parsed.price, Decimal("450120"))
        self.assertEqual(parsed.bid, Decimal("433900"))
        self.assertEqual(parsed.ask, parsed.price)
        self.assertIs(parsed.currency, Currency.TOMAN)
        self.assertIs(parsed.weight_unit, WeightUnit.GRAM)
        self.assertEqual(parsed.purity, Decimal("0.925"))
        self.assertEqual(parsed.observed_at, datetime(2026, 10, 17, 11, 49, tzinfo=UTC))
        self.assertEqual(parsed.metadata["selected_price_field"], "prices.gram_925")
        self.assertEqual(parsed.metadata["conversion_factor"], "1")
        self.assertTrue(parsed.metadata["provider_timestamp_available"])

    def test_actual_public_sample_remains_stale(self) -> None:
        self.assertEqual(
            (context().received_at - datetime.fromisoformat(SAMPLED_PAYLOAD["updated_at"])).total_seconds(),
            7757,
        )
        self.assert_rejected(copy.deepcopy(SAMPLED_PAYLOAD), "stale_timestamp")

    def test_999_and_other_instruments_cannot_relabel_990(self) -> None:
        for instrument in ("SILVER_999_TOMAN_GRAM", "XAG_USD_OZ", "GOLD_18K_TOMAN_GRAM"):
            with self.subTest(instrument=instrument), self.assertRaises(ParserError) as caught:
                self.parser.parse(fresh_payload(), context(instrument))
            self.assertEqual(caught.exception.code, "instrument_mismatch")

    def test_mutated_instrument_units_or_purity_are_rejected(self) -> None:
        base = context()
        for changes in ({"purity": Decimal("0.999")}, {"weight_unit": WeightUnit.UNIT}, {"quote_currency": Currency.USD}):
            altered = replace(base, instrument=replace(base.instrument, **changes))
            with self.subTest(changes=changes), self.assertRaises(ParserError):
                self.parser.parse(fresh_payload(), altered)

    def test_response_must_be_success_object(self) -> None:
        for payload in (None, [], "", {"ok": 1}, {"ok": False}, {"ok": "true"}):
            with self.subTest(payload=payload):
                self.assert_rejected(payload)

    def test_currency_is_explicit_irt_only(self) -> None:
        for unit in (None, "", "IRR", "RIAL", "USD", "USDT", "TOMAN", 1, [], {}):
            payload = fresh_payload()
            payload["currency"] = unit
            with self.subTest(unit=unit):
                self.assert_rejected(payload, "currency_mismatch")
        payload = fresh_payload()
        del payload["currency"]
        self.assert_rejected(payload, "currency_mismatch")

    def test_missing_925_never_uses_990_mesghal_or_ounce(self) -> None:
        payload = fresh_payload()
        del payload["prices"]["gram_925"]
        self.assert_rejected(payload, "missing_field")

    def test_malformed_and_out_of_bounds_prices_are_rejected(self) -> None:
        for price in (None, True, 0, -1, "nan", float("inf"), [], {}, 999, 10000001):
            payload = fresh_payload()
            payload.pop("items")
            payload["prices"]["gram_925"] = price
            with self.subTest(price=price):
                self.assert_rejected(payload)

    def test_missing_naive_and_non_iso_source_times_are_rejected(self) -> None:
        for stamp in (None, "", "2026-10-17", "2026-10-17T11:49:00", "not-a-time", True, 1792237740, [], {}):
            payload = fresh_payload()
            payload["updated_at"] = stamp
            with self.subTest(stamp=stamp):
                self.assert_rejected(payload, "invalid_timestamp")
        payload = fresh_payload()
        del payload["updated_at"]
        self.assert_rejected(payload, "missing_field")

    def test_stale_future_or_receive_time_cannot_freshen_source(self) -> None:
        for stamp in ("2026-10-17T11:40:00Z", "2026-10-17T12:49:00Z"):
            payload = fresh_payload()
            payload.update(updated_at=stamp, received_at=context().received_at.isoformat())
            with self.subTest(stamp=stamp):
                self.assert_rejected(payload, "stale_timestamp")

    def test_utc_timestamp_matches_offset_timestamp(self) -> None:
        local = self.parser.parse(fresh_payload(), context())
        payload = fresh_payload()
        payload["updated_at"] = "2026-10-17T11:49:00Z"
        self.assertEqual(self.parser.parse(payload, context()).observed_at, local.observed_at)

    def test_no_items_does_not_invent_buy_or_sell(self) -> None:
        payload = fresh_payload()
        payload.pop("items")
        parsed = self.parser.parse(payload, context())
        self.assertEqual(parsed.price, Decimal("450120"))
        self.assertIsNone(parsed.bid)
        self.assertIsNone(parsed.ask)
        self.assertFalse(parsed.metadata["bid_ask_available"])

    def test_other_weighted_items_never_supply_gram_sides(self) -> None:
        payload = fresh_payload()
        payload["items"] = [{"title": "شمش 500 گرمی", "purity": 925, "buy_toman": 1, "sell_toman": 450120}]
        parsed = self.parser.parse(payload, context())
        self.assertIsNone(parsed.bid)
        self.assertIsNone(parsed.ask)

    def test_duplicate_gram_items_are_ambiguous(self) -> None:
        payload = fresh_payload()
        payload["items"].append(copy.deepcopy(payload["items"][1]))
        self.assert_rejected(payload, "ambiguous_quote")

    def test_mismatched_purity_and_sell_are_rejected(self) -> None:
        for field, value, error in (("purity", 990, "purity_mismatch"), ("purity", True, "purity_mismatch"), ("sell_toman", 450121, "inconsistent_quote")):
            payload = fresh_payload()
            payload["items"][1][field] = value
            with self.subTest(field=field, value=value):
                self.assert_rejected(payload, error)

    def test_crossed_and_out_of_bounds_sides_are_rejected(self) -> None:
        for bid, code in ((450121, "crossed_orderbook"), (999, "outside_sanity_bounds"), (10000001, "outside_sanity_bounds")):
            payload = fresh_payload()
            payload["items"][1]["buy_toman"] = bid
            with self.subTest(bid=bid):
                self.assert_rejected(payload, code)

    def test_bad_items_and_selected_side_shapes_are_rejected(self) -> None:
        for items in (None, {}, [1], [None]):
            payload = fresh_payload()
            payload["items"] = items
            with self.subTest(items=items):
                self.assert_rejected(payload, "invalid_shape")
        for value in (None, True, "nan", [], {}):
            payload = fresh_payload()
            payload["items"][1]["buy_toman"] = value
            with self.subTest(buy=value):
                self.assert_rejected(payload, "invalid_number")

    def test_unrelated_values_do_not_change_native_gram_price(self) -> None:
        payload = fresh_payload()
        payload["prices"].update(gram_990=1, mesghal_990=1, troy_ounce_usd=1)
        payload["items"][0]["title"] = []
        parsed = self.parser.parse(payload, context())
        self.assertEqual(parsed.price, Decimal("450120"))


if __name__ == "__main__":
    unittest.main()
