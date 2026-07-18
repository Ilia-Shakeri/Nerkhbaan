from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import pstdev
from typing import Iterable

from .models import InstrumentDefinition, ensure_utc, utc_now


@dataclass(frozen=True, slots=True)
class AnomalyAssessment:
    is_suspicious: bool
    deviation_percent: Decimal
    dynamic_threshold_percent: Decimal
    volatility_percent: Decimal
    severity: str
    reason: str


class DynamicAnomalyDetector:
    def assess(
        self,
        *,
        instrument: InstrumentDefinition,
        candidate_price: Decimal,
        previous_price: Decimal,
        previous_observed_at: datetime,
        recent_prices: Iterable[Decimal],
        provider_success_rate: Decimal,
        now: datetime | None = None,
    ) -> AnomalyAssessment:
        if not instrument.accepts(candidate_price):
            return AnomalyAssessment(
                is_suspicious=True,
                deviation_percent=Decimal("999"),
                dynamic_threshold_percent=instrument.base_anomaly_threshold_percent,
                volatility_percent=Decimal(0),
                severity="critical",
                reason="candidate_outside_sanity_bounds",
            )
        if previous_price <= 0:
            raise ValueError("Previous canonical price must be positive")

        current = ensure_utc(now or utc_now())
        previous_time = ensure_utc(previous_observed_at)
        age_seconds = max(0.0, (current - previous_time).total_seconds())
        volatility = self._volatility_percent(recent_prices)
        reliability = min(Decimal(1), max(Decimal(0), provider_success_rate))

        base = instrument.base_anomaly_threshold_percent
        volatility_allowance = min(base * Decimal(2), volatility * Decimal("1.5"))
        age_ratio = Decimal(str(min(4.0, age_seconds / instrument.operational_ttl_seconds)))
        age_allowance = min(base, base * age_ratio * Decimal("0.20"))
        reliability_factor = Decimal("0.65") + Decimal("0.35") * reliability
        dynamic = (base + volatility_allowance + age_allowance) * reliability_factor
        dynamic = min(instrument.maximum_dynamic_threshold_percent, max(base * Decimal("0.5"), dynamic))

        deviation = abs(candidate_price - previous_price) / previous_price * Decimal(100)
        suspicious = deviation > dynamic
        if not suspicious:
            severity = "none"
            reason = "within_dynamic_threshold"
        elif deviation >= dynamic * Decimal(3):
            severity = "critical"
            reason = "candidate_exceeds_dynamic_threshold_by_3x"
        elif deviation >= dynamic * Decimal(2):
            severity = "high"
            reason = "candidate_exceeds_dynamic_threshold_by_2x"
        else:
            severity = "medium"
            reason = "candidate_exceeds_dynamic_threshold"
        return AnomalyAssessment(
            is_suspicious=suspicious,
            deviation_percent=deviation.quantize(Decimal("0.000001")),
            dynamic_threshold_percent=dynamic.quantize(Decimal("0.000001")),
            volatility_percent=volatility.quantize(Decimal("0.000001")),
            severity=severity,
            reason=reason,
        )

    @staticmethod
    def _volatility_percent(prices: Iterable[Decimal]) -> Decimal:
        values = [float(value) for value in prices if value.is_finite() and value > 0]
        if len(values) < 3:
            return Decimal(0)
        returns = [
            (current - previous) / previous * 100
            for previous, current in zip(values, values[1:])
            if previous > 0 and math.isfinite(current)
        ]
        if len(returns) < 2:
            return Decimal(0)
        return Decimal(str(pstdev(returns)))


anomaly_detector = DynamicAnomalyDetector()
