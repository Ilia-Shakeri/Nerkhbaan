from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import false, func, or_, select, text
from sqlalchemy.orm import Session

from ...db import get_db
from ...pricing import rights
from ...pricing.db_models import PricingAnomalyRecord
from ..audit import add_audit_event
from ..dbtools import reflected_table, safe_rows, serialize_mapping
from ..deps import AdminPrincipal, require_permission
from ..models import AdminJob
from ..permissions import AdminPermissionKey
from ..redaction import redact
from ..schemas import AnomalyReviewRequest, RefreshRequest

router = APIRouter(prefix="/pricing", tags=["admin-pricing"])

_INSTRUMENT_IDS = (
    "GOLD_18K_TOMAN_GRAM",
    "XAU_USD_OZ",
    "SILVER_999_TOMAN_GRAM",
    "SILVER_925_TOMAN_GRAM",
    "XAG_USD_OZ",
    "USDT_TOMAN",
    "USDT_USD",
    "BTC_TOMAN",
    "BTC_USD",
)
_INSTRUMENT_COLUMNS = (
    "id",
    "instrument_id",
    "base_asset",
    "quote_currency",
    "market",
    "region",
    "weight_unit",
    "purity",
    "display_decimals",
    "operational_ttl_seconds",
    "stale_after_seconds",
    "expire_after_seconds",
    "base_anomaly_threshold_percent",
    "maximum_dynamic_threshold_percent",
    "importance",
    "enabled",
    "updated_at",
)
_CANONICAL_COLUMNS = (
    "id",
    "instrument_id",
    "price",
    "status",
    "primary_quote_id",
    "verification_quote_ids",
    "source_summary",
    "candidate_provider_id",
    "observed_at",
    "canonical_at",
    "valid_until",
    "stale_at",
    "expires_at",
    "is_persisted",
    "decision_reason",
    "change_1h",
    "change_24h",
    "change_7d",
    "change_30d",
)
_PROVIDER_QUOTE_COLUMNS = (
    "id",
    "instrument_id",
    "provider_id",
    "source_type",
    "price",
    "currency",
    "weight_unit",
    "purity",
    "bid",
    "ask",
    "volume",
    "observed_at",
    "received_at",
    "latency_ms",
    "http_status",
    "parser_version",
    "validation_status",
    "confidence_score",
    "is_direct",
    "is_derived",
    "is_suspicious",
    "rejection_reason",
    "metadata",
    "raw_payload_reference",
    "persistence_status",
)
_ANOMALY_COLUMNS = (
    "id",
    "instrument_id",
    "candidate_quote_id",
    "previous_canonical_quote_id",
    "deviation_percent",
    "dynamic_threshold_percent",
    "severity",
    "status",
    "reason",
    "reviewed_by_admin_id",
    "reviewed_at",
    "review_note",
    "created_at",
)
_ANOMALY_REVIEW_TRANSITIONS = {
    "open": frozenset({"reviewed", "dismissed", "resolved"}),
    "reviewed": frozenset({"resolved", "dismissed"}),
}
_MAX_BIGINT = 9_223_372_036_854_775_807
_VERIFICATION_COLUMNS = (
    "id",
    "instrument_id",
    "anomaly_id",
    "candidate_quote_id",
    "verifier_quote_id",
    "verifier_quote_ids",
    "difference_percent",
    "tolerance_percent",
    "decision",
    "reason",
    "decision_reason",
    "created_at",
)

_REVIEW_METADATA = frozenset({"id", "instrument_id", "status", "reviewed_by_admin_id", "reviewed_at", "review_note", "created_at"})


def _permitted_statement(statement, table, table_name: str):
    if not rights.enforced():
        return statement
    if table_name == "provider_quotes":
        return statement.where(table.c.provider_id.in_(rights.allowed_provider_ids("display"))) if "provider_id" in table.c else statement.where(false())
    if table_name == "canonical_quotes":
        if "source_summary" not in table.c:
            return statement.where(false())
        clause, parameters = rights.sql_filter("display")
        statement = statement.where(text(clause).bindparams(**parameters))
        if "status" in table.c:
            statement = statement.where(text("(status <> 'derived_fallback' OR source_summary->>'derived' = 'true' OR source_summary->>'primary_provider_id' LIKE 'derived:%')"))
        if "candidate_provider_id" in table.c:
            statement = statement.where(or_(table.c.candidate_provider_id.is_(None), table.c.candidate_provider_id.in_(rights.allowed_provider_ids("display"))))
            if "candidate_price" in table.c:
                statement = statement.where(or_(table.c.candidate_price.is_(None), table.c.candidate_provider_id.in_(rights.allowed_provider_ids("display"))))
        elif "candidate_price" in table.c:
            statement = statement.where(table.c.candidate_price.is_(None))
    return statement


