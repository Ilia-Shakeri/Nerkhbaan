from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import UserSecurityProfile


def get_or_create_user_security_profile(db: Session, user_id: int) -> UserSecurityProfile:
    profile = db.get(UserSecurityProfile, user_id)
    if profile is None:
        profile = UserSecurityProfile(user_id=user_id, is_active=True)
        db.add(profile)
        db.flush()
    return profile


def enforce_user_security_state(
    db: Session,
    user_id: int,
    *,
    session_created_at: datetime | None = None,
) -> UserSecurityProfile:
    profile = get_or_create_user_security_profile(db, user_id)
    if not profile.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    now = datetime.now(UTC)
    if profile.locked_until:
        locked_until = (
            profile.locked_until
            if profile.locked_until.tzinfo
            else profile.locked_until.replace(tzinfo=UTC)
        )
        if locked_until > now:
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked")
    if profile.sessions_revoked_before and session_created_at:
        revoked_before = (
            profile.sessions_revoked_before
            if profile.sessions_revoked_before.tzinfo
            else profile.sessions_revoked_before.replace(tzinfo=UTC)
        )
        created_at = (
            session_created_at
            if session_created_at.tzinfo
            else session_created_at.replace(tzinfo=UTC)
        )
        if created_at <= revoked_before:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")
    return profile
