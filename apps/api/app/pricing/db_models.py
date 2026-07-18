from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class InstrumentRecord(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(24), nullable=False)
    weight_unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    purity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    display_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    operational_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    expire_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    base_anomaly_threshold_percent: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )
    maximum_dynamic_threshold_percent: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )
    minimum_sanity_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    maximum_sanity_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_derived_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PricingProviderRecord(Base):
    __tablename__ = "pricing_providers"

    provider_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="http")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="fallback")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    trust_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required_key_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_per_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    requests_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_anomaly_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_fallback_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_after_429_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_request_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InstrumentProviderConfigRecord(Base):
    __tablename__ = "instrument_provider_configs"
    __table_args__ = (
        Index("ix_instrument_provider_role_priority", "instrument_id", "role", "priority"),
    )

    instrument_id: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_id", ondelete="CASCADE"), primary_key=True
    )
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("pricing_providers.provider_id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    trust_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    operational_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    maximum_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    maximum_verification_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    parser_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProviderQuoteRecord(Base):
    __tablename__ = "provider_quotes"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "observed_at", name="uq_provider_quote_idempotency_time"),
        Index("ix_provider_quotes_instrument_time", "instrument_id", "observed_at"),
        Index("ix_provider_quotes_provider_time", "provider_id", "instrument_id", "observed_at"),
        Index("ix_provider_quotes_validation_time", "validation_status", "observed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    weight_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    purity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    ask: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    is_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    extra: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    raw_payload_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    persistence_status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    quote_role: Mapped[str] = mapped_column(String(24), nullable=False, default="normal")


class CanonicalQuoteRecord(Base):
    __tablename__ = "canonical_quotes"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "canonical_at", name="uq_canonical_quote_idempotency_time"),
        Index("ix_canonical_quotes_instrument_time", "instrument_id", "canonical_at"),
        Index("ix_canonical_quotes_status_time", "status", "canonical_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    canonical_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(String(64), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_quote_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verification_quote_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidate_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    candidate_provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_persisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision_reason: Mapped[str] = mapped_column(String(240), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    change_1h: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    change_24h: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    change_7d: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    change_30d: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class PricingAnomalyRecord(Base):
    __tablename__ = "pricing_anomalies"
    __table_args__ = (Index("ix_pricing_anomalies_status_time", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_id"), nullable=False
    )
    candidate_quote_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    previous_canonical_quote_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deviation_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    dynamic_threshold_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingVerificationRecord(Base):
    __tablename__ = "pricing_verifications"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    anomaly_id: Mapped[int | None] = mapped_column(
        ForeignKey("pricing_anomalies.id", ondelete="CASCADE"), nullable=True
    )
    instrument_id: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_id"), nullable=False, index=True
    )
    candidate_quote_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verifier_quote_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    tolerance_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawProviderPayloadRecord(Base):
    __tablename__ = "raw_provider_payloads"
    __table_args__ = (Index("ix_raw_provider_payloads_expiry", "expires_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sanitized_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sanitized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProviderRuntimeEventRecord(Base):
    __tablename__ = "provider_runtime_events"
    __table_args__ = (
        Index("ix_provider_runtime_events_provider_time", "provider_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sanitized_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingBackfillJobRecord(Base):
    __tablename__ = "pricing_backfill_jobs"
    __table_args__ = (
        Index("ix_pricing_backfill_jobs_queue", "status", "priority", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instrument_id: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_id"), nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PricingPersistenceEventRecord(Base):
    __tablename__ = "pricing_persistence_events"
    __table_args__ = (Index("ix_pricing_persistence_events_status", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    stream_event_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    persisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


PRICING_TABLES = (
    InstrumentRecord.__table__,
    PricingProviderRecord.__table__,
    InstrumentProviderConfigRecord.__table__,
    ProviderQuoteRecord.__table__,
    CanonicalQuoteRecord.__table__,
    PricingAnomalyRecord.__table__,
    PricingVerificationRecord.__table__,
    RawProviderPayloadRecord.__table__,
    ProviderRuntimeEventRecord.__table__,
    PricingBackfillJobRecord.__table__,
    PricingPersistenceEventRecord.__table__,
)


__all__ = [
    "CanonicalQuoteRecord",
    "InstrumentProviderConfigRecord",
    "InstrumentRecord",
    "PRICING_TABLES",
    "PricingAnomalyRecord",
    "PricingBackfillJobRecord",
    "PricingPersistenceEventRecord",
    "PricingProviderRecord",
    "PricingVerificationRecord",
    "ProviderQuoteRecord",
    "ProviderRuntimeEventRecord",
    "RawProviderPayloadRecord",
]
