from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ..db import SessionLocal
from .instruments import get_instrument
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    VerificationStatus,
    decimal_or_none,
    decimal_value,
    ensure_utc,
    parse_datetime,
    utc_now,
)

_ACCEPTED_STATUSES = (
    "live",
    "confirmed",
    "fresh_cache",
    "derived_fallback",
    "unpersisted",
)


@dataclass(frozen=True, slots=True)
class TimeframePolicy:
    duration: timedelta
    bucket: str
    bucket_seconds: int
    baseline_tolerance: timedelta


TIMEFRAMES = {
    "1h": TimeframePolicy(timedelta(hours=1), "1 minute", 60, timedelta(minutes=15)),
    "24h": TimeframePolicy(timedelta(hours=24), "15 minutes", 900, timedelta(hours=3)),
    "7d": TimeframePolicy(timedelta(days=7), "1 hour", 3600, timedelta(hours=12)),
    "30d": TimeframePolicy(timedelta(days=30), "4 hours", 14400, timedelta(days=2)),
    "1y": TimeframePolicy(timedelta(days=365), "1 day", 86400, timedelta(days=7)),
}


@dataclass(frozen=True, slots=True)
class HistoryResult:
    instrument_id: str
    timeframe: str
    status: str
    range_start: datetime
    range_end: datetime
    points: list[dict[str, Any]]
    missing_before: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "status": self.status,
            "range_start": self.range_start.isoformat(),
            "range_end": self.range_end.isoformat(),
            "missing_before": self.missing_before.isoformat() if self.missing_before else None,
            "points": self.points,
        }


