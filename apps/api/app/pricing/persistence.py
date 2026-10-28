from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, DecimalException
from typing import Any, Callable

from sqlalchemy import select, text
from sqlalchemy.exc import DataError

from ..config import settings
from ..db import SessionLocal
from ..observability import background_failures_total
from .cache import PricingRedisStore, PricingRedisUnavailable, pricing_redis
from .db_models import (
    CanonicalQuoteRecord,
    InstrumentRecord,
    InstrumentProviderConfigRecord,
    PricingAnomalyRecord,
    PricingPersistenceEventRecord,
    PricingProviderRecord,
    PricingVerificationRecord,
    ProviderQuoteRecord,
    ProviderRuntimeEventRecord,
    RawProviderPayloadRecord,
)
from .instruments import INSTRUMENTS
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    ProviderQuote,
    VerificationDecision,
    utc_now,
)
from .registry import PROVIDERS
from . import rights


logger = logging.getLogger(__name__)


_ACK_DELETE_PERSISTENCE_EVENT = """
redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
return redis.call('XDEL', KEYS[1], ARGV[2])
"""


class InvalidPersistenceEvent(ValueError):
    """A queued record cannot be replayed without an operator repair."""


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
        # Read through Settings so a .env file and the process environment
        # cannot disagree; these were previously separate os.environ lookups
        # with their own defaults, which made the declared settings dead.
        self.stream_max_length = settings.pricing_persistence_stream_maxlen
        self.raw_retention_days = settings.raw_provider_payload_retention_days
        self.consumer_name = f"{socket.gethostname()}-{os.getpid()}"

    async def sync_provider_catalog(self) -> None:
        await asyncio.to_thread(self._sync_provider_catalog)

    async def persist_provider_quote(self, quote: ProviderQuote) -> PersistenceResult:
        if not self._provider_storage_allowed(quote):
            quote.persistence_status = PersistenceStatus.UNPERSISTED
            return PersistenceResult(False, False, None, "provider_rights_denied")
        try:
            await asyncio.to_thread(self._persist_provider_quote, quote)
            quote.persistence_status = PersistenceStatus.PERSISTED
            return PersistenceResult(True, False, None, None)
        except InvalidPersistenceEvent:
            quote.persistence_status = PersistenceStatus.UNPERSISTED
            return PersistenceResult(False, False, None, "provider_rights_denied")
        except Exception as exc:
            quote.persistence_status = PersistenceStatus.QUEUED
            result = await self._queue(
                "provider_quote",
                quote.idempotency_key,
                quote.to_dict(authenticated=True),
                exc,
            )
            if not result.queued:
                quote.persistence_status = PersistenceStatus.UNPERSISTED
            return result

    async def persist_canonical(self, quote: CanonicalQuote) -> PersistenceResult:
        if not self._canonical_storage_allowed(quote):
            quote.is_persisted = False
            return PersistenceResult(False, False, None, "provider_rights_denied")
        quote.source_summary = rights.stamp_summary(quote.source_summary)
        try:
            await asyncio.to_thread(self._persist_canonical, quote)
            quote.is_persisted = True
            return PersistenceResult(True, False, None, None)
        except InvalidPersistenceEvent:
            quote.is_persisted = False
            return PersistenceResult(False, False, None, "provider_rights_denied")
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
        if not rights.provider_allowed(provider_id, "store"):
            return None
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
        recovered: list[tuple[bytes, dict[bytes, bytes]]] = []
        limit = max(1, min(batch_size, 1000))
        try:
            # Per-command raw decoding leaves the shared cache pool unchanged
            # and lets malformed UTF-8 reach the durable quarantine path.
            claimed = await client.execute_command(
                "XAUTOCLAIM",
                self.store.persistence_stream,
                self.consumer_group,
                self.consumer_name,
                60_000, "0-0", "COUNT", limit,
                NEVER_DECODE=True,
            )
            if isinstance(claimed, (list, tuple)) and len(claimed) >= 2:
                recovered = list(claimed[1] or [])
        except Exception:
            recovered = []
        messages = await client.execute_command(
            "XREADGROUP", "GROUP", self.consumer_group, self.consumer_name,
            "COUNT", limit, "BLOCK", 1, "STREAMS", self.store.persistence_stream, ">",
            NEVER_DECODE=True,
        )
        processed = 0
        failed = 0
        quarantined = 0
        batches = [(self.store.persistence_stream, recovered)] if recovered else []
        batches.extend(messages)
        for _stream, rows in batches:
            for stream_id, fields in rows:
                stream_id = stream_id.decode("ascii") if isinstance(stream_id, bytes) else str(stream_id)
                try:
                    try:
                        decoded = {key.decode("utf-8") if isinstance(key, bytes) else key: value for key, value in fields.items()}
                        event_type = decoded["event_type"]
                        event_type = event_type.decode("ascii") if isinstance(event_type, bytes) else str(event_type)
                        idempotency_key = decoded["idempotency_key"]
                        idempotency_key = idempotency_key.decode("ascii") if isinstance(idempotency_key, bytes) else str(idempotency_key)
                        payload = json.loads(decoded["payload"])
                        if not isinstance(payload, dict):
                            raise ValueError("Persistence payload must be an object")
                        if not idempotency_key or len(idempotency_key) > 160:
                            raise ValueError("Invalid persistence idempotency key")
                    except (KeyError, TypeError, ValueError) as exc:
                        raise InvalidPersistenceEvent("Invalid persistence envelope") from exc
                    await asyncio.to_thread(
                        self._replay_event,
                        str(stream_id),
                        event_type,
                        idempotency_key,
                        payload,
                    )
                except (InvalidPersistenceEvent, DataError) as exc:
                    try:
                        # Preserve every original field durably before removing
                        # poison from the queue. An unavailable database leaves
                        # the original entry pending for a later retry.
                        await asyncio.to_thread(self._quarantine_event, str(stream_id), fields, exc)
                        quarantined += 1
                        background_failures_total.labels(loop="pricing_persistence_quarantine").inc()
                        logger.warning("Pricing persistence record quarantined: stream_id=%s", stream_id)
                    except Exception:
                        failed += 1
                        break
                except Exception:
                    failed += 1
                    break
                else:
                    processed += 1
                try:
                    await self._acknowledge_stream_event(stream_id)
                except Exception:
                    failed += 1
                    break
            if failed:
                break
        return {"processed": processed, "failed": failed, "quarantined": quarantined}

    async def _acknowledge_stream_event(self, stream_id: str) -> None:
        # A network failure may leave both commands committed or neither;
        # it must never strand an acknowledged entry outside the pending list.
        await self.store.client().eval(_ACK_DELETE_PERSISTENCE_EVENT, 1, self.store.persistence_stream, self.consumer_group, stream_id)

    def _quarantine_event(self, stream_id: str, fields: dict, error: Exception) -> None:
        def encode(value: Any) -> str:
            raw = value if isinstance(value, bytes) else str(value).encode("utf-8", errors="surrogatepass")
            return base64.b64encode(raw).decode("ascii")

        # Base64 retains NULs and the complete malformed payload, which JSONB
        # could otherwise reject. Do not truncate or log provider contents.
        preserved = {"fields_base64": [[encode(key), encode(value)] for key, value in fields.items()]}
        quarantine_key = hashlib.sha256(f"{self.store.persistence_stream}|{stream_id}".encode()).hexdigest()
        db = SessionLocal()
        try:
            existing = db.scalar(select(PricingPersistenceEventRecord).where(PricingPersistenceEventRecord.stream_event_id == stream_id).with_for_update())
            if existing is None:
                db.add(PricingPersistenceEventRecord(stream_event_id=stream_id, event_type="quarantined", idempotency_key=f"quarantine:{quarantine_key}", payload=preserved, status="quarantined", attempt_count=1, last_error=f"{type(error).__name__}: invalid persistence record"))
            elif existing.status != "quarantined" or existing.payload != preserved:
                raise RuntimeError("Persistence quarantine conflicts with an existing record")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _queue(
        self,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        error: Exception,
    ) -> PersistenceResult:
        if rights.enforced():
            try:
                allowed = (
                    self._provider_storage_allowed(ProviderQuote.from_dict(payload))
                    if event_type == "provider_quote"
                    else event_type == "canonical_quote" and self._canonical_storage_allowed(CanonicalQuote.from_dict(payload))
                )
            except (ValueError, TypeError, KeyError, DecimalException, OverflowError):
                allowed = False
            if not allowed:
                return PersistenceResult(False, False, None, "provider_rights_denied")
        sanitized_error = _sanitize_error(error)
        try:
            stream_id = await self.store.append_persistence_event(
                event_type,
                idempotency_key,
                payload,
                self.stream_max_length,
            )
        except Exception:
            background_failures_total.labels(loop="pricing_persistence_queue").inc()
            logger.warning("Pricing persistence enqueue failed; quote remains unpersisted")
            return PersistenceResult(False, False, None, sanitized_error)
        return PersistenceResult(False, True, stream_id, sanitized_error)

    @staticmethod
    def _canonical_storage_allowed(quote: CanonicalQuote) -> bool:
        if rights.enforced():
            if quote.candidate_price is not None and quote.candidate_provider_id is None:
                return False
            status = getattr(quote.status, "value", quote.status)
            if status == CanonicalStatus.DERIVED_FALLBACK.value and quote.source_summary.get("derived") is not True:
                return False
        if not rights.canonical_allowed(quote.source_summary, "store"):
            return False
        if quote.candidate_provider_id is not None and not rights.provider_allowed(quote.candidate_provider_id, "store"):
            return False
        return not quote.source_summary.get("historical_backfill") or rights.canonical_allowed(quote.source_summary, "history")

    @staticmethod
    def _provider_storage_allowed(quote: ProviderQuote) -> bool:
        if quote.metadata.get("quote_role") == "backfill" and not rights.provider_allowed(quote.provider_id, "history"):
            return False
        if quote.is_derived:
            return rights.canonical_allowed({
                "derived": True, "primary_provider_id": quote.provider_id,
                "provider_ids": [quote.provider_id], "inputs": quote.metadata.get("inputs"),
            }, "store")
        return rights.provider_allowed(quote.provider_id, "store")

    @staticmethod
    def _persist_provider_quote(quote: ProviderQuote) -> None:
        if not PricingPersistence._provider_storage_allowed(quote):
            raise InvalidPersistenceEvent("Provider storage permission unavailable")
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
        if not PricingPersistence._canonical_storage_allowed(quote):
            raise InvalidPersistenceEvent("Canonical storage permission unavailable")
        quote.source_summary = rights.stamp_summary(quote.source_summary)
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
    def _decision_id(value: int | None) -> int:
        if type(value) is not int or not 0 < value < 2**63:
            raise InvalidPersistenceEvent("Decision source identity unavailable")
        return value

    @staticmethod
    def _decision_record(db, entity, instrument_id: str, record_id: int | None):
        record_id = PricingPersistence._decision_id(record_id)
        rows = db.scalars(select(entity).where(
            entity.instrument_id == instrument_id, entity.id == record_id,
        ).with_for_update(read=True)).all()
        if len(rows) != 1:
            raise InvalidPersistenceEvent("Decision source record unavailable or ambiguous")
        return rows[0]

    @staticmethod
    def _require_decision_sources(
        db,
        instrument_id: str,
        candidate_quote_id: int | None,
        previous_canonical_quote_id: int | None,
        verifier_quote_ids: tuple[int, ...] = (),
    ) -> None:
        if not rights.enforced():
            return
        revision = rights.revision()
        candidate_id = PricingPersistence._decision_id(candidate_quote_id)
        if not isinstance(verifier_quote_ids, (list, tuple)) or len(verifier_quote_ids) > 64:
            raise InvalidPersistenceEvent("Decision verifier identities unavailable")
        verifier_ids = [PricingPersistence._decision_id(value) for value in verifier_quote_ids]
        if len(set(verifier_ids)) != len(verifier_ids) or candidate_id in verifier_ids:
            raise InvalidPersistenceEvent("Decision verifier identities are not independent")
        source_ids = {candidate_id, *verifier_ids}
        sources = db.scalars(select(ProviderQuoteRecord).where(
            ProviderQuoteRecord.instrument_id == instrument_id,
            ProviderQuoteRecord.id.in_(sorted(source_ids)),
        ).with_for_update(read=True)).all()
        if len(sources) != len(source_ids) or {row.id for row in sources} != source_ids:
            raise InvalidPersistenceEvent("Decision provider evidence unavailable or ambiguous")
        for row in sources:
            metadata = row.extra if isinstance(row.extra, dict) else {}
            derived = (row.is_derived or row.source_type == "derived"
                       or metadata.get("source_semantic") == "derived")
            summary = {"provider_ids": [row.provider_id], "primary_provider_id": row.provider_id,
                       "derived": bool(derived)}
            if derived:
                summary["inputs"] = metadata.get("inputs")
            if not rights.quality_check_allowed(summary):
                raise InvalidPersistenceEvent("Decision provider permissions unavailable")
        previous = PricingPersistence._decision_record(
            db, CanonicalQuoteRecord, instrument_id, previous_canonical_quote_id,
        )
        if (not PricingPersistence._canonical_storage_allowed(previous)
                or not rights.quality_check_allowed(previous.source_summary)
                or (previous.candidate_provider_id is not None
                    and not rights.provider_quality_check_allowed(previous.candidate_provider_id))
                or revision != rights.revision()):
            raise InvalidPersistenceEvent("Decision previous-source permissions unavailable")

    @staticmethod
    def _require_verification_sources(
        db, anomaly_id: int | None, instrument_id: str, decision: VerificationDecision,
    ) -> None:
        if not rights.enforced():
            return
        anomaly = PricingPersistence._decision_record(db, PricingAnomalyRecord, instrument_id, anomaly_id)
        if anomaly.candidate_quote_id != decision.candidate_quote_id:
            raise InvalidPersistenceEvent("Verification candidate does not match its anomaly")
        PricingPersistence._require_decision_sources(
            db, instrument_id, decision.candidate_quote_id,
            anomaly.previous_canonical_quote_id, decision.verification_quote_ids,
        )

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
            PricingPersistence._require_decision_sources(
                db, instrument_id, candidate_quote_id, previous_canonical_quote_id,
            )
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
            PricingPersistence._require_decision_sources(
                db, instrument_id, candidate_quote_id, previous_canonical_quote_id,
            )
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
            PricingPersistence._require_verification_sources(db, anomaly_id, instrument_id, decision)
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
            PricingPersistence._require_verification_sources(db, anomaly_id, instrument_id, decision)
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
        if not rights.provider_allowed(provider_id, "store"):
            raise InvalidPersistenceEvent("Raw source storage permission unavailable")
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
            # Every API replica runs startup. Serialize catalog reconciliation so
            # two fresh replicas cannot race while inserting the same parent rows.
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": 5640009418248479041},
            )

            for instrument in INSTRUMENTS.values():
                instrument_record = db.get(InstrumentRecord, instrument.instrument_id)
                values = {
                    "base_asset": instrument.base_asset,
                    "quote_currency": instrument.quote_currency.value,
                    "market": instrument.market.value,
                    "region": instrument.region.value,
                    "weight_unit": instrument.weight_unit.value,
                    "purity": str(instrument.purity) if instrument.purity is not None else None,
                    "display_decimals": instrument.display_decimals,
                    "operational_ttl_seconds": instrument.operational_ttl_seconds,
                    "stale_after_seconds": instrument.stale_after_seconds,
                    "expire_after_seconds": instrument.expire_after_seconds,
                    "base_anomaly_threshold_percent": instrument.base_anomaly_threshold_percent,
                    "maximum_dynamic_threshold_percent": instrument.maximum_dynamic_threshold_percent,
                    "minimum_sanity_price": instrument.minimum_price,
                    "maximum_sanity_price": instrument.maximum_price,
                    "importance": instrument.importance,
                    "enabled": instrument.enabled,
                    "allow_derived_fallback": instrument.allow_derived_fallback,
                }
                if instrument_record is None:
                    db.add(
                        InstrumentRecord(
                            instrument_id=instrument.instrument_id,
                            **values,
                        )
                    )
                else:
                    # Operator policy survives restart. Only immutable descriptors
                    # follow the release catalogue; policy changes use migrations.
                    for field in ("base_asset", "quote_currency", "market", "region", "weight_unit", "purity", "display_decimals"):
                        setattr(instrument_record, field, values[field])

            for provider in PROVIDERS.values():
                budget = provider.budget
                provider_record = db.get(PricingProviderRecord, provider.provider_id)
                if provider_record is None:
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
                else:
                    provider_record.display_name = provider.display_name
                    provider_record.source_type = "http"
                    provider_record.required_key_name = provider.api_key_setting
                    provider_record.parser_name = provider.parser_id
                    provider_record.parser_version = provider.parser_version

            # Provider configs reference both parent catalogs. Flush every new
            # parent row before adding configs so PostgreSQL can enforce both keys.
            db.flush()

            for provider in PROVIDERS.values():
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
            raise InvalidPersistenceEvent("Unsupported persistence event type") from exc
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
        try:
            quote = ProviderQuote.from_dict(payload)
        except (KeyError, TypeError, ValueError, DecimalException, OverflowError) as exc:
            raise InvalidPersistenceEvent("Invalid provider quote") from exc
        quote.persistence_status = PersistenceStatus.PERSISTED
        PricingPersistence._persist_provider_quote(quote)

    @staticmethod
    def _replay_canonical_quote(payload: dict[str, Any]) -> None:
        try:
            quote = CanonicalQuote.from_dict(payload)
            quote.is_persisted = True
            prior_status = quote.source_summary.get("status_before_persistence_failure")
            if quote.status is CanonicalStatus.UNPERSISTED and isinstance(prior_status, str):
                quote.status = CanonicalStatus(prior_status)
        except (KeyError, TypeError, ValueError, DecimalException, OverflowError) as exc:
            raise InvalidPersistenceEvent("Invalid canonical quote") from exc
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
