from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from collections.abc import Iterable, Mapping

from sqlalchemy import bindparam, text

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
        return self._setting_value(row, default)

    @staticmethod
    def _setting_value(row, default=None):
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
        resolved = self._instrument_from_row(fallback, row)
        if resolved is None:
            return fallback
        expiry = await self.value("canonical_expiry_seconds", fallback.instrument_id)
        threshold = await self.value("anomaly_threshold_percent", fallback.instrument_id)
        return self._instrument_overrides(resolved, expiry, threshold)

    async def instruments(self, instrument_ids: Iterable[str]) -> dict[str, InstrumentDefinition]:
        fallbacks = {}
        for instrument_id in instrument_ids:
            fallback = get_instrument(instrument_id)
            fallbacks[fallback.instrument_id] = fallback
        if not fallbacks:
            return {}
        ids = tuple(fallbacks)
        rows, settings = await asyncio.gather(
            asyncio.to_thread(self._instrument_rows, ids),
            asyncio.to_thread(self._instrument_override_rows, ids),
            return_exceptions=True,
        )
        # An instrument read failure uses the same defaults as an individual read.
        if isinstance(rows, BaseException):
            return fallbacks
        by_id = {row["instrument_id"]: row for row in rows}
        overrides = {} if isinstance(settings, BaseException) else {
            (row["key"], row["scope_id"]): row for row in settings
        }
        resolved = {}
        for instrument_id, fallback in fallbacks.items():
            definition = self._instrument_from_row(fallback, by_id.get(instrument_id))
            if definition is None:
                resolved[instrument_id] = fallback
                continue
            values = []
            for key in ("canonical_expiry_seconds", "anomaly_threshold_percent"):
                # A present scoped null or malformed value still shadows the global row.
                row = overrides.get((key, instrument_id), overrides.get((key, "global")))
                values.append(self._setting_value(row))
            resolved[instrument_id] = self._instrument_overrides(definition, *values)
        return resolved

    @staticmethod
    def _instrument_from_row(fallback: InstrumentDefinition, row) -> InstrumentDefinition | None:
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
                allow_derived_fallback=(
                    fallback.allow_derived_fallback and bool(row["allow_derived_fallback"])
                ),
            )
        except (TypeError, ValueError, InvalidOperation):
            return None

    @staticmethod
    def _instrument_overrides(resolved: InstrumentDefinition, expiry, threshold) -> InstrumentDefinition:
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
        try:
            setting_rows = await asyncio.to_thread(
                self._provider_override_rows, tuple(provider.provider_id for provider in providers)
            )
        except Exception:
            setting_rows = []
        overrides = {(row["key"], row["scope_id"]): row for row in setting_rows}

        def setting(key, provider_id, default=None):
            row = overrides.get((key, provider_id), overrides.get((key, "global")))
            return self._setting_value(row, default)

        effective = []
        for provider in providers:
            override = setting("provider.config", provider.provider_id, {})
            override = override if isinstance(override, dict) else {}
            try:
                budget_fields = {name: int(override[name]) for name in (
                    "requests_per_minute", "requests_per_hour", "requests_per_day",
                    "reserved_anomaly_requests", "reserved_fallback_requests", "minimum_interval_seconds",
                ) if name in override}
                hourly = setting("provider_budget_requests_per_hour", provider.provider_id)
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
    def _provider_override_rows(provider_ids: tuple[str, ...]):
        if not provider_ids:
            return []
        db = SessionLocal()
        try:
            return db.execute(
                text("""
                    SELECT key, scope_id, value FROM operational_settings
                    WHERE key IN ('provider.config', 'provider_budget_requests_per_hour')
                      AND scope_id IN :scope_ids
                """).bindparams(bindparam("scope_ids", expanding=True)),
                {"scope_ids": (*provider_ids, "global")},
            ).mappings().all()
        finally:
            db.close()

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
    def _instrument_rows(instrument_ids: tuple[str, ...]):
        db = SessionLocal()
        try:
            return db.execute(
                text("""
                    SELECT instrument_id, operational_ttl_seconds, stale_after_seconds,
                           expire_after_seconds, base_anomaly_threshold_percent,
                           maximum_dynamic_threshold_percent, minimum_sanity_price,
                           maximum_sanity_price, importance, enabled, allow_derived_fallback
                    FROM instruments WHERE instrument_id IN :instrument_ids
                """).bindparams(bindparam("instrument_ids", expanding=True)),
                {"instrument_ids": instrument_ids},
            ).mappings().all()
        finally:
            db.close()

    @staticmethod
    def _instrument_override_rows(instrument_ids: tuple[str, ...]):
        db = SessionLocal()
        try:
            return db.execute(
                text("""
                    SELECT key, scope_id, value FROM operational_settings
                    WHERE key IN ('canonical_expiry_seconds', 'anomaly_threshold_percent')
                      AND scope_id IN :scope_ids
                """).bindparams(bindparam("scope_ids", expanding=True)),
                {"scope_ids": (*instrument_ids, "global")},
            ).mappings().all()
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
