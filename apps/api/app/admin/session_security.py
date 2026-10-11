from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import AdminRole, AdminSession, AdminUserRole, UserSecurityProfile


def user_has_admin_role(db: Session, user_id: int) -> bool:
    return db.scalar(
        select(AdminUserRole.id).join(AdminRole, AdminRole.id == AdminUserRole.role_id)
        .where(AdminUserRole.user_id == user_id, AdminUserRole.is_active.is_(True), AdminRole.is_active.is_(True))
        .limit(1)
    ) is not None


def revoke_admin_sessions(
    db: Session, user_id: int, reason: str = "password_changed", *,
    now: datetime | None = None, exclude_session_id: str | None = None,
) -> int:
    """Revoke administrator credentials in the caller's password transaction."""
    cutoff = now or datetime.now(UTC)
    statement = update(AdminSession).where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
    if exclude_session_id:
        statement = statement.where(AdminSession.id != exclude_session_id)
    result = db.execute(statement.values(revoked_at=cutoff, revoke_reason=reason))
    profile = db.get(UserSecurityProfile, user_id)
    if profile is not None:
        profile.sessions_revoked_before = cutoff
        if reason in {"password_changed", "password_reset"}:
            profile.password_changed_at = cutoff
            profile.must_change_password = False
    return int(result.rowcount or 0)
