from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import TelegramSource
from ...pricing.instruments import INSTRUMENTS
from ...pricing.registry import PROVIDERS
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
                "enabled": get_admin_config().frontend_enabled if key == "admin_frontend_enabled" else flag.enabled if flag else default,
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
        "allowed_keys": [{"key": key.value, "description": description} for key, description in _SETTING_DESCRIPTIONS.items()],
        "instrument_scopes": list(INSTRUMENTS),
        "provider_scopes": list(PROVIDERS),
        "telegram_scopes": [str(value) for value in db.scalars(select(TelegramSource.id)).all()],
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
    if flag_key == "admin_frontend_enabled":
        raise HTTPException(status_code=409, detail="Admin visibility is controlled by deployment configuration")
    if flag_key == "derived_fallback_enabled" and payload.enabled:
        require_recent_reauthentication(principal)
        require_confirmation(payload.confirmation, "ENABLE DERIVED FALLBACK")
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
    _validate_scope(db, payload)
    _lock_setting(db, payload.key.value, payload.scope_id)
    if payload.key in _DANGEROUS_SETTINGS or (payload.key == OperationalSettingKey.DERIVED_FALLBACK_ENABLED and payload.value is True):
        require_recent_reauthentication(principal)
        require_confirmation(
            payload.confirmation,
            f"CHANGE SETTING {payload.key.value}:{payload.scope_id}",
        )
    setting = db.scalar(
        select(OperationalSetting).where(
            OperationalSetting.key == payload.key.value,
            OperationalSetting.scope_id == payload.scope_id,
        ).with_for_update()
    )
    _check_version(setting, payload.expected_version)
    before = {"value": setting.value, "version": setting.version} if setting else None
    if setting is None:
        setting = OperationalSetting(
            key=payload.key.value,
            scope_id=payload.scope_id,
            value=payload.value,
            version=1,
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


def _lock_setting(db: Session, key: str, scope: str) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('lock_timeout', '5s', true)"))
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": f"setting:{key}:{scope}"})


def _check_version(setting: OperationalSetting | None, expected: int | None) -> None:
    actual = setting.version if setting else 0
    if expected != actual and not (setting is None and expected is None):
        raise HTTPException(status_code=409, detail={"message": "Setting changed; reload before writing", "current_version": actual})


def _validate_scope(db: Session, payload: OperationalSettingUpdate) -> None:
    from ...models import TelegramSource
    from ...pricing.instruments import INSTRUMENTS
    from ...pricing.registry import PROVIDERS
    if payload.scope_id == "global":
        return
    if payload.key == OperationalSettingKey.PROVIDER_BUDGET_PER_HOUR:
        valid = payload.scope_id in PROVIDERS
    elif payload.key == OperationalSettingKey.TELEGRAM_SOURCE_ENABLED:
        valid = db.scalar(select(TelegramSource.id).where((TelegramSource.id == int(payload.scope_id) if payload.scope_id.isdigit() else TelegramSource.channel_id == payload.scope_id))) is not None
    else:
        valid = payload.scope_id in INSTRUMENTS
    if not valid:
        raise HTTPException(status_code=422, detail="Scope is not valid for this setting")


@router.post("/operational/reset")
def reset_operational_setting(payload: OperationalSettingUpdate, request: Request, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    _validate_scope(db, payload)
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"RESET SETTING {payload.key.value}:{payload.scope_id}")
    _lock_setting(db, payload.key.value, payload.scope_id)
    row = db.scalar(select(OperationalSetting).where(OperationalSetting.key == payload.key.value, OperationalSetting.scope_id == payload.scope_id).with_for_update())
    _check_version(row, payload.expected_version)
    if row is not None:
        add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.settings.operational_reset", resource_type="operational_setting", resource_id=f"{row.key}:{row.scope_id}", before={"value": row.value, "version": row.version})
        db.delete(row)
    db.commit()
    return {"reset": True}


@router.get("/effective")
async def effective_settings(scope_id: str = Query(default="global", max_length=160), principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_READ)), db: Session = Depends(get_db)) -> dict:
    from ...pricing.operational import OperationalPricingSettings
    from ...pricing.instruments import INSTRUMENTS
    from ...pricing.registry import PROVIDERS
    policy = OperationalPricingSettings()
    items = []
    defaults = {"comparison_visible": True, "derived_fallback_enabled": False, "backfill_enabled": True, "telegram_source_enabled": True, "anomaly_threshold_percent": None, "canonical_expiry_seconds": None, "provider_budget_requests_per_hour": None}
    if scope_id in INSTRUMENTS:
        instrument = await policy.instrument(scope_id)
        defaults.update(anomaly_threshold_percent=float(instrument.base_anomaly_threshold_percent), canonical_expiry_seconds=instrument.expire_after_seconds)
    if scope_id in PROVIDERS:
        provider = PROVIDERS[scope_id]
        candidates = await policy.providers_for(provider.instrument_id)
        current = next((item for item in candidates if item.provider_id == scope_id), provider)
        defaults["provider_budget_requests_per_hour"] = current.budget.requests_per_hour
    for key, default in defaults.items():
        value = await policy.feature_enabled(key, default, scope_id=scope_id) if type(default) is bool else await policy.value(key, scope_id, default)
        row = db.scalar(select(OperationalSetting).where(OperationalSetting.key == key, OperationalSetting.scope_id == scope_id))
        inherited = db.scalar(select(OperationalSetting).where(OperationalSetting.key == key, OperationalSetting.scope_id == "global")) if scope_id != "global" else None
        items.append({"key": key, "scope_id": scope_id, "effective_value": value, "source": "scoped" if row else "global" if inherited else "catalog_or_feature_default", "version": row.version if row else 0})
    return {"items": items}
