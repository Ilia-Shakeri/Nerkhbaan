from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping

from sqlalchemy import text

from ..db import SessionLocal
from .instruments import get_instrument
from .models import InstrumentDefinition, ProviderRole
from .registry import PROVIDERS_BY_INSTRUMENT, ProviderDefinition


class OperationalPricingSettings:
    async def value(self, key: str, scope_id: str = "global", default=None):
        try:
            row = await asyncio.to_thread(self._setting_row, key, scope_id)
        except Exception:
            return default
        if not isinstance(row, Mapping) or "value" not in row:
            return default
        value = row["value"]
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return default
        return value

    async def feature_enabled(self, key: str, default: bool | None = None, *, scope_id: str = "global") -> bool:
        fallback = self._feature_default(key) if default is None else bool(default)
        override = await self.value(key, scope_id)
        if type(override) is bool:
            return override
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
            row = {
                "operational_ttl_seconds": fallback.operational_ttl_seconds,
                "stale_after_seconds": fallback.stale_after_seconds,
                "expire_after_seconds": fallback.expire_after_seconds,
                "base_anomaly_threshold_percent": fallback.base_anomaly_threshold_percent,
                "maximum_dynamic_threshold_percent": fallback.maximum_dynamic_threshold_percent,
                "minimum_sanity_price": fallback.minimum_price,
                "maximum_sanity_price": fallback.maximum_price,
                "importance": fallback.importance, "enabled": fallback.enabled,
                "allow_derived_fallback": fallback.allow_derived_fallback,
            }
        try:
            resolved = replace(
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
                allow_derived_fallback=(
                    fallback.allow_derived_fallback and bool(row["allow_derived_fallback"])
                ),
            )
        except (TypeError, ValueError, InvalidOperation):
            return fallback
        expiry = await self.value("canonical_expiry_seconds", fallback.instrument_id)
        threshold = await self.value("anomaly_threshold_percent", fallback.instrument_id)
        try:
            overrides = {}
            if expiry is not None:
                expire = int(expiry)
                overrides.update(
                    expire_after_seconds=expire,
                    stale_after_seconds=min(resolved.stale_after_seconds, expire),
                    operational_ttl_seconds=min(resolved.operational_ttl_seconds, expire),
                )
            if threshold is not None:
                base = Decimal(str(threshold))
                overrides.update(base_anomaly_threshold_percent=base,
                                 maximum_dynamic_threshold_percent=max(base, resolved.maximum_dynamic_threshold_percent))
            return replace(resolved, **overrides)
        except (TypeError, ValueError, InvalidOperation):
            return resolved

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
                            # Registry defaults are a safety ceiling. An older database row
                            # must not revive a route that code has quarantined.
                            enabled=bool(
                                provider.enabled
                                and row["provider_enabled"]
                                and row["config_enabled"]
                            ),
                            operational_ttl_seconds=int(
                                row["operational_ttl_seconds"]
                                or provider.operational_ttl_seconds
                            ),
                            budget=budget,
                        )
                    )
                except (TypeError, ValueError, InvalidOperation):
                    resolved.append(replace(provider, enabled=False))
            providers = tuple(sorted(resolved, key=lambda item: (item.priority, item.provider_id)))
        effective = []
        for provider in providers:
            override = await self.value("provider.config", provider.provider_id, {})
            override = override if isinstance(override, dict) else {}
            try:
                budget_fields = {name: int(override[name]) for name in (
                    "requests_per_minute", "requests_per_hour", "requests_per_day",
                    "reserved_anomaly_requests", "reserved_fallback_requests", "minimum_interval_seconds",
                ) if name in override}
                hourly = await self.value("provider_budget_requests_per_hour", provider.provider_id)
                if hourly is not None:
                    budget_fields["requests_per_hour"] = int(hourly)
                enabled = override.get("enabled", True)
                if type(enabled) is not bool:
                    raise ValueError("Provider enabled setting must be boolean")
                candidate = replace(provider,
                    enabled=provider.enabled and enabled,
                    role=ProviderRole(override.get("role", provider.role)),
                    priority=int(override.get("priority", provider.priority)),
                    trust_score=Decimal(str(override.get("trust_score", provider.trust_score))),
                    operational_ttl_seconds=int(override.get("operational_ttl_seconds", provider.operational_ttl_seconds)),
                    budget=replace(provider.budget, **budget_fields),
                )
                if (candidate.priority < 0 or candidate.operational_ttl_seconds <= 0
                    or not candidate.trust_score.is_finite() or not 0 <= candidate.trust_score <= 1
                    or any(getattr(candidate.budget, name) < 0 for name in (
                        "requests_per_minute", "requests_per_hour", "requests_per_day",
                        "reserved_anomaly_requests", "reserved_fallback_requests", "minimum_interval_seconds",
                    ))):
                    raise ValueError("Provider runtime settings are invalid")
                effective.append(candidate)
            except (TypeError, ValueError, InvalidOperation):
                # Corrupt policy must not revive a disabled source or break other sources.
                effective.append(replace(provider, enabled=False))
        providers = tuple(sorted(effective, key=lambda item: (item.priority, item.provider_id)))
        if not roles:
            return providers
        allowed = set(roles)
        return tuple(provider for provider in providers if provider.role in allowed)

    @staticmethod
    def _setting_row(key: str, scope_id: str):
        db = SessionLocal()
        try:
            row = db.execute(text("SELECT value FROM operational_settings WHERE key = :key AND scope_id = :scope"),
                             {"key": key, "scope": scope_id}).mappings().first()
            if row is None and scope_id != "global":
                row = db.execute(text("SELECT value FROM operational_settings WHERE key = :key AND scope_id = 'global'"),
                                 {"key": key}).mappings().first()
            return row
        finally:
            db.close()

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
            return bool(getattr(settings, "pricing_comparison_visible", True))
        if key == "telegram_source_enabled":
            return True
        return False


operational_pricing_settings = OperationalPricingSettings()
