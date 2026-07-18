from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import User, UserSession
from ..audit import add_audit_event
from ..deps import (
    AdminPrincipal,
    require_confirmation,
    require_permission,
    require_recent_reauthentication,
)
from ..models import (
    AdminAuditLog,
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminSession,
    AdminUserRole,
    UserSecurityProfile,
)
from ..permissions import AdminPermissionKey
from ..redaction import redact
from ..schemas import AdminRoleAssignmentRequest, DangerousConfirmation, UserStateUpdate

router = APIRouter(tags=["admin-access"])


def _security_profile(db: Session, user_id: int) -> UserSecurityProfile:
    profile = db.get(UserSecurityProfile, user_id)
    if profile is None:
        profile = UserSecurityProfile(user_id=user_id, is_active=True)
        db.add(profile)
        db.flush()
    return profile


def _active_super_admin_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(func.distinct(AdminUserRole.user_id)))
            .join(AdminRole, AdminRole.id == AdminUserRole.role_id)
            .join(UserSecurityProfile, UserSecurityProfile.user_id == AdminUserRole.user_id)
            .join(User, User.id == AdminUserRole.user_id)
            .where(
                AdminRole.name == "super_admin",
                AdminRole.is_active.is_(True),
                AdminUserRole.is_active.is_(True),
                UserSecurityProfile.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        or 0
    )


def _target_is_active_super_admin(db: Session, user_id: int) -> bool:
    return (
        db.scalar(
            select(AdminUserRole.id)
            .join(AdminRole, AdminRole.id == AdminUserRole.role_id)
            .where(
                AdminUserRole.user_id == user_id,
                AdminUserRole.is_active.is_(True),
                AdminRole.name == "super_admin",
                AdminRole.is_active.is_(True),
            )
        )
        is not None
    )


def _user_payload(user: User, profile: UserSecurityProfile | None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
        "is_active": user.is_active and (profile.is_active if profile else True),
        "must_change_password": user.must_change_password or (profile.must_change_password if profile else False),
        "locked_until": profile.locked_until.isoformat() if profile and profile.locked_until else None,
        "last_login_at": profile.last_login_at.isoformat() if profile and profile.last_login_at else None,
    }


