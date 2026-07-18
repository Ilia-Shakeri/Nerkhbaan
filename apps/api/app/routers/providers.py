from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from ..pricing.service import instrument_pricing_service
from ..services.api_registry import API_REGISTRY

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def get_provider_catalog() -> dict:
    catalog = await instrument_pricing_service.provider_catalog(authenticated=False)
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
        },
    }
