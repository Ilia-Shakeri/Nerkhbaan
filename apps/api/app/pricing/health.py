from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from ..db import SessionLocal
from .backfill import PricingBackfillQueue, backfill_queue
from .cache import PricingRedisStore, pricing_redis
from .history import InternalPriceHistory, internal_history
from .instruments import get_instrument
from .models import utc_now
from .registry import PROVIDERS, PROVIDERS_BY_INSTRUMENT
from .contracts import provider_contract, provider_contract_inventory


class PricingHealthService:
    def __init__(
        self,
        *,
        store: PricingRedisStore = pricing_redis,
        history: InternalPriceHistory = internal_history,
        backfill: PricingBackfillQueue = backfill_queue,
    ) -> None:
        self.store = store
        self.history = history
        self.backfill = backfill

    async def instrument_health(
        self, instrument_id: str, *, authenticated: bool = False
    ) -> dict[str, Any]:
        normalized = get_instrument(instrument_id).instrument_id
        redis_ok, database = await asyncio.gather(
            self.store.ping(),
            asyncio.to_thread(self._database_probe),
        )
        quote = None
        if redis_ok:
            try:
                quote = await self.store.get_canonical(normalized)
            except Exception:
                quote = None
        if quote is None and database["connected"]:
            try:
                quote = await self.history.latest_canonical(normalized)
            except Exception:
                quote = None
        backlog = await self.store.persistence_backlog() if redis_ok else None
        payload: dict[str, Any] = {
            "instrument_id": normalized,
            "status": quote.effective_status().value if quote else "unavailable",
            "updated_at": quote.canonical_at.isoformat() if quote else None,
            "observed_at": quote.observed_at.isoformat() if quote else None,
            "age_seconds": (
                max(0, int((utc_now() - quote.observed_at).total_seconds()))
                if quote
                else None
            ),
            "database": "connected" if database["connected"] else "unavailable",
            "redis": "connected" if redis_ok else "unavailable",
            "refresh_enabled": redis_ok,
            "persistence_backlog": backlog,
            "degraded": not redis_ok or not database["connected"],
        }
        if authenticated:
            providers: list[dict[str, Any]] = []
            if redis_ok:
                for provider in PROVIDERS_BY_INSTRUMENT.get(normalized, ()):
                    try:
                        runtime = await self.store.get_provider_runtime(
                            provider.provider_id, normalized
                        )
                        providers.append(runtime.to_dict())
                    except Exception:
                        continue
            payload["providers"] = providers
            payload["provider_canaries"] = self.provider_canaries(normalized)
            payload["migration_version"] = database["migration_version"]
        return payload

    async def detailed(self, *, authenticated: bool = False) -> dict[str, Any]:
        redis_ok, database, backfill = await asyncio.gather(
            self.store.ping(),
            asyncio.to_thread(self._database_probe),
            self.backfill.backlog(),
        )
        persistence_backlog = await self.store.persistence_backlog() if redis_ok else None
        payload: dict[str, Any] = {
            "status": "ok" if database["connected"] or redis_ok else "degraded",
            "checked_at": datetime.now(UTC).isoformat(),
            "database": "connected" if database["connected"] else "unavailable",
            "redis": "connected" if redis_ok else "unavailable",
            "pricing_refresh": "enabled" if redis_ok else "suspended",
            "persistence_backlog": persistence_backlog,
            "backfill_backlog": backfill,
        }
        if authenticated:
            payload["migration_version"] = database["migration_version"]
            payload["database_error"] = database["error"]
            payload["provider_contracts"] = provider_contract_inventory()
            payload["provider_canaries"] = self.provider_canaries()
        return payload

    def provider_canaries(self, instrument_id: str | None = None) -> list[dict[str, Any]]:
        providers = (
            PROVIDERS_BY_INSTRUMENT.get(instrument_id, ())
            if instrument_id
            else tuple(PROVIDERS.values())
        )
        rows: list[dict[str, Any]] = []
        from ..config import settings

        for provider in providers:
            contract = provider_contract(provider)
            configured = provider.configured(settings)
            if not provider.enabled:
                status = "provider_disabled"
            elif not configured:
                status = "not_configured"
            elif contract.tier == "B" and contract.commercial_status != "operator_rights_confirmed":
                status = "rights_review_required"
            else:
                status = "eligible_for_live_canary"
            rows.append(
                {
                    "provider_id": provider.provider_id,
                    "instrument_id": provider.instrument_id,
                    "status": status,
                    "tier": contract.tier,
                    "owner": contract.owner,
                    "credential_placement": contract.credential_placement,
                    "unit_contract": contract.unit_contract,
                    "attribution_required": contract.attribution_required,
                    "last_live_probe_at": None,
                }
            )
        return rows

    @staticmethod
    def _database_probe() -> dict[str, Any]:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            try:
                version = db.execute(
                    text(
                        "SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1"
                    )
                ).scalar_one_or_none()
            except Exception:
                db.rollback()
                version = None
            return {"connected": True, "migration_version": version, "error": None}
        except Exception as exc:
            return {
                "connected": False,
                "migration_version": None,
                "error": f"{type(exc).__name__}: database probe failed",
            }
        finally:
            db.close()


pricing_health_service = PricingHealthService()
