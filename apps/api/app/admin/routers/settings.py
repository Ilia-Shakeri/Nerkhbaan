from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ..audit import add_audit_event
from ..config import get_admin_config
from ..deps import (
    AdminPrincipal,
    require_confirmation,
    require_permission,
    require_recent_reauthentication,
)
from ..models import AdminFeatureFlag, OperationalSetting
from ..permissions import AdminPermissionKey
from ..redaction import redact
from ..schemas import (
    FeatureFlagUpdate,
    OperationalSettingKey,
    OperationalSettingUpdate,
)

router = APIRouter(prefix="/settings", tags=["admin-settings"])

_FEATURE_FLAGS = {
    "comparison_visible": (True, "Show provider comparison to eligible users"),
    "derived_fallback_enabled": (False, "Allow policy-controlled derived fallback"),
    "backfill_enabled": (True, "Allow distributed history backfill jobs"),
    "admin_frontend_enabled": (True, "Admin frontend runtime visibility flag"),
}
_SETTING_DESCRIPTIONS = {
    OperationalSettingKey.COMPARISON_VISIBLE: "Instrument source comparison visibility",
    OperationalSettingKey.DERIVED_FALLBACK_ENABLED: "Derived canonical fallback policy",
    OperationalSettingKey.BACKFILL_ENABLED: "History backfill worker policy",
    OperationalSettingKey.TELEGRAM_SOURCE_ENABLED: "Telegram ingestion source policy",
    OperationalSettingKey.ANOMALY_THRESHOLD_PERCENT: "Instrument anomaly threshold override",
    OperationalSettingKey.CANONICAL_EXPIRY_SECONDS: "Instrument canonical expiry override",
    OperationalSettingKey.PROVIDER_BUDGET_PER_HOUR: "Provider hourly request budget override",
}
_DANGEROUS_SETTINGS = {
    OperationalSettingKey.ANOMALY_THRESHOLD_PERCENT,
    OperationalSettingKey.CANONICAL_EXPIRY_SECONDS,
    OperationalSettingKey.PROVIDER_BUDGET_PER_HOUR,
}


@router.get("")
def list_settings(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    stored_flags = {flag.key: flag for flag in db.scalars(select(AdminFeatureFlag)).all()}
    flags = []
    for key, (default, description) in _FEATURE_FLAGS.items():
        flag = stored_flags.get(key)
        flags.append(
            {
                "key": key,
                "enabled": flag.enabled if flag else default,
                "description": flag.description if flag and flag.description else description,
                "updated_by": flag.updated_by if flag else None,
                "updated_at": flag.updated_at.isoformat() if flag else None,
                "environment_authoritative": key == "admin_frontend_enabled",
            }
        )
    settings_rows = db.scalars(
        select(OperationalSetting)
        .where(OperationalSetting.is_sensitive.is_(False))
        .order_by(OperationalSetting.key, OperationalSetting.scope_id)
    ).all()
    return {
        "feature_flags": flags,
        "operational_settings": [
            redact(
                {
                    "key": row.key,
                    "scope_id": row.scope_id,
                    "value": row.value,
                    "description": row.description,
                    "version": row.version,
                    "updated_by": row.updated_by,
                    "updated_at": row.updated_at,
                }
            )
            for row in settings_rows
        ],
        "environment": {
            "admin_frontend_enabled": get_admin_config().frontend_enabled,
            "ip_allowlist_configured": bool(get_admin_config().ip_allowlist),
            "session_duration_minutes": get_admin_config().session_duration_minutes,
        },
    }


@router.patch("/feature-flags/{flag_key}")
def update_feature_flag(
    flag_key: str,
    payload: FeatureFlagUpdate,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    if flag_key not in _FEATURE_FLAGS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")
    if flag_key == "admin_frontend_enabled" and not payload.enabled:
        require_recent_reauthentication(principal)
        require_confirmation(payload.confirmation, "DISABLE ADMIN FRONTEND")
    default, description = _FEATURE_FLAGS[flag_key]
    flag = db.get(AdminFeatureFlag, flag_key)
    before = {"enabled": flag.enabled if flag else default}
    if flag is None:
        flag = AdminFeatureFlag(
            key=flag_key,
            enabled=payload.enabled,
            description=description,
            updated_by=principal.user.id,
        )
        db.add(flag)
    else:
        flag.enabled = payload.enabled
        flag.updated_by = principal.user.id
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.settings.feature_flag_updated",
        resource_type="feature_flag",
        resource_id=flag_key,
        before=before,
        after={"enabled": payload.enabled},
    )
    db.commit()
    return {"key": flag_key, "enabled": flag.enabled}


@router.put("/operational")
def update_operational_setting(
    payload: OperationalSettingUpdate,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    if payload.key in _DANGEROUS_SETTINGS:
        require_recent_reauthentication(principal)
        require_confirmation(
            payload.confirmation,
            f"CHANGE SETTING {payload.key.value}:{payload.scope_id}",
        )
    setting = db.scalar(
        select(OperationalSetting).where(
            OperationalSetting.key == payload.key.value,
            OperationalSetting.scope_id == payload.scope_id,
        )
    )
    before = {"value": setting.value, "version": setting.version} if setting else None
    if setting is None:
        setting = OperationalSetting(
            key=payload.key.value,
            scope_id=payload.scope_id,
            value=payload.value,
            description=_SETTING_DESCRIPTIONS[payload.key],
            is_sensitive=False,
            updated_by=principal.user.id,
        )
        db.add(setting)
    else:
        setting.value = payload.value
        setting.version += 1
        setting.updated_by = principal.user.id
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.settings.operational_updated",
        resource_type="operational_setting",
        resource_id=f"{payload.key.value}:{payload.scope_id}",
        before=before,
        after={"value": payload.value, "version": setting.version},
    )
    db.commit()
    return {
        "key": setting.key,
        "scope_id": setting.scope_id,
        "value": setting.value,
        "version": setting.version,
    }
