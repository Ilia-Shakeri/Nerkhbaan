from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import TelegramSource
from ...services.pricing_registry import PRICE_REGISTRY
from ..audit import add_audit_event
from ..dbtools import reflected_table, safe_rows
from ..deps import (
    AdminPrincipal,
    require_confirmation,
    require_permission,
    require_recent_reauthentication,
)
from ..models import AdminProviderConfigDraft, OperationalSetting
from ..permissions import AdminPermissionKey
from ..redaction import masked_secret_status, redact
from ..schemas import (
    DangerousConfirmation,
    ProviderDraftRequest,
    TelegramSourceCreate,
    TelegramSourceUpdate,
)

router = APIRouter(tags=["admin-providers"])

_PROVIDER_SAFE_COLUMNS = (
    "id",
    "provider_id",
    "name",
    "display_name",
    "enabled",
    "role",
    "priority",
    "trust_score",
    "minimum_interval_seconds",
    "operational_ttl_seconds",
    "requests_per_minute",
    "requests_per_hour",
    "requests_per_day",
    "reserved_anomaly_requests",
    "reserved_fallback_requests",
    "parser_version",
    "health_status",
    "circuit_state",
    "last_success_at",
    "last_failure_at",
    "latency_ms",
    "error_rate",
    "required_env_key",
    "secret_env_name",
    "required_key_name",
)
_TELEGRAM_SAFE_COLUMNS = (
    "id",
    "channel_id",
    "username",
    "display_name",
    "source_type",
    "allowed_instruments",
    "role",
    "trust_score",
    "minimum_confidence",
    "maximum_message_age_seconds",
    "maximum_deviation_percent",
    "requires_multiple_sources",
    "parser_type",
    "parser_version",
    "enabled",
    "last_accepted_message_at",
    "last_rejection_reason",
)


