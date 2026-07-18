from __future__ import annotations

from datetime import UTC, datetime
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.orm import Session

try:
    import redis
except ImportError:
    redis = None

from ...config import settings
from ...db import get_db
from ..audit import add_audit_event
from ..dbtools import reflected_table, safe_count, safe_rows
from ..deps import (
    AdminPrincipal,
    require_confirmation,
    require_permission,
    require_recent_reauthentication,
)
from ..models import AdminJob
from ..permissions import AdminPermissionKey
from ..redaction import redact, sanitize_error
from ..schemas import DangerousConfirmation, JobRetryRequest

router = APIRouter(tags=["admin-operations"])


def _database_state(db: Session) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        db.rollback()
        return {"status": "unavailable"}


def _redis_state() -> tuple[dict[str, Any], Any | None]:
    if redis is None or not settings.redis_url:
        return {"status": "disabled", "persistence_backlog": None}, None
    try:
        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.75,
            socket_timeout=0.75,
        )
        client.ping()
        persistence_backlog = int(client.xlen("pricing:persistence-stream"))
        backfill_backlog = int(client.llen("pricing:backfill-jobs"))
        return {
            "status": "ok",
            "persistence_backlog": persistence_backlog,
            "backfill_backlog": backfill_backlog,
            "pubsub": "available",
        }, client
    except Exception:
        return {"status": "unavailable", "persistence_backlog": None, "backfill_backlog": None}, None


def _latest_migration(db: Session) -> dict[str, Any] | None:
    rows = safe_rows(
        db,
        "schema_migrations",
        ("id", "version", "name", "checksum", "applied_at", "created_at"),
        limit=1,
        order_candidates=("applied_at", "created_at", "id"),
    )
    return rows[0] if rows else None


def _enabled_provider_count(db: Session) -> int | None:
    table = reflected_table(db, "pricing_providers")
    if table is None:
        return None
    statement = select(func.count()).select_from(table)
    if "enabled" in table.c:
        statement = statement.where(table.c.enabled.is_(True))
    return int(db.scalar(statement) or 0)


def _health_payload(db: Session) -> dict[str, Any]:
    database = _database_state(db)
    redis_state, _ = _redis_state()
    if database["status"] != "ok":
        return {
            "status": "degraded",
            "database": database,
            "redis": redis_state,
            "migration": None,
            "websocket": {"status": "degraded" if redis_state["status"] != "ok" else "available"},
            "background_refresh": {"status": "unknown"},
            "backlogs": {},
            "provider_health": {},
            "telegram": {"status": "unknown"},
        }

    provider_rows = safe_rows(
        db,
        "pricing_providers",
        (
            "provider_id",
            "health_status",
            "circuit_state",
            "last_success_at",
            "last_failure_at",
            "requests_per_day",
        ),
        limit=1000,
    )
    provider_health: dict[str, int] = {}
    for provider in provider_rows:
        key = str(provider.get("health_status") or "unknown")
        provider_health[key] = provider_health.get(key, 0) + 1
    canonical_rows = safe_rows(
        db,
        "canonical_quotes",
        ("instrument_id", "status", "canonical_at", "is_persisted"),
        limit=200,
        order_candidates=("canonical_at",),
    )
    last_by_instrument: dict[str, dict[str, Any]] = {}
    for row in canonical_rows:
        instrument_id = str(row.get("instrument_id") or "")
        if instrument_id and instrument_id not in last_by_instrument:
            last_by_instrument[instrument_id] = row
    backlogs = {
        "persistence": redis_state.get("persistence_backlog"),
        "backfill": safe_count(db, "pricing_backfill_jobs", {"pending", "retrying"}),
        "delivery": safe_count(db, "alert_delivery_jobs", {"pending", "retrying", "processing"}),
        "dlq": safe_count(db, "alert_delivery_jobs", {"dead"}),
        "admin_jobs": safe_count(db, "admin_operational_jobs", {"pending", "retrying"}),
    }
    anomaly_count = safe_count(db, "pricing_anomalies", {"open", "verifying", "unresolved"})
    telegram_count = safe_count(db, "telegram_sources")
    budget_usage: list[dict[str, Any]] = []
    redis_client = _redis_state()[1]
    if redis_client is not None and provider_rows:
        day_bucket = int(time.time()) // 86400
        keys = [
            f"pricing:budget:{provider.get('provider_id')}:all:day:{day_bucket}"
            for provider in provider_rows
            if provider.get("provider_id")
        ]
        try:
            values = redis_client.mget(keys) if keys else []
            for provider, used in zip(
                [item for item in provider_rows if item.get("provider_id")],
                values,
            ):
                limit = int(provider.get("requests_per_day") or 0)
                count = int(used or 0)
                budget_usage.append(
                    {
                        "provider_id": provider.get("provider_id"),
                        "used_today": count,
                        "daily_limit": limit,
                        "pressure": round(count / limit, 4) if limit > 0 else None,
                    }
                )
        except Exception:
            budget_usage = []
    overall_ok = redis_state["status"] in {"ok", "disabled"}
    return {
        "status": "ok" if overall_ok else "degraded",
        "database": database,
        "redis": redis_state,
        "migration": _latest_migration(db),
        "websocket": {
            "status": "available" if redis_state["status"] == "ok" else "degraded",
            "fanout": redis_state.get("pubsub", "unavailable"),
        },
        "background_refresh": {
            "status": "active" if last_by_instrument else "no_recent_snapshot",
            "last_by_instrument": last_by_instrument,
        },
        "backlogs": backlogs,
        "anomaly_count": anomaly_count,
        "provider_health": provider_health,
        "api_budget_usage": budget_usage,
        "telegram": {
            "status": "configured" if telegram_count else "not_configured",
            "source_count": telegram_count,
        },
    }


