from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class Currency(StrEnum):
    TOMAN = "TOMAN"
    USD = "USD"


class WeightUnit(StrEnum):
    GRAM = "gram"
    TROY_OUNCE = "troy_ounce"
    UNIT = "unit"


class Market(StrEnum):
    IRAN_PHYSICAL = "iran_physical"
    GLOBAL_SPOT = "global_spot"
    IRAN_EXCHANGE = "iran_exchange"
    GLOBAL_EXCHANGE = "global_exchange"
    REFERENCE = "reference"


class Region(StrEnum):
    IRAN = "iran"
    INTERNATIONAL = "international"
    GLOBAL = "global"


class SourceType(StrEnum):
    HTTP = "http"
    TELEGRAM = "telegram"
    DERIVED = "derived"
    LEGACY = "legacy"


class ProviderRole(StrEnum):
    PRIMARY = "primary"
    VERIFIER = "verifier"
    FALLBACK = "fallback"
    COMPARE = "compare"


class RequestPurpose(StrEnum):
    NORMAL = "normal"
    ANOMALY = "anomaly"
    FALLBACK = "fallback"
    BACKFILL = "backfill"


class ValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUSPICIOUS = "suspicious"


class PersistenceStatus(StrEnum):
    PERSISTED = "persisted"
    QUEUED = "queued"
    UNPERSISTED = "unpersisted"


class CanonicalStatus(StrEnum):
    LIVE = "live"
    CONFIRMED = "confirmed"
    FRESH_CACHE = "fresh_cache"
    VERIFYING = "verifying"
    SUSPICIOUS = "suspicious"
    SUSPICIOUS_UNCONFIRMED = "suspicious_unconfirmed"
    DERIVED_FALLBACK = "derived_fallback"
    STALE = "stale"
    EXPIRED = "expired"
    UNPERSISTED = "unpersisted"
    UNAVAILABLE = "unavailable"


class VerificationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISAGREED = "disagreed"
    INSUFFICIENT = "insufficient"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str):
        raise ValueError("Expected an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ensure_utc(parsed)


def decimal_value(value: object, *, allow_zero: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Expected a decimal number") from exc
    if not result.is_finite() or (result < 0 if allow_zero else result <= 0):
        raise ValueError("Price values must be finite and positive")
    return result


def decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return decimal_value(value)


def json_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("JSON numbers must be finite")
    return result


@dataclass(frozen=True, slots=True)
class InstrumentDefinition:
    instrument_id: str
    base_asset: str
    quote_currency: Currency
    market: Market
    region: Region
    weight_unit: WeightUnit
    purity: Decimal | None
    display_decimals: int
    operational_ttl_seconds: int
    stale_after_seconds: int
    expire_after_seconds: int
    base_anomaly_threshold_percent: Decimal
    maximum_dynamic_threshold_percent: Decimal
    minimum_price: Decimal
    maximum_price: Decimal
    importance: int
    maximum_verification_depth: int
    enabled: bool = True
    allow_derived_fallback: bool = False

    def __post_init__(self) -> None:
        if not self.instrument_id or self.instrument_id != self.instrument_id.upper():
            raise ValueError("Instrument IDs must be uppercase")
        if not 0 <= self.display_decimals <= 12:
            raise ValueError("Display decimals are out of range")
        if not (
            0 < self.operational_ttl_seconds
            <= self.stale_after_seconds
            <= self.expire_after_seconds
        ):
            raise ValueError("Instrument cache windows are invalid")
        if self.minimum_price >= self.maximum_price:
            raise ValueError("Instrument sanity bounds are invalid")
        if self.base_anomaly_threshold_percent > self.maximum_dynamic_threshold_percent:
            raise ValueError("Instrument anomaly thresholds are invalid")

    def accepts(self, price: Decimal) -> bool:
        return price.is_finite() and self.minimum_price <= price <= self.maximum_price

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "base_asset": self.base_asset,
            "quote_currency": self.quote_currency.value,
            "market": self.market.value,
            "region": self.region.value,
            "weight_unit": self.weight_unit.value,
            "purity": json_number(self.purity),
            "display_decimals": self.display_decimals,
            "operational_ttl_seconds": self.operational_ttl_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "expire_after_seconds": self.expire_after_seconds,
            "base_anomaly_threshold_percent": json_number(
                self.base_anomaly_threshold_percent
            ),
            "maximum_dynamic_threshold_percent": json_number(
                self.maximum_dynamic_threshold_percent
            ),
            "importance": self.importance,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class ProviderQuote:
    id: int | None
    instrument_id: str
    provider_id: str
    source_type: SourceType
    price: Decimal | None
    currency: Currency
    weight_unit: WeightUnit
    purity: Decimal | None
    observed_at: datetime
    received_at: datetime
    parser_version: str
    validation_status: ValidationStatus
    bid: Decimal | None = None
    ask: Decimal | None = None
    volume: Decimal | None = None
    latency_ms: int | None = None
    http_status: int | None = None
    confidence_score: Decimal = Decimal("1")
    is_direct: bool = True
    is_derived: bool = False
    is_suspicious: bool = False
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_payload_reference: str | None = None
    persistence_status: PersistenceStatus = PersistenceStatus.UNPERSISTED
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        self.observed_at = ensure_utc(self.observed_at)
        self.received_at = ensure_utc(self.received_at)
        if self.received_at < self.observed_at:
            raise ValueError("Quote receive time cannot precede observation time")
        if self.price is not None:
            self.price = decimal_value(self.price)
        self.bid = decimal_or_none(self.bid)
        self.ask = decimal_or_none(self.ask)
        self.volume = decimal_or_none(self.volume)
        self.confidence_score = decimal_value(self.confidence_score, allow_zero=True)
        if self.confidence_score > 1:
            raise ValueError("Confidence score must be between zero and one")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("Order book bid cannot exceed ask")
        if self.validation_status is ValidationStatus.ACCEPTED and self.price is None:
            raise ValueError("Accepted quotes require a price")
        if self.validation_status is ValidationStatus.REJECTED and not self.rejection_reason:
            raise ValueError("Rejected quotes require a reason")
        if not self.idempotency_key:
            raw = "|".join(
                (
                    self.instrument_id,
                    self.provider_id,
                    self.observed_at.isoformat(),
                    str(self.price),
                    self.parser_version,
                )
            )
            self.idempotency_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create(cls, **values: Any) -> "ProviderQuote":
        values.setdefault("id", None)
        values.setdefault("received_at", utc_now())
        return cls(**values)

    def to_dict(self, *, authenticated: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "instrument_id": self.instrument_id,
            "provider_id": self.provider_id if authenticated else None,
            "source_type": self.source_type.value,
            "price": json_number(self.price),
            "currency": self.currency.value,
            "weight_unit": self.weight_unit.value,
            "purity": json_number(self.purity),
            "bid": json_number(self.bid),
            "ask": json_number(self.ask),
            "volume": json_number(self.volume),
            "observed_at": self.observed_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "latency_ms": self.latency_ms,
            "http_status": self.http_status if authenticated else None,
            "parser_version": self.parser_version if authenticated else None,
            "validation_status": self.validation_status.value,
            "confidence_score": json_number(self.confidence_score),
            "is_direct": self.is_direct,
            "is_derived": self.is_derived,
            "is_suspicious": self.is_suspicious,
            "rejection_reason": self.rejection_reason if authenticated else None,
            "raw_payload_reference": (
                self.raw_payload_reference if authenticated else None
            ),
            "persistence_status": self.persistence_status.value,
            "idempotency_key": self.idempotency_key if authenticated else None,
        }
        if authenticated:
            payload["metadata"] = self.metadata
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderQuote":
        return cls(
            id=int(payload["id"]) if payload.get("id") is not None else None,
            instrument_id=str(payload["instrument_id"]),
            provider_id=str(payload["provider_id"]),
            source_type=SourceType(payload["source_type"]),
            price=decimal_or_none(payload.get("price")),
            currency=Currency(payload["currency"]),
            weight_unit=WeightUnit(payload["weight_unit"]),
            purity=decimal_or_none(payload.get("purity")),
            bid=decimal_or_none(payload.get("bid")),
            ask=decimal_or_none(payload.get("ask")),
            volume=decimal_or_none(payload.get("volume")),
            observed_at=parse_datetime(payload["observed_at"]),
            received_at=parse_datetime(payload["received_at"]),
            latency_ms=payload.get("latency_ms"),
            http_status=payload.get("http_status"),
            parser_version=str(payload["parser_version"]),
            validation_status=ValidationStatus(payload["validation_status"]),
            confidence_score=decimal_value(
                payload.get("confidence_score", 1), allow_zero=True
            ),
            is_direct=bool(payload.get("is_direct", True)),
            is_derived=bool(payload.get("is_derived", False)),
            is_suspicious=bool(payload.get("is_suspicious", False)),
            rejection_reason=payload.get("rejection_reason"),
            metadata=dict(payload.get("metadata") or {}),
            raw_payload_reference=payload.get("raw_payload_reference"),
            persistence_status=PersistenceStatus(
                payload.get("persistence_status", PersistenceStatus.UNPERSISTED.value)
            ),
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )


@dataclass(slots=True)
class CanonicalQuote:
    id: int | None
    instrument_id: str
    price: Decimal
    status: CanonicalStatus
    primary_quote_id: int | None
    verification_quote_ids: list[int]
    source_summary: dict[str, Any]
    observed_at: datetime
    canonical_at: datetime
    valid_until: datetime
    stale_at: datetime
    expires_at: datetime
    is_persisted: bool
    decision_reason: str
    change_1h: Decimal | None = None
    change_24h: Decimal | None = None
    change_7d: Decimal | None = None
    change_30d: Decimal | None = None
    verification_status: VerificationStatus = VerificationStatus.NOT_REQUIRED
    candidate_price: Decimal | None = None
    candidate_provider_id: str | None = None
    sequence_number: int | None = None
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        self.price = decimal_value(self.price)
        self.candidate_price = decimal_or_none(self.candidate_price)
        self.observed_at = ensure_utc(self.observed_at)
        self.canonical_at = ensure_utc(self.canonical_at)
        self.valid_until = ensure_utc(self.valid_until)
        self.stale_at = ensure_utc(self.stale_at)
        self.expires_at = ensure_utc(self.expires_at)
        if not (
            self.observed_at <= self.canonical_at
            and self.valid_until <= self.stale_at <= self.expires_at
        ):
            raise ValueError("Canonical quote timestamps are invalid")
        if (
            self.status
            in {
                CanonicalStatus.LIVE,
                CanonicalStatus.CONFIRMED,
                CanonicalStatus.FRESH_CACHE,
                CanonicalStatus.DERIVED_FALLBACK,
                CanonicalStatus.UNPERSISTED,
            }
            and self.canonical_at > self.expires_at
        ):
            raise ValueError("Accepted canonical quote is already expired")
        for name in ("change_1h", "change_24h", "change_7d", "change_30d"):
            value = getattr(self, name)
            if value is not None:
                parsed = Decimal(str(value))
                if not parsed.is_finite():
                    raise ValueError("Change values must be finite")
                setattr(self, name, parsed)
        if not self.idempotency_key:
            raw = "|".join(
                (
                    self.instrument_id,
                    self.canonical_at.isoformat(),
                    str(self.price),
                    self.status.value,
                )
            )
            self.idempotency_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create(cls, **values: Any) -> "CanonicalQuote":
        values.setdefault("id", None)
        return cls(**values)

    def effective_status(self, now: datetime | None = None) -> CanonicalStatus:
        current = ensure_utc(now or utc_now())
        if current > self.expires_at:
            return CanonicalStatus.EXPIRED
        if current > self.stale_at:
            return CanonicalStatus.STALE
        if current > self.valid_until and self.status in {
            CanonicalStatus.LIVE,
            CanonicalStatus.CONFIRMED,
        }:
            return CanonicalStatus.FRESH_CACHE
        return self.status

    def to_dict(
        self,
        *,
        authenticated: bool = True,
        now: datetime | None = None,
        evaluate_status: bool = True,
    ) -> dict[str, Any]:
        effective = self.effective_status(now) if evaluate_status else self.status
        public_status = effective
        if not authenticated:
            public_status = {
                CanonicalStatus.CONFIRMED: CanonicalStatus.LIVE,
                CanonicalStatus.SUSPICIOUS_UNCONFIRMED: CanonicalStatus.SUSPICIOUS,
            }.get(effective, effective)
        current = ensure_utc(now or utc_now())
        summary = self.source_summary if authenticated else _public_source_summary(self.source_summary)
        return {
            "id": self.id,
            "instrument_id": self.instrument_id,
            "price": json_number(self.price),
            "status": public_status.value,
            "primary_quote_id": self.primary_quote_id if authenticated else None,
            "verification_quote_ids": self.verification_quote_ids if authenticated else [],
            "source_summary": summary,
            "observed_at": self.observed_at.isoformat(),
            "canonical_at": self.canonical_at.isoformat(),
            "age_seconds": max(0, int((current - self.observed_at).total_seconds())),
            "valid_until": self.valid_until.isoformat(),
            "stale_at": self.stale_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "is_persisted": self.is_persisted,
            "persistence_status": "persisted" if self.is_persisted else "unpersisted",
            "decision_reason": self.decision_reason if authenticated else None,
            "verification_status": self.verification_status.value,
            "candidate_price": json_number(self.candidate_price),
            "candidate_provider_id": self.candidate_provider_id if authenticated else None,
            "sequence_number": self.sequence_number,
            "change_1h": json_number(self.change_1h),
            "change_24h": json_number(self.change_24h),
            "change_7d": json_number(self.change_7d),
            "change_30d": json_number(self.change_30d),
            "idempotency_key": self.idempotency_key if authenticated else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CanonicalQuote":
        return cls(
            id=int(payload["id"]) if payload.get("id") is not None else None,
            instrument_id=str(payload["instrument_id"]),
            price=decimal_value(payload["price"]),
            status=CanonicalStatus(payload["status"]),
            primary_quote_id=payload.get("primary_quote_id"),
            verification_quote_ids=[int(value) for value in payload.get("verification_quote_ids", [])],
            source_summary=dict(payload.get("source_summary") or {}),
            observed_at=parse_datetime(payload["observed_at"]),
            canonical_at=parse_datetime(payload["canonical_at"]),
            valid_until=parse_datetime(payload["valid_until"]),
            stale_at=parse_datetime(payload["stale_at"]),
            expires_at=parse_datetime(payload["expires_at"]),
            is_persisted=bool(payload.get("is_persisted", False)),
            decision_reason=str(payload.get("decision_reason") or "not recorded"),
            change_1h=_change_or_none(payload.get("change_1h")),
            change_24h=_change_or_none(payload.get("change_24h")),
            change_7d=_change_or_none(payload.get("change_7d")),
            change_30d=_change_or_none(payload.get("change_30d")),
            verification_status=VerificationStatus(
                payload.get("verification_status", VerificationStatus.NOT_REQUIRED.value)
            ),
            candidate_price=decimal_or_none(payload.get("candidate_price")),
            candidate_provider_id=payload.get("candidate_provider_id"),
            sequence_number=(
                int(payload["sequence_number"])
                if payload.get("sequence_number") is not None
                else None
            ),
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    status: VerificationStatus
    candidate_quote_id: int | None
    verification_quote_ids: tuple[int, ...]
    deviation_percent: Decimal | None
    threshold_percent: Decimal
    decision_reason: str


@dataclass(slots=True)
class ProviderRuntimeState:
    provider_id: str
    instrument_id: str
    circuit_state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    success_count: int = 0
    failure_count: int = 0
    average_latency_ms: Decimal | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    circuit_open_until: datetime | None = None
    cooldown_until: datetime | None = None
    last_error_code: str | None = None
    operational_status: str = "unknown"

    @property
    def success_rate(self) -> Decimal:
        total = self.success_count + self.failure_count
        if total == 0:
            return Decimal("0.5")
        return Decimal(self.success_count) / Decimal(total)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "instrument_id": self.instrument_id,
            "circuit_state": self.circuit_state.value,
            "consecutive_failures": self.consecutive_failures,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": json_number(self.success_rate),
            "average_latency_ms": json_number(self.average_latency_ms),
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
            "circuit_open_until": self.circuit_open_until.isoformat() if self.circuit_open_until else None,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
            "last_error_code": self.last_error_code,
            "operational_status": self.operational_status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderRuntimeState":
        return cls(
            provider_id=str(payload["provider_id"]),
            instrument_id=str(payload["instrument_id"]),
            circuit_state=CircuitState(payload.get("circuit_state", CircuitState.CLOSED.value)),
            consecutive_failures=int(payload.get("consecutive_failures", 0)),
            success_count=int(payload.get("success_count", 0)),
            failure_count=int(payload.get("failure_count", 0)),
            average_latency_ms=_change_or_none(payload.get("average_latency_ms")),
            last_success_at=_datetime_or_none(payload.get("last_success_at")),
            last_failure_at=_datetime_or_none(payload.get("last_failure_at")),
            circuit_open_until=_datetime_or_none(payload.get("circuit_open_until")),
            cooldown_until=_datetime_or_none(payload.get("cooldown_until")),
            last_error_code=payload.get("last_error_code"),
            operational_status=str(payload.get("operational_status", "unknown")),
        )


@dataclass(slots=True)
class InstrumentRuntimeState:
    instrument_id: str
    status: CanonicalStatus
    last_refresh_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    refresh_owner: str | None = None


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _public_source_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "source_count",
        "direct_source_count",
        "derived",
        "candidate_price",
        "candidate_difference_percent",
        "verification_progress",
        "fallback_reason",
    }
    return {key: value for key, value in summary.items() if key in allowed}


def _change_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Expected a finite decimal")
    return result


def _datetime_or_none(value: object) -> datetime | None:
    return None if value is None else parse_datetime(value)
