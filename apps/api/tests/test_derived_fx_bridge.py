"""Derived Toman metal prices: which FX bridge is used, and how it is labelled.

Toman metal prices are reconstructed from an international reference times a
USD/Toman rate. Using USDT for that rate is a stand-in, not an equivalent: in
this market USDT carries a premium, so the two bridges disagree by percent, not
basis points. These tests pin the preference order, the purity arithmetic, and
the flag that tells a consumer which one produced the number.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.pricing.derived import DerivedPriceUnavailable, derived_price_engine
from app.pricing.models import CanonicalQuote, CanonicalStatus

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
TROY_OUNCE_GRAMS = Decimal("31.1034768")


def _quote(
    instrument_id: str,
    price: str,
    *,
    derived: bool = False,
    provenance: list[str] | None = None,
) -> CanonicalQuote:
    return CanonicalQuote.create(
        instrument_id=instrument_id,
        price=Decimal(price),
        status=(
            CanonicalStatus.DERIVED_FALLBACK if derived else CanonicalStatus.LIVE
        ),
        primary_quote_id=1,
        verification_quote_ids=[],
        source_summary={
            "derivation_depth": 1 if derived else 0,
            "confidence_score": "1",
            "derived": derived,
            "provenance": provenance or [instrument_id],
        },
        observed_at=NOW,
        canonical_at=NOW,
        valid_until=NOW + timedelta(minutes=5),
        stale_at=NOW + timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=15),
        is_persisted=True,
        decision_reason="test",
    )


class DerivedFxBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = {
            "XAU_USD_OZ": _quote("XAU_USD_OZ", "2400"),
            "XAG_USD_OZ": _quote("XAG_USD_OZ", "30"),
            "USD_TOMAN": _quote("USD_TOMAN", "58000"),
            "USDT_TOMAN": _quote("USDT_TOMAN", "60000"),
            "USDT_USD": _quote("USDT_USD", "1.00"),
        }

    def test_free_market_usd_is_preferred_over_the_usdt_proxy(self) -> None:
        quote = derived_price_engine.derive(
            "GOLD_24K_TOMAN_GRAM", self.snapshot, now=NOW
        )
        self.assertEqual(quote.metadata["fx_bridge"], "usd_toman")
        self.assertFalse(quote.metadata["fx_bridge_is_proxy"])
        expected = Decimal("2400") * Decimal("58000") / TROY_OUNCE_GRAMS
        self.assertAlmostEqual(float(quote.price), float(expected), delta=1.0)

    def test_usdt_bridge_is_used_only_as_a_fallback_and_is_flagged(self) -> None:
        snapshot = {
            key: value
            for key, value in self.snapshot.items()
            if key != "USD_TOMAN"
        }
        quote = derived_price_engine.derive("GOLD_24K_TOMAN_GRAM", snapshot, now=NOW)
        self.assertEqual(quote.metadata["fx_bridge"], "usdt_proxy")
        self.assertTrue(quote.metadata["fx_bridge_is_proxy"])

    def test_the_two_bridges_disagree_enough_to_matter(self) -> None:
        """Guards the reason the preference order exists at all."""
        with_usd = derived_price_engine.derive(
            "GOLD_24K_TOMAN_GRAM", self.snapshot, now=NOW
        )
        without_usd = derived_price_engine.derive(
            "GOLD_24K_TOMAN_GRAM",
            {k: v for k, v in self.snapshot.items() if k != "USD_TOMAN"},
            now=NOW,
        )
        difference = abs(without_usd.price - with_usd.price) / with_usd.price
        self.assertGreater(float(difference), 0.02)

    def test_a_derived_usd_toman_input_is_still_reported_as_a_proxy(self) -> None:
        snapshot = {
            "XAG_USD_OZ": self.snapshot["XAG_USD_OZ"],
            "USD_TOMAN": _quote(
                "USD_TOMAN",
                "60000",
                derived=True,
                provenance=["USDT_TOMAN", "USD_TOMAN"],
            ),
        }
        quote = derived_price_engine.derive(
            "SILVER_999_TOMAN_GRAM", snapshot, now=NOW
        )
        self.assertTrue(quote.metadata["fx_bridge_is_proxy"])

    def test_gold_18k_uses_the_purity_ratio_not_a_flat_factor(self) -> None:
        snapshot = dict(self.snapshot)
        snapshot["GOLD_24K_TOMAN_GRAM"] = _quote("GOLD_24K_TOMAN_GRAM", "4476000")
        quote = derived_price_engine.derive(
            "GOLD_18K_TOMAN_GRAM", snapshot, now=NOW
        )
        ratio = quote.price / Decimal("4476000")
        # 0.750 fine against a 0.9999 reference, not a flat 0.75.
        self.assertAlmostEqual(
            float(ratio), float(Decimal("0.750") / Decimal("0.9999")), places=9
        )

    def test_silver_925_normalises_against_999(self) -> None:
        snapshot = {
            "SILVER_999_TOMAN_GRAM": _quote("SILVER_999_TOMAN_GRAM", "100000"),
        }
        quote = derived_price_engine.derive(
            "SILVER_925_TOMAN_GRAM", snapshot, now=NOW
        )
        self.assertAlmostEqual(
            float(quote.price / Decimal("100000")),
            float(Decimal("0.925") / Decimal("0.999")),
            places=9,
        )

    def test_no_bridge_means_no_derived_price(self) -> None:
        snapshot = {"XAU_USD_OZ": self.snapshot["XAU_USD_OZ"]}
        with self.assertRaises(DerivedPriceUnavailable):
            derived_price_engine.derive("GOLD_24K_TOMAN_GRAM", snapshot, now=NOW)

    def test_usdt_outside_the_safe_band_blocks_the_proxy_bridge(self) -> None:
        snapshot = {
            key: value
            for key, value in self.snapshot.items()
            if key != "USD_TOMAN"
        }
        snapshot["USDT_USD"] = _quote("USDT_USD", "1.40")
        with self.assertRaises(DerivedPriceUnavailable):
            derived_price_engine.derive("GOLD_24K_TOMAN_GRAM", snapshot, now=NOW)


if __name__ == "__main__":
    unittest.main()
