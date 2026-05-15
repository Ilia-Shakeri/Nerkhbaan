from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .pricing_fetcher import ChainResult


def required_provider_keys(
    registry: dict[str, dict[str, dict[str, Any]]],
) -> set[str]:
    required: set[str] = set()
    for asset in registry.values():
        for region in asset.values():
            providers = region.get("providers", [])
            for provider in providers:
                auth = provider.get("auth") or {}
                key_source = auth.get("key_source")
                if key_source:
                    required.add(str(key_source))
    return required


def build_startup_checks(settings: Any, registry: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    required_keys = sorted(required_provider_keys(registry))
    missing_keys = sorted(
        key_name
        for key_name in required_keys
        if not getattr(settings, key_name, None)
    )
    return {
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "required_env_keys": required_keys,
        "missing_env_keys": missing_keys,
        "strict_mode": settings.pricing_require_provider_keys,
        "ok": len(missing_keys) == 0,
    }


def chain_result_payload(chain_result: ChainResult) -> dict[str, Any]:
    return {
        "status": chain_result.status,
        "source": chain_result.source,
        "updated_at": (
            chain_result.updated_at.replace(microsecond=0).isoformat()
            if chain_result.updated_at
            else None
        ),
        "error": chain_result.error,
    }
