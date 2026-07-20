from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import User, UserSession
from ...security import (
    hash_password,
    rate_limit_clear,
    rate_limit_hit,
    rate_limit_status,
    verify_password,
)
from ..audit import add_audit_event
from ..config import get_admin_config
from ..deps import (
    AdminPrincipal,
    admin_roles_and_permissions,
    delete_admin_session_cookie,
    get_admin_principal,
    new_admin_session,
    rotate_csrf_token,
    set_admin_session_cookie,
)
from ..models import AdminSession, AdminUserRole, UserSecurityProfile
from ..network import admin_client_ip, enforce_admin_network
from ..schemas import (
    AdminPasswordChangeRequest,
    AdminReauthenticationRequest,
    AdminSigninRequest,
)

router = APIRouter(prefix="/auth", tags=["admin-auth"])

LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_DUMMY_PASSWORD_HASH = "$2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW"


def _profile_payload(principal: AdminPrincipal) -> dict:
    return {
        "id": principal.user.id,
        "username": principal.user.username,
        "full_name": principal.user.full_name,
        "email": principal.user.email,
        "roles": sorted(principal.roles),
        "permissions": sorted(principal.permissions),
        "must_change_password": principal.security.must_change_password,
        "session_expires_at": principal.session.expires_at.isoformat(),
    }


def _raise_login_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid administrator credentials",
    )


@router.post("/signin")
def signin(
    payload: AdminSigninRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    enforce_admin_network(request)
    admin_config = get_admin_config()
    login_identity = f"{admin_client_ip(request)}:{payload.identifier}"
    limit = rate_limit_status(
        "admin-signin-failure",
        login_identity,
        admin_config.login_failure_limit,
        LOGIN_FAILURE_WINDOW_SECONDS,
    )
    if limit.count >= admin_config.login_failure_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Administrator sign-in temporarily locked",
            headers={"Retry-After": str(limit.retry_after)},
        )

    user = db.scalar(
        select(User).where(
            (User.email == payload.identifier) | (User.username == payload.identifier)
        )
    )
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    security_profile = db.get(UserSecurityProfile, user.id) if user is not None else None
    now = datetime.now(UTC)
    active_role = (
        db.scalar(
            select(AdminUserRole.id).where(
                AdminUserRole.user_id == user.id,
                AdminUserRole.is_active.is_(True),
            )
        )
        if user is not None
        else None
    )
    locked = bool(
        security_profile
        and security_profile.locked_until
        and (
            security_profile.locked_until
            if security_profile.locked_until.tzinfo
            else security_profile.locked_until.replace(tzinfo=UTC)
        )
        > now
    )
    if (
        user is None
        or not password_valid
        or security_profile is None
        or not user.is_active
        or not security_profile.is_active
        or active_role is None
        or locked
    ):
        rate_limit_hit(
            "admin-signin-failure",
            login_identity,
            admin_config.login_failure_limit,
            LOGIN_FAILURE_WINDOW_SECONDS,
        )
        if security_profile is not None and not password_valid:
            security_profile.failed_login_count += 1
            if security_profile.failed_login_count >= admin_config.login_failure_limit:
                security_profile.locked_until = now + timedelta(minutes=admin_config.lockout_minutes)
        add_audit_event(
            db,
            request,
            actor_admin_id=user.id if user is not None and active_role is not None else None,
            action="admin.auth.signin",
            resource_type="admin_session",
            resource_id=user.id if user is not None else None,
            result="denied",
            detail="Invalid credentials, inactive account, missing role, or lockout",
        )
        db.commit()
        _raise_login_error()

    rate_limit_clear("admin-signin-failure", login_identity)
    security_profile.failed_login_count = 0
    security_profile.locked_until = None
    security_profile.last_login_at = now
    session, raw_token, csrf_token = new_admin_session(db, user, request)
    add_audit_event(
        db,
        request,
        actor_admin_id=user.id,
        action="admin.auth.signin",
        resource_type="admin_session",
        resource_id=session.id,
        after={"ip": session.ip_address, "expires_at": session.expires_at},
    )
    db.commit()
    roles, permissions = admin_roles_and_permissions(db, user.id)
    principal = AdminPrincipal(
        user=user,
        security=security_profile,
        session=session,
        roles=roles,
        permissions=permissions,
    )
    set_admin_session_cookie(response, raw_token)
    return {"admin": _profile_payload(principal), "csrf_token": csrf_token}


@router.get("/me")
def me(principal: AdminPrincipal = Depends(get_admin_principal)) -> dict:
    return {"admin": _profile_payload(principal)}


@router.get("/csrf")
def refresh_csrf(
    principal: AdminPrincipal = Depends(get_admin_principal),
    db: Session = Depends(get_db),
) -> dict:
    csrf_token = rotate_csrf_token(principal.session)
    db.commit()
    return {"csrf_token": csrf_token}


@router.post("/reauthenticate")
def reauthenticate(
    payload: AdminReauthenticationRequest,
    request: Request,
    principal: AdminPrincipal = Depends(get_admin_principal),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.password, principal.user.password_hash):
        add_audit_event(
            db,
            request,
            actor_admin_id=principal.user.id,
            action="admin.auth.reauthenticate",
            resource_type="admin_session",
            resource_id=principal.session.id,
            result="denied",
            detail="Password verification failed",
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Password is incorrect")
    principal.session.reauthenticated_at = datetime.now(UTC)
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.auth.reauthenticate",
        resource_type="admin_session",
        resource_id=principal.session.id,
    )
    db.commit()
    return {"reauthenticated": True, "reauthenticated_at": principal.session.reauthenticated_at}


@router.post("/change-password")
def change_password(
    payload: AdminPasswordChangeRequest,
    request: Request,
    principal: AdminPrincipal = Depends(get_admin_principal),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.current_password, principal.user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if verify_password(payload.new_password, principal.user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must differ")
    now = datetime.now(UTC)
    principal.user.password_hash = hash_password(payload.new_password)
    principal.user.must_change_password = False
    principal.user.password_changed_at = now
    principal.user.security_version += 1
    principal.security.must_change_password = False
    principal.security.password_changed_at = now
    principal.security.sessions_revoked_before = now
    db.execute(
        update(AdminSession)
        .where(
            AdminSession.user_id == principal.user.id,
            AdminSession.id != principal.session.id,
            AdminSession.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason="password_changed")
    )
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == principal.user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    principal.session.reauthenticated_at = now
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.auth.password_changed",
        resource_type="user",
        resource_id=principal.user.id,
        after={"other_admin_sessions_revoked": True},
    )
    db.commit()
    return {"message": "Administrator password changed"}


@router.post(
    "/signout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def signout(
    request: Request,
    response: Response,
    principal: AdminPrincipal = Depends(get_admin_principal),
    db: Session = Depends(get_db),
) -> Response:
    principal.session.revoked_at = datetime.now(UTC)
    principal.session.revoke_reason = "signout"
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.auth.signout",
        resource_type="admin_session",
        resource_id=principal.session.id,
    )
    db.commit()
    delete_admin_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