def _canonical_row_allowed(row) -> bool:
    candidate = row.get("candidate_provider_id")
    summary = row.get("source_summary")
    return rights.canonical_allowed(summary, "display") and (candidate is None or rights.provider_allowed(candidate, "display")) and (row.get("candidate_price") is None or candidate is not None) and (row.get("status") != "derived_fallback" or summary.get("derived") is True or str(summary.get("primary_provider_id", "")).startswith("derived:"))


def _restricted_rows(db: Session, table_name: str, rows: list[dict]) -> list[dict]:
    if not rights.enforced() or not rows:
        return rows
    if table_name == "canonical_quotes":
        return [{**row, **{key: None for key in ("change_1h", "change_24h", "change_7d", "change_30d") if key in row}} for row in rows if _canonical_row_allowed(row)]
    if table_name == "provider_quotes":
        return [row for row in rows if rights.provider_allowed(row.get("provider_id"), "display")]
    if table_name not in {"pricing_anomalies", "pricing_verifications"}:
        return rows

    def reference_id(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    def fetch(table_name, identifiers):
        table = reflected_table(db, table_name)
        if table is None or "id" not in table.c or not identifiers:
            return {}
        return {row["id"]: dict(row) for row in db.execute(select(table).where(table.c.id.in_(identifiers))).mappings().all()}

    anomaly_ids = {value for row in rows if (value := reference_id(row.get("anomaly_id"))) is not None}
    anomalies = fetch("pricing_anomalies", anomaly_ids) if table_name == "pricing_verifications" else {}
    related = [*rows, *anomalies.values()]
    provider_ids = {value for row in related if (value := reference_id(row.get("candidate_quote_id"))) is not None}
    canonical_ids = {value for row in related if (value := reference_id(row.get("previous_canonical_quote_id"))) is not None}
    for row in rows:
        if (value := reference_id(row.get("verifier_quote_id"))) is not None:
            provider_ids.add(value)
        values = row.get("verifier_quote_ids")
        if isinstance(values, list):
            provider_ids.update(value for value in values if reference_id(value) is not None)
    providers = fetch("provider_quotes", provider_ids)
    canonicals = fetch("canonical_quotes", canonical_ids)

    def provider_ok(identifier, instrument):
        value = providers.get(reference_id(identifier))
        return bool(value and value.get("instrument_id") == instrument and rights.provider_allowed(value.get("provider_id"), "display"))

    def anomaly_ok(row):
        instrument = row.get("instrument_id")
        previous = canonicals.get(reference_id(row.get("previous_canonical_quote_id")))
        return bool(provider_ok(row.get("candidate_quote_id"), instrument) and previous and previous.get("instrument_id") == instrument and _canonical_row_allowed(previous))

    result = []
    for row in rows:
        if table_name == "pricing_anomalies":
            approved = anomaly_ok(row)
        else:
            instrument = row.get("instrument_id")
            values = row.get("verifier_quote_ids")
            approved = isinstance(values, list) and all(provider_ok(value, instrument) for value in values) and provider_ok(row.get("candidate_quote_id"), instrument)
            if row.get("verifier_quote_id") is not None:
                approved = approved and provider_ok(row["verifier_quote_id"], instrument)
            if row.get("anomaly_id") is not None:
                anomaly = anomalies.get(reference_id(row["anomaly_id"]))
                approved = approved and bool(anomaly and anomaly.get("instrument_id") == instrument and anomaly_ok(anomaly))
        result.append(row if approved else {**{key: value for key, value in row.items() if key in _REVIEW_METADATA}, "rights_restricted": True})
    return result


def _rows_for(
    db: Session,
    table_name: str,
    columns: tuple[str, ...],
    *,
    identity_fields: tuple[str, ...],
    identity: Any,
    limit: int = 500,
    order_fields: tuple[str, ...] = ("canonical_at", "observed_at", "created_at", "time"),
) -> list[dict[str, Any]]:
    table = reflected_table(db, table_name)
    if table is None:
        return []
    selected = [table.c[name] for name in columns if name in table.c]
    identity_column = next((table.c[name] for name in identity_fields if name in table.c), None)
    if not selected or identity_column is None:
        return []
    statement = _permitted_statement(select(*selected).where(identity_column == identity), table, table_name)
    for field in order_fields:
        if field in table.c:
            statement = statement.order_by(table.c[field].desc())
            break
    records = db.execute(statement.limit(max(1, min(limit, 2000)))).mappings().all()
    rows = _restricted_rows(db, table_name, [dict(record) for record in records])
    return [redact(serialize_mapping(record)) for record in rows]


def _anomaly_review_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    reviewed_at = row.get("reviewed_at")
    if reviewed_at is None:
        return None
    return {
        "status": row.get("status"),
        "note": row.get("review_note") or "",
        "reviewed_by": row.get("reviewed_by_admin_id"),
        "reviewed_at": (reviewed_at if reviewed_at.tzinfo else reviewed_at.replace(tzinfo=UTC)).isoformat() if isinstance(reviewed_at, datetime) else reviewed_at,
    }


def _anomaly_review_snapshot(anomaly: PricingAnomalyRecord) -> dict[str, Any]:
    return {
        "status": anomaly.status,
        "reviewed_by_admin_id": anomaly.reviewed_by_admin_id,
        "reviewed_at": anomaly.reviewed_at.isoformat() if anomaly.reviewed_at else None,
        "review_note": anomaly.review_note,
    }


@router.get("/instruments")
def list_instruments(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_READ)),
    db: Session = Depends(get_db),
) -> dict:
    instruments = safe_rows(db, "instruments", _INSTRUMENT_COLUMNS, limit=1000)
    if not instruments:
        instruments = [
            {"instrument_id": instrument_id, "enabled": False, "status": "schema_pending"}
            for instrument_id in _INSTRUMENT_IDS
        ]
    latest: dict[str, dict[str, Any]] = {}
    table = reflected_table(db, "canonical_quotes")
    if table is not None:
        columns = [table.c[name] for name in _CANONICAL_COLUMNS if name in table.c]
        ranked = _permitted_statement(select(*columns, func.row_number().over(partition_by=table.c.instrument_id, order_by=[table.c.canonical_at.desc(), table.c.id.desc()]).label("rank")), table, "canonical_quotes").subquery()
        rows = [dict(row) for row in db.execute(select(ranked).where(ranked.c.rank == 1)).mappings().all()]
        for row in _restricted_rows(db, "canonical_quotes", rows):
            latest[str(row["instrument_id"])] = redact(serialize_mapping({key: value for key, value in row.items() if key != "rank"}))
    return {
        "items": [
            {**instrument, "latest_canonical": latest.get(str(instrument.get("instrument_id") or instrument.get("id")))}
            for instrument in instruments
        ]
    }


