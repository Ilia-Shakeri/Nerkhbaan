from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from .anomaly import AnomalyAssessment
from .freshness import FreshnessPolicy, FreshnessStatus, freshness_boundaries
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    InstrumentDefinition,
    PersistenceStatus,
    ProviderQuote,
    SourceSemantic,
    SourceType,
    ValidationStatus,
    VerificationDecision,
    VerificationStatus,
    ensure_utc,
    json_number,
    parse_datetime,
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
        current = ensure_utc(now or utc_now())
        if primary.price is None or primary.validation_status is ValidationStatus.REJECTED:
            raise ValueError("Rejected provider quotes cannot become canonical")
        if primary.persistence_status is not PersistenceStatus.PERSISTED:
            raise ValueError("Unstored provider quotes cannot become canonical")
        if primary.source_semantic in {
            SourceSemantic.TELEGRAM_OBSERVATION,
            SourceSemantic.DERIVED,
        }:
            raise ValueError("Non-market quotes cannot be primary canonical sources")
        if not self._is_fresh_quote(primary, instrument, current):
            raise ValueError("Primary quote is not live-eligible")
        valid_verifiers: list[ProviderQuote] = []
        primary_family, primary_venue = self._independence_values(primary)
        seen_families = {primary_family}
        seen_venues = {primary_venue}
        for quote in verifier_quotes:
            family, venue = self._independence_values(quote)
            if (
                quote.price is not None
                and self._is_market_quote(quote)
                and quote.validation_status is ValidationStatus.ACCEPTED
                and quote.persistence_status is PersistenceStatus.PERSISTED
                and quote.instrument_id == primary.instrument_id
                and self._is_fresh_quote(quote, instrument, current)
                and family not in seen_families
                and venue not in seen_venues
            ):
                valid_verifiers.append(quote)
                seen_families.add(family)
                seen_venues.add(venue)

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
                    "direct_source_count": int(primary.is_direct),
                    "derived": False,
                    **self._source_fields(primary),
                },
                source_live_eligible_until=self._quote_live_eligible_until(
                    primary, instrument
                ),
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
        if confirming:
            confirming_ids = [quote.id for quote in confirming if quote.id is not None]
            canonical = self._from_price(
                instrument=instrument,
                price=primary.price,
                observed_at=primary.observed_at,
                current=current,
                status=CanonicalStatus.CONFIRMED,
                primary_quote_id=primary.id,
                verification_quote_ids=confirming_ids,
                verification_status=VerificationStatus.CONFIRMED,
                reason="anomalous_primary_confirmed_by_independent_source",
                source_summary=self._verification_summary(primary, confirming, assessment),
                candidate_price=primary.price,
                candidate_provider_id=primary.provider_id,
                source_live_eligible_until=min(
                    self._quote_live_eligible_until(quote, instrument)
                    for quote in (primary, *confirming)
                ),
            )
            return CanonicalDecision(
                canonical=canonical,
                verification=VerificationDecision(
                    status=VerificationStatus.CONFIRMED,
                    candidate_quote_id=primary.id,
                    verification_quote_ids=tuple(confirming_ids),
                    deviation_percent=assessment.deviation_percent,
                    threshold_percent=tolerance,
                    decision_reason="independent_quote_within_tolerance",
                ),
            )

        comparable = [primary, *valid_verifiers]
        consensus_cluster = self._consensus_cluster(comparable, tolerance)
        consensus_quorum = len(comparable) // 2 + 1
        if len(comparable) >= 3 and len(consensus_cluster) >= consensus_quorum:
            chosen_price = Decimal(
                str(
                    median(
                        [
                            quote.price
                            for quote in consensus_cluster
                            if quote.price is not None
                        ]
                    )
                )
            )
            observed_at = min(quote.observed_at for quote in consensus_cluster)
            consensus_primary = next(
                (quote for quote in consensus_cluster if quote is primary),
                consensus_cluster[0],
            )
            consensus_verifiers = [
                quote for quote in consensus_cluster if quote is not consensus_primary
            ]
            consensus_verifier_ids = [
                quote.id for quote in consensus_verifiers if quote.id is not None
            ]
            source_summary = self._verification_summary(
                consensus_primary,
                consensus_verifiers,
                assessment,
            )
            source_summary.update(
                {
                    "candidate_price": json_number(primary.price),
                    "candidate_provider_id": primary.provider_id,
                    "consensus_method": "median_inlier_cluster",
                    "consensus_source_count": len(consensus_cluster),
                }
            )
            canonical = self._from_price(
                instrument=instrument,
                price=chosen_price,
                observed_at=observed_at,
                current=current,
                status=CanonicalStatus.CONFIRMED,
                primary_quote_id=consensus_primary.id,
                verification_quote_ids=consensus_verifier_ids,
                verification_status=VerificationStatus.CONFIRMED,
                reason="robust_median_of_independent_fresh_inlier_cluster",
                source_summary=source_summary,
                candidate_price=primary.price,
                candidate_provider_id=primary.provider_id,
                source_live_eligible_until=min(
                    self._quote_live_eligible_until(quote, instrument)
                    for quote in consensus_cluster
                ),
            )
            return CanonicalDecision(
                canonical=canonical,
                verification=VerificationDecision(
                    status=VerificationStatus.CONFIRMED,
                    candidate_quote_id=primary.id,
                    verification_quote_ids=tuple(consensus_verifier_ids),
                    deviation_percent=assessment.deviation_percent,
                    threshold_percent=tolerance,
                    decision_reason="independent_inlier_cluster_reached_robust_consensus",
                ),
            )

        verifier_ids = [quote.id for quote in valid_verifiers if quote.id is not None]
        if len(comparable) >= 2:
            if previous is None:
                raise ValueError("Disagreeing quotes cannot bootstrap a canonical price")
            canonical = self.keep_previous(
                previous=previous,
                candidate=primary,
                assessment=assessment,
                status=CanonicalStatus.SUSPICIOUS_UNCONFIRMED,
                current=current,
            )
            canonical.verification_status = VerificationStatus.DISAGREED
            canonical.decision_reason = "disagreeing_sources_previous_canonical_kept"
            canonical.source_summary["verification_progress"] = "disagreed"
            return CanonicalDecision(
                canonical=canonical,
                verification=VerificationDecision(
                    status=VerificationStatus.DISAGREED,
                    candidate_quote_id=primary.id,
                    verification_quote_ids=tuple(verifier_ids),
                    deviation_percent=assessment.deviation_percent,
                    threshold_percent=tolerance,
                    decision_reason="independent_quotes_disagreed_previous_canonical_kept",
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
        if (
            not instrument.allow_derived_fallback
            or not derived.is_derived
            or derived.price is None
            or derived.persistence_status is not PersistenceStatus.PERSISTED
        ):
            raise ValueError("Instrument does not allow this derived fallback")
        now = ensure_utc(current or utc_now())
        source_live_eligible_until = self._quote_live_eligible_until(
            derived, instrument
        )
        if now > source_live_eligible_until:
            raise ValueError("Derived fallback inputs are no longer live-eligible")
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
                "derivation_depth": derived.metadata.get("derivation_depth", 1),
                "provenance": derived.metadata.get("provenance", []),
                "confidence_score": str(derived.confidence_score),
                "fallback_reason": "no_valid_direct_quote",
                **self._source_fields(derived),
            },
            source_live_eligible_until=source_live_eligible_until,
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
            or quote.source_semantic is not SourceSemantic.TELEGRAM_OBSERVATION
            or quote.validation_status is not ValidationStatus.ACCEPTED
            or quote.instrument_id != instrument.instrument_id
            or quote.price is None
            or quote.is_derived
            or quote.persistence_status is not PersistenceStatus.PERSISTED
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
                "direct_source_count": 0,
                "derived": False,
                "source_semantic": SourceSemantic.TELEGRAM_OBSERVATION.value,
                "source_families": [quote.source_family for quote in quotes],
                "venues": [quote.venue for quote in quotes],
                "derivation_depth": 0,
                "provenance": [
                    item
                    for quote in quotes
                    for item in quote.provenance
                ],
                "verification_progress": "complete",
                "fallback_reason": "approved_telegram_fallback",
            },
            source_live_eligible_until=min(
                self._quote_live_eligible_until(quote, instrument)
                for quote in quotes
            ),
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
        source_live_eligible_until: datetime | None = None,
    ) -> CanonicalQuote:
        freshness_anchor = ensure_utc(observed_at)
        valid_until = freshness_anchor + timedelta(
            seconds=instrument.operational_ttl_seconds
        )
        if source_live_eligible_until is not None:
            valid_until = min(valid_until, ensure_utc(source_live_eligible_until))
        return CanonicalQuote.create(
            instrument_id=instrument.instrument_id,
            price=price,
            status=status,
            primary_quote_id=primary_quote_id,
            verification_quote_ids=verification_quote_ids,
            source_summary=source_summary,
            observed_at=observed_at,
            canonical_at=current,
            valid_until=valid_until,
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

    @classmethod
    def _consensus_cluster(
        cls,
        quotes: list[ProviderQuote],
        tolerance_percent: Decimal,
    ) -> list[ProviderQuote]:
        ordered = sorted(
            (quote for quote in quotes if quote.price is not None),
            key=lambda quote: quote.price,
        )
        best: list[ProviderQuote] = []
        for start in range(len(ordered)):
            for end in range(start + 1, len(ordered) + 1):
                cluster = ordered[start:end]
                center = Decimal(str(median([quote.price for quote in cluster])))
                maximum_deviation = max(
                    abs(quote.price - center) / center * Decimal(100)
                    for quote in cluster
                    if quote.price is not None
                )
                if maximum_deviation <= tolerance_percent and len(cluster) > len(best):
                    best = cluster
        return best

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
            "direct_source_count": sum(
                int(quote.is_direct) for quote in (primary, *verifiers)
            ),
            "derived": False,
            "candidate_price": json_number(primary.price),
            "candidate_difference_percent": json_number(assessment.deviation_percent),
            "verification_progress": "complete",
            **CanonicalPricePolicy._source_fields(primary),
            "sources": [
                CanonicalPricePolicy._source_fields(quote)
                for quote in (primary, *verifiers)
            ],
        }

    @staticmethod
    def _is_market_quote(quote: ProviderQuote) -> bool:
        return quote.source_semantic in {
            SourceSemantic.EXCHANGE_ORDERBOOK,
            SourceSemantic.EXCHANGE_TRADE,
            SourceSemantic.AGGREGATOR,
            SourceSemantic.REFERENCE_RATE,
            SourceSemantic.PHYSICAL_MARKET_QUOTE,
        }

    @staticmethod
    def _independence_values(quote: ProviderQuote) -> tuple[str, str]:
        family = str(quote.source_family or quote.provider_id).strip().lower()
        venue = str(quote.venue or quote.source_family or quote.provider_id).strip().lower()
        return family, venue

    @staticmethod
    def _is_fresh_quote(
        quote: ProviderQuote,
        instrument: InstrumentDefinition,
        current: datetime,
    ) -> bool:
        try:
            boundaries = CanonicalPricePolicy._quote_freshness_boundaries(
                quote, instrument
            )
        except ValueError:
            return False
        return boundaries.status_at(current) is FreshnessStatus.LIVE

    @staticmethod
    def _quote_freshness_boundaries(
        quote: ProviderQuote,
        instrument: InstrumentDefinition,
    ):
        raw_provider_ttl = quote.metadata.get(
            "provider_live_ttl_seconds",
            instrument.operational_ttl_seconds,
        )
        try:
            provider_ttl = int(raw_provider_ttl)
        except (TypeError, ValueError):
            provider_ttl = instrument.operational_ttl_seconds
        if provider_ttl <= 0:
            raise ValueError("Provider live TTL must be positive")
        policy = FreshnessPolicy(
            maximum_source_age_seconds=min(
                provider_ttl,
                instrument.operational_ttl_seconds,
                instrument.expire_after_seconds,
            ),
            provider_live_ttl_seconds=provider_ttl,
            instrument_operational_ttl_seconds=instrument.operational_ttl_seconds,
            instrument_stale_after_seconds=instrument.stale_after_seconds,
            instrument_expire_after_seconds=instrument.expire_after_seconds,
        )
        return freshness_boundaries(
            quote.observed_at,
            quote.received_at,
            policy,
        )

    @staticmethod
    def _quote_live_eligible_until(
        quote: ProviderQuote,
        instrument: InstrumentDefinition,
    ) -> datetime:
        live_until = CanonicalPricePolicy._quote_freshness_boundaries(
            quote, instrument
        ).live_eligible_until
        for field_name in (
            "effective_live_eligible_until",
            "input_live_eligible_until",
        ):
            raw_value = quote.metadata.get(field_name)
            if raw_value is not None:
                live_until = min(live_until, parse_datetime(raw_value))
        return live_until

    @staticmethod
    def _source_fields(quote: ProviderQuote) -> dict:
        return {
            "source_semantic": quote.source_semantic.value,
            "source_family": quote.source_family,
            "venue": quote.venue,
            "bid": json_number(quote.bid),
            "ask": json_number(quote.ask),
            "last": json_number(quote.last),
            "selected_price_semantic": quote.selected_price_semantic.value,
            "original_currency": quote.original_currency,
            "original_value": json_number(quote.original_value),
            "conversion_factor": json_number(quote.conversion_factor),
            "source_timestamp": quote.observed_at.isoformat(),
            "receive_timestamp": quote.received_at.isoformat(),
            "route_id": quote.route_id,
            "spread_bps": json_number(quote.spread_bps),
            "derivation_depth": quote.derivation_depth,
            "provenance": list(quote.provenance),
        }


canonical_policy = CanonicalPricePolicy()
