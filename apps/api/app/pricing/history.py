from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Lock
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..db import SessionLocal
from .instruments import get_instrument
from .registry import PROVIDERS, RETIRED_PROVIDERS
from . import rights
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    VerificationStatus,
    _change_or_none,
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

logger = logging.getLogger(__name__)

_BOOKEND_CAPABILITIES: WeakKeyDictionary[Engine, bool] = WeakKeyDictionary()
_BOOKEND_CAPABILITY_LOCK = Lock()
_LATEST_STATEMENT_TIMEOUT_MS = 1500
_LATEST_LOCK_TIMEOUT_MS = 250
_BOOKEND_CAPABILITY_SQL = """
    SELECT COUNT(DISTINCT p.proname) = 2
    FROM pg_extension e
    JOIN pg_depend d ON d.refobjid = e.oid
    JOIN pg_proc p ON p.oid = d.objid
    WHERE e.extname = 'timescaledb'
      AND d.refclassid = 'pg_extension'::regclass
      AND d.classid = 'pg_proc'::regclass AND d.deptype = 'e'
      AND p.proname IN ('first', 'last') AND p.pronargs = 2
      AND p.prokind = 'a' AND pg_function_is_visible(p.oid)
"""


def _history_supports_bookends(db) -> bool:
    bind = db.get_bind()
    engine = bind if isinstance(bind, Engine) else getattr(bind, "engine", None)
    if not isinstance(engine, Engine) or engine.dialect.name != "postgresql":
        return False
    # Metadata is tied to this actual database engine, never to a URL or quote TTL.
    with _BOOKEND_CAPABILITY_LOCK:
        if engine in _BOOKEND_CAPABILITIES:
            return _BOOKEND_CAPABILITIES[engine]
        supported = bool(db.execute(text(_BOOKEND_CAPABILITY_SQL)).scalar_one())
        # A failed read raises and leaves the capability unknown for the next retry.
        _BOOKEND_CAPABILITIES[engine] = supported
        return supported

# Preserve historical evidence, but never blend old calculated gold into
# current prices, chart buckets, anomaly baselines, or percentage changes.
_DIRECT_GOLD_SQL = """(
    instrument_id NOT IN ('GOLD_18K_TOMAN_GRAM', 'GOLD_24K_TOMAN_GRAM') OR (
        status <> 'derived_fallback'
        AND COALESCE(source_summary->>'derived', 'false') = 'false'
        AND COALESCE(source_summary->>'primary_provider_id', '') NOT LIKE 'derived:%'
        AND COALESCE(source_summary->>'primary_provider_id', '') <> 'persian_toolbox_gold24'
        AND NOT (COALESCE(source_summary->'provider_ids', '[]'::jsonb) ? 'persian_toolbox_gold24')
    )
)"""


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
    attributions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "status": self.status,
            "range_start": self.range_start.isoformat(),
            "range_end": self.range_end.isoformat(),
            "missing_before": self.missing_before.isoformat() if self.missing_before else None,
            "points": self.points,
        }
        if rights.enforced():
            result["attributions"] = self.attributions
        return result


