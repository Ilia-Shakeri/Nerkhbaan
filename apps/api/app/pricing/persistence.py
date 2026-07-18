from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select, text

from ..db import SessionLocal
from .cache import PricingRedisStore, PricingRedisUnavailable, pricing_redis
from .db_models import (
    CanonicalQuoteRecord,
    InstrumentProviderConfigRecord,
    PricingAnomalyRecord,
    PricingPersistenceEventRecord,
    PricingProviderRecord,
    PricingVerificationRecord,
    ProviderQuoteRecord,
    ProviderRuntimeEventRecord,
    RawProviderPayloadRecord,
)
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    ProviderQuote,
    VerificationDecision,
    canonical_json,
    json_number,
    utc_now,
)
from .registry import PROVIDERS


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    persisted: bool
    queued: bool
    stream_event_id: str | None
    sanitized_error: str | None


class PricingPersistence:
    consumer_group = "pricing-persistence-writers"

    def __init__(self, store: PricingRedisStore = pricing_redis) -> None:
        self.store = store
        self.stream_max_length = _positive_int_env(
            "PRICING_PERSISTENCE_STREAM_MAXLEN", 50_000
        )
        self.raw_retention_days = _positive_int_env(
            "PRICING_RAW_PAYLOAD_RETENTION_DAYS", 30
        )
        self.consumer_name = f"{socket.gethostname()}-{os.getpid()}"

    async def sync_provider_catalog(self) -> None:
        await asyncio.to_thread(self._sync_provider_catalog)

    async def persist_provider_quote(self, quote: ProviderQuote) -> PersistenceResult:
        try:
            await asyncio.to_thread(self._persist_provider_quote, quote)
            quote.persistence_status = PersistenceStatus.PERSISTED
            return PersistenceResult(True, False, None, None)
        except Exception as exc:
            quote.persistence_status = PersistenceStatus.QUEUED
            return await self._queue(
                "provider_quote",
                quote.idempotency_key,
                quote.to_dict(authenticated=True),
                exc,
            )

    async def persist_canonical(self, quote: CanonicalQuote) -> PersistenceResult:
        try:
            await asyncio.to_thread(self._persist_canonical, quote)
            quote.is_persisted = True
            return PersistenceResult(True, False, None, None)
        except Exception as exc:
            quote.is_persisted = False
            if quote.status in {
                CanonicalStatus.LIVE,
                CanonicalStatus.CONFIRMED,
                CanonicalStatus.FRESH_CACHE,
            }:
                quote.source_summary["status_before_persistence_failure"] = quote.status.value
                quote.status = CanonicalStatus.UNPERSISTED
            return await self._queue(
                "canonical_quote",
                quote.idempotency_key,
                quote.to_dict(authenticated=True, evaluate_status=False),
                exc,
            )

    async def mark_provider_quote_suspicious(self, quote: ProviderQuote) -> None:
        if quote.id is None:
            return
        await asyncio.to_thread(self._mark_provider_quote_suspicious, quote)

    async def persist_anomaly(
        self,
        *,
        instrument_id: str,
        candidate_quote_id: int | None,
        previous_canonical_quote_id: int | None,
        deviation_percent: Decimal,
        dynamic_threshold_percent: Decimal,
        severity: str,
        reason: str,
    ) -> int | None:
        try:
            return await asyncio.to_thread(
                self._persist_anomaly,
                instrument_id,
                candidate_quote_id,
                previous_canonical_quote_id,
                deviation_percent,
                dynamic_threshold_percent,
                severity,
                reason,
            )
        except Exception:
            return None

    async def persist_verification(
        self,
        *,
        anomaly_id: int | None,
        instrument_id: str,
        decision: VerificationDecision,
    ) -> int | None:
        try:
            return await asyncio.to_thread(
                self._persist_verification,
                anomaly_id,
                instrument_id,
                decision,
            )
        except Exception:
            return None

    async def store_raw_payload(
        self,
        *,
        provider_id: str,
        instrument_id: str,
        reason: str,
        sanitized_text: str,
        content_type: str | None,
    ) -> str | None:
        try:
            record_id = await asyncio.to_thread(
                self._store_raw_payload,
                provider_id,
                instrument_id,
                reason,
                sanitized_text,
                content_type,
            )
        except Exception:
            return None
        return f"raw-provider-payload:{record_id}"

    async def record_runtime_event(
        self,
        *,
        provider_id: str,
        instrument_id: str,
        event_type: str,
        status: str,
        latency_ms: int | None = None,
        http_status: int | None = None,
        sanitized_error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._record_runtime_event,
                provider_id,
                instrument_id,
                event_type,
                status,
                latency_ms,
                http_status,
                sanitized_error,
                detail or {},
            )
        except Exception:
            return

    async def flush_stream(self, batch_size: int = 100) -> dict[str, int]:
        client = self.store.client()
        try:
            await client.xgroup_create(
                self.store.persistence_stream,
                self.consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise PricingRedisUnavailable("Persistence consumer group failed") from exc
        recovered: list[tuple[str, dict[str, str]]] = []
        try:
            claimed = await client.xautoclaim(
                self.store.persistence_stream,
                self.consumer_group,
                self.consumer_name,
                min_idle_time=60_000,
                start_id="0-0",
                count=max(1, min(batch_size, 1000)),
            )
            if isinstance(claimed, (list, tuple)) and len(claimed) >= 2:
                recovered = list(claimed[1] or [])
        except Exception:
            recovered = []
        messages = await client.xreadgroup(
            self.consumer_group,
            self.consumer_name,
            {self.store.persistence_stream: ">"},
            count=max(1, min(batch_size, 1000)),
            block=1,
        )
        processed = 0
        failed = 0
        batches = [(self.store.persistence_stream, recovered)] if recovered else []
        batches.extend(messages)
        for _stream, rows in batches:
            for stream_id, fields in rows:
                try:
                    event_type = str(fields["event_type"])
                    idempotency_key = str(fields["idempotency_key"])
                    payload = json.loads(fields["payload"])
                    if not isinstance(payload, dict):
                        raise ValueError("Persistence payload must be an object")
                    await asyncio.to_thread(
                        self._replay_event,
                        str(stream_id),
                        event_type,
                        idempotency_key,
                        payload,
                    )
                    await client.xack(
                        self.store.persistence_stream, self.consumer_group, stream_id
                    )
                    await client.xdel(self.store.persistence_stream, stream_id)
                    processed += 1
                except Exception:
                    failed += 1
                    break
            if failed:
                break
        return {"processed": processed, "failed": failed}

    async def _queue(
        self,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        error: Exception,
    ) -> PersistenceResult:
        sanitized_error = _sanitize_error(error)
        try:
            stream_id = await self.store.append_persistence_event(
                event_type,
                idempotency_key,
                payload,
                self.stream_max_length,
            )
        except Exception:
            return PersistenceResult(False, False, None, sanitized_error)
        return PersistenceResult(False, True, stream_id, sanitized_error)

    @staticmethod
    def _persist_provider_quote(quote: ProviderQuote) -> None:
        db = SessionLocal()
        try:
            existing = db.scalar(
                select(ProviderQuoteRecord).where(
                    ProviderQuoteRecord.idempotency_key == quote.idempotency_key,
                    ProviderQuoteRecord.observed_at == quote.observed_at,
                )
            )
            if existing is not None:
                quote.id = existing.id
                quote.persistence_status = PersistenceStatus.PERSISTED
                return
            record = ProviderQuoteRecord(
                instrument_id=quote.instrument_id,
                provider_id=quote.provider_id,
                source_type=quote.source_type.value,
                price=quote.price,
                currency=quote.currency.value,
                weight_unit=quote.weight_unit.value,
                purity=str(quote.purity) if quote.purity is not None else None,
                bid=quote.bid,
                ask=quote.ask,
                volume=quote.volume,
                observed_at=quote.observed_at,
                received_at=quote.received_at,
                latency_ms=quote.latency_ms,
                http_status=quote.http_status,
                parser_version=quote.parser_version,
                validation_status=quote.validation_status.value,
                confidence_score=quote.confidence_score,
                is_direct=quote.is_direct,
                is_derived=quote.is_derived,
                is_suspicious=quote.is_suspicious,
                rejection_reason=quote.rejection_reason,
                extra=quote.metadata,
                raw_payload_reference=quote.raw_payload_reference,
                persistence_status=PersistenceStatus.PERSISTED.value,
                idempotency_key=quote.idempotency_key,
                quote_role=str(quote.metadata.get("quote_role", "normal")),
            )
            db.add(record)
            db.flush()
            quote.id = record.id
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _persist_canonical(quote: CanonicalQuote) -> None:
        db = SessionLocal()
        try:
            existing = db.scalar(
                select(CanonicalQuoteRecord).where(
                    CanonicalQuoteRecord.idempotency_key == quote.idempotency_key,
                    CanonicalQuoteRecord.canonical_at == quote.canonical_at,
                )
            )
            if existing is not None:
                quote.id = existing.id
                quote.is_persisted = True
                return
            record = CanonicalQuoteRecord(
                instrument_id=quote.instrument_id,
                price=quote.price,
                status=quote.status.value,
                primary_quote_id=quote.primary_quote_id,
                verification_quote_ids=quote.verification_quote_ids,
                source_summary=quote.source_summary,
                candidate_price=quote.candidate_price,
                candidate_provider_id=quote.candidate_provider_id,
                observed_at=quote.observed_at,
                canonical_at=quote.canonical_at,
                valid_until=quote.valid_until,
                stale_at=quote.stale_at,
                expires_at=quote.expires_at,
                is_persisted=True,
                decision_reason=quote.decision_reason[:240],
                verification_status=quote.verification_status.value,
                change_1h=quote.change_1h,
                change_24h=quote.change_24h,
                change_7d=quote.change_7d,
                change_30d=quote.change_30d,
                idempotency_key=quote.idempotency_key,
                sequence_number=quote.sequence_number,
            )
            db.add(record)
            db.flush()
            quote.id = record.id
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _mark_provider_quote_suspicious(quote: ProviderQuote) -> None:
        db = SessionLocal()
        try:
            record = db.get(
                ProviderQuoteRecord,
                {"id": quote.id, "observed_at": quote.observed_at},
            )
            if record is not None:
                record.is_suspicious = True
                record.validation_status = quote.validation_status.value
                record.raw_payload_reference = quote.raw_payload_reference
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _persist_anomaly(
        instrument_id: str,
        candidate_quote_id: int | None,
        previous_canonical_quote_id: int | None,
        deviation_percent: Decimal,
        dynamic_threshold_percent: Decimal,
        severity: str,
        reason: str,
    ) -> int:
        db = SessionLocal()
        try:
            record = PricingAnomalyRecord(
                instrument_id=instrument_id,
                candidate_quote_id=candidate_quote_id,
                previous_canonical_quote_id=previous_canonical_quote_id,
                deviation_percent=deviation_percent,
                dynamic_threshold_percent=dynamic_threshold_percent,
                severity=severity,
                status="open",
                reason=reason[:240],
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _persist_verification(
        anomaly_id: int | None,
        instrument_id: str,
        decision: VerificationDecision,
    ) -> int:
        db = SessionLocal()
        try:
            record = PricingVerificationRecord(
                anomaly_id=anomaly_id,
                instrument_id=instrument_id,
                candidate_quote_id=decision.candidate_quote_id,
                verifier_quote_ids=list(decision.verification_quote_ids),
                decision=decision.status.value,
                tolerance_percent=decision.threshold_percent,
                decision_reason=decision.decision_reason[:240],
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _store_raw_payload(
        self,
        provider_id: str,
        instrument_id: str,
        reason: str,
        sanitized_text: str,
        content_type: str | None,
    ) -> int:
        payload_bytes = len(sanitized_text.encode("utf-8"))
        checksum = hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest()
        parsed_payload: dict[str, Any] | None = None
        try:
            candidate = json.loads(sanitized_text)
            if isinstance(candidate, dict):
                parsed_payload = candidate
        except json.JSONDecodeError:
            pass
        db = SessionLocal()
        try:
            record = RawProviderPayloadRecord(
                provider_id=provider_id,
                instrument_id=instrument_id,
                reason=reason[:32],
                content_type=(content_type or "application/json")[:80],
                sanitized_payload=parsed_payload,
                sanitized_text=None if parsed_payload is not None else sanitized_text,
                payload_bytes=payload_bytes,
                checksum=checksum,
                expires_at=utc_now() + timedelta(days=self.raw_retention_days),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _record_runtime_event(
        provider_id: str,
        instrument_id: str,
        event_type: str,
        status: str,
        latency_ms: int | None,
        http_status: int | None,
        sanitized_error: str | None,
        detail: dict[str, Any],
    ) -> None:
        db = SessionLocal()
        try:
            db.add(
                ProviderRuntimeEventRecord(
                    provider_id=provider_id,
                    instrument_id=instrument_id,
                    event_type=event_type,
                    status=status,
                    latency_ms=latency_ms,
                    http_status=http_status,
                    sanitized_error=(sanitized_error or "")[:500] or None,
                    detail=detail,
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _sync_provider_catalog() -> None:
        db = SessionLocal()
        try:
            for provider in PROVIDERS.values():
                provider_record = db.get(PricingProviderRecord, provider.provider_id)
                if provider_record is None:
                    budget = provider.budget
                    provider_record = PricingProviderRecord(
                        provider_id=provider.provider_id,
                        display_name=provider.display_name,
                        source_type="http",
                        role=provider.role.value,
                        priority=provider.priority,
                        trust_score=provider.trust_score,
                        enabled=provider.enabled,
                        required_key_name=provider.api_key_setting,
                        parser_name=provider.parser_id,
                        parser_version=provider.parser_version,
                        requests_per_minute=budget.requests_per_minute,
                        requests_per_hour=budget.requests_per_hour,
                        requests_per_day=budget.requests_per_day,
                        reserved_anomaly_requests=budget.reserved_anomaly_requests,
                        reserved_fallback_requests=budget.reserved_fallback_requests,
                        minimum_interval_seconds=budget.minimum_interval_seconds,
                        cooldown_after_429_seconds=budget.cooldown_after_429_seconds,
                        estimated_request_cost=budget.estimated_request_cost,
                    )
                    db.add(provider_record)
                config_key = {
                    "instrument_id": provider.instrument_id,
                    "provider_id": provider.provider_id,
                }
                if db.get(InstrumentProviderConfigRecord, config_key) is None:
                    db.add(
                        InstrumentProviderConfigRecord(
                            **config_key,
                            enabled=provider.enabled,
                            role=provider.role.value,
                            priority=provider.priority,
                            trust_score=provider.trust_score,
                            operational_ttl_seconds=provider.operational_ttl_seconds,
                            maximum_verification_depth=2,
                            parser_config={"parser_id": provider.parser_id},
                        )
                    )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _replay_event(
        self,
        stream_id: str,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> None:
        handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "provider_quote": self._replay_provider_quote,
            "canonical_quote": self._replay_canonical_quote,
        }
        try:
            handler = handlers[event_type]
        except KeyError as exc:
            raise ValueError("Unsupported persistence event type") from exc
        handler(payload)
        db = SessionLocal()
        try:
            existing = db.scalar(
                select(PricingPersistenceEventRecord).where(
                    PricingPersistenceEventRecord.idempotency_key == idempotency_key
                )
            )
            if existing is None:
                db.add(
                    PricingPersistenceEventRecord(
                        stream_event_id=stream_id,
                        event_type=event_type,
                        idempotency_key=idempotency_key,
                        payload=payload,
                        status="persisted",
                        attempt_count=1,
                        persisted_at=utc_now(),
                    )
                )
            else:
                existing.status = "persisted"
                existing.persisted_at = utc_now()
                existing.attempt_count += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _replay_provider_quote(payload: dict[str, Any]) -> None:
        quote = ProviderQuote.from_dict(payload)
        quote.persistence_status = PersistenceStatus.PERSISTED
        PricingPersistence._persist_provider_quote(quote)

    @staticmethod
    def _replay_canonical_quote(payload: dict[str, Any]) -> None:
        quote = CanonicalQuote.from_dict(payload)
        quote.is_persisted = True
        prior_status = quote.source_summary.get("status_before_persistence_failure")
        if quote.status is CanonicalStatus.UNPERSISTED and isinstance(prior_status, str):
            quote.status = CanonicalStatus(prior_status)
        PricingPersistence._persist_canonical(quote)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _sanitize_error(error: Exception) -> str:
    name = type(error).__name__
    message = str(error).replace("\r", " ").replace("\n", " ")
    return f"{name}: {message[:300]}"


pricing_persistence = PricingPersistence()