@router.get("/health")
def detailed_health(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.HEALTH_READ)),
    db: Session = Depends(get_db),
) -> dict:
    return _health_payload(db)


@router.get("/dashboard")
def dashboard(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.HEALTH_READ)),
    db: Session = Depends(get_db),
) -> dict:
    payload = _health_payload(db)
    payload["counts"] = {
        "users": safe_count(db, "users"),
        "open_support_tickets": safe_count(db, "support_tickets", {"open", "in_progress", "waiting_for_user"}),
        "enabled_providers": _enabled_provider_count(db),
        "delivery_dlq": safe_count(db, "alert_delivery_jobs", {"dead"}),
    }
    payload["recent_jobs"] = [
        {
            "id": job.id,
            "job_type": job.job_type,
            "resource_type": job.resource_type,
            "resource_id": job.resource_id,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
        }
        for job in db.scalars(select(AdminJob).order_by(AdminJob.created_at.desc()).limit(10)).all()
    ]
    return payload


def _admin_job_payload(job: AdminJob) -> dict[str, Any]:
    return redact(
        {
            "id": job.id,
            "job_type": job.job_type,
            "resource_type": job.resource_type,
            "resource_id": job.resource_id,
            "payload": job.payload,
            "status": job.status,
            "requested_by": job.requested_by,
            "attempt_count": job.attempt_count,
            "last_error": sanitize_error(job.last_error),
            "next_attempt_at": job.next_attempt_at,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "completed_at": job.completed_at,
        }
    )


