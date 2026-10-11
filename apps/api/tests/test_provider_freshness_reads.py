from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
import unittest

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.instruments import get_instrument
from app.pricing.models import (
    CanonicalQuote, Currency, PersistenceStatus, ProviderQuote,
    ValidationStatus, WeightUnit,
)
from app.pricing.service import InstrumentPricingService

NOW = datetime(2026, 10, 11, 13, 0, tzinfo=UTC)


def relay_canonical(age: int = 120) -> CanonicalQuote:
    provider = ProviderQuote.create(
        instrument_id="USDT_USD", provider_id="coingecko_usdt", source_type="http",
        price=Decimal("0.999"), currency=Currency.USD, weight_unit=WeightUnit.UNIT,
        purity=None, observed_at=NOW-timedelta(seconds=age), received_at=NOW,
        parser_version="read-proof", validation_status=ValidationStatus.ACCEPTED,
        persistence_status=PersistenceStatus.PERSISTED,
        metadata={"provider_live_ttl_seconds": 360, "maximum_source_age_seconds": 600,
                  "anchor_live_window_at_receive_time": True},
    )
    canonical = CanonicalPricePolicy().select(
        instrument=get_instrument("USDT_USD"), primary=provider, previous=None,
        assessment=None, verifier_quotes=[], now=NOW,
    ).canonical
    canonical.is_persisted = True
    return CanonicalQuote.from_dict(canonical.to_dict(now=NOW, evaluate_status=False))


class ProviderFreshnessReadTests(unittest.TestCase):
    def test_persisted_relay_retains_vetted_receive_window_on_read(self):
        quote = relay_canonical()
        before = (quote.valid_until, quote.stale_at, quote.expires_at)
        current = InstrumentPricingService._current_policy(quote, get_instrument("USDT_USD"))
        self.assertEqual((current.valid_until, current.stale_at, current.expires_at), before)
        self.assertEqual(current.valid_until, NOW+timedelta(seconds=360))
        self.assertEqual(current.observed_at, NOW-timedelta(seconds=120))

    def test_runtime_tighter_policy_uses_anchor_and_never_reextends_window(self):
        quote = relay_canonical()
        instrument = get_instrument("USDT_USD")
        tighter = replace(instrument, operational_ttl_seconds=30,
                          stale_after_seconds=60, expire_after_seconds=90)
        InstrumentPricingService._current_policy(quote, tighter)
        self.assertEqual(quote.valid_until, NOW+timedelta(seconds=30))
        self.assertEqual(quote.stale_at, NOW+timedelta(seconds=60))
        self.assertEqual(quote.expires_at, NOW+timedelta(seconds=90))
        InstrumentPricingService._current_policy(quote, instrument)
        self.assertEqual(quote.valid_until, NOW+timedelta(seconds=30))
        self.assertEqual(quote.expires_at, NOW+timedelta(seconds=90))

    def test_original_source_age_cap_cannot_be_extended_by_read(self):
        quote = relay_canonical(age=580)
        InstrumentPricingService._current_policy(quote, get_instrument("USDT_USD"))
        self.assertEqual(quote.valid_until, NOW+timedelta(seconds=20))
        quote.valid_until += timedelta(minutes=10)
        InstrumentPricingService._current_policy(quote, get_instrument("USDT_USD"))
        self.assertEqual(quote.valid_until, NOW+timedelta(seconds=20))
        self.assertEqual(quote.observed_at, NOW-timedelta(seconds=580))

    def test_legacy_or_invalid_anchor_keeps_observation_based_bound(self):
        instrument = get_instrument("USDT_USD")
        for metadata in ({}, {"freshness_anchor": "bad", "source_live_eligible_until": "bad"},
                         {"freshness_anchor": (NOW+timedelta(minutes=1)).isoformat(),
                          "source_live_eligible_until": (NOW+timedelta(hours=1)).isoformat()}):
            with self.subTest(metadata=metadata):
                quote = relay_canonical()
                quote.source_summary = metadata
                InstrumentPricingService._current_policy(quote, instrument)
                self.assertEqual(quote.valid_until, quote.observed_at+timedelta(seconds=360))


if __name__ == "__main__":
    unittest.main()
