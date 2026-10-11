from __future__ import annotations

from datetime import UTC, datetime, timedelta
import base64
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...db import get_db
from ...config import settings
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
from ..models import AdminMfaProfile, AdminRole, AdminSession, AdminUserRole, UserSecurityProfile
from ..mfa import encrypt_secret, new_backup_codes, verify_mfa
from ..session_security import revoke_admin_sessions
from ..network import admin_client_ip, enforce_admin_network
from ..schemas import (
    AdminPasswordChangeRequest,
    AdminReauthenticationRequest,
    AdminSigninRequest,
    AdminMfaVerification,
)

router = APIRouter(prefix="/auth", tags=["admin-auth"])

LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_DUMMY_PASSWORD_HASH = "$2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW"


def _profile_payload(principal: AdminPrincipal, db: Session) -> dict:
    mfa = db.get(AdminMfaProfile, principal.user.id)
    return {
        "id": principal.user.id,
        "username": principal.user.username,
        "full_name": principal.user.full_name,
        "email": principal.user.email,
        "roles": sorted(principal.roles),
        "permissions": sorted(principal.permissions),
        "must_change_password": principal.security.must_change_password,
        "session_expires_at": principal.session.expires_at.isoformat(),
        "mfa_enabled": bool(mfa and mfa.totp_enabled),
        "mfa_required": bool(getattr(settings, "admin_mfa_required", False)),
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
    ip_limit = rate_limit_hit("admin-signin-ip", admin_client_ip(request), 30, 60)
    if ip_limit.count > 30:
        raise HTTPException(status_code=429, detail="Sign-in rate exceeded", headers={"Retry-After": str(ip_limit.retry_after)})
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

    identifier = payload.identifier.strip().lower()
    user = db.scalar(
        select(User).where(
            (User.email == identifier) | (User.username == identifier)
        ).with_for_update().execution_options(populate_existing=True)
    )
    account_identity = str(user.id) if user is not None else identifier
    account_limit = rate_limit_status("admin-signin-account", account_identity, admin_config.login_failure_limit, LOGIN_FAILURE_WINDOW_SECONDS)
    if account_limit.count >= admin_config.login_failure_limit:
        raise HTTPException(status_code=429, detail="Administrator sign-in temporarily locked", headers={"Retry-After": str(account_limit.retry_after)})
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    security_profile = db.get(UserSecurityProfile, user.id) if user is not None else None
    now = datetime.now(UTC)
    active_role = (
        db.scalar(
            select(AdminUserRole.id).join(AdminRole, AdminRole.id == AdminUserRole.role_id).where(
                AdminUserRole.user_id == user.id,
                AdminUserRole.is_active.is_(True),
                AdminRole.is_active.is_(True),
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
        rate_limit_hit("admin-signin-account", account_identity, admin_config.login_failure_limit, LOGIN_FAILURE_WINDOW_SECONDS)
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

    try:
        verify_mfa(db, user.id, payload.mfa_code)
    except HTTPException:
        rate_limit_hit("admin-signin-failure", login_identity, admin_config.login_failure_limit, LOGIN_FAILURE_WINDOW_SECONDS)
        rate_limit_hit("admin-signin-account", account_identity, admin_config.login_failure_limit, LOGIN_FAILURE_WINDOW_SECONDS)
        db.rollback()
        raise
    rate_limit_clear("admin-signin-failure", login_identity)
    rate_limit_clear("admin-signin-account", account_identity)
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
    return {"admin": _profile_payload(principal, db), "csrf_token": csrf_token}


@router.get("/me")
def me(principal: AdminPrincipal = Depends(get_admin_principal), db: Session = Depends(get_db)) -> dict:
    return {"admin": _profile_payload(principal, db)}


def _sensitive_attempt(principal: AdminPrincipal, request: Request) -> None:
    for bucket, identity, maximum in (("admin-sensitive-account", str(principal.user.id), 10), ("admin-sensitive-ip", admin_client_ip(request), 30)):
        state = rate_limit_hit(bucket, identity, maximum, 300)
        if state.count > maximum:
            raise HTTPException(status_code=429, detail="Sensitive operation temporarily locked", headers={"Retry-After": str(state.retry_after)})


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
    _sensitive_attempt(principal, request)
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
    verify_mfa(db, principal.user.id, payload.mfa_code)
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
    _sensitive_attempt(principal, request)
    db.scalar(select(User).where(User.id == principal.user.id).with_for_update().execution_options(populate_existing=True))
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
    # Preserve only the session that performed this verified change.
    principal.session.created_at = now
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


@router.get("/mfa")
def mfa_status(principal: AdminPrincipal = Depends(get_admin_principal), db: Session = Depends(get_db)) -> dict:
    profile = db.get(AdminMfaProfile, principal.user.id)
    return {"enabled": bool(profile and profile.totp_enabled), "pending": bool(profile and profile.encrypted_totp_secret and not profile.totp_enabled), "backup_codes_remaining": len(profile.backup_code_digests or []) if profile else 0}


@router.post("/mfa/enroll")
def mfa_enroll(request: Request, principal: AdminPrincipal = Depends(get_admin_principal), db: Session = Depends(get_db)) -> dict:
    from ..deps import require_recent_reauthentication
    require_recent_reauthentication(principal)
    _sensitive_attempt(principal, request)
    db.scalar(select(User.id).where(User.id == principal.user.id).with_for_update())
    profile = db.scalar(select(AdminMfaProfile).where(AdminMfaProfile.user_id == principal.user.id).with_for_update().execution_options(populate_existing=True))
    if profile and profile.totp_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    if profile is None:
        profile = AdminMfaProfile(user_id=principal.user.id)
        db.add(profile)
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    profile.encrypted_totp_secret = encrypt_secret(secret)
    profile.last_totp_step = None
    profile.backup_code_digests = []
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.mfa.enrollment_started", resource_type="administrator", resource_id=principal.user.id)
    db.commit()
    label = quote(f"Nerkhbaan:{principal.user.email}", safe="")
    return {"secret": secret, "otpauth_uri": f"otpauth://totp/{label}?secret={secret}&issuer=Nerkhbaan&algorithm=SHA1&digits=6&period=30"}


@router.post("/mfa/confirm")
def mfa_confirm(payload: AdminMfaVerification, request: Request, principal: AdminPrincipal = Depends(get_admin_principal), db: Session = Depends(get_db)) -> dict:
    from ..deps import require_recent_reauthentication
    require_recent_reauthentication(principal)
    _sensitive_attempt(principal, request)
    existing = db.get(AdminMfaProfile, principal.user.id)
    if existing and existing.totp_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    profile = verify_mfa(db, principal.user.id, payload.code, enrollment=True)
    codes, digests = new_backup_codes()
    profile.totp_enabled = True
    profile.backup_code_digests = digests
    revoke_admin_sessions(db, principal.user.id, "mfa_enabled", exclude_session_id=principal.session.id)
    principal.session.created_at = datetime.now(UTC)
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.mfa.enabled", resource_type="administrator", resource_id=principal.user.id)
    db.commit()
    return {"enabled": True, "backup_codes": codes}


@router.post("/mfa/disable")
def mfa_disable(payload: AdminMfaVerification, request: Request, principal: AdminPrincipal = Depends(get_admin_principal), db: Session = Depends(get_db)) -> dict:
    from ..deps import require_recent_reauthentication
    require_recent_reauthentication(principal)
    _sensitive_attempt(principal, request)
    if getattr(settings, "admin_mfa_required", False):
        raise HTTPException(status_code=409, detail="MFA is required by deployment policy")
    profile = verify_mfa(db, principal.user.id, payload.code)
    if profile is None or not profile.totp_enabled:
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    profile.totp_enabled = False
    profile.encrypted_totp_secret = None
    profile.backup_code_digests = []
    profile.last_totp_step = None
    revoke_admin_sessions(db, principal.user.id, "mfa_disabled", exclude_session_id=principal.session.id)
    principal.session.created_at = datetime.now(UTC)
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.mfa.disabled", resource_type="administrator", resource_id=principal.user.id)
    db.commit()
    return {"enabled": False}


@router.post("/mfa/recovery-codes")
def mfa_recovery_codes(payload: AdminMfaVerification, request: Request, principal: AdminPrincipal = Depends(get_admin_principal), db: Session = Depends(get_db)) -> dict:
    from ..deps import require_recent_reauthentication
    require_recent_reauthentication(principal)
    _sensitive_attempt(principal, request)
    profile = verify_mfa(db, principal.user.id, payload.code)
    if profile is None or not profile.totp_enabled:
        raise HTTPException(status_code=409, detail="Enable MFA first")
    codes, digests = new_backup_codes()
    profile.backup_code_digests = digests
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.mfa.recovery_codes_rotated", resource_type="administrator", resource_id=principal.user.id)
    db.commit()
    return {"backup_codes": codes}


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