@router.get("/instruments/{instrument_id}")
def instrument_detail(
    instrument_id: str,
    history_limit: int = Query(default=200, ge=1, le=1000),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_READ)),
    db: Session = Depends(get_db),
) -> dict:
    instrument_rows = _rows_for(
        db,
        "instruments",
        _INSTRUMENT_COLUMNS,
        identity_fields=("instrument_id", "id"),
        identity=instrument_id,
        limit=1,
        order_fields=("updated_at",),
    )
    if not instrument_rows and instrument_id not in _INSTRUMENT_IDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrument not found")
    canonical = _rows_for(
        db,
        "canonical_quotes",
        _CANONICAL_COLUMNS,
        identity_fields=("instrument_id",),
        identity=instrument_id,
        limit=history_limit,
    )
    sources = _rows_for(
        db,
        "provider_quotes",
        _PROVIDER_QUOTE_COLUMNS,
        identity_fields=("instrument_id",),
        identity=instrument_id,
        limit=history_limit,
        order_fields=("observed_at", "received_at", "created_at"),
    )
    anomalies = _rows_for(
        db,
        "pricing_anomalies",
        _ANOMALY_COLUMNS,
        identity_fields=("instrument_id",),
        identity=instrument_id,
        limit=100,
        order_fields=("created_at",),
    )
    verifications = _rows_for(
        db,
        "pricing_verifications",
        _VERIFICATION_COLUMNS,
        identity_fields=("instrument_id",),
        identity=instrument_id,
        limit=100,
        order_fields=("created_at",),
    )
    return {
        "instrument": instrument_rows[0] if instrument_rows else {"instrument_id": instrument_id},
        "latest_canonical": canonical[0] if canonical else None,
        "canonical_history": canonical,
        "source_quotes": sources,
        "anomalies": anomalies,
        "verifications": verifications,
    }


