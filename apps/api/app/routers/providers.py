from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from ..models import User
from ..pricing.service import instrument_pricing_service
from ..pricing.health import pricing_health_service
from ..routers.instruments import optional_current_user
from ..services.api_registry import API_REGISTRY

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def get_provider_catalog(
    user: User | None = Depends(optional_current_user),
) -> dict:
    """Provider catalogue.

    Anonymous callers get counts only. The per-provider view names every
    upstream, says which credentials are configured and reports circuit state,
    which is a map of exactly what to attack to degrade pricing.
    """
    authenticated = user is not None
    catalog = await instrument_pricing_service.provider_catalog(
        authenticated=authenticated
    )
    if not authenticated:
        by_instrument: dict[str, dict[str, int]] = {}
        for row in catalog["providers"]:
            bucket = by_instrument.setdefault(
                row["instrument_id"], {"provider_count": 0, "healthy_count": 0}
            )
            bucket["provider_count"] += 1
            if row["enabled"] and row["configured"] and row["status"] not in {
                "circuit_open",
                "disabled",
                "disabled_missing_key",
            }:
                bucket["healthy_count"] += 1
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "instruments": by_instrument,
            "authentication_required_for_details": True,
        }

    providers = [
        {
            "asset": row["instrument_id"],
            "region": "iran" if row["instrument_id"].endswith("TOMAN") else "international",
            "provider_id": row["provider_id"],
            "provider_name": row["display_name"],
            "status": row["status"],
            "last_success_time": row["last_success_at"],
            "has_api_key": row["configured"],
            "enabled": row["enabled"],
            "role": row["role"],
        }
        for row in catalog["providers"]
    ]
    return {
        **API_REGISTRY,
        "_health": {
            "checked_at": datetime.now(UTC).isoformat(),
            "providers": providers,
            "canaries": pricing_health_service.provider_canaries(),
        },
    }