@router.get("/users")
def list_users(
    search: str = Query(default="", max_length=120),
    active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.USERS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(User, UserSecurityProfile).outerjoin(
        UserSecurityProfile, UserSecurityProfile.user_id == User.id
    )
    count_statement = select(func.count(User.id)).outerjoin(
        UserSecurityProfile, UserSecurityProfile.user_id == User.id
    )
    clean_search = search.strip()
    if clean_search:
        pattern = f"%{clean_search}%"
        condition = or_(
            User.username.ilike(pattern),
            User.full_name.ilike(pattern),
            User.email.ilike(pattern),
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    if active is not None:
        condition = (
            or_(UserSecurityProfile.is_active.is_(True), UserSecurityProfile.user_id.is_(None))
            if active
            else UserSecurityProfile.is_active.is_(False)
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    rows = db.execute(statement.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "items": [_user_payload(user, profile) for user, profile in rows],
        "total": int(db.scalar(count_statement) or 0),
        "limit": limit,
        "offset": offset,
    }


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.USERS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    profile = db.get(UserSecurityProfile, user_id)
    events = db.scalars(
        select(AdminAuditLog)
        .where(
            (AdminAuditLog.resource_type == "user") & (AdminAuditLog.resource_id == str(user_id))
            | (AdminAuditLog.actor_admin_id == user_id)
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(30)
    ).all()
    sessions = db.scalars(
        select(AdminSession)
        .where(AdminSession.user_id == user_id)
        .order_by(AdminSession.created_at.desc())
        .limit(20)
    ).all()
    user_sessions = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .order_by(UserSession.created_at.desc())
        .limit(20)
    ).all()
    return {
        "user": _user_payload(user, profile),
        "security_history": [
            {
                "action": event.action,
                "result": event.result,
                "created_at": event.created_at.isoformat(),
                "ip_address": event.ip_address,
            }
            for event in events
        ],
        "admin_sessions": [
            {
                "id": session.id,
                "created_at": session.created_at.isoformat(),
                "last_seen_at": session.last_seen_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
                "ip_address": session.ip_address,
            }
            for session in sessions
        ],
        "user_sessions": [
            {
                "id": session.id,
                "created_at": session.created_at.isoformat(),
                "last_used_at": session.last_used_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
            }
            for session in user_sessions
        ],
    }


@router.patch("/users/{user_id}/state")
def set_user_state(
    user_id: int,
    payload: UserStateUpdate,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    action_word = "ENABLE" if payload.is_active else "DISABLE"
    require_confirmation(payload.confirmation, f"{action_word} USER {user_id}")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    profile = _security_profile(db, user_id)
    if not payload.is_active and _target_is_active_super_admin(db, user_id) and _active_super_admin_count(db) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Last active super administrator is protected")
    before = {"is_active": profile.is_active, "disabled_reason": profile.disabled_reason}
    profile.is_active = payload.is_active
    user.is_active = payload.is_active
    user.disabled_at = None if payload.is_active else datetime.now(UTC)
    profile.disabled_reason = None if payload.is_active else payload.reason
    if not payload.is_active:
        now = datetime.now(UTC)
        profile.sessions_revoked_before = now
        user.security_version += 1
        db.execute(
            update(AdminSession)
            .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="account_disabled")
        )
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.user.state_changed",
        resource_type="user",
        resource_id=user_id,
        before=before,
        after={"is_active": profile.is_active, "disabled_reason": profile.disabled_reason},
    )
    db.commit()
    return {"user": _user_payload(user, profile)}


@router.post("/users/{user_id}/force-password-change")
def force_password_change(
    user_id: int,
    payload: DangerousConfirmation,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"FORCE PASSWORD CHANGE {user_id}")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    profile = _security_profile(db, user_id)
    now = datetime.now(UTC)
    profile.must_change_password = True
    profile.sessions_revoked_before = now
    user.must_change_password = True
    user.security_version += 1
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.execute(
        update(AdminSession)
        .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="password_change_forced")
    )
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.user.password_change_forced",
        resource_type="user",
        resource_id=user_id,
        after={"must_change_password": True, "sessions_revoked": True},
    )
    db.commit()
    return {"must_change_password": True}


@router.post("/users/{user_id}/sessions/close")
def close_user_sessions(
    user_id: int,
    payload: DangerousConfirmation,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SESSIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"CLOSE USER SESSIONS {user_id}")
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    now = datetime.now(UTC)
    profile = _security_profile(db, user_id)
    profile.sessions_revoked_before = now
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    admin_result = db.execute(
        update(AdminSession)
        .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="forced_session_close")
    )
    user = db.get(User, user_id)
    if user:
        user.security_version += 1
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.user.sessions_closed",
        resource_type="user",
        resource_id=user_id,
        after={
            "user_session_count": result.rowcount,
            "admin_session_count": admin_result.rowcount,
            "revoked_before": now,
        },
    )
    db.commit()
    return {
        "closed_user_sessions": result.rowcount,
        "closed_admin_sessions": admin_result.rowcount,
        "sessions_revoked_before": now,
    }


@router.get("/roles")
def list_roles(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ROLES_READ)),
    db: Session = Depends(get_db),
) -> dict:
    roles = db.scalars(select(AdminRole).order_by(AdminRole.name)).all()
    items = []
    for role in roles:
        permissions = db.scalars(
            select(AdminPermission.key)
            .join(AdminRolePermission, AdminRolePermission.permission_id == AdminPermission.id)
            .where(AdminRolePermission.role_id == role.id)
            .order_by(AdminPermission.key)
        ).all()
        items.append(
            {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "is_system": role.is_system,
                "is_active": role.is_active,
                "permissions": permissions,
            }
        )
    return {"items": items}


@router.get("/permissions")
def list_permissions(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ROLES_READ)),
    db: Session = Depends(get_db),
) -> dict:
    values = db.scalars(select(AdminPermission).order_by(AdminPermission.key)).all()
    return {"items": [{"key": item.key, "description": item.description} for item in values]}


