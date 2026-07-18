from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import text

from ..db import SessionLocal
from .instruments import get_instrument
from .models import InstrumentDefinition, ProviderRole
from .registry import PROVIDERS_BY_INSTRUMENT, ProviderDefinition


class OperationalPricingSettings:
    async def feature_enabled(self, key: str, default: bool | None = None) -> bool:
        fallback = self._feature_default(key) if default is None else bool(default)
        try:
            row = await asyncio.to_thread(self._feature_flag_row, key)
        except Exception:
            return fallback
        if row is None:
            return fallback
        return bool(row["enabled"])

    async def instrument(self, instrument_id: str) -> InstrumentDefinition:
        fallback = get_instrument(instrument_id)
        try:
            row = await asyncio.to_thread(self._instrument_row, fallback.instrument_id)
        except Exception:
            return fallback
        if row is None:
            return fallback
        try:
            return replace(
                fallback,
                operational_ttl_seconds=int(row["operational_ttl_seconds"]),
                stale_after_seconds=int(row["stale_after_seconds"]),
                expire_after_seconds=int(row["expire_after_seconds"]),
                base_anomaly_threshold_percent=Decimal(
                    str(row["base_anomaly_threshold_percent"])
                ),
                maximum_dynamic_threshold_percent=Decimal(
                    str(row["maximum_dynamic_threshold_percent"])
                ),
                minimum_price=Decimal(str(row["minimum_sanity_price"])),
                maximum_price=Decimal(str(row["maximum_sanity_price"])),
                importance=int(row["importance"]),
                enabled=bool(row["enabled"]),
                allow_derived_fallback=bool(row["allow_derived_fallback"]),
            )
        except (TypeError, ValueError):
            return fallback

    async def providers_for(
        self,
        instrument_id: str,
        *roles: ProviderRole,
    ) -> tuple[ProviderDefinition, ...]:
        normalized = get_instrument(instrument_id).instrument_id
        fallback = PROVIDERS_BY_INSTRUMENT.get(normalized, ())
        try:
            rows = await asyncio.to_thread(self._provider_rows, normalized)
        except Exception:
            rows = []
        if not rows:
            providers = fallback
        else:
            by_id = {row["provider_id"]: row for row in rows}
            resolved: list[ProviderDefinition] = []
            for provider in fallback:
                row = by_id.get(provider.provider_id)
                if row is None:
                    resolved.append(provider)
                    continue
                try:
                    budget = replace(
                        provider.budget,
                        requests_per_minute=int(row["requests_per_minute"]),
                        requests_per_hour=int(row["requests_per_hour"]),
                        requests_per_day=int(row["requests_per_day"]),
                        reserved_anomaly_requests=int(row["reserved_anomaly_requests"]),
                        reserved_fallback_requests=int(row["reserved_fallback_requests"]),
                        minimum_interval_seconds=int(row["minimum_interval_seconds"]),
                        cooldown_after_429_seconds=int(row["cooldown_after_429_seconds"]),
                        estimated_request_cost=Decimal(
                            str(row["estimated_request_cost"])
                        ),
                    )
                    resolved.append(
                        replace(
                            provider,
                            role=ProviderRole(row["role"]),
                            priority=int(row["priority"]),
                            trust_score=Decimal(str(row["trust_score"])),
                            enabled=bool(row["provider_enabled"] and row["config_enabled"]),
                            operational_ttl_seconds=int(
                                row["operational_ttl_seconds"]
                                or provider.operational_ttl_seconds
                            ),
                            budget=budget,
                        )
                    )
                except (TypeError, ValueError):
                    resolved.append(provider)
            providers = tuple(sorted(resolved, key=lambda item: (item.priority, item.provider_id)))
        if not roles:
            return providers
        allowed = set(roles)
        return tuple(provider for provider in providers if provider.role in allowed)

    @staticmethod
    def _instrument_row(instrument_id: str):
        db = SessionLocal()
        try:
            return db.execute(
                text(
                    """
                    SELECT operational_ttl_seconds, stale_after_seconds,
                           expire_after_seconds, base_anomaly_threshold_percent,
                           maximum_dynamic_threshold_percent, minimum_sanity_price,
                           maximum_sanity_price, importance, enabled,
                           allow_derived_fallback
                    FROM instruments
                    WHERE instrument_id = :instrument_id
                    """
                ),
                {"instrument_id": instrument_id},
            ).mappings().first()
        finally:
            db.close()

    @staticmethod
    def _provider_rows(instrument_id: str):
        db = SessionLocal()
        try:
            return db.execute(
                text(
                    """
                    SELECT p.provider_id,
                           COALESCE(c.role, p.role) AS role,
                           COALESCE(c.priority, p.priority) AS priority,
                           COALESCE(c.trust_score, p.trust_score) AS trust_score,
                           p.enabled AS provider_enabled,
                           c.enabled AS config_enabled,
                           c.operational_ttl_seconds,
                           p.requests_per_minute, p.requests_per_hour,
                           p.requests_per_day, p.reserved_anomaly_requests,
                           p.reserved_fallback_requests,
                           p.minimum_interval_seconds,
                           p.cooldown_after_429_seconds,
                           p.estimated_request_cost
                    FROM pricing_providers p
                    JOIN instrument_provider_configs c
                      ON c.provider_id = p.provider_id
                    WHERE c.instrument_id = :instrument_id
                    """
                ),
                {"instrument_id": instrument_id},
            ).mappings().all()
        finally:
            db.close()

    @staticmethod
    def _feature_flag_row(key: str):
        db = SessionLocal()
        try:
            return db.execute(
                text(
                    """
                    SELECT enabled
                    FROM feature_flags
                    WHERE key = :key
                    """
                ),
                {"key": key},
            ).mappings().first()
        finally:
            db.close()

    @staticmethod
    def _feature_default(key: str) -> bool:
        from ..config import settings

        if key == "backfill_enabled":
            return bool(settings.pricing_backfill_enabled)
        if key == "derived_fallback_enabled":
            return bool(settings.pricing_derived_fallback_enabled)
        if key == "comparison_visible":
            value = os.getenv("PRICING_COMPARISON_VISIBLE")
            if value is None:
                return True
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False


operational_pricing_settings = OperationalPricingSettings()
