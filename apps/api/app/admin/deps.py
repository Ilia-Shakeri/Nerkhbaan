from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .config import get_admin_config
from .models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminSession,
    AdminUserRole,
    UserSecurityProfile,
)
from .network import admin_client_ip, enforce_admin_network
from .permissions import AdminPermissionKey


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def user_agent_digest(request: Request) -> str:
    return token_digest(request.headers.get("user-agent", "unknown")[:1024])


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class AdminPrincipal:
    user: User
    security: UserSecurityProfile
    session: AdminSession
    roles: frozenset[str]
    permissions: frozenset[str]


def admin_roles_and_permissions(db: Session, user_id: int) -> tuple[frozenset[str], frozenset[str]]:
    roles = frozenset(
        db.scalars(
            select(AdminRole.name)
            .join(AdminUserRole, AdminUserRole.role_id == AdminRole.id)
            .where(
                AdminUserRole.user_id == user_id,
                AdminUserRole.is_active.is_(True),
                AdminRole.is_active.is_(True),
            )
        ).all()
    )
    permissions = frozenset(
        db.scalars(
            select(AdminPermission.key)
            .join(
                AdminRolePermission,
                AdminRolePermission.permission_id == AdminPermission.id,
            )
            .join(AdminRole, AdminRole.id == AdminRolePermission.role_id)
            .join(AdminUserRole, AdminUserRole.role_id == AdminRole.id)
            .where(
                AdminUserRole.user_id == user_id,
                AdminUserRole.is_active.is_(True),
                AdminRole.is_active.is_(True),
            )
            .distinct()
        ).all()
    )
    return roles, permissions


def new_admin_session(
    db: Session,
    user: User,
    request: Request,
) -> tuple[AdminSession, str, str]:
    config = get_admin_config()
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    session = AdminSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=token_digest(raw_token),
        csrf_token_hash=token_digest(csrf_token),
        ip_address=admin_client_ip(request),
        user_agent_hash=user_agent_digest(request),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(minutes=config.session_duration_minutes),
    )
    db.add(session)
    return session, raw_token, csrf_token


def set_admin_session_cookie(response: Response, raw_token: str) -> None:
    config = get_admin_config()
    response.set_cookie(
        key=config.cookie_name,
        value=raw_token,
        max_age=config.session_duration_minutes * 60,
        httponly=True,
        secure=config.cookie_secure,
        samesite=config.cookie_samesite,
        domain=config.cookie_domain,
        path="/api/admin",
    )


def delete_admin_session_cookie(response: Response) -> None:
    config = get_admin_config()
    response.delete_cookie(
        key=config.cookie_name,
        httponly=True,
        secure=config.cookie_secure,
        samesite=config.cookie_samesite,
        domain=config.cookie_domain,
        path="/api/admin",
    )


def rotate_csrf_token(session: AdminSession) -> str:
    raw = secrets.token_urlsafe(32)
    session.csrf_token_hash = token_digest(raw)
    return raw


def _enforce_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    configured = get_admin_config().frontend_origin
    if origin and origin.rstrip("/") != configured:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin origin denied")


def _enforce_csrf(request: Request, session: AdminSession) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    csrf = request.headers.get("x-csrf-token", "")
    if not csrf or not secrets.compare_digest(token_digest(csrf), session.csrf_token_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin request check failed")


def get_admin_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> AdminPrincipal:
    enforce_admin_network(request)
    _enforce_origin(request)
    config = get_admin_config()
    raw_token = request.cookies.get(config.cookie_name, "")
    if not raw_token or len(raw_token) > 512:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session required")
    session = db.scalar(select(AdminSession).where(AdminSession.token_hash == token_digest(raw_token)))
    now = datetime.now(UTC)
    if (
        session is None
        or session.revoked_at is not None
        or _as_utc(session.expires_at) <= now
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")
    if config.bind_ip and session.ip_address != admin_client_ip(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session binding changed")
    if config.bind_user_agent and not secrets.compare_digest(
        session.user_agent_hash, user_agent_digest(request)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session binding changed")
    _enforce_csrf(request, session)

    user = db.get(User, session.user_id)
    security = db.get(UserSecurityProfile, session.user_id)
    if user is None or security is None or not user.is_active or not security.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin account disabled")
    if security.locked_until and _as_utc(security.locked_until) > now:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Admin account temporarily locked")
    roles, permissions = admin_roles_and_permissions(db, user.id)
    if not roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access not assigned")
    if _as_utc(session.last_seen_at) < now - timedelta(minutes=1):
        session.last_seen_at = now
        db.commit()
    return AdminPrincipal(
        user=user,
        security=security,
        session=session,
        roles=roles,
        permissions=permissions,
    )


def require_permission(
    permission: AdminPermissionKey,
) -> Callable[[AdminPrincipal], AdminPrincipal]:
    def dependency(
        principal: AdminPrincipal = Depends(get_admin_principal),
    ) -> AdminPrincipal:
        if principal.security.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin password change required",
            )
        if permission.value not in principal.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission denied")
        return principal

    return dependency


def require_recent_reauthentication(principal: AdminPrincipal) -> None:
    reauthenticated_at = principal.session.reauthenticated_at
    if reauthenticated_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin re-authentication required")
    cutoff = datetime.now(UTC) - timedelta(minutes=get_admin_config().reauthentication_minutes)
    if _as_utc(reauthenticated_at) < cutoff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin re-authentication expired")


def require_confirmation(actual: str | None, expected: str) -> None:
    if not actual or not secrets.compare_digest(actual.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Typed confirmation does not match", "expected": expected},
        )
