from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import User
from ..security import hash_password
from .models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminUserRole,
    UserSecurityProfile,
)
from .permissions import PERMISSION_DESCRIPTIONS, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from .schemas import BootstrapIdentity

logger = logging.getLogger(__name__)


def ensure_admin_catalog(db: Session) -> None:
    permissions: dict[str, AdminPermission] = {
        permission.key: permission for permission in db.scalars(select(AdminPermission)).all()
    }
    for key, description in PERMISSION_DESCRIPTIONS.items():
        permission = permissions.get(key.value)
        if permission is None:
            permission = AdminPermission(key=key.value, description=description)
            db.add(permission)
            permissions[key.value] = permission
        elif not permission.description:
            permission.description = description
    db.flush()

    roles: dict[str, AdminRole] = {role.name: role for role in db.scalars(select(AdminRole)).all()}
    for role_name, required_permissions in ROLE_PERMISSIONS.items():
        role = roles.get(role_name)
        if role is None:
            role = AdminRole(
                name=role_name,
                description=ROLE_DESCRIPTIONS[role_name],
                is_system=True,
                is_active=True,
            )
            db.add(role)
            roles[role_name] = role
        else:
            role.is_system = True
            role.is_active = True
            if not role.description:
                role.description = ROLE_DESCRIPTIONS[role_name]
        db.flush()
        existing_permission_ids = set(
            db.scalars(
                select(AdminRolePermission.permission_id).where(
                    AdminRolePermission.role_id == role.id
                )
            ).all()
        )
        for permission_key in required_permissions:
            permission = permissions[permission_key.value]
            if permission.id not in existing_permission_ids:
                db.add(AdminRolePermission(role_id=role.id, permission_id=permission.id))


def bootstrap_admin_from_environment(db: Session) -> int | None:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 592741831})

    ensure_admin_catalog(db)
    super_admin_role = db.scalar(select(AdminRole).where(AdminRole.name == "super_admin"))
    if super_admin_role is None:
        raise RuntimeError("Admin role catalog could not be initialized")

    super_admin_count = db.scalar(
        select(func.count(AdminUserRole.id)).where(
            AdminUserRole.role_id == super_admin_role.id,
            AdminUserRole.is_active.is_(True),
        )
    )
    if int(super_admin_count or 0) > 0:
        db.commit()
        return None

    environment = {
        "username": "ADMIN_BOOTSTRAP_USERNAME",
        "email": "ADMIN_BOOTSTRAP_EMAIL",
        "password": "ADMIN_BOOTSTRAP_PASSWORD",
        "full_name": "ADMIN_BOOTSTRAP_FULL_NAME",
    }
    raw = {field: os.getenv(variable, "") for field, variable in environment.items()}
    supplied = [bool(str(value).strip()) for value in raw.values()]
    if not any(supplied):
        db.commit()
        return None
    if not all(supplied):
        missing = sorted(
            variable for field, variable in environment.items() if not str(raw[field]).strip()
        )
        raise RuntimeError(
            f"Admin bootstrap identity is incomplete; missing: {', '.join(missing)}"
        )
    try:
        identity = BootstrapIdentity.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError("Admin bootstrap identity does not meet security policy") from exc

    existing = db.scalar(
        select(User).where(
            (User.username == identity.username) | (User.email == str(identity.email).lower())
        )
    )
    if existing is not None:
        raise RuntimeError("Admin bootstrap identity conflicts with an existing account")

    user = User(
        username=identity.username,
        email=str(identity.email).lower(),
        full_name=identity.full_name.strip(),
        password_hash=hash_password(identity.password),
    )
    if hasattr(User, "is_active"):
        user.is_active = True
    if hasattr(User, "must_change_password"):
        user.must_change_password = True
    if hasattr(User, "password_changed_at"):
        user.password_changed_at = datetime.now(UTC)
    db.add(user)
    db.flush()
    db.add(
        UserSecurityProfile(
            user_id=user.id,
            is_active=True,
            must_change_password=True,
        )
    )
    db.add(
        AdminUserRole(
            user_id=user.id,
            role_id=super_admin_role.id,
            assigned_by=None,
            is_active=True,
        )
    )
    db.commit()
    logger.info("Initial super administrator created with forced password change")
    return user.id


def bootstrap_super_admin() -> int | None:
    db = SessionLocal()
    try:
        return bootstrap_admin_from_environment(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    try:
        bootstrap_super_admin()
    except Exception:
        logger.exception("Initial administrator bootstrap failed")
        raise


if __name__ == "__main__":
    main()
