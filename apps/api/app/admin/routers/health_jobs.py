from __future__ import annotations

from datetime import UTC, datetime
import time
import json
import os
from pathlib import Path
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
from ...services.alert_delivery_state import finalize_trigger_event, lock_trigger_event
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


def _utc_stamp(value: Any) -> datetime:
    stamp = datetime.fromisoformat(str(value))
    return stamp.astimezone(UTC) if stamp.tzinfo else stamp.replace(tzinfo=UTC)


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
    client = None
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
        if client is not None:
            client.close()
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
    from ...services.background import background_runner
    from ...pricing.cache import PricingRedisStore
    from ...pricing.registry import PROVIDERS
    from .pricing import list_instruments
    from ..worker import admin_operations_worker

    database = _database_state(db)
    redis_state, redis_client = _redis_state()
    now = datetime.now(UTC)
    refresh = background_runner.refresh_health()
    stamp = refresh.get("last_completed_at") or refresh.get("last_started_at")
    try:
        age = max(0, (now - _utc_stamp(stamp)).total_seconds())
    except (ValueError, TypeError):
        age = None
    refresh_active = bool(refresh.get("enabled") and age is not None and age <= max(180, background_runner.interval * 4) and refresh.get("state") in {"healthy", "running"})
    payload: dict[str, Any] = {"status": "degraded", "checked_at": now.isoformat(), "database": database, "redis": redis_state, "migration": None, "websocket": {"status": "available" if redis_state["status"] == "ok" else "degraded"}, "background_refresh": {**refresh, "status": "active" if refresh_active else "stale" if refresh.get("enabled") else "disabled", "age_seconds": age, "last_by_instrument": {}}, "admin_worker": admin_operations_worker.health(), "backlogs": {}, "provider_health": {}, "provider_runtime": [], "telegram": {"status": "unknown"}, "api_budget_usage": []}
    try:
        if database["status"] != "ok":
            return payload
        inventory = list_instruments(principal=None, db=db)["items"]
        latest = {str(item.get("instrument_id")): item.get("latest_canonical") for item in inventory if item.get("enabled")}
        if redis_client is not None:
            try:
                values = redis_client.mget([PricingRedisStore.canonical_key(key) for key in latest])
                for key, value in zip(latest, values):
                    if value:
                        latest[key] = json.loads(value)
                runtime_values = redis_client.mget([PricingRedisStore.provider_runtime_key(provider.provider_id, provider.instrument_id) for provider in PROVIDERS.values()])
                for provider, raw in zip(PROVIDERS.values(), runtime_values):
                    item = json.loads(raw) if raw else {"provider_id": provider.provider_id, "instrument_id": provider.instrument_id, "operational_status": "unknown", "circuit_state": "unknown"}
                    payload["provider_runtime"].append(redact(item))
                    key = str(item.get("operational_status") or "unknown")
                    payload["provider_health"][key] = payload["provider_health"].get(key, 0) + 1
                day_bucket = int(time.time()) // 86400
                used = redis_client.mget([f"pricing:budget:{provider.provider_id}:all:day:{day_bucket}" for provider in PROVIDERS.values()])
                for provider, value in zip(PROVIDERS.values(), used):
                    count = int(value or 0)
                    maximum = provider.budget.requests_per_day
                    payload["api_budget_usage"].append({"provider_id": provider.provider_id, "used_today": count, "daily_limit": maximum, "pressure": round(count / maximum, 4) if maximum else None})
            except Exception:
                payload["redis"]["runtime_status"] = "unavailable"
        missing = []
        for key, quote in latest.items():
            if not quote:
                missing.append(key)
                continue
            effective = dict(quote)
            try:
                observed = _utc_stamp(quote["observed_at"])
                effective["age_seconds"] = max(0, int((now - observed).total_seconds()))
                expired = _utc_stamp(quote["expires_at"]) <= now
                stale = _utc_stamp(quote["stale_at"]) <= now
                if expired:
                    effective["status"] = "expired"
                elif stale:
                    effective["status"] = "stale"
            except (ValueError, KeyError, TypeError):
                effective["status"] = "unknown"
            if effective.get("status") not in {"live", "confirmed", "derived_fallback"}:
                missing.append(key)
            payload["background_refresh"]["last_by_instrument"][key] = effective
        payload["missing_or_stale_instruments"] = missing
        payload["migration"] = _latest_migration(db)
        payload["backlogs"] = {"persistence": redis_state.get("persistence_backlog"), "backfill": safe_count(db, "pricing_backfill_jobs", {"pending", "retrying", "deferred", "processing"}), "delivery": safe_count(db, "alert_delivery_jobs", {"pending", "retrying", "processing", "sending"}), "dlq": safe_count(db, "alert_delivery_jobs", {"dead"}), "admin_jobs": safe_count(db, "admin_operational_jobs", {"pending", "retrying", "processing"})}
        payload["anomaly_count"] = safe_count(db, "pricing_anomalies", {"open", "reviewed"})
        telegram_count = safe_count(db, "telegram_sources")
        payload["telegram"] = {"status": "configured" if telegram_count else "not_configured", "source_count": telegram_count}
        payload["status"] = "ok" if redis_state["status"] == "ok" and refresh_active and latest and not missing and payload["admin_worker"]["status"] == "active" else "degraded"
        return payload
    finally:
        if redis_client is not None:
            redis_client.close()


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