@router.get("/administrators")
def list_administrators(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ROLES_READ)),
    db: Session = Depends(get_db),
) -> dict:
    user_ids = db.scalars(
        select(AdminUserRole.user_id).where(AdminUserRole.is_active.is_(True)).distinct()
    ).all()
    items = []
    for user_id in user_ids:
        user = db.get(User, user_id)
        if user is None:
            continue
        profile = db.get(UserSecurityProfile, user_id)
        roles = db.scalars(
            select(AdminRole.name)
            .join(AdminUserRole, AdminUserRole.role_id == AdminRole.id)
            .where(AdminUserRole.user_id == user_id, AdminUserRole.is_active.is_(True))
            .order_by(AdminRole.name)
        ).all()
        items.append({**_user_payload(user, profile), "roles": roles})
    return {"items": items}


@router.put("/administrators/{user_id}/roles")
def assign_admin_roles(
    user_id: int,
    payload: AdminRoleAssignmentRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ROLES_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"SET ADMIN ROLES {user_id}")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role_rows = db.scalars(select(AdminRole).where(AdminRole.name.in_(payload.roles))).all()
    if len(role_rows) != len(payload.roles):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown administrator role")
    previous = db.scalars(
        select(AdminRole.name)
        .join(AdminUserRole, AdminUserRole.role_id == AdminRole.id)
        .where(AdminUserRole.user_id == user_id, AdminUserRole.is_active.is_(True))
    ).all()
    if (
        "super_admin" in previous
        and "super_admin" not in payload.roles
        and _active_super_admin_count(db) <= 1
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Last active super administrator is protected")
    wanted_ids = {role.id for role in role_rows}
    assignments = db.scalars(select(AdminUserRole).where(AdminUserRole.user_id == user_id)).all()
    by_role = {assignment.role_id: assignment for assignment in assignments}
    now = datetime.now(UTC)
    for assignment in assignments:
        assignment.is_active = assignment.role_id in wanted_ids
        assignment.disabled_at = None if assignment.is_active else now
    for role in role_rows:
        if role.id not in by_role:
            db.add(
                AdminUserRole(
                    user_id=user_id,
                    role_id=role.id,
                    assigned_by=principal.user.id,
                    is_active=True,
                )
            )
    _security_profile(db, user_id)
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.roles.assigned",
        resource_type="user",
        resource_id=user_id,
        before={"roles": previous},
        after={"roles": payload.roles},
    )
    db.commit()
    return {"user_id": user_id, "roles": payload.roles}


@router.post("/administrators/{user_id}/sessions/close")
def close_admin_sessions(
    user_id: int,
    payload: DangerousConfirmation,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SESSIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"CLOSE ADMIN SESSIONS {user_id}")
    now = datetime.now(UTC)
    result = db.execute(
        update(AdminSession)
        .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason="administrator_forced_close")
    )
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.sessions.closed",
        resource_type="administrator",
        resource_id=user_id,
        after={"closed_count": result.rowcount},
    )
    db.commit()
    return {"closed_sessions": result.rowcount}


@router.get("/audit")
def list_audit_events(
    action: str = Query(default="", max_length=120),
    resource_type: str = Query(default="", max_length=80),
    result: str = Query(default="", max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AdminAuditLog)
    count_statement = select(func.count(AdminAuditLog.id))
    for condition in (
        AdminAuditLog.action == action if action else None,
        AdminAuditLog.resource_type == resource_type if resource_type else None,
        AdminAuditLog.result == result if result else None,
    ):
        if condition is not None:
            statement = statement.where(condition)
            count_statement = count_statement.where(condition)
    events = db.scalars(
        statement.order_by(AdminAuditLog.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {
        "items": [
            redact(
                {
                    "id": event.id,
                    "actor_admin_id": event.actor_admin_id,
                    "action": event.action,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "before": event.before_data,
                    "after": event.after_data,
                    "ip_address": event.ip_address,
                    "request_id": event.request_id,
                    "result": event.result,
                    "detail": event.detail,
                    "created_at": event.created_at,
                },
                mask_personal=True,
            )
            for event in events
        ],
        "total": int(db.scalar(count_statement) or 0),
        "limit": limit,
        "offset": offset,
    }