def _canonical_permissions(action: str):
    clause, parameters = rights.sql_filter(action)
    if action == "display":
        # Filter complete source trees before DISTINCT/LIMIT. A later Python
        # rejection must not hide an older valid current price.
        clause += """ AND NOT EXISTS (
            WITH RECURSIVE current_source_nodes(summary, depth) AS (
                SELECT source_summary, 0
                UNION ALL
                SELECT child.value->'source_summary', node.depth + 1
                FROM current_source_nodes AS node
                CROSS JOIN LATERAL jsonb_array_elements(CASE
                    WHEN node.depth < 6 AND jsonb_typeof(node.summary->'inputs') = 'array'
                    THEN node.summary->'inputs' ELSE '[]'::jsonb END) AS child(value)
            )
            SELECT 1 FROM current_source_nodes AS node
            WHERE node.summary->>'timestamp_precision' = 'day'
               OR COALESCE(node.summary->'provider_ids', '[]'::jsonb) ?| :history_only_sources
               OR node.summary->>'primary_provider_id' = ANY(:history_only_sources)
               OR node.summary->>'candidate_provider_id' = ANY(:history_only_sources)
               OR node.summary->>'previous_provider_id' = ANY(:history_only_sources)
        ) AND (candidate_provider_id IS NULL OR NOT (candidate_provider_id = ANY(:history_only_sources)))"""
        parameters["history_only_sources"] = [name for name, provider in PROVIDERS.items() if provider.history_only] + list(RETIRED_PROVIDERS)
    if rights.enforced():
        clause = f"({clause}) AND (candidate_provider_id IS NULL OR candidate_provider_id = ANY(:rights_candidate_ids)) AND (candidate_price IS NULL OR candidate_provider_id = ANY(:rights_candidate_ids))"
        clause += " AND (status <> 'derived_fallback' OR source_summary->>'derived' = 'true' OR source_summary->>'primary_provider_id' LIKE 'derived:%')"
        parameters["rights_candidate_ids"] = list(rights.allowed_provider_ids(action))
    return clause, parameters


def _latest_read_budget(db) -> None:
    bind_reader = getattr(db, "get_bind", None)
    bind = bind_reader() if callable(bind_reader) else None
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return
    db.execute(text("SET TRANSACTION READ ONLY"), {})
    configured = {row["name"]: int(row["timeout_ms"]) for row in db.execute(text("""
        SELECT name, setting::bigint AS timeout_ms FROM pg_settings
        WHERE name IN ('statement_timeout', 'lock_timeout')
    """), {}).mappings().all()}
    if set(configured) != {"statement_timeout", "lock_timeout"}:
        raise RuntimeError("Cannot verify current quote read budgets")
    budgets = {"statement_timeout": _LATEST_STATEMENT_TIMEOUT_MS, "lock_timeout": _LATEST_LOCK_TIMEOUT_MS}
    selected = {name: str(min(value, configured[name]) if configured[name] > 0 else value) + "ms"
                for name, value in budgets.items()}
    db.execute(text("""SELECT set_config('statement_timeout', :statement_timeout, true),
        set_config('lock_timeout', :lock_timeout, true), set_config('jit', 'off', true)"""), selected)


def _latest_rows_sql(instrument_id: str | None):
    permitted, parameters = _canonical_permissions("display")
    columns = """id, instrument_id, price, status, primary_quote_id,
        verification_quote_ids, source_summary, candidate_price,
        candidate_provider_id, observed_at, canonical_at, valid_until,
        stale_at, expires_at, is_persisted, decision_reason,
        verification_status, change_1h, change_24h, change_7d,
        change_30d, idempotency_key, sequence_number"""
    # Reject only necessary root failures before the full recursive checks.
    cheap = f"""{_DIRECT_GOLD_SQL}
        AND COALESCE(source_summary->>'historical_backfill', 'false') <> 'true'
        AND COALESCE(source_summary->>'timestamp_precision', '') <> 'day'
        AND NOT (COALESCE(source_summary->'provider_ids', '[]'::jsonb) ?| :history_only_sources)
        AND COALESCE(source_summary->>'primary_provider_id', '') <> ALL(:history_only_sources)
        AND COALESCE(source_summary->>'candidate_provider_id', '') <> ALL(:history_only_sources)
        AND COALESCE(source_summary->>'previous_provider_id', '') <> ALL(:history_only_sources)
        AND (candidate_provider_id IS NULL OR NOT (candidate_provider_id = ANY(:history_only_sources)))"""
    if rights.enforced():
        cheap += """ AND (COALESCE(source_summary->>'derived', 'false') = 'true'
            OR COALESCE(source_summary->>'primary_provider_id', '') LIKE 'derived:%'
            OR (source_summary->'provider_ids') <@ CAST(:rights_allowed_sources AS jsonb))"""
    if instrument_id is None:
        definitions = "SELECT DISTINCT instrument_id FROM canonical_quotes"
    else:
        definitions = "SELECT CAST(:instrument_id AS text) AS instrument_id"
        parameters["instrument_id"] = instrument_id
    # OFFSET 0 keeps the permission subplans above the ordered cheap scan.
    # LIMIT follows the complete permission check, so older eligible rows remain
    # reachable and an approved newest row needs no older permission scans.
    query = f"""SELECT selected.* FROM ({definitions}) AS definitions
        CROSS JOIN LATERAL (
            SELECT {columns} FROM (
                SELECT {columns} FROM canonical_quotes
                WHERE {cheap} AND instrument_id = definitions.instrument_id
                ORDER BY observed_at DESC, canonical_at DESC, id DESC OFFSET 0
            ) AS roots
            WHERE {permitted}
            ORDER BY observed_at DESC, canonical_at DESC, id DESC LIMIT 1
        ) AS selected ORDER BY selected.instrument_id"""
    return text(query), parameters


