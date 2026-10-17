from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from decimal import Decimal

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import INSTRUMENTS
from app.pricing.models import Currency
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.registry import PROVIDERS


# Synthetic contract cases; no authenticated provider response was obtained.
# https://servix.cc/docs/current-prices specifies quoteUnit and businessTime.
def context(instrument: str = "USD_TOMAN") -> ParserContext:
    return ParserContext(
        instrument=INSTRUMENTS[instrument],
        received_at=datetime(2026, 10, 16, 12, 1, tzinfo=UTC),
        maximum_timestamp_age_seconds=3600,
    )


def quote(**changes: object) -> dict[str, object]:
    return {
        "code": "USD_RLS",
        "quoteUnit": "RLS",
        "value": "1420000",
        "businessTime": "2026-10-16T12:00:00Z",
        **changes,
    }


class ServixCurrentPriceContractTests(unittest.TestCase):
    def test_accepted_and_rejected_quote_sources_share_the_new_parser_version(self) -> None:
        for provider_id in ("servix_usd_toman", "servix_btc_usd", "servix_usdt_usd"):
            with self.subTest(provider=provider_id):
                provider = PROVIDERS[provider_id]
                parser = build_parser(provider.parser_id)
                self.assertEqual(parser.parser_version, "servix-assets/1.1.0")
                self.assertEqual(provider.parser_version, parser.parser_version)

    def test_documented_array_and_single_quote_shapes(self) -> None:
        parser = build_parser("servix_usd_rls_v1")
        for payload in ([quote()], quote()):
            with self.subTest(shape=type(payload).__name__):
                parsed = parser.parse(payload, context())
                self.assertEqual(parsed.price, Decimal("142000"))
                self.assertEqual(parsed.currency, Currency.TOMAN)
                self.assertEqual(parsed.observed_at, datetime(2026, 10, 16, 12, tzinfo=UTC))
                self.assertEqual(parsed.metadata["source_currency"], "RIAL")
                self.assertEqual(parsed.metadata["conversion_factor"], "0.1")

    def test_explicit_toman_is_not_divided_because_code_ends_in_rls(self) -> None:
        parsed = build_parser("servix_usd_rls_v1").parse(
            {"data": [quote(quoteUnit="TOMAN", value="142000")]}, context()
        )
        self.assertEqual(parsed.price, Decimal("142000"))
        self.assertEqual(parsed.metadata["source_currency"], "TOMAN")
        self.assertEqual(parsed.metadata["conversion_factor"], "1")

    def test_missing_unknown_and_non_text_quote_units_are_rejected(self) -> None:
        parser = build_parser("servix_usd_rls_v1")
        for unit in (None, "", " ", "EUR", "INDEX", False, 10, {}, ["RLS"]):
            with self.subTest(unit=unit), self.assertRaises(ParserError):
                parser.parse({"data": [quote(quoteUnit=unit)]}, context())
        missing = quote()
        del missing["quoteUnit"]
        with self.assertRaises(ParserError):
            parser.parse({"data": [missing]}, context())

    def test_explicit_currency_cannot_be_relabelled_to_the_instrument(self) -> None:
        cases = (
            ("servix_usd_rls_v1", "USD_RLS", "USD_TOMAN", "USD", "1420000"),
            ("servix_usd_rls_v1", "USD_RLS", "USD_TOMAN", "USDT", "1420000"),
            ("servix_btc_usd_v1", "BTC_USD", "BTC_USD", "RLS", "77000"),
            ("servix_btc_usd_v1", "BTC_USD", "BTC_USD", "TOMAN", "77000"),
            ("servix_usdt_usd_v1", "USDT_USD", "USDT_USD", "USDT", "1.01"),
        )
        for parser_id, code, instrument, unit, value in cases:
            with self.subTest(code=code, unit=unit), self.assertRaises(ParserError):
                build_parser(parser_id).parse(
                    {"data": [quote(code=code, quoteUnit=unit, value=value)]},
                    context(instrument),
                )

    def test_usd_quotes_keep_their_unit_and_value(self) -> None:
        for parser_id, code, instrument, value in (
            ("servix_btc_usd_v1", "BTC_USD", "BTC_USD", "77000"),
            ("servix_usdt_usd_v1", "USDT_USD", "USDT_USD", "1.01"),
        ):
            with self.subTest(code=code):
                parsed = build_parser(parser_id).parse(
                    {"data": [quote(code=code, quoteUnit="USD", value=value)]},
                    context(instrument),
                )
                self.assertEqual(parsed.price, Decimal(value))
                self.assertEqual(parsed.currency, Currency.USD)

    def test_missing_business_time_never_uses_updated_at_or_receive_time(self) -> None:
        parser = build_parser("servix_usd_rls_v1")
        for timestamp in (None, "", " ", False, 0):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                parser.parse(
                    {"data": [quote(businessTime=timestamp, updated_at="2026-10-16T12:00:00Z")]},
                    context(),
                )
        missing = quote(updated_at="2026-10-16T12:00:00Z")
        del missing["businessTime"]
        with self.assertRaises(ParserError):
            parser.parse({"data": [missing]}, context())

    def test_ambiguous_and_invalid_business_times_are_rejected(self) -> None:
        parser = build_parser("servix_usd_rls_v1")
        for timestamp in ("2026-10-16T12:00:00", "2026-10-16", 1792152000, True, {}, [], "not-a-time"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                parser.parse({"data": [quote(businessTime=timestamp)]}, context())

    def test_stale_and_future_source_time_cannot_be_freshened(self) -> None:
        for timestamp in ("2026-10-15T12:00:00Z", "2026-10-17T12:00:00Z"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                build_parser("servix_usd_rls_v1").parse(
                    {"data": [quote(businessTime=timestamp, updated_at="2026-10-16T12:00:00Z")]},
                    context(),
                )

    def test_source_offset_is_converted_to_the_same_instant(self) -> None:
        parsed = build_parser("servix_usd_rls_v1").parse(
            {"data": [quote(businessTime="2026-10-16T15:30:00+03:30", updated_at="2026-10-16T12:01:00Z")]},
            context(),
        )
        self.assertEqual(parsed.observed_at, datetime(2026, 10, 16, 12, tzinfo=UTC))

    def test_selected_mid_value_does_not_fall_back_to_buy_or_sell(self) -> None:
        parser = build_parser("servix_usd_rls_v1")
        row = quote(value=None, buyPrice="1400000", sellPrice="1440000", midPrice="1420000")
        with self.assertRaises(ParserError):
            parser.parse({"data": [row]}, context())

    def test_duplicate_selected_codes_are_ambiguous_and_rejected(self) -> None:
        with self.assertRaises(ParserError):
            build_parser("servix_usd_rls_v1").parse(
                {"data": [quote(), quote(code="usd_rls", value="1430000")]},
                context(),
            )

    def test_unselected_assets_do_not_change_the_selected_quote(self) -> None:
        parsed = build_parser("servix_usd_rls_v1").parse(
            [quote(code="USDT_USD", quoteUnit="USD", value="1.01"), quote()],
            context(),
        )
        self.assertEqual(parsed.price, Decimal("142000"))

    def test_dictionary_key_cannot_override_a_different_quote_code(self) -> None:
        with self.assertRaises(ParserError):
            build_parser("servix_usd_rls_v1").parse(
                {"data": {"USD_RLS": quote(code="BTC_USD")}}, context()
            )


if __name__ == "__main__":
    unittest.main()