@router.get("/anomalies")
def list_anomalies(
    anomaly_status: str = Query(default="", alias="status", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_READ)),
    db: Session = Depends(get_db),
) -> dict:
    filters = {"status": anomaly_status} if anomaly_status else {}
    rows = safe_rows(db, "pricing_anomalies", _ANOMALY_COLUMNS, limit=limit, offset=offset, filters=filters)
    rows = _restricted_rows(db, "pricing_anomalies", rows)
    table = reflected_table(db, "pricing_anomalies")
    total_query = select(func.count()).select_from(table) if table is not None else None
    if total_query is not None and anomaly_status:
        total_query = total_query.where(table.c.status == anomaly_status)
    for row in rows:
        if row.get("rights_restricted"):
            continue
        candidates = _rows_for(db, "provider_quotes", _PROVIDER_QUOTE_COLUMNS, identity_fields=("id",), identity=row.get("candidate_quote_id"), limit=1) if row.get("candidate_quote_id") else []
        previous = _rows_for(db, "canonical_quotes", _CANONICAL_COLUMNS, identity_fields=("id",), identity=row.get("previous_canonical_quote_id"), limit=1) if row.get("previous_canonical_quote_id") else []
        row.update(candidate_quote=candidates[0] if candidates else None, previous_canonical=previous[0] if previous else None, candidate_price=candidates[0].get("price") if candidates else None, previous_price=previous[0].get("price") if previous else None)
    return {"items": [{**row, "admin_review": _anomaly_review_payload(row)} for row in rows], "total": int(db.scalar(total_query) or 0) if total_query is not None else 0, "limit": limit, "offset": offset}


@router.post("/anomalies/{anomaly_id}/review")
def review_anomaly(
    anomaly_id: str,
    payload: AnomalyReviewRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    try:
        anomaly_key = int(anomaly_id)
    except ValueError:
        anomaly_key = 0
    if anomaly_key <= 0 or anomaly_key > _MAX_BIGINT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing anomaly not found")
    anomaly = db.scalar(
        select(PricingAnomalyRecord)
        .where(PricingAnomalyRecord.id == anomaly_key)
        .with_for_update()
    )
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing anomaly not found")
    if payload.status not in _ANOMALY_REVIEW_TRANSITIONS.get(anomaly.status, frozenset()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pricing anomaly must be open for review",
        )

    before = _anomaly_review_snapshot(anomaly)
    reviewed_at = datetime.now(UTC)
    try:
        anomaly.status = payload.status
        anomaly.reviewed_by_admin_id = principal.user.id
        anomaly.reviewed_at = reviewed_at
        anomaly.review_note = payload.note
        response = {
            "anomaly_id": anomaly_id,
            "review_status": payload.status,
            "reviewed_by_admin_id": principal.user.id,
            "reviewed_at": reviewed_at.isoformat(),
            "review_note": payload.note,
        }
        add_audit_event(
            db,
            request,
            actor_admin_id=principal.user.id,
            action="admin.pricing.anomaly_reviewed",
            resource_type="pricing_anomaly",
            resource_id=anomaly.id,
            before=before,
            after=_anomaly_review_snapshot(anomaly),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response


@router.post("/instruments/{instrument_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
def request_instrument_refresh(
    instrument_id: str,
    payload: RefreshRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    instrument_known = instrument_id in _INSTRUMENT_IDS or bool(
        _rows_for(
            db,
            "instruments",
            _INSTRUMENT_COLUMNS,
            identity_fields=("instrument_id", "id"),
            identity=instrument_id,
            limit=1,
        )
    )
    if not instrument_known:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrument not found")
    job = AdminJob(
        job_type="instrument_refresh",
        resource_type="instrument",
        resource_id=instrument_id,
        payload={"reason": payload.reason, "budget_controlled": True},
        status="pending",
        requested_by=principal.user.id,
    )
    db.add(job)
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.pricing.refresh_requested",
        resource_type="instrument",
        resource_id=instrument_id,
        after={"budget_controlled": True, "reason": payload.reason},
    )
    db.commit()
    db.refresh(job)
    return {"job_id": job.id, "status": job.status, "budget_controlled": True}