def _provider_overrides(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.scalars(select(OperationalSetting).where(OperationalSetting.key == "provider.config")).all()
    return {
        row.scope_id: dict(row.value) if isinstance(row.value, dict) else {}
        for row in rows
        if not row.is_sensitive
    }


def _legacy_providers() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for asset_id, regions in PRICE_REGISTRY.items():
        for region_id, policy in regions.items():
            for position, provider in enumerate(policy.get("providers", []), start=1):
                auth = provider.get("auth") or {}
                secret_env_name = auth.get("key_source")
                secret_status = masked_secret_status(
                    os.getenv(str(secret_env_name)) if secret_env_name else None
                )
                providers.append(
                    {
                        "provider_id": str(provider.get("id")),
                        "name": str(provider.get("id")),
                        "asset": asset_id,
                        "region": region_id,
                        "enabled": True,
                        "role": "primary" if position == 1 else "fallback",
                        "priority": int(provider.get("priority", position)),
                        "trust_score": float(provider.get("trust_score", 0.75 if position == 1 else 0.6)),
                        "minimum_interval_seconds": int(provider.get("min_interval_seconds", 60)),
                        "operational_ttl_seconds": int(
                            provider.get("operational_ttl_seconds", provider.get("min_interval_seconds", 60) * 2)
                        ),
                        "parser_version": str(provider.get("parser_version", "legacy-explicit")),
                        "health_status": "configured" if secret_status["configured"] or not secret_env_name else "disabled_missing_key",
                        "circuit_state": "unknown",
                        "credential_status": secret_status,
                    }
                )
    return providers


def _db_providers(db: Session) -> list[dict[str, Any]]:
    rows = safe_rows(db, "pricing_providers", _PROVIDER_SAFE_COLUMNS, limit=1000)
    configs = safe_rows(
        db,
        "instrument_provider_configs",
        (
            "instrument_id",
            "provider_id",
            "enabled",
            "role",
            "priority",
            "trust_score",
            "operational_ttl_seconds",
            "maximum_verification_depth",
        ),
        limit=2000,
    )
    configs_by_provider: dict[str, list[dict[str, Any]]] = {}
    for config in configs:
        configs_by_provider.setdefault(str(config.get("provider_id")), []).append(config)
    for row in rows:
        env_name = (
            row.pop("required_env_key", None)
            or row.pop("secret_env_name", None)
            or row.pop("required_key_name", None)
        )
        row["provider_id"] = str(row.get("provider_id") or row.get("id"))
        provider_configs = configs_by_provider.get(row["provider_id"], [])
        row["instrument_configs"] = provider_configs
        ttl_values = [
            int(config["operational_ttl_seconds"])
            for config in provider_configs
            if config.get("operational_ttl_seconds") is not None
        ]
        row["operational_ttl_seconds"] = min(ttl_values) if ttl_values else None
        row["credential_status"] = masked_secret_status(
            os.getenv(str(env_name)) if env_name else None
        )
    return rows


def _provider_inventory(db: Session) -> list[dict[str, Any]]:
    database_rows = _db_providers(db)
    source_rows = database_rows if database_rows else _legacy_providers()
    overrides = _provider_overrides(db)
    return [
        {**provider, **overrides.get(str(provider.get("provider_id")), {})}
        for provider in source_rows
    ]


def _provider(db: Session, provider_id: str) -> dict[str, Any]:
    for provider in _provider_inventory(db):
        if str(provider.get("provider_id")) == provider_id:
            return provider
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")


def _impact_preview(
    inventory: list[dict[str, Any]],
    provider: dict[str, Any],
    proposed: dict[str, Any],
) -> dict[str, Any]:
    enabled_after = proposed.get("enabled", provider.get("enabled", True))
    role_after = proposed.get("role", provider.get("role"))
    peer_count = 0
    if provider.get("asset") and provider.get("region"):
        peer_count = sum(
            1
            for item in inventory
            if item.get("asset") == provider.get("asset")
            and item.get("region") == provider.get("region")
            and item.get("provider_id") != provider.get("provider_id")
            and item.get("enabled", True)
        )
    warnings: list[str] = []
    if provider.get("role") == "primary" and not enabled_after:
        warnings.append("Primary provider will be disabled")
    if not enabled_after and peer_count == 0 and provider.get("asset"):
        warnings.append("No enabled peer provider is known for this market path")
    if provider.get("role") == "primary" and role_after != "primary":
        warnings.append("Primary provider role will change")
    critical_fields = {
        "enabled",
        "role",
        "operational_ttl_seconds",
        "requests_per_hour",
        "requests_per_day",
        "reserved_anomaly_requests",
        "reserved_fallback_requests",
    }
    changed = sorted(key for key, value in proposed.items() if provider.get(key) != value)
    return {
        "provider_id": provider.get("provider_id"),
        "changed_fields": changed,
        "warnings": warnings,
        "risk": "high" if warnings or critical_fields.intersection(changed) else "normal",
        "reversible": True,
    }


@router.get("/providers")
def list_providers(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PROVIDERS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": redact(_provider_inventory(db))}


@router.get("/providers/{provider_id}/impact")
def provider_impact(
    provider_id: str,
    enabled: bool | None = None,
    role: str | None = Query(default=None, pattern="^(primary|verifier|fallback|compare)$"),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PROVIDERS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    inventory = _provider_inventory(db)
    provider = _provider(db, provider_id)
    proposed = {key: value for key, value in {"enabled": enabled, "role": role}.items() if value is not None}
    return _impact_preview(inventory, provider, proposed)


@router.get("/providers/drafts")
def list_provider_drafts(
    draft_status: str = Query(default="draft", alias="status", max_length=24),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PROVIDERS_READ)),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AdminProviderConfigDraft)
    if draft_status:
        statement = statement.where(AdminProviderConfigDraft.status == draft_status)
    drafts = db.scalars(statement.order_by(AdminProviderConfigDraft.created_at.desc()).limit(200)).all()
    return {
        "items": [
            redact(
                {
                    "id": draft.id,
                    "provider_id": draft.provider_id,
                    "before": draft.before_data,
                    "proposed": draft.proposed_data,
                    "impact": draft.impact_preview,
                    "status": draft.status,
                    "created_by": draft.created_by,
                    "applied_by": draft.applied_by,
                    "created_at": draft.created_at,
                    "applied_at": draft.applied_at,
                }
            )
            for draft in drafts
        ]
    }


@router.post("/providers/{provider_id}/drafts", status_code=status.HTTP_201_CREATED)
def create_provider_draft(
    provider_id: str,
    payload: ProviderDraftRequest,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PROVIDERS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    provider = _provider(db, provider_id)
    proposed = payload.model_dump(exclude_none=True)
    impact = _impact_preview(_provider_inventory(db), provider, proposed)
    draft = AdminProviderConfigDraft(
        provider_id=provider_id,
        before_data=redact(provider),
        proposed_data=proposed,
        impact_preview=impact,
        status="draft",
        created_by=principal.user.id,
    )
    db.add(draft)
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.provider.draft_created",
        resource_type="provider",
        resource_id=provider_id,
        before=provider,
        after=proposed,
    )
    db.commit()
    db.refresh(draft)
    return {"draft_id": draft.id, "impact": impact, "confirmation": f"APPLY PROVIDER {provider_id}"}


@router.post("/providers/drafts/{draft_id}/apply")
def apply_provider_draft(
    draft_id: int,
    payload: DangerousConfirmation,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PROVIDERS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    draft = db.get(AdminProviderConfigDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider draft not found")
    if draft.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider draft is no longer pending")
    require_confirmation(payload.confirmation, f"APPLY PROVIDER {draft.provider_id}")
    setting = db.scalar(
        select(OperationalSetting).where(
            OperationalSetting.key == "provider.config",
            OperationalSetting.scope_id == draft.provider_id,
        )
    )
    current = dict(setting.value) if setting and isinstance(setting.value, dict) else {}
    merged = {**current, **draft.proposed_data}
    if setting is None:
        setting = OperationalSetting(
            key="provider.config",
            scope_id=draft.provider_id,
            value=merged,
            description="Safe provider runtime override",
            is_sensitive=False,
            updated_by=principal.user.id,
        )
        db.add(setting)
    else:
        setting.value = merged
        setting.version += 1
        setting.updated_by = principal.user.id
    draft.status = "applied"
    draft.applied_by = principal.user.id
    draft.applied_at = datetime.now(UTC)
    provider_table = reflected_table(db, "pricing_providers")
    if provider_table is not None and "provider_id" in provider_table.c:
        provider_values = {
            key: value
            for key, value in draft.proposed_data.items()
            if key in provider_table.c
            and key
            in {
                "enabled",
                "role",
                "priority",
                "trust_score",
                "minimum_interval_seconds",
                "requests_per_minute",
                "requests_per_hour",
                "requests_per_day",
                "reserved_anomaly_requests",
                "reserved_fallback_requests",
            }
        }
        if provider_values:
            db.execute(
                provider_table.update()
                .where(provider_table.c.provider_id == draft.provider_id)
                .values(**provider_values)
            )
    config_table = reflected_table(db, "instrument_provider_configs")
    if config_table is not None and "provider_id" in config_table.c:
        config_values = {
            key: value
            for key, value in draft.proposed_data.items()
            if key in config_table.c
            and key in {"enabled", "role", "priority", "trust_score", "operational_ttl_seconds"}
        }
        if config_values:
            db.execute(
                config_table.update()
                .where(config_table.c.provider_id == draft.provider_id)
                .values(**config_values)
            )
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.provider.draft_applied",
        resource_type="provider",
        resource_id=draft.provider_id,
        before=draft.before_data,
        after=merged,
    )
    db.commit()
    return {"provider_id": draft.provider_id, "applied": True, "runtime_override": merged}


@router.post("/providers/drafts/{draft_id}/reject")
def reject_provider_draft(
    draft_id: int,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.PROVIDERS_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    draft = db.get(AdminProviderConfigDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider draft not found")
    if draft.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Provider draft is no longer pending")
    draft.status = "rejected"
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.provider.draft_rejected",
        resource_type="provider",
        resource_id=draft.provider_id,
        before=draft.proposed_data,
    )
    db.commit()
    return {"rejected": True}


@router.get("/telegram/sources")
def list_telegram_sources(
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.TELEGRAM_READ)),
    db: Session = Depends(get_db),
) -> dict:
    rows = safe_rows(db, "telegram_sources", _TELEGRAM_SAFE_COLUMNS, limit=500)
    overrides = {
        item.scope_id: item.value
        for item in db.scalars(
            select(OperationalSetting).where(OperationalSetting.key == "telegram.source")
        ).all()
        if isinstance(item.value, dict) and not item.is_sensitive
    }
    items = []
    for row in rows:
        source_id = str(row.get("id") or row.get("channel_id"))
        items.append({**row, **overrides.get(source_id, {}), "source_id": source_id})
    rejected = safe_rows(
        db,
        "telegram_parse_results",
        (
            "id",
            "telegram_message_id",
            "instrument_id",
            "validation_status",
            "rejection_reason",
            "created_at",
        ),
        limit=100,
    )
    return {"items": redact(items), "recent_rejections": redact(rejected)}


@router.post("/telegram/sources", status_code=status.HTTP_201_CREATED)
def create_telegram_source(
    payload: TelegramSourceCreate,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.TELEGRAM_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"CREATE TELEGRAM SOURCE {payload.channel_id}")
    existing = db.scalar(
        select(TelegramSource).where(
            (TelegramSource.channel_id == payload.channel_id)
            | (
                TelegramSource.username == payload.username
                if payload.username
                else TelegramSource.id == -1
            )
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telegram source already exists",
        )
    values = payload.model_dump(exclude={"confirmation"})
    source = TelegramSource(**values, expected_patterns={})
    db.add(source)
    db.flush()
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.telegram.source_created",
        resource_type="telegram_source",
        resource_id=source.id,
        after=values,
    )
    db.commit()
    db.refresh(source)
    return {"source_id": str(source.id), "channel_id": source.channel_id, "created": True}


@router.patch("/telegram/sources/{source_id}")
def update_telegram_source(
    source_id: str,
    payload: TelegramSourceUpdate,
    request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.TELEGRAM_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    proposed = payload.model_dump(exclude_none=True, exclude={"confirmation"})
    if not proposed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No source changes supplied")
    require_recent_reauthentication(principal)
    require_confirmation(payload.confirmation, f"UPDATE TELEGRAM SOURCE {source_id}")
    source = db.scalar(
        select(TelegramSource).where(
            or_(
                cast(TelegramSource.id, String) == source_id,
                TelegramSource.channel_id == source_id,
            )
        )
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Telegram source not found")
    setting = db.scalar(
        select(OperationalSetting).where(
            OperationalSetting.key == "telegram.source",
            OperationalSetting.scope_id == source_id,
        )
    )
    before = dict(setting.value) if setting and isinstance(setting.value, dict) else {}
    merged = {**before, **proposed}
    model_before = {
        key: getattr(source, key)
        for key in proposed
        if hasattr(source, key)
    }
    for key, value in proposed.items():
        if hasattr(source, key):
            setattr(source, key, value)
    if setting is None:
        setting = OperationalSetting(
            key="telegram.source",
            scope_id=source_id,
            value=merged,
            description="Safe Telegram source runtime override",
            is_sensitive=False,
            updated_by=principal.user.id,
        )
        db.add(setting)
    else:
        setting.value = merged
        setting.version += 1
        setting.updated_by = principal.user.id
    add_audit_event(
        db,
        request,
        actor_admin_id=principal.user.id,
        action="admin.telegram.source_updated",
        resource_type="telegram_source",
        resource_id=source_id,
        before={**before, **model_before},
        after=merged,
    )
    db.commit()
    return {"source_id": source_id, "settings": merged}
