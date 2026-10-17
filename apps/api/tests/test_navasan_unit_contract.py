from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.instruments import get_instrument
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.parsers.local_reference import NavasanLatestParser
from app.pricing.registry import PROVIDERS

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


class NavasanUnitContractTests(unittest.TestCase):
    def setUp(self):
        self.context = ParserContext(get_instrument("USD_TOMAN"), NOW, 3600)
        self.row = {"value": "1000000", "timestamp": int(NOW.timestamp())}

    def test_key_alone_never_confirms_ambiguous_currency(self):
        candidate = SimpleNamespace(navasan_api_key="test-key", navasan_api_base_url="https://api.navasan.tech")
        self.assertFalse(PROVIDERS["navasan_usd_toman"].configured(candidate))
        with self.assertRaises(ParserError):
            NavasanLatestParser("usd_sell").parse({"usd_sell": self.row}, self.context)

    def test_verified_rial_and_toman_convert_exactly_once(self):
        for unit, raw in (("RIAL", "1000000"), ("TOMAN", "100000")):
            with self.subTest(unit=unit):
                parsed = NavasanLatestParser("usd_sell", unit).parse(
                    {"usd_sell": {**self.row, "value": raw}}, self.context)
                self.assertEqual(parsed.price, Decimal("100000"))
                self.assertEqual(parsed.metadata["source_currency"], unit)

    def test_missing_bool_naive_and_invalid_source_timestamp_are_rejected(self):
        for timestamp in (None, True, "2026-10-16T12:00:00", "not-a-time"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                NavasanLatestParser("usd_sell", "TOMAN").parse(
                    {"usd_sell": {**self.row, "timestamp": timestamp}}, self.context)

    def test_explicit_payload_unit_must_match_confirmed_contract(self):
        with self.assertRaises(ParserError):
            NavasanLatestParser("usd_sell", "TOMAN").parse(
                {"usd_sell": {**self.row, "unit": "RIAL"}}, self.context)

    def test_secure_direct_endpoint_or_proxy_and_confirmed_unit_are_required(self):
        values = dict(navasan_api_key="test-key", navasan_local_unit="RIAL", navasan_https_proxy_base_url=None)
        provider = PROVIDERS["navasan_usd_toman"]
        self.assertTrue(provider.configured(SimpleNamespace(**values, navasan_api_base_url="https://api.navasan.tech")))
        self.assertFalse(provider.configured(SimpleNamespace(**values, navasan_api_base_url="http://api.navasan.tech")))

    def test_factory_and_rejected_provider_provenance_match(self):
        with patch("app.pricing.parsers.settings.navasan_local_unit", "TOMAN"):
            parser = build_parser("navasan_usd_v1")
        self.assertEqual(parser.source_unit, "TOMAN")
        self.assertEqual(parser.parser_version, PROVIDERS["navasan_usd_toman"].parser_version)


if __name__ == "__main__":
    unittest.main()
