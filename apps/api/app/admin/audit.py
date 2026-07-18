from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AdminAuditLog
from .network import admin_client_ip
from .redaction import redact, sanitize_error


def add_audit_event(
    db: Session,
    request: Request,
    *,
    actor_admin_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    before: Any = None,
    after: Any = None,
    result: str = "success",
    detail: str | None = None,
) -> AdminAuditLog:
    request_id = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
    event = AdminAuditLog(
        actor_admin_id=actor_admin_id,
        action=action[:120],
        resource_type=resource_type[:80],
        resource_id=str(resource_id)[:160] if resource_id is not None else None,
        before_data=redact(before, mask_personal=True),
        after_data=redact(after, mask_personal=True),
        ip_address=admin_client_ip(request)[:64],
        user_agent=request.headers.get("user-agent", "unknown")[:512],
        request_id=str(request_id or uuid.uuid4().hex)[:80],
        result=result[:32],
        detail=sanitize_error(detail),
    )
    db.add(event)
    return event