class InternalPriceHistory:
    async def canonical_history(
        self,
        instrument_id: str,
        timeframe: str,
        *,
        end: datetime | None = None,
    ) -> HistoryResult:
        get_instrument(instrument_id)
        try:
            policy = TIMEFRAMES[timeframe]
        except KeyError as exc:
            raise ValueError("Unsupported timeframe") from exc
        range_end = ensure_utc(end or utc_now())
        range_start = range_end - policy.duration
        points = await asyncio.to_thread(
            self._query_canonical_history,
            instrument_id,
            range_start,
            range_end,
            policy.bucket,
        )
        if not points and instrument_id in {"USDT_TOMAN", "USDT_USD", "BTC_TOMAN", "BTC_USD"}:
            points = await asyncio.to_thread(
                self._query_legacy_history,
                instrument_id,
                range_start,
                range_end,
                policy.bucket,
            )
        first = parse_datetime(points[0]["timestamp"]) if points else None
        is_partial = first is None or first > range_start + timedelta(seconds=policy.bucket_seconds * 2)
        return HistoryResult(
            instrument_id=instrument_id,
            timeframe=timeframe,
            status="partial" if is_partial else "complete",
            range_start=range_start,
            range_end=range_end,
            points=points,
            missing_before=first if is_partial else None,
        )

    async def provider_history(
        self,
        instrument_id: str,
        timeframe: str,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        get_instrument(instrument_id)
        try:
            policy = TIMEFRAMES[timeframe]
        except KeyError as exc:
            raise ValueError("Unsupported timeframe") from exc
        end = utc_now()
        start = end - policy.duration
        rows = await asyncio.to_thread(
            self._query_provider_history,
            instrument_id,
            provider_id,
            start,
            end,
        )
        return {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "status": "complete" if rows else "partial",
            "sources": rows,
        }

    async def recent_prices(self, instrument_id: str, limit: int = 120) -> list[Decimal]:
        return await asyncio.to_thread(self._query_recent_prices, instrument_id, limit)

    async def changes(
        self,
        instrument_id: str,
        current_price: Decimal,
        current_time: datetime | None = None,
    ) -> dict[str, Decimal | None]:
        end = ensure_utc(current_time or utc_now())
        result: dict[str, Decimal | None] = {}
        for label in ("1h", "24h", "7d", "30d"):
            policy = TIMEFRAMES[label]
            target = end - policy.duration
            baseline = await asyncio.to_thread(
                self._query_baseline,
                instrument_id,
                target,
                target - policy.baseline_tolerance,
            )
            if baseline is None or baseline <= 0:
                result[label] = None
            else:
                result[label] = (
                    (current_price - baseline) / baseline * Decimal(100)
                ).quantize(Decimal("0.000001"))
        return result

    async def latest_canonical(self, instrument_id: str) -> CanonicalQuote | None:
        return await asyncio.to_thread(self._query_latest_canonical, instrument_id)

    async def latest_all(self) -> dict[str, CanonicalQuote]:
        return await asyncio.to_thread(self._query_latest_all)

    async def latest_sources(self, instrument_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._query_latest_sources, instrument_id)

    async def verification_details(
        self, instrument_id: str, *, authenticated: bool
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._query_verification_details, instrument_id, authenticated
        )

    @staticmethod
    def _query_canonical_history(
        instrument_id: str,
        start: datetime,
        end: datetime,
        bucket: str,
    ) -> list[dict[str, Any]]:
        query = text(
            """
            WITH bucketed AS (
                SELECT
                    date_bin(CAST(:bucket AS interval), canonical_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                    canonical_at,
                    price
                FROM canonical_quotes
                WHERE instrument_id = :instrument_id
                  AND canonical_at >= :start
                  AND canonical_at <= :end
                  AND status = ANY(:statuses)
            )
            SELECT
                bucket,
                (array_agg(price ORDER BY canonical_at ASC))[1] AS open,
                (array_agg(price ORDER BY canonical_at DESC))[1] AS close,
                MAX(price) AS high,
                MIN(price) AS low,
                COUNT(*) AS sample_count
            FROM bucketed
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(
                query,
                {
                    "bucket": bucket,
                    "instrument_id": instrument_id,
                    "start": start,
                    "end": end,
                    "statuses": list(_ACCEPTED_STATUSES),
                },
            ).mappings().all()
        finally:
            db.close()
        return [
            {
                "timestamp": ensure_utc(row["bucket"]).isoformat(),
                "open": float(row["open"]),
                "close": float(row["close"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "value": float(row["close"]),
                "sample_count": int(row["sample_count"]),
            }
            for row in rows
        ]

    @staticmethod
    def _query_legacy_history(
        instrument_id: str,
        start: datetime,
        end: datetime,
        bucket: str,
    ) -> list[dict[str, Any]]:
        asset = "usdt" if instrument_id.startswith("USDT") else "btc"
        region = "iran" if instrument_id.endswith("TOMAN") else "international"
        column = "price_toman" if region == "iran" else "price_usd"
        query = text(
            f"""
            SELECT
                date_bin(CAST(:bucket AS interval), time, TIMESTAMPTZ '2000-01-01') AS bucket,
                AVG({column}) AS value,
                COUNT(*) AS sample_count
            FROM market_prices
            WHERE asset = :asset
              AND region = :region
              AND time >= :start
              AND time <= :end
              AND {column} IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket ASC
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(
                query,
                {"bucket": bucket, "asset": asset, "region": region, "start": start, "end": end},
            ).mappings().all()
        finally:
            db.close()
        return [
            {
                "timestamp": ensure_utc(row["bucket"]).isoformat(),
                "open": float(row["value"]),
                "close": float(row["value"]),
                "high": float(row["value"]),
                "low": float(row["value"]),
                "value": float(row["value"]),
                "sample_count": int(row["sample_count"]),
                "source": "legacy_internal_history",
            }
            for row in rows
        ]

    @staticmethod
    def _query_provider_history(
        instrument_id: str,
        provider_id: str | None,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        query = text(
            """
            SELECT provider_id, price, bid, ask, observed_at, validation_status,
                   is_direct, is_derived, is_suspicious, rejection_reason
            FROM provider_quotes
            WHERE instrument_id = :instrument_id
              AND observed_at >= :start
              AND observed_at <= :end
              AND (:provider_id IS NULL OR provider_id = :provider_id)
            ORDER BY observed_at ASC
            LIMIT 10000
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(
                query,
                {
                    "instrument_id": instrument_id,
                    "provider_id": provider_id,
                    "start": start,
                    "end": end,
                },
            ).mappings().all()
        finally:
            db.close()
        return [
            {
                "provider_id": row["provider_id"],
                "price": float(row["price"]) if row["price"] is not None else None,
                "bid": float(row["bid"]) if row["bid"] is not None else None,
                "ask": float(row["ask"]) if row["ask"] is not None else None,
                "observed_at": ensure_utc(row["observed_at"]).isoformat(),
                "validation_status": row["validation_status"],
                "is_direct": bool(row["is_direct"]),
                "is_derived": bool(row["is_derived"]),
                "is_suspicious": bool(row["is_suspicious"]),
                "rejection_reason": row["rejection_reason"],
            }
            for row in rows
        ]

    @staticmethod
    def _query_recent_prices(instrument_id: str, limit: int) -> list[Decimal]:
        query = text(
            """
            SELECT price
            FROM canonical_quotes
            WHERE instrument_id = :instrument_id
              AND status = ANY(:statuses)
            ORDER BY canonical_at DESC
            LIMIT :limit
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(
                query,
                {"instrument_id": instrument_id, "statuses": list(_ACCEPTED_STATUSES), "limit": max(3, min(limit, 1000))},
            ).scalars().all()
        finally:
            db.close()
        return [Decimal(str(value)) for value in reversed(rows)]

    @staticmethod
    def _query_baseline(
        instrument_id: str,
        target: datetime,
        earliest: datetime,
    ) -> Decimal | None:
        query = text(
            """
            SELECT price
            FROM canonical_quotes
            WHERE instrument_id = :instrument_id
              AND status = ANY(:statuses)
              AND canonical_at <= :target
              AND canonical_at >= :earliest
            ORDER BY canonical_at DESC
            LIMIT 1
            """
        )
        db = SessionLocal()
        try:
            value = db.execute(
                query,
                {
                    "instrument_id": instrument_id,
                    "statuses": list(_ACCEPTED_STATUSES),
                    "target": target,
                    "earliest": earliest,
                },
            ).scalar_one_or_none()
        finally:
            db.close()
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _query_latest_canonical(instrument_id: str) -> CanonicalQuote | None:
        rows = InternalPriceHistory._query_latest_rows(instrument_id)
        return _canonical_from_row(rows[0]) if rows else None

    @staticmethod
    def _query_latest_all() -> dict[str, CanonicalQuote]:
        rows = InternalPriceHistory._query_latest_rows(None)
        return {row["instrument_id"]: _canonical_from_row(row) for row in rows}

    @staticmethod
    def _query_latest_rows(instrument_id: str | None) -> list[Any]:
        query_sql = """
            SELECT DISTINCT ON (instrument_id)
                id, instrument_id, price, status, primary_quote_id,
                verification_quote_ids, source_summary, candidate_price,
                candidate_provider_id, observed_at, canonical_at, valid_until,
                stale_at, expires_at, is_persisted, decision_reason,
                verification_status, change_1h, change_24h, change_7d,
                change_30d, idempotency_key, sequence_number
            FROM canonical_quotes
        """
        parameters: dict[str, str] = {}
        if instrument_id is not None:
            query_sql += " WHERE instrument_id = :instrument_id"
            parameters["instrument_id"] = instrument_id
        query_sql += " ORDER BY instrument_id, canonical_at DESC"

        db = SessionLocal()
        try:
            return db.execute(text(query_sql), parameters).mappings().all()
        finally:
            db.close()

    @staticmethod
    def _query_latest_sources(instrument_id: str) -> list[dict[str, Any]]:
        query = text(
            """
            SELECT DISTINCT ON (provider_id)
                id, provider_id, source_type, price, currency, weight_unit,
                purity, bid, ask, volume, observed_at, received_at, latency_ms,
                http_status, parser_version, validation_status, confidence_score,
                is_direct, is_derived, is_suspicious, rejection_reason,
                metadata, raw_payload_reference, persistence_status
            FROM provider_quotes
            WHERE instrument_id = :instrument_id
            ORDER BY provider_id, observed_at DESC
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(query, {"instrument_id": instrument_id}).mappings().all()
        finally:
            db.close()
        now = utc_now()
        return [
            {
                **dict(row),
                "price": float(row["price"]) if row["price"] is not None else None,
                "bid": float(row["bid"]) if row["bid"] is not None else None,
                "ask": float(row["ask"]) if row["ask"] is not None else None,
                "volume": float(row["volume"]) if row["volume"] is not None else None,
                "purity": float(row["purity"]) if row["purity"] is not None else None,
                "confidence_score": float(row["confidence_score"]),
                "observed_at": ensure_utc(row["observed_at"]).isoformat(),
                "received_at": ensure_utc(row["received_at"]).isoformat(),
                "age_seconds": max(0, int((now - ensure_utc(row["observed_at"])).total_seconds())),
            }
            for row in rows
        ]

    @staticmethod
    def _query_verification_details(
        instrument_id: str,
        authenticated: bool,
    ) -> dict[str, Any]:
        query = text(
            """
            SELECT
                a.id AS anomaly_id, a.deviation_percent, a.dynamic_threshold_percent,
                a.severity, a.status AS anomaly_status, a.reason, a.created_at,
                v.verifier_quote_ids, v.decision, v.tolerance_percent,
                v.decision_reason, v.created_at AS verification_created_at
            FROM pricing_anomalies a
            LEFT JOIN LATERAL (
                SELECT * FROM pricing_verifications
                WHERE anomaly_id = a.id
                ORDER BY created_at DESC
                LIMIT 1
            ) v ON TRUE
            WHERE a.instrument_id = :instrument_id
            ORDER BY a.created_at DESC
            LIMIT 1
            """
        )
        db = SessionLocal()
        try:
            row = db.execute(query, {"instrument_id": instrument_id}).mappings().first()
        finally:
            db.close()
        if row is None:
            return {"instrument_id": instrument_id, "status": "not_required"}
        payload = {
            "instrument_id": instrument_id,
            "status": row["decision"] or row["anomaly_status"],
            "severity": row["severity"],
            "created_at": ensure_utc(row["created_at"]).isoformat(),
        }
        if authenticated:
            payload.update(
                {
                    "anomaly_id": row["anomaly_id"],
                    "deviation_percent": float(row["deviation_percent"]),
                    "dynamic_threshold_percent": float(row["dynamic_threshold_percent"]),
                    "reason": row["reason"],
                    "verifier_quote_ids": row["verifier_quote_ids"] or [],
                    "tolerance_percent": (
                        float(row["tolerance_percent"])
                        if row["tolerance_percent"] is not None
                        else None
                    ),
                    "decision_reason": row["decision_reason"],
                }
            )
        return payload


def _canonical_from_row(row: Any) -> CanonicalQuote:
    return CanonicalQuote(
        id=int(row["id"]),
        instrument_id=row["instrument_id"],
        price=decimal_value(row["price"]),
        status=CanonicalStatus(row["status"]),
        primary_quote_id=(int(row["primary_quote_id"]) if row["primary_quote_id"] is not None else None),
        verification_quote_ids=[int(value) for value in (row["verification_quote_ids"] or [])],
        source_summary=dict(row["source_summary"] or {}),
        candidate_price=decimal_or_none(row["candidate_price"]),
        candidate_provider_id=row["candidate_provider_id"],
        observed_at=ensure_utc(row["observed_at"]),
        canonical_at=ensure_utc(row["canonical_at"]),
        valid_until=ensure_utc(row["valid_until"]),
        stale_at=ensure_utc(row["stale_at"]),
        expires_at=ensure_utc(row["expires_at"]),
        is_persisted=bool(row["is_persisted"]),
        decision_reason=row["decision_reason"],
        verification_status=VerificationStatus(row["verification_status"]),
        change_1h=decimal_or_none(row["change_1h"]),
        change_24h=decimal_or_none(row["change_24h"]),
        change_7d=decimal_or_none(row["change_7d"]),
        change_30d=decimal_or_none(row["change_30d"]),
        idempotency_key=row["idempotency_key"],
        sequence_number=(int(row["sequence_number"]) if row["sequence_number"] is not None else None),
    )


internal_history = InternalPriceHistory()
