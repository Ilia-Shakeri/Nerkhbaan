from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..audit import add_audit_event
from ..dbtools import reflected_table, safe_rows, serialize_mapping
from ..deps import AdminPrincipal, require_permission
from ..models import AdminJob, AdminResourceReview
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
    "candidate_price",
    "previous_price",
    "deviation_percent",
    "dynamic_threshold_percent",
    "status",
    "decision_reason",
    "created_at",
    "resolved_at",
)
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
    statement = select(*selected).where(identity_column == identity)
    for field in order_fields:
        if field in table.c:
            statement = statement.order_by(table.c[field].desc())
            break
    records = db.execute(statement.limit(max(1, min(limit, 2000)))).mappings().all()
    return [redact(serialize_mapping(dict(record))) for record in records]


def _resource_exists(db: Session, table_name: str, resource_id: str) -> bool:
    table = reflected_table(db, table_name)
    if table is None or "id" not in table.c:
        return False
    return (
        db.scalar(
            select(table.c.id).where(cast(table.c.id, String) == resource_id).limit(1)
        )
        is not None
    )


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
    canonical_rows = safe_rows(db, "canonical_quotes", _CANONICAL_COLUMNS, limit=2000)
    latest: dict[str, dict[str, Any]] = {}
    for row in canonical_rows:
        instrument_id = str(row.get("instrument_id") or "")
        if instrument_id and instrument_id not in latest:
            latest[instrument_id] = row
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
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_READ)),
    db: Session = Depends(get_db),
) -> dict:
    rows = safe_rows(db, "pricing_anomalies", _ANOMALY_COLUMNS, limit=limit)
    if anomaly_status:
        rows = [row for row in rows if row.get("status") == anomaly_status]
    resource_ids = {str(row.get("id")) for row in rows if row.get("id") is not None}
    reviews = db.scalars(
        select(AdminResourceReview).where(
            AdminResourceReview.resource_type == "pricing_anomaly",
            AdminResourceReview.resource_id.in_(resource_ids),
        )
    ).all() if resource_ids else []
    review_by_id = {
        review.resource_id: {
            "status": review.status,
            "note": review.note,
            "reviewed_by": review.reviewed_by,
            "reviewed_at": review.reviewed_at.isoformat(),
        }
        for review in reviews
    }
    return {
        "items": [
            {**row, "admin_review": review_by_id.get(str(row.get("id")))}
            for row in rows
        ]
    }


@router.post("/anomalies/{anomaly_id}/review")
def review_anomaly(
    anomaly_id: str,
    payload: AnomalyReviewRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PRICING_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    if not _resource_exists(db, "pricing_anomalies", anomaly_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing anomaly not found")
    review = db.scalar(
        select(AdminResourceReview).where(
            AdminResourceReview.resource_type == "pricing_anomaly",
            AdminResourceReview.resource_id == anomaly_id,
        )
    )
    before = None
    if review is None:
        review = AdminResourceReview(
            resource_type="pricing_anomaly",
            resource_id=anomaly_id,
            status=payload.status,
            note=payload.note.strip(),
            reviewed_by=principal.user.id,
        )
        db.add(review)
    else:
        before = {"status": review.status, "note": review.note}
        review.status = payload.status
        review.note = payload.note.strip()
        review.reviewed_by = principal.user.id
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.pricing.anomaly_reviewed",
        resource_type="pricing_anomaly",
        resource_id=anomaly_id,
        before=before,
        after={"status": review.status, "note": review.note},
    )
    db.commit()
    return {"anomaly_id": anomaly_id, "review_status": review.status}


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
