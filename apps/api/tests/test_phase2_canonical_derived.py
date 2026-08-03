from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

os.environ["DEBUG"] = "false"

from app.pricing.anomaly import AnomalyAssessment
from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.derived import DerivedPriceEngine, DerivedPriceUnavailable
from app.pricing.instruments import get_instrument
from app.pricing.models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    ProviderQuote,
    SourceType,
    ValidationStatus,
    VerificationStatus,
)


FROZEN_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _provider_quote(
    instrument_id: str,
    provider_id: str,
    price: str,
    *,
    quote_id: int,
    source_family: str,
    venue: str | None = None,
    observed_seconds_ago: int = 5,
    provider_live_ttl_seconds: int | None = None,
) -> ProviderQuote:
    instrument = get_instrument(instrument_id)
    return ProviderQuote.create(
        id=quote_id,
        instrument_id=instrument_id,
        provider_id=provider_id,
        source_type=SourceType.HTTP,
        price=Decimal(price),
        currency=instrument.quote_currency,
        weight_unit=instrument.weight_unit,
        purity=instrument.purity,
        observed_at=FROZEN_NOW - timedelta(seconds=observed_seconds_ago),
        received_at=FROZEN_NOW,
        parser_version="phase2-test/1",
        validation_status=ValidationStatus.ACCEPTED,
        metadata={
            "source_family": source_family,
            "venue": venue or source_family,
            **(
                {"provider_live_ttl_seconds": provider_live_ttl_seconds}
                if provider_live_ttl_seconds is not None
                else {}
            ),
        },
        persistence_status=PersistenceStatus.PERSISTED,
    )


def _canonical(
    instrument_id: str,
    price: str,
    *,
    observed_seconds_ago: int = 5,
    status: CanonicalStatus = CanonicalStatus.LIVE,
    derivation_depth: int = 0,
    confidence_score: str = "0.90",
    provenance: list[str] | None = None,
    valid_for_seconds: int = 60,
) -> CanonicalQuote:
    observed_at = FROZEN_NOW - timedelta(seconds=observed_seconds_ago)
    return CanonicalQuote.create(
        instrument_id=instrument_id,
        price=Decimal(price),
        status=status,
        primary_quote_id=1,
        verification_quote_ids=[],
        source_summary={
            "derived": derivation_depth > 0,
            "derivation_depth": derivation_depth,
            "confidence_score": confidence_score,
            "provenance": provenance or [instrument_id],
        },
        observed_at=observed_at,
        canonical_at=FROZEN_NOW,
        valid_until=FROZEN_NOW + timedelta(seconds=valid_for_seconds),
        stale_at=FROZEN_NOW + timedelta(seconds=180),
        expires_at=FROZEN_NOW + timedelta(seconds=900),
        is_persisted=True,
        decision_reason="phase2_test_fixture",
    )


def _disagreement_decision():
    instrument = get_instrument("BTC_USD")
    primary = _provider_quote(
        instrument.instrument_id,
        "venue_a_btc",
        "100000",
        quote_id=10,
        source_family="venue_a",
    )
    verifier = _provider_quote(
        instrument.instrument_id,
        "venue_b_btc",
        "120000",
        quote_id=11,
        source_family="venue_b",
    )
    previous = _canonical(instrument.instrument_id, "95000")
    assessment = AnomalyAssessment(
        is_suspicious=True,
        deviation_percent=Decimal("5.263158"),
        dynamic_threshold_percent=Decimal("1"),
        volatility_percent=Decimal("0"),
        severity="high",
        reason="phase2_test_disagreement",
    )
    decision = CanonicalPricePolicy().select(
        instrument=instrument,
        primary=primary,
        previous=previous,
        assessment=assessment,
        verifier_quotes=[verifier],
        now=FROZEN_NOW,
    )
    return decision, previous


def _depth(quote: ProviderQuote):
    return getattr(
        quote,
        "derivation_depth",
        quote.metadata.get("derivation_depth"),
    )


