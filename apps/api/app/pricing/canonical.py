from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from .anomaly import AnomalyAssessment
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    InstrumentDefinition,
    ProviderQuote,
    SourceType,
    ValidationStatus,
    VerificationDecision,
    VerificationStatus,
    ensure_utc,
    json_number,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class CanonicalDecision:
    canonical: CanonicalQuote
    verification: VerificationDecision


class CanonicalPricePolicy:
    def select(
        self,
        *,
        instrument: InstrumentDefinition,
        primary: ProviderQuote,
        previous: CanonicalQuote | None,
        assessment: AnomalyAssessment | None,
        verifier_quotes: list[ProviderQuote],
        from_fresh_cache: bool = False,
        now: datetime | None = None,
    ) -> CanonicalDecision:
        if primary.price is None or primary.validation_status is ValidationStatus.REJECTED:
            raise ValueError("Rejected provider quotes cannot become canonical")
        if primary.source_type is SourceType.TELEGRAM:
            raise ValueError("Telegram quotes cannot be primary canonical sources")
        current = ensure_utc(now or utc_now())
        valid_verifiers = [
            quote
            for quote in verifier_quotes
            if quote.price is not None
            and quote.is_direct
            and quote.validation_status is ValidationStatus.ACCEPTED
            and quote.instrument_id == primary.instrument_id
        ]

        if assessment is None or not assessment.is_suspicious:
            status = CanonicalStatus.FRESH_CACHE if from_fresh_cache else CanonicalStatus.LIVE
            canonical = self._from_price(
                instrument=instrument,
                price=primary.price,
                observed_at=primary.observed_at,
                current=current,
                status=status,
                primary_quote_id=primary.id,
                verification_quote_ids=[],
                verification_status=VerificationStatus.NOT_REQUIRED,
                reason="valid_primary_provider_quote",
                source_summary={
                    "primary_provider_id": primary.provider_id,
                    "provider_ids": [primary.provider_id],
                    "source_count": 1,
                    "direct_source_count": 1,
                    "derived": False,
                },
            )
            return CanonicalDecision(
                canonical=canonical,
                verification=VerificationDecision(
                    status=VerificationStatus.NOT_REQUIRED,
                    candidate_quote_id=primary.id,
                    verification_quote_ids=(),
                    deviation_percent=(assessment.deviation_percent if assessment else None),
                    threshold_percent=(
                        assessment.dynamic_threshold_percent
                        if assessment
                        else instrument.base_anomaly_threshold_percent
                    ),
                    decision_reason="primary_quote_accepted",
                ),
            )

        tolerance = assessment.dynamic_threshold_percent
        confirming = [
            quote
            for quote in valid_verifiers
            if self._difference_percent(primary.price, quote.price) <= tolerance
        ]
        verifier_ids = [quote.id for quote in valid_verifiers if quote.id is not None]
        if confirming:
            canonical = self._from_price(
                instrument=instrument,
                price=primary.price,
                observed_at=primary.observed_at,
                current=current,
                status=CanonicalStatus.CONFIRMED,
                primary_quote_id=primary.id,
                verification_quote_ids=verifier_ids,
                verification_status=VerificationStatus.CONFIRMED,
                reason="anomalous_primary_confirmed_by_independent_source",
                source_summary=self._verification_summary(primary, valid_verifiers, assessment),
                candidate_price=primary.price,
                candidate_provider_id=primary.provider_id,
            )
            return CanonicalDecision(
                canonical=canonical,
                verification=VerificationDecision(
                    status=VerificationStatus.CONFIRMED,
                    candidate_quote_id=primary.id,
                    verification_quote_ids=tuple(verifier_ids),
                    deviation_percent=assessment.deviation_percent,
                    threshold_percent=tolerance,
                    decision_reason="independent_quote_within_tolerance",
                ),
            )

        comparable = [primary, *valid_verifiers]
        if len(comparable) >= 2:
            chosen_price = Decimal(str(median([quote.price for quote in comparable if quote.price is not None])))
            observed_at = min(quote.observed_at for quote in comparable)
            canonical = self._from_price(
                instrument=instrument,
                price=chosen_price,
                observed_at=observed_at,
                current=current,
                status=CanonicalStatus.CONFIRMED,
                primary_quote_id=primary.id,
                verification_quote_ids=verifier_ids,
                verification_status=VerificationStatus.DISAGREED,
                reason="median_of_disagreeing_fresh_direct_quotes",
                source_summary=self._verification_summary(primary, valid_verifiers, assessment),
                candidate_price=primary.price,
                candidate_provider_id=primary.provider_id,
            )
            return CanonicalDecision(
                canonical=canonical,
                verification=VerificationDecision(
                    status=VerificationStatus.DISAGREED,
                    candidate_quote_id=primary.id,
                    verification_quote_ids=tuple(verifier_ids),
                    deviation_percent=assessment.deviation_percent,
                    threshold_percent=tolerance,
                    decision_reason="independent_quote_disagreed_median_selected",
                ),
            )

        if previous is None:
            raise ValueError("Suspicious quote cannot bootstrap a canonical price")
        canonical = self.keep_previous(
            previous=previous,
            candidate=primary,
            assessment=assessment,
            status=CanonicalStatus.SUSPICIOUS_UNCONFIRMED,
            current=current,
        )
        return CanonicalDecision(
            canonical=canonical,
            verification=VerificationDecision(
                status=VerificationStatus.INSUFFICIENT,
                candidate_quote_id=primary.id,
                verification_quote_ids=tuple(verifier_ids),
                deviation_percent=assessment.deviation_percent,
                threshold_percent=tolerance,
                decision_reason="insufficient_independent_quotes_previous_canonical_kept",
            ),
        )

    def keep_previous(
        self,
        *,
        previous: CanonicalQuote,
        candidate: ProviderQuote,
        assessment: AnomalyAssessment,
        status: CanonicalStatus,
        current: datetime | None = None,
    ) -> CanonicalQuote:
        now = ensure_utc(current or utc_now())
        if candidate.price is None:
            raise ValueError("Suspicious candidate requires a price")
        return CanonicalQuote.create(
            instrument_id=previous.instrument_id,
            price=previous.price,
            status=status,
            primary_quote_id=previous.primary_quote_id,
            verification_quote_ids=[],
            source_summary={
                **previous.source_summary,
                "candidate_price": json_number(candidate.price),
                "candidate_provider_id": candidate.provider_id,
                "candidate_difference_percent": json_number(assessment.deviation_percent),
                "verification_progress": "pending" if status is CanonicalStatus.VERIFYING else "insufficient",
                "fallback_reason": "previous_canonical_kept_during_anomaly",
            },
            observed_at=previous.observed_at,
            canonical_at=now,
            valid_until=previous.valid_until,
            stale_at=previous.stale_at,
            expires_at=previous.expires_at,
            is_persisted=False,
            decision_reason="suspicious_candidate_not_activated",
            change_1h=previous.change_1h,
            change_24h=previous.change_24h,
            change_7d=previous.change_7d,
            change_30d=previous.change_30d,
            verification_status=(
                VerificationStatus.PENDING
                if status is CanonicalStatus.VERIFYING
                else VerificationStatus.INSUFFICIENT
            ),
            candidate_price=candidate.price,
            candidate_provider_id=candidate.provider_id,
        )

    def derived_fallback(
        self,
        *,
        instrument: InstrumentDefinition,
        derived: ProviderQuote,
        current: datetime | None = None,
    ) -> CanonicalQuote:
        if not instrument.allow_derived_fallback or not derived.is_derived or derived.price is None:
            raise ValueError("Instrument does not allow this derived fallback")
        now = ensure_utc(current or utc_now())
        return self._from_price(
            instrument=instrument,
            price=derived.price,
            observed_at=derived.observed_at,
            current=now,
            status=CanonicalStatus.DERIVED_FALLBACK,
            primary_quote_id=derived.id,
            verification_quote_ids=[],
            verification_status=VerificationStatus.NOT_REQUIRED,
            reason="no_fresh_direct_quote_derived_fallback_allowed",
            source_summary={
                "primary_provider_id": derived.provider_id,
                "provider_ids": [derived.provider_id],
                "source_count": len(derived.metadata.get("inputs", [])),
                "direct_source_count": 0,
                "derived": True,
                "formula": derived.metadata.get("formula"),
                "inputs": derived.metadata.get("inputs", []),
                "fallback_reason": "no_valid_direct_quote",
            },
        )

    def telegram_fallback(
        self,
        *,
        instrument: InstrumentDefinition,
        quotes: list[ProviderQuote],
        price: Decimal,
        reason: str,
        current: datetime | None = None,
    ) -> CanonicalQuote:
        if not quotes or any(
            quote.source_type is not SourceType.TELEGRAM
            or quote.validation_status is not ValidationStatus.ACCEPTED
            or quote.instrument_id != instrument.instrument_id
            or quote.price is None
            or not quote.is_direct
            or quote.is_derived
            or not bool(quote.metadata.get("whitelisted", False))
            or quote.metadata.get("source_role") != "fallback"
            or not bool(quote.metadata.get("approved_fallback", False))
            for quote in quotes
        ):
            raise ValueError("Telegram fallback requires approved direct quotes")
        now = ensure_utc(current or utc_now())
        quote_ids = [quote.id for quote in quotes if quote.id is not None]
        if len(quote_ids) != len(quotes):
            raise ValueError("Telegram fallback quotes must already be stored")
        confirmed = len(quotes) >= 2
        return self._from_price(
            instrument=instrument,
            price=price,
            observed_at=min(quote.observed_at for quote in quotes),
            current=now,
            status=(CanonicalStatus.CONFIRMED if confirmed else CanonicalStatus.LIVE),
            primary_quote_id=None,
            verification_quote_ids=quote_ids,
            verification_status=(
                VerificationStatus.CONFIRMED
                if confirmed
                else VerificationStatus.NOT_REQUIRED
            ),
            reason=reason,
            source_summary={
                "primary_provider_id": None,
                "provider_ids": [quote.provider_id for quote in quotes],
                "source_count": len(quotes),
                "direct_source_count": len(quotes),
                "derived": False,
                "verification_progress": "complete",
                "fallback_reason": "approved_telegram_fallback",
            },
        )

    @staticmethod
    def _from_price(
        *,
        instrument: InstrumentDefinition,
        price: Decimal,
        observed_at: datetime,
        current: datetime,
        status: CanonicalStatus,
        primary_quote_id: int | None,
        verification_quote_ids: list[int],
        verification_status: VerificationStatus,
        reason: str,
        source_summary: dict,
        candidate_price: Decimal | None = None,
        candidate_provider_id: str | None = None,
    ) -> CanonicalQuote:
        freshness_anchor = ensure_utc(observed_at)
        return CanonicalQuote.create(
            instrument_id=instrument.instrument_id,
            price=price,
            status=status,
            primary_quote_id=primary_quote_id,
            verification_quote_ids=verification_quote_ids,
            source_summary=source_summary,
            observed_at=observed_at,
            canonical_at=current,
            valid_until=freshness_anchor + timedelta(seconds=instrument.operational_ttl_seconds),
            stale_at=freshness_anchor + timedelta(seconds=instrument.stale_after_seconds),
            expires_at=freshness_anchor + timedelta(seconds=instrument.expire_after_seconds),
            is_persisted=False,
            decision_reason=reason,
            verification_status=verification_status,
            candidate_price=candidate_price,
            candidate_provider_id=candidate_provider_id,
        )

    @staticmethod
    def _difference_percent(left: Decimal, right: Decimal | None) -> Decimal:
        if right is None or right <= 0:
            return Decimal("999")
        return abs(left - right) / right * Decimal(100)

    @staticmethod
    def _verification_summary(
        primary: ProviderQuote,
        verifiers: list[ProviderQuote],
        assessment: AnomalyAssessment,
    ) -> dict:
        provider_ids = [primary.provider_id, *[quote.provider_id for quote in verifiers]]
        return {
            "primary_provider_id": primary.provider_id,
            "provider_ids": provider_ids,
            "source_count": len(provider_ids),
            "direct_source_count": len(provider_ids),
            "derived": False,
            "candidate_price": json_number(primary.price),
            "candidate_difference_percent": json_number(assessment.deviation_percent),
            "verification_progress": "complete",
        }


canonical_policy = CanonicalPricePolicy()