def _job_table_page(db: Session, table_name: str, columns: tuple[str, ...], job_status: str, limit: int, offset: int) -> tuple[list[dict], int]:
    table = reflected_table(db, table_name)
    if table is None:
        return [], 0
    statement = select(func.count()).select_from(table)
    filters = {"status": job_status} if job_status else {}
    if job_status:
        statement = statement.where(table.c.status == job_status)
    total = int(db.scalar(statement) or 0)
    rows = safe_rows(db, table_name, columns, filters=filters, limit=limit, offset=offset)
    for row in rows:
        if "last_error" in row:
            row["last_error"] = sanitize_error(row["last_error"])
    return rows, total


_DELIVERY_COLUMNS = ("id", "alert_id", "trigger_event_id", "channel", "status", "attempt_count", "next_retry_at", "last_error", "provider_response_summary", "created_at", "updated_at", "delivered_at", "dead_at")
_BACKFILL_COLUMNS = ("id", "instrument_id", "provider_id", "range_start", "range_end", "status", "attempt_count", "next_attempt_at", "last_error", "created_at", "updated_at", "completed_at")


@router.get("/jobs")
def list_jobs(job_status: str = Query(default="", alias="status", max_length=24), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_READ)), db: Session = Depends(get_db)) -> dict:
    statement = select(AdminJob)
    if job_status:
        statement = statement.where(AdminJob.status == job_status)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    admin_jobs = db.scalars(statement.order_by(AdminJob.created_at.desc(), AdminJob.id.desc()).offset(offset).limit(limit)).all()
    backfill, backfill_total = _job_table_page(db, "pricing_backfill_jobs", _BACKFILL_COLUMNS, job_status, limit, offset)
    delivery, delivery_total = _job_table_page(db, "alert_delivery_jobs", _DELIVERY_COLUMNS, job_status, limit, offset)
    return {"admin_jobs": [_admin_job_payload(job) for job in admin_jobs], "backfill_jobs": backfill, "delivery_jobs": delivery, "totals": {"admin_jobs": int(total or 0), "backfill_jobs": backfill_total, "delivery_jobs": delivery_total}, "limit": limit, "offset": offset}