@router.get("/jobs")
def list_jobs(
    job_status: str = Query(default="", alias="status", max_length=24),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AdminJob)
    if job_status:
        statement = statement.where(AdminJob.status == job_status)
    admin_jobs = db.scalars(statement.order_by(AdminJob.created_at.desc()).limit(limit)).all()
    backfill_jobs = safe_rows(
        db,
        "pricing_backfill_jobs",
        (
            "id",
            "instrument_id",
            "provider_id",
            "range_start",
            "range_end",
            "status",
            "attempt_count",
            "next_retry_at",
            "last_error",
            "created_at",
            "updated_at",
        ),
        limit=limit,
    )
    delivery_jobs = safe_rows(
        db,
        "alert_delivery_jobs",
        (
            "id",
            "alert_id",
            "trigger_event_id",
            "channel",
            "status",
            "attempt_count",
            "next_retry_at",
            "last_error",
            "created_at",
            "delivered_at",
            "dead_at",
        ),
        limit=limit,
    )
    return {
        "admin_jobs": [_admin_job_payload(job) for job in admin_jobs],
        "backfill_jobs": redact(backfill_jobs),
        "delivery_jobs": redact(delivery_jobs),
    }


@router.get("/jobs/dlq")
def list_dlq(
    limit: int = Query(default=100, ge=1, le=500),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.DLQ_READ)),
    db: Session = Depends(get_db),
) -> dict:
    rows = safe_rows(
        db,
        "alert_delivery_jobs",
        (
            "id",
            "alert_id",
            "trigger_event_id",
            "channel",
            "status",
            "attempt_count",
            "next_retry_at",
            "last_error",
            "created_at",
            "dead_at",
        ),
        limit=limit,
    )
    return {"items": redact([row for row in rows if row.get("status") == "dead"])}


@router.post("/jobs/{job_id}/retry")
def retry_admin_job(
    job_id: int,
    payload: JobRetryRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(AdminJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operational job not found")
    if job.status not in {"failed", "dead", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed jobs can be retried")
    before = {"status": job.status, "attempt_count": job.attempt_count, "last_error": job.last_error}
    job.status = "pending"
    job.next_attempt_at = datetime.now(UTC)
    job.last_error = None
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.job.retry_requested",
        resource_type="admin_job",
        resource_id=job.id,
        before=before,
        after={"status": job.status, "next_attempt_at": job.next_attempt_at},
    )
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.post("/jobs/delivery/{delivery_job_id}/retry")
def retry_delivery_job(
    delivery_job_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.DLQ_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    table = reflected_table(db, "alert_delivery_jobs")
    if table is None or "id" not in table.c or "status" not in table.c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery job store unavailable")
    current = db.execute(
        select(table).where(cast(table.c.id, String) == delivery_job_id).limit(1)
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery job not found")
    if current.get("status") not in {"failed", "dead", "retrying"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delivery job is not retryable")
    values: dict[str, Any] = {"status": "pending"}
    if "next_retry_at" in table.c:
        values["next_retry_at"] = datetime.now(UTC)
    if "last_error" in table.c:
        values["last_error"] = None
    db.execute(table.update().where(cast(table.c.id, String) == delivery_job_id).values(**values))
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.delivery.retry_requested",
        resource_type="alert_delivery_job",
        resource_id=delivery_job_id,
        before={"status": current.get("status"), "attempt_count": current.get("attempt_count")},
        after=values,
    )
    db.commit()
    return {"delivery_job_id": delivery_job_id, "status": "pending"}


@router.post("/jobs/delivery/{delivery_job_id}/cancel")
def cancel_delivery_job(
    delivery_job_id: str,
    payload: DangerousConfirmation,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.DLQ_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"CANCEL DELIVERY {delivery_job_id}")
    table = reflected_table(db, "alert_delivery_jobs")
    if table is None or "id" not in table.c or "status" not in table.c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery job store unavailable")
    current = db.execute(
        select(table).where(cast(table.c.id, String) == delivery_job_id).limit(1)
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery job not found")
    if current.get("status") in {"delivered", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delivery job cannot be cancelled")
    db.execute(
        table.update().where(cast(table.c.id, String) == delivery_job_id).values(status="cancelled")
    )
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.delivery.cancelled",
        resource_type="alert_delivery_job",
        resource_id=delivery_job_id,
        before={"status": current.get("status")},
        after={"status": "cancelled"},
    )
    db.commit()
    return {"delivery_job_id": delivery_job_id, "status": "cancelled"}
