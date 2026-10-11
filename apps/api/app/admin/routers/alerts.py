from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Alert, AlertDeliveryJob, User
from ..audit import add_audit_event
from ..deps import AdminPrincipal, require_confirmation, require_permission, require_recent_reauthentication
from ..permissions import AdminPermissionKey
from ..redaction import redact
from ..schemas import UserStateUpdate

router = APIRouter(prefix="/alerts", tags=["admin-alerts"])


@router.get("")
def list_alerts(user_id: int | None = Query(default=None, ge=1), active: bool | None = None, instrument_id: str = Query(default="", max_length=64), limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ALERTS_READ)), db: Session = Depends(get_db)) -> dict:
    statement = select(Alert, User.username).join(User, User.id == Alert.user_id)
    if user_id is not None:
        statement = statement.where(Alert.user_id == user_id)
    if active is not None:
        statement = statement.where(Alert.is_active == active)
    if instrument_id:
        statement = statement.where(Alert.instrument_id == instrument_id)
    total = int(db.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = db.execute(statement.order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(limit)).all()
    fields = ("id", "user_id", "asset", "instrument_id", "target_price", "alert_type", "formula", "currency_mode", "price_source_mode", "condition", "mode", "cooldown_seconds", "max_notifications_per_day", "notify_app", "notify_email", "notify_webhook", "notify_sms", "notify_telegram", "enable_dlq", "is_active", "triggered_at", "created_at", "notifications_today", "next_eligible_trigger_at")
    return {"items": [redact({**{key: getattr(alert, key) for key in fields}, "username": username}) for alert, username in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{alert_id}")
def alert_detail(alert_id: int, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ALERTS_READ)), db: Session = Depends(get_db)) -> dict:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    jobs = db.scalars(select(AlertDeliveryJob).where(AlertDeliveryJob.alert_id == alert_id).order_by(AlertDeliveryJob.created_at.desc()).limit(100)).all()
    return {"alert_id": alert_id, "user_id": alert.user_id, "delivery_jobs": [redact({"id": job.id, "channel": job.channel, "status": job.status, "attempt_count": job.attempt_count, "last_error": job.last_error, "provider_response_summary": job.provider_response_summary, "created_at": job.created_at, "delivered_at": job.delivered_at}) for job in jobs]}


@router.patch("/{alert_id}/state")
def alert_state(alert_id: int, payload: UserStateUpdate, request: Request, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ALERTS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"{'ENABLE' if payload.is_active else 'DISABLE'} ALERT {alert_id}")
    alert = db.scalar(select(Alert).where(Alert.id == alert_id).with_for_update())
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    before = {"is_active": alert.is_active}
    alert.is_active = payload.is_active
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.alert.state_changed", resource_type="alert", resource_id=alert_id, before=before, after={"is_active": alert.is_active, "reason": payload.reason})
    db.commit()
    return {"alert_id": alert_id, "is_active": alert.is_active}