@router.get("/jobs/dlq")
def list_dlq(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.DLQ_READ)), db: Session = Depends(get_db)) -> dict:
    items, total = _job_table_page(db, "alert_delivery_jobs", _DELIVERY_COLUMNS, "dead", limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/jobs/{job_id}/retry")
def retry_admin_job(
    job_id: int,
    payload: JobRetryRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    job = db.scalar(select(AdminJob).where(AdminJob.id == job_id).with_for_update())
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
        select(table).where(cast(table.c.id, String) == delivery_job_id).with_for_update().limit(1)
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
        select(table).where(cast(table.c.id, String) == delivery_job_id).with_for_update().limit(1)
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery job not found")
    if current.get("status") not in {"pending", "retrying", "processing", "failed", "dead"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delivery job cannot be cancelled")
    event = None
    if current.get("trigger_event_id") is not None and reflected_table(db, "alert_trigger_events") is not None:
        event = lock_trigger_event(db, current["trigger_event_id"])
    db.execute(
        table.update().where(cast(table.c.id, String) == delivery_job_id, table.c.status == current["status"]).values(status="cancelled")
    )
    finalize_trigger_event(db, event)
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


@router.post("/jobs/{job_id}/cancel")
def cancel_admin_job(job_id: int, payload: DangerousConfirmation, request: Request, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"CANCEL ADMIN JOB {job_id}")
    job = db.scalar(select(AdminJob).where(AdminJob.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="Operational job not found")
    if job.status not in {"pending", "retrying", "failed", "dead"}:
        raise HTTPException(status_code=409, detail="Only queued or failed jobs can be cancelled")
    before = {"status": job.status}
    job.status = "cancelled"
    job.completed_at = datetime.now(UTC)
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.job.cancelled", resource_type="admin_job", resource_id=job_id, before=before, after={"status": "cancelled"})
    db.commit()
    return {"job_id": job_id, "status": "cancelled"}


def _change_backfill(db: Session, job_id: str, action: str, request: Request, principal: AdminPrincipal) -> dict:
    table = reflected_table(db, "pricing_backfill_jobs")
    if table is None:
        raise HTTPException(status_code=404, detail="Backfill store unavailable")
    row = db.execute(select(table).where(cast(table.c.id, String) == job_id).with_for_update()).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    allowed = {"failed", "dead", "cancelled", "deferred"} if action == "retry" else {"pending", "retrying", "deferred", "failed", "dead"}
    if row["status"] not in allowed:
        raise HTTPException(status_code=409, detail="Job is running or has an incompatible state")
    values = {"status": "pending" if action == "retry" else "cancelled"}
    if "completed_at" in table.c:
        values["completed_at"] = None if action == "retry" else datetime.now(UTC)
    if "next_attempt_at" in table.c:
        values["next_attempt_at"] = datetime.now(UTC) if action == "retry" else None
    if action == "retry" and "last_error" in table.c:
        values["last_error"] = None
    db.execute(table.update().where(cast(table.c.id, String) == job_id, table.c.status == row["status"]).values(**values))
    add_audit_event(db, request, actor_admin_id=principal.user.id, action=f"admin.backfill.{action}", resource_type="pricing_backfill_job", resource_id=job_id, before={"status": row["status"]}, after=values)
    db.commit()
    return {"job_id": job_id, "status": values["status"]}


@router.post("/jobs/backfill/{job_id}/retry")
def retry_backfill(job_id: str, request: Request, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    return _change_backfill(db, job_id, "retry", request, principal)


@router.post("/jobs/backfill/{job_id}/cancel")
def cancel_backfill(job_id: str, payload: DangerousConfirmation, request: Request, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.JOBS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"CANCEL BACKFILL {job_id}")
    return _change_backfill(db, job_id, "cancel", request, principal)


@router.get("/backups/status")
def backup_status(principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.HEALTH_READ))) -> dict:
    configured = os.getenv("ADMIN_BACKUP_STATUS_FILE", "").strip()
    if not configured:
        return {"status": "not_configured", "verified": False}
    try:
        path = Path(configured)
        if not path.is_absolute() or path.stat().st_size > 16384:
            raise ValueError("Invalid backup manifest")
        raw = json.loads(path.read_text(encoding="utf-8"))
        allowed = {"last_backup_at", "last_restore_at", "backup_status", "restore_status", "verified", "size_bytes"}
        result = {key: raw[key] for key in allowed if key in raw and isinstance(raw[key], (str, int, bool, type(None)))}
        now = datetime.now(UTC)
        for key in ("last_backup_at", "last_restore_at"):
            if result.get(key):
                stamp = _utc_stamp(result[key])
                result[key.replace("last_", "").replace("_at", "_age_seconds")] = max(0, int((now - stamp).total_seconds()))
        result["status"] = "reported"
        return redact(result)
    except (OSError, ValueError, TypeError, AttributeError):
        return {"status": "unavailable", "verified": False}
