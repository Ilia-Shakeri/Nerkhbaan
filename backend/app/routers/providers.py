from fastapi import APIRouter

from ..services.api_registry import API_REGISTRY
from ..services.pricing import pricing_service
from ..services.pricing_registry import PRICE_REGISTRY

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _provider_has_api_key(provider: dict) -> bool:
    auth = provider.get("auth") or {}
    key_source = auth.get("key_source")
    if not key_source:
        return True
    startup = pricing_service.startup_checks()
    return key_source not in set(startup.get("missing_env_keys", []))


def _chain_provider_rows(asset_id: str, region: str, chain_payload: dict) -> list[dict]:
    providers = sorted(PRICE_REGISTRY[asset_id][region]["providers"], key=lambda provider: provider.get("priority", 99))
    rows: list[dict] = []

    known_by_id = {
        entry.get("provider_id"): entry
        for entry in (chain_payload.get("providers") or [])
        if isinstance(entry, dict)
    }

    for provider in providers:
        provider_id = provider["id"]
        provider_status = known_by_id.get(provider_id, {})
        rows.append(
            {
                "asset": asset_id,
                "region": region,
                "provider_id": provider_id,
                "provider_name": provider_id,
                "status": provider_status.get("status", "unavailable"),
                "last_success_time": provider_status.get("last_success_time"),
                "has_api_key": provider_status.get("has_api_key", _provider_has_api_key(provider)),
            }
        )

    return rows


@router.get("")
async def get_provider_catalog() -> dict:
    try:
        if not pricing_service.has_refreshed():
            await pricing_service.get_prices()
    except Exception:
        pass

    health = pricing_service.get_chain_health()

    provider_rows: list[dict] = []
    for asset_id, regions in (health.get("chains") or {}).items():
        if not isinstance(regions, dict):
            continue
        for region in ("iran", "international"):
            chain_payload = regions.get(region)
            if not isinstance(chain_payload, dict):
                continue
            provider_rows.extend(_chain_provider_rows(asset_id, region, chain_payload))

    if not provider_rows:
        for asset_id, asset_config in PRICE_REGISTRY.items():
            for region in ("iran", "international"):
                for provider in asset_config[region]["providers"]:
                    provider_rows.append(
                        {
                            "asset": asset_id,
                            "region": region,
                            "provider_id": provider["id"],
                            "provider_name": provider["id"],
                            "status": "unavailable",
                            "last_success_time": None,
                            "has_api_key": _provider_has_api_key(provider),
                        }
                    )

    return {
        **API_REGISTRY,
        "_health": {
            "checked_at": health.get("checked_at"),
            "last_refresh_at": health.get("last_refresh_at"),
            "startup": health.get("startup"),
            "providers": provider_rows,
        },
    }