def _canonical_history_sql(use_bookends: bool):
    permitted, parameters = _canonical_permissions("history")
    lineage = ""
    attribution = ""
    if rights.enforced():
        lineage = """, (
            WITH RECURSIVE attribution_nodes(summary, depth) AS (
                SELECT source_summary, 0
                UNION ALL
                SELECT attribution_input.value->'source_summary', attribution_node.depth + 1
                FROM attribution_nodes AS attribution_node
                CROSS JOIN LATERAL jsonb_array_elements(CASE
                    WHEN attribution_node.depth < 6
                      AND (attribution_node.summary->>'derived' = 'true'
                        OR attribution_node.summary->>'primary_provider_id' LIKE 'derived:%')
                      AND jsonb_typeof(attribution_node.summary->'inputs') = 'array'
                    THEN attribution_node.summary->'inputs' ELSE '[]'::jsonb END
                ) AS attribution_input(value)
            )
            SELECT COALESCE(jsonb_agg(DISTINCT attribution_source.value), '[]'::jsonb)
            FROM attribution_nodes AS attribution_node
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE WHEN jsonb_typeof(attribution_node.summary->'provider_ids') = 'array'
                    THEN attribution_node.summary->'provider_ids' ELSE '[]'::jsonb END
                || jsonb_build_array(attribution_node.summary->'candidate_provider_id',
                                     attribution_node.summary->'previous_provider_id')
            ) AS attribution_source(value)
            WHERE jsonb_typeof(attribution_source.value) = 'string'
              AND attribution_source.value #>> '{}' NOT LIKE 'derived:%'
        ) || jsonb_build_array(candidate_provider_id) AS rights_source_ids"""
        attribution = ", jsonb_agg(DISTINCT rights_source_ids) AS rights_source_groups"
    opening = "first(price, canonical_at)" if use_bookends else "(array_agg(price ORDER BY canonical_at ASC))[1]"
    closing = "last(price, canonical_at)" if use_bookends else "(array_agg(price ORDER BY canonical_at DESC))[1]"
    return text(
        f"""
        WITH bucketed AS (
            SELECT
                CASE WHEN source_summary->>'timestamp_precision' = 'day' THEN canonical_at
                     ELSE date_bin(CAST(:bucket AS interval), canonical_at, TIMESTAMPTZ '2000-01-01') END AS bucket,
                canonical_at,
                COALESCE(source_summary->>'timestamp_precision' = 'day', false) AS day_precision,
                CASE WHEN source_summary->>'timestamp_precision' = 'day'
                     THEN source_summary->>'source_timezone' END AS source_timezone,
                CASE WHEN source_summary->>'timestamp_precision' = 'day'
                     THEN source_summary->>'source_calendar' END AS source_calendar,
                CASE WHEN source_summary->>'timestamp_precision' = 'day'
                     THEN source_summary->>'source_date' END AS source_date,
                source_summary,
                price{lineage}
            FROM canonical_quotes
            WHERE instrument_id = :instrument_id
              AND canonical_at >= :start
              AND canonical_at <= :end
              AND status = ANY(:statuses)
              AND {_DIRECT_GOLD_SQL}
              AND {permitted}
        ), aggregated AS (
        SELECT
            bucket,
            {opening} AS open,
            {closing} AS close,
            MAX(price) AS high,
            MIN(price) AS low,
            COUNT(*) AS sample_count,
            day_precision,
            source_timezone,
            source_calendar,
            source_date{attribution}
        FROM bucketed
        GROUP BY bucket, day_precision, source_timezone, source_calendar, source_date
        ), chosen AS (
            SELECT aggregated.*, ROW_NUMBER() OVER (
                PARTITION BY bucket ORDER BY day_precision ASC, sample_count DESC,
                    source_timezone ASC NULLS LAST, source_calendar ASC NULLS LAST,
                    source_date ASC NULLS LAST
            ) AS precision_rank
            FROM aggregated
        )
        SELECT * FROM chosen WHERE precision_rank = 1
        ORDER BY bucket ASC
        """
    ).bindparams(**parameters)


