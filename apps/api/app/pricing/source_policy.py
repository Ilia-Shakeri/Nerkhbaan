from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from statistics import median

from .models import (
    InstrumentDefinition,
    ProviderQuote,
    SourceType,
    ValidationStatus,
    ensure_utc,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class TelegramFallbackDecision:
    eligible: bool
    price: Decimal | None
    quote_ids: tuple[int, ...]
    source_ids: tuple[str, ...]
    reason: str


class SourceEligibilityPolicy:
    minimum_verifier_trust = Decimal("0.5")
    minimum_fallback_trust = Decimal("0.8")

    def telegram_verifiers(
        self,
        *,
        instrument: InstrumentDefinition,
        candidate: ProviderQuote,
        quotes: list[ProviderQuote],
        maximum_difference_percent: Decimal,
        maximum_count: int,
        now: datetime | None = None,
    ) -> list[ProviderQuote]:
        eligible = self._eligible_for_role(
            instrument=instrument,
            quotes=quotes,
            role="verifier",
            minimum_trust=self.minimum_verifier_trust,
            now=now,
        )
        confirming: list[ProviderQuote] = []
        for quote in eligible:
            maximum_deviation = self._metadata_decimal(
                quote, "maximum_deviation_percent"
            )
            if (
                maximum_deviation is not None
                and quote.price is not None
                and candidate.price is not None
                and self._difference_percent(candidate.price, quote.price)
                <= min(maximum_difference_percent, maximum_deviation)
            ):
                confirming.append(quote)
        confirming.sort(
            key=lambda quote: (
                Decimal(str(quote.metadata["trust_score"])),
                quote.confidence_score,
                quote.observed_at,
            ),
            reverse=True,
        )
        return confirming[: max(0, maximum_count)]

    def telegram_fallback(
        self,
        *,
        instrument: InstrumentDefinition,
        quotes: list[ProviderQuote],
        maximum_difference_percent: Decimal,
        reference_price: Decimal | None = None,
        now: datetime | None = None,
    ) -> TelegramFallbackDecision:
        eligible = self._eligible_for_role(
            instrument=instrument,
            quotes=quotes,
            role="fallback",
            minimum_trust=self.minimum_fallback_trust,
            now=now,
        )
        if reference_price is not None and reference_price > 0:
            within_reference: list[ProviderQuote] = []
            for quote in eligible:
                maximum_deviation = self._metadata_decimal(
                    quote, "maximum_deviation_percent"
                )
                if (
                    maximum_deviation is not None
                    and quote.price is not None
                    and self._difference_percent(reference_price, quote.price)
                    <= maximum_deviation
                ):
                    within_reference.append(quote)
            eligible = within_reference
        source_ids = {
            str(quote.metadata["source_identity"])
            for quote in eligible
        }
        requires_two = any(
            bool(quote.metadata.get("requires_multiple_sources", False))
            for quote in eligible
        )
        required_count = 2 if requires_two else 1
        if len(eligible) < required_count:
            return TelegramFallbackDecision(
                False,
                None,
                (),
                tuple(sorted(source_ids)),
                "insufficient_independent_telegram_sources",
            )
        prices = [quote.price for quote in eligible if quote.price is not None]
        chosen = Decimal(str(median(prices)))
        if len(prices) >= 2:
            spread = (max(prices) - min(prices)) / chosen * Decimal(100)
            source_limits = [
                maximum_deviation
                for quote in eligible
                if (
                    maximum_deviation := self._metadata_decimal(
                        quote, "maximum_deviation_percent"
                    )
                ) is not None
            ]
            if not source_limits:
                return TelegramFallbackDecision(
                    False,
                    None,
                    (),
                    tuple(sorted(source_ids)),
                    "invalid_telegram_source_deviation",
                )
            source_limit = min(source_limits)
            if spread > min(maximum_difference_percent, source_limit):
                return TelegramFallbackDecision(
                    False,
                    None,
                    (),
                    tuple(sorted(source_ids)),
                    "telegram_sources_disagree",
                )
        return TelegramFallbackDecision(
            True,
            chosen,
            tuple(quote.id for quote in eligible if quote.id is not None),
            tuple(sorted(source_ids)),
            "approved_telegram_fallback_sources_agree",
        )

    def _eligible_for_role(
        self,
        *,
        instrument: InstrumentDefinition,
        quotes: list[ProviderQuote],
        role: str,
        minimum_trust: Decimal,
        now: datetime | None,
    ) -> list[ProviderQuote]:
        current = ensure_utc(now or utc_now())
        eligible: list[ProviderQuote] = []
        source_ids: set[str] = set()
        approval_key = f"approved_{role}"
        for quote in quotes:
            source_id = str(quote.metadata.get("source_identity") or "")
            try:
                source_trust = Decimal(str(quote.metadata.get("trust_score", "0")))
                minimum_confidence = Decimal(
                    str(quote.metadata.get("minimum_confidence", "1"))
                )
                maximum_age = int(
                    quote.metadata.get(
                        "maximum_message_age_seconds",
                        instrument.operational_ttl_seconds,
                    )
                )
                maximum_deviation = Decimal(
                    str(quote.metadata.get("maximum_deviation_percent", "0"))
                )
            except (InvalidOperation, OverflowError, TypeError, ValueError):
                continue
            age_seconds = (current - quote.observed_at).total_seconds()
            if (
                quote.source_type is not SourceType.TELEGRAM
                or quote.instrument_id != instrument.instrument_id
                or quote.validation_status is not ValidationStatus.ACCEPTED
                or quote.price is None
                or not quote.is_direct
                or quote.is_derived
                or quote.is_suspicious
                or not bool(quote.metadata.get("whitelisted", False))
                or quote.metadata.get("source_role") != role
                or not bool(quote.metadata.get(approval_key, False))
                or quote.id is None
                or not source_id
                or source_id in source_ids
                or not source_trust.is_finite()
                or source_trust < minimum_trust
                or source_trust > 1
                or not minimum_confidence.is_finite()
                or not Decimal(0) <= minimum_confidence <= Decimal(1)
                or quote.confidence_score < minimum_confidence
                or not maximum_deviation.is_finite()
                or maximum_deviation <= 0
                or maximum_age <= 0
                or age_seconds < 0
                or age_seconds > min(maximum_age, instrument.operational_ttl_seconds)
            ):
                continue
            eligible.append(quote)
            source_ids.add(source_id)
        return eligible

    @staticmethod
    def _difference_percent(left: Decimal, right: Decimal) -> Decimal:
        if right <= 0:
            return Decimal("999")
        return abs(left - right) / right * Decimal(100)

    @staticmethod
    def _metadata_decimal(quote: ProviderQuote, key: str) -> Decimal | None:
        try:
            value = Decimal(str(quote.metadata[key]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return None
        return value if value.is_finite() and value > 0 else None


source_eligibility_policy = SourceEligibilityPolicy()