class CanonicalDisagreementTests(unittest.TestCase):
    def test_two_disagreeing_sources_keep_previous_not_midpoint(self) -> None:
        decision, previous = _disagreement_decision()

        self.assertEqual(decision.canonical.price, previous.price)
        self.assertNotEqual(decision.canonical.price, Decimal("110000"))

    def test_two_disagreeing_sources_are_never_confirmed(self) -> None:
        decision, _previous = _disagreement_decision()

        self.assertNotEqual(decision.canonical.status, CanonicalStatus.CONFIRMED)
        self.assertEqual(decision.verification.status, VerificationStatus.DISAGREED)

    def test_stale_primary_is_rejected(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_btc",
            "100000",
            quote_id=20,
            source_family="venue_a",
            observed_seconds_ago=instrument.operational_ttl_seconds + 1,
        )

        with self.assertRaises(ValueError):
            CanonicalPricePolicy().select(
                instrument=instrument,
                primary=primary,
                previous=None,
                assessment=None,
                verifier_quotes=[],
                now=FROZEN_NOW,
            )

    def test_stale_verifier_cannot_confirm(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_btc",
            "100000",
            quote_id=21,
            source_family="venue_a",
        )
        stale = _provider_quote(
            instrument.instrument_id,
            "venue_b_btc",
            "100000",
            quote_id=22,
            source_family="venue_b",
            observed_seconds_ago=instrument.operational_ttl_seconds + 1,
        )
        previous = _canonical(instrument.instrument_id, "95000")
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_stale_verifier",
        )

        decision = CanonicalPricePolicy().select(
            instrument=instrument,
            primary=primary,
            previous=previous,
            assessment=assessment,
            verifier_quotes=[stale],
            now=FROZEN_NOW,
        )

        self.assertEqual(decision.canonical.price, previous.price)
        self.assertIs(decision.verification.status, VerificationStatus.INSUFFICIENT)
        self.assertEqual(decision.canonical.verification_quote_ids, [])

    def test_same_family_verifier_cannot_confirm(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_trade",
            "100000",
            quote_id=23,
            source_family="venue_a",
        )
        same_family = _provider_quote(
            instrument.instrument_id,
            "venue_a_book",
            "100000",
            quote_id=24,
            source_family="venue_a",
        )
        previous = _canonical(instrument.instrument_id, "95000")
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_same_family",
        )

        decision = CanonicalPricePolicy().select(
            instrument=instrument,
            primary=primary,
            previous=previous,
            assessment=assessment,
            verifier_quotes=[same_family],
            now=FROZEN_NOW,
        )

        self.assertIs(decision.verification.status, VerificationStatus.INSUFFICIENT)
        self.assertEqual(decision.canonical.verification_quote_ids, [])

    def test_duplicate_family_endpoints_do_not_make_three_source_median(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_trade",
            "100000",
            quote_id=25,
            source_family="venue_a",
        )
        duplicate = _provider_quote(
            instrument.instrument_id,
            "venue_a_book",
            "120000",
            quote_id=26,
            source_family="venue_a",
        )
        other = _provider_quote(
            instrument.instrument_id,
            "venue_b_trade",
            "140000",
            quote_id=27,
            source_family="venue_b",
        )
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_duplicate_family",
        )

        with self.assertRaises(ValueError):
            CanonicalPricePolicy().select(
                instrument=instrument,
                primary=primary,
                previous=None,
                assessment=assessment,
                verifier_quotes=[duplicate, other],
                now=FROZEN_NOW,
            )

    def test_duplicate_venue_with_different_family_does_not_add_consensus(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_trade",
            "100000",
            quote_id=28,
            source_family="family_a",
            venue="shared_venue",
        )
        same_venue = _provider_quote(
            instrument.instrument_id,
            "venue_a_book",
            "120000",
            quote_id=29,
            source_family="family_b",
            venue="shared_venue",
        )
        other = _provider_quote(
            instrument.instrument_id,
            "venue_c_trade",
            "140000",
            quote_id=30,
            source_family="family_c",
            venue="other_venue",
        )
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_duplicate_venue",
        )

        with self.assertRaises(ValueError):
            CanonicalPricePolicy().select(
                instrument=instrument,
                primary=primary,
                previous=None,
                assessment=assessment,
                verifier_quotes=[same_venue, other],
                now=FROZEN_NOW,
            )

    def test_three_wild_prices_do_not_make_false_median_consensus(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_trade",
            "100000",
            quote_id=31,
            source_family="family_a",
        )
        verifier_b = _provider_quote(
            instrument.instrument_id,
            "venue_b_trade",
            "200000",
            quote_id=32,
            source_family="family_b",
        )
        verifier_c = _provider_quote(
            instrument.instrument_id,
            "venue_c_trade",
            "300000",
            quote_id=33,
            source_family="family_c",
        )
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_wild_prices",
        )

        with self.assertRaises(ValueError):
            CanonicalPricePolicy().select(
                instrument=instrument,
                primary=primary,
                previous=None,
                assessment=assessment,
                verifier_quotes=[verifier_b, verifier_c],
                now=FROZEN_NOW,
            )

    def test_median_uses_tight_majority_cluster_only(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "venue_a_trade",
            "100000",
            quote_id=34,
            source_family="family_a",
        )
        verifier_b = _provider_quote(
            instrument.instrument_id,
            "venue_b_trade",
            "200000",
            quote_id=35,
            source_family="family_b",
        )
        verifier_c = _provider_quote(
            instrument.instrument_id,
            "venue_c_trade",
            "201000",
            quote_id=36,
            source_family="family_c",
        )
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_inlier_cluster",
        )

        decision = CanonicalPricePolicy().select(
            instrument=instrument,
            primary=primary,
            previous=None,
            assessment=assessment,
            verifier_quotes=[verifier_b, verifier_c],
            now=FROZEN_NOW,
        )

        self.assertEqual(decision.canonical.price, Decimal("200500"))
        self.assertEqual(
            decision.canonical.source_summary["consensus_source_count"],
            2,
        )

    def test_provider_ttl_limits_canonical_live_window(self) -> None:
        instrument = get_instrument("BTC_USD")
        primary = _provider_quote(
            instrument.instrument_id,
            "short_ttl_venue",
            "100000",
            quote_id=37,
            source_family="short_ttl_venue",
            observed_seconds_ago=5,
            provider_live_ttl_seconds=10,
        )

        decision = CanonicalPricePolicy().select(
            instrument=instrument,
            primary=primary,
            previous=None,
            assessment=None,
            verifier_quotes=[],
            now=FROZEN_NOW,
        )

        self.assertEqual(
            decision.canonical.valid_until,
            primary.observed_at + timedelta(seconds=10),
        )

        expired_primary = _provider_quote(
            instrument.instrument_id,
            "short_ttl_venue",
            "100000",
            quote_id=38,
            source_family="short_ttl_venue",
            observed_seconds_ago=11,
            provider_live_ttl_seconds=10,
        )
        with self.assertRaises(ValueError):
            CanonicalPricePolicy().select(
                instrument=instrument,
                primary=expired_primary,
                previous=None,
                assessment=None,
                verifier_quotes=[],
                now=FROZEN_NOW,
            )


class DerivedPriceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = DerivedPriceEngine()

    def test_silver_925_uses_925_over_999_basis(self) -> None:
        result = self.engine.derive(
            "SILVER_925_TOMAN_GRAM",
            {"SILVER_999_TOMAN_GRAM": _canonical("SILVER_999_TOMAN_GRAM", "9990")},
            now=FROZEN_NOW,
        )

        self.assertEqual(result.price, Decimal("9250"))

    def test_derivation_depth_is_max_input_depth_plus_one(self) -> None:
        inputs = {
            "XAU_USD_OZ": _canonical("XAU_USD_OZ", "2400"),
            "USDT_TOMAN": _canonical(
                "USDT_TOMAN",
                "60000",
                status=CanonicalStatus.DERIVED_FALLBACK,
                derivation_depth=1,
            ),
            "USDT_USD": _canonical("USDT_USD", "1"),
        }

        result = self.engine.derive(
            "GOLD_18K_TOMAN_GRAM",
            inputs,
            now=FROZEN_NOW,
        )

        self.assertEqual(_depth(result), 2)

    def test_derivation_rejects_cycle_in_input_provenance(self) -> None:
        inputs = {
            "XAU_USD_OZ": _canonical("XAU_USD_OZ", "2400"),
            "USDT_TOMAN": _canonical(
                "USDT_TOMAN",
                "60000",
                status=CanonicalStatus.DERIVED_FALLBACK,
                derivation_depth=1,
                provenance=["GOLD_18K_TOMAN_GRAM", "USDT_TOMAN"],
            ),
            "USDT_USD": _canonical("USDT_USD", "1"),
        }

        with self.assertRaises(DerivedPriceUnavailable):
            self.engine.derive(
                "GOLD_18K_TOMAN_GRAM",
                inputs,
                now=FROZEN_NOW,
            )

    def test_derived_confidence_decays_below_weakest_input(self) -> None:
        inputs = {
            "XAU_USD_OZ": _canonical(
                "XAU_USD_OZ", "2400", confidence_score="0.60"
            ),
            "USDT_TOMAN": _canonical(
                "USDT_TOMAN", "60000", confidence_score="0.60"
            ),
            "USDT_USD": _canonical(
                "USDT_USD", "1", confidence_score="0.60"
            ),
        }

        result = self.engine.derive(
            "GOLD_18K_TOMAN_GRAM",
            inputs,
            now=FROZEN_NOW,
        )

        self.assertLess(result.confidence_score, Decimal("0.60"))

    def test_derived_observation_time_is_oldest_required_input(self) -> None:
        inputs = {
            "XAU_USD_OZ": _canonical(
                "XAU_USD_OZ", "2400", observed_seconds_ago=10
            ),
            "USDT_TOMAN": _canonical(
                "USDT_TOMAN", "60000", observed_seconds_ago=40
            ),
            "USDT_USD": _canonical(
                "USDT_USD", "1", observed_seconds_ago=20
            ),
        }

        result = self.engine.derive(
            "GOLD_18K_TOMAN_GRAM",
            inputs,
            now=FROZEN_NOW,
        )

        self.assertEqual(
            result.observed_at,
            FROZEN_NOW - timedelta(seconds=40),
        )

    def test_derived_live_window_ends_with_weakest_input(self) -> None:
        inputs = {
            "XAU_USD_OZ": _canonical(
                "XAU_USD_OZ",
                "2400",
                valid_for_seconds=5,
            ),
            "USDT_TOMAN": _canonical("USDT_TOMAN", "60000"),
            "USDT_USD": _canonical("USDT_USD", "1"),
        }

        result = self.engine.derive(
            "GOLD_18K_TOMAN_GRAM",
            inputs,
            now=FROZEN_NOW,
        )
        result.persistence_status = PersistenceStatus.PERSISTED
        policy = CanonicalPricePolicy()
        canonical = policy.derived_fallback(
            instrument=get_instrument("GOLD_18K_TOMAN_GRAM"),
            derived=result,
            current=FROZEN_NOW,
        )

        self.assertEqual(
            result.metadata["input_live_eligible_until"],
            (FROZEN_NOW + timedelta(seconds=5)).isoformat(),
        )
        self.assertEqual(
            canonical.valid_until,
            FROZEN_NOW + timedelta(seconds=5),
        )
        with self.assertRaises(ValueError):
            policy.derived_fallback(
                instrument=get_instrument("GOLD_18K_TOMAN_GRAM"),
                derived=result,
                current=FROZEN_NOW + timedelta(seconds=6),
            )


if __name__ == "__main__":
    unittest.main()