class InternalPriceHistory:
    def __init__(self) -> None:
        self._canonical_reads: dict[tuple[str, str, datetime | None, str | None], asyncio.Task] = {}
        self._canonical_guard = asyncio.Lock()

    async def canonical_history(
        self, instrument_id: str, timeframe: str, *, end: datetime | None = None,
    ) -> HistoryResult:
        normalized = get_instrument(instrument_id).instrument_id
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        requested_end = ensure_utc(end) if end is not None else None
        revision = rights.revision() if rights.enforced() else None
        key = (normalized, timeframe, requested_end, revision)
        async with self._canonical_guard:
            task = self._canonical_reads.get(key)
            if task is None or task.done():
                task = asyncio.create_task(self._read_canonical_history(normalized, timeframe, end=requested_end))
                self._canonical_reads[key] = task
                task.add_done_callback(lambda done: self._canonical_read_done(key, done))
        await asyncio.wait({task})
        result = task.result()
        if revision is not None and revision != rights.revision():
            # Aggregated values cannot be separated once a source loses permission.
            return HistoryResult(result.instrument_id, result.timeframe, "partial", result.range_start, result.range_end, [])
        return result

    def _canonical_read_done(self, key, task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()
        if self._canonical_reads.get(key) is task:
            del self._canonical_reads[key]

    async def _read_canonical_history(
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
        timestamps = sorted({parse_datetime(point["timestamp"]) for point in points})
        tolerance = timedelta(seconds=policy.bucket_seconds * 2)
        is_partial = (
            first is None
            or first > range_start + tolerance
            or timestamps[-1] < range_end - tolerance
            or any(right - left > tolerance for left, right in zip(timestamps, timestamps[1:]))
            or len(timestamps) < max(1, int(policy.duration.total_seconds() / policy.bucket_seconds) - 2)
        )
        return HistoryResult(
            instrument_id=instrument_id,
            timeframe=timeframe,
            status="partial" if is_partial else "complete",
            range_start=range_start,
            range_end=range_end,
            points=points,
            missing_before=first if is_partial and first and first > range_start + tolerance else None,
            attributions=_attribution_union(point.get("attributions", []) for point in points),
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
        db = SessionLocal()
        try:
            query = _canonical_history_sql(_history_supports_bookends(db))
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
                **({"timestamp_precision": "day", "timestamp_role": "day_bucket_start",
                    "source_observation_time_known": False,
                    "source_timezone": row.get("source_timezone"),
                    "source_calendar": row.get("source_calendar"), "source_date": row.get("source_date")}
                   if row.get("day_precision") else {}),
                **({"attributions": _attributions_for_groups(row.get("rights_source_groups") or [])} if rights.enforced() else {}),
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
        if rights.enforced():
            # These rows have no complete, reviewed provider lineage.
            return []
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
        allowed = rights.allowed_provider_ids("history") if rights.enforced() else None
        if allowed is not None and (not allowed or provider_id is not None and provider_id not in allowed):
            return []
        permission_filter = "provider_id = ANY(:rights_provider_ids)" if allowed is not None else "TRUE"
        query = text(
            f"""
            SELECT provider_id, price, bid, ask, observed_at, validation_status,
                   is_direct, is_derived, is_suspicious, rejection_reason, metadata
            FROM provider_quotes
            WHERE instrument_id = :instrument_id
              AND observed_at >= :start
              AND observed_at <= :end
              AND (CAST(:provider_id AS TEXT) IS NULL OR provider_id = :provider_id)
              AND {permission_filter}
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
                    **({"rights_provider_ids": list(allowed)} if allowed is not None else {}),
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
                **({key: row["metadata"][key] for key in ("timestamp_precision", "timestamp_role", "source_observation_time_known", "source_timezone", "source_calendar", "source_date") if key in row["metadata"]}
                   if isinstance(row.get("metadata"), dict) and row["metadata"].get("timestamp_precision") == "day" else {}),
            }
            for row in rows
        ]

    @staticmethod
    def _query_recent_prices(instrument_id: str, limit: int) -> list[Decimal]:
        permitted, parameters = _canonical_permissions("history")
        query = text(
            f"""
            SELECT price
            FROM canonical_quotes
            WHERE instrument_id = :instrument_id
              AND status = ANY(:statuses)
              AND {_DIRECT_GOLD_SQL}
              AND {permitted}
              AND COALESCE(source_summary->>'timestamp_precision', 'instant') <> 'day'
            ORDER BY canonical_at DESC
            LIMIT :limit
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(
                query,
                {"instrument_id": instrument_id, "statuses": list(_ACCEPTED_STATUSES), "limit": max(3, min(limit, 1000)), **parameters},
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
        permitted, parameters = _canonical_permissions("history")
        query = text(
            f"""
            SELECT price
            FROM canonical_quotes
            WHERE instrument_id = :instrument_id
              AND status = ANY(:statuses)
              AND {_DIRECT_GOLD_SQL}
              AND {permitted}
              AND COALESCE(source_summary->>'timestamp_precision', 'instant') <> 'day'
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
                    **parameters,
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
        quotes: dict[str, CanonicalQuote] = {}
        for row in rows:
            try:
                quote = _canonical_from_row(row)
            except Exception as exc:
                # One corrupt historical row must not erase every other
                # instrument from the public aggregate response.
                logger.error(
                    "Skipping malformed canonical quote in aggregate read",
                    extra={
                        "instrument_id": str(row.get("instrument_id", "unknown")),
                        "error_type": type(exc).__name__,
                    },
                )
                continue
            quotes[quote.instrument_id] = quote
        return quotes

    @staticmethod
    def _query_latest_rows(instrument_id: str | None) -> list[Any]:
        query, parameters = _latest_rows_sql(instrument_id)
        db = SessionLocal()
        try:
            _latest_read_budget(db)
            return db.execute(query, parameters).mappings().all()
        finally:
            db.close()

    @staticmethod
    def _query_latest_sources(instrument_id: str) -> list[dict[str, Any]]:
        allowed = rights.allowed_provider_ids("display") if rights.enforced() else None
        if allowed is not None and not allowed:
            return []
        permission_filter = "provider_id = ANY(:rights_provider_ids)" if allowed is not None else "TRUE"
        query = text(
            f"""
            SELECT DISTINCT ON (provider_id)
                id, provider_id, source_type, price, currency, weight_unit,
                purity, bid, ask, volume, observed_at, received_at, latency_ms,
                http_status, parser_version, validation_status, confidence_score,
                is_direct, is_derived, is_suspicious, rejection_reason,
                metadata, raw_payload_reference, persistence_status
            FROM provider_quotes
            WHERE instrument_id = :instrument_id
              AND {permission_filter}
              AND NOT (provider_id = ANY(:history_only_sources))
            ORDER BY provider_id, observed_at DESC
            """
        )
        db = SessionLocal()
        try:
            rows = db.execute(query, {"instrument_id": instrument_id,
                "history_only_sources": [name for name, provider in PROVIDERS.items() if provider.history_only] + list(RETIRED_PROVIDERS),
                **({"rights_provider_ids": list(allowed)} if allowed is not None else {})}).mappings().all()
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
                a.candidate_quote_id, a.previous_canonical_quote_id,
                a.severity, a.status AS anomaly_status, a.reason, a.created_at,
                v.id AS verification_id, v.candidate_quote_id AS verification_candidate_id,
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
            if row is not None and rights.enforced():
                # A decision, percentage or severity is also source data.
                # Resolve every contributing record before exposing any part.
                candidate = row.get("candidate_quote_id")
                has_verification = row.get("verification_id") is not None
                verification_candidate = row.get("verification_candidate_id")
                verifier_ids = row.get("verifier_quote_ids") if has_verification else []
                valid_ids = (isinstance(candidate, int) and not isinstance(candidate, bool)
                             and (not has_verification or isinstance(verification_candidate, int) and not isinstance(verification_candidate, bool))
                             and isinstance(verifier_ids, list)
                             and all(isinstance(value, int) and not isinstance(value, bool) for value in verifier_ids))
                approved = False
                if valid_ids:
                    quote_ids = {candidate, *verifier_ids}
                    if has_verification:
                        quote_ids.add(verification_candidate)
                    sources = db.execute(text("""SELECT id, provider_id FROM provider_quotes
                        WHERE instrument_id = :instrument_id AND id = ANY(:quote_ids)"""),
                        {"instrument_id": instrument_id, "quote_ids": list(quote_ids)}).mappings().all()
                    approved = ({source["id"] for source in sources} == quote_ids
                                and all(rights.provider_allowed(source["provider_id"], "display")
                                        and rights.provider_quality_check_allowed(source["provider_id"]) for source in sources))
                previous_id = row.get("previous_canonical_quote_id")
                approved = approved and isinstance(previous_id, int) and not isinstance(previous_id, bool)
                if approved and previous_id is not None:
                    previous = db.execute(text("""SELECT source_summary, candidate_provider_id, candidate_price FROM canonical_quotes
                        WHERE id = :quote_id AND instrument_id = :instrument_id"""),
                        {"quote_id": previous_id, "instrument_id": instrument_id}).mappings().all()
                    approved = (len(previous) == 1
                        and rights.quality_check_allowed(previous[0]["source_summary"])
                        and (previous[0]["candidate_price"] is None or previous[0]["candidate_provider_id"] is not None)
                        and (previous[0]["candidate_provider_id"] is None
                            or (rights.provider_allowed(previous[0]["candidate_provider_id"], "display")
                                and rights.provider_quality_check_allowed(previous[0]["candidate_provider_id"]))))
                if not approved:
                    return {"instrument_id": instrument_id, "status": "unavailable"}
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
        # Price fields must be positive; percentage changes may be negative.
        change_1h=_change_or_none(row["change_1h"]),
        change_24h=_change_or_none(row["change_24h"]),
        change_7d=_change_or_none(row["change_7d"]),
        change_30d=_change_or_none(row["change_30d"]),
        idempotency_key=row["idempotency_key"],
        sequence_number=(int(row["sequence_number"]) if row["sequence_number"] is not None else None),
    )


internal_history = InternalPriceHistory()


def _attributions_for_groups(groups) -> list[dict[str, str]]:
    providers = sorted({name for group in groups if isinstance(group, list) for name in group if isinstance(name, str)})
    return rights.attribution({"provider_ids": providers, "derived": False})


def _attribution_union(groups) -> list[dict[str, str]]:
    entries = {(entry["label"], entry["url"]) for group in groups for entry in group}
    return [{"label": label, "url": url} for label, url in sorted(entries)]
