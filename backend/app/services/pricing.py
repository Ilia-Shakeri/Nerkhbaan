from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from .pricing_cache import PricingCacheStore
from .pricing_fetcher import ChainResult, PricingFetcher
from .pricing_health import build_startup_checks, chain_result_payload
from .pricing_registry import (
    ASSET_LABELS,
    CHART_ERROR_MESSAGE,
    PRICE_REGISTRY,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_ATTEMPTS,
)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 20
HISTORY_MAX_POINTS = 48


@dataclass
class LivePrices:
    payload: dict[str, Any]


class PricingService:
    def __init__(self) -> None:
        self._last_refresh: datetime | None = None
        self._history: dict[str, list[dict[str, float | str | None]]] = {
            "gold": [],
            "silver": [],
            "usdt": [],
            "btc": [],
        }
        self._latest: LivePrices | None = None
        self._chain_health: dict[str, dict[str, dict[str, Any]]] = {}

        self._cache = PricingCacheStore(self._resolve_cache_file())
        self.fetcher = PricingFetcher(
            settings=settings,
            cache=self._cache,
            registry=PRICE_REGISTRY,
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            retry_attempts=RETRY_ATTEMPTS,
        )
        self._load_history_from_cache()
        self._startup_checks = self._build_startup_checks()

    async def get_prices(self) -> dict:
        if self._should_refresh():
            await self._refresh_prices()

        if not self._latest:
            raise RuntimeError("Price cache is not initialized")

        return self._latest.payload

    def _should_refresh(self) -> bool:
        if not self._last_refresh:
            return True
        return datetime.now(UTC) - self._last_refresh > timedelta(seconds=CACHE_TTL_SECONDS)

    async def _refresh_prices(self) -> None:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            snapshots = await asyncio.gather(
                *(self._build_asset_snapshot(client, asset_id) for asset_id in ASSET_LABELS)
            )

        payload = {
            "refreshed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "source": self._build_global_sources(snapshots),
            "assets": snapshots,
        }

        self._latest = LivePrices(payload=payload)
        self._last_refresh = datetime.now(UTC)
        self._cache.persist_if_dirty()

    async def _build_asset_snapshot(self, client: httpx.AsyncClient, asset_id: str) -> dict[str, Any]:
        iran_chain, intl_chain = await asyncio.gather(
            self._fetch_chain(client, asset_id, "iran"),
            self._fetch_chain(client, asset_id, "international"),
        )

        self._chain_health[asset_id] = {
            "iran": self._build_chain_health(asset_id, "iran", iran_chain),
            "international": self._build_chain_health(asset_id, "international", intl_chain),
        }

        if iran_chain.status == "live" or intl_chain.status == "live":
            self._append_history(asset_id, intl_chain.value, iran_chain.value)

        change = self._calc_change_percent(asset_id)
        stale_candidates = [
            self._stale_minutes(iran_chain.updated_at) if iran_chain.status == "cached" else None,
            self._stale_minutes(intl_chain.updated_at) if intl_chain.status == "cached" else None,
        ]
        stale_minutes = max((value for value in stale_candidates if value is not None), default=None)

        return {
            "asset": asset_id,
            "label_fa": ASSET_LABELS[asset_id]["fa"],
            "label_en": ASSET_LABELS[asset_id]["en"],
            "price_usd": intl_chain.value,
            "price_toman": iran_chain.value,
            "change_percent": change,
            "trend": "up" if change >= 0 else "down",
            "history": self._history_points(asset_id),
            "source_usd": intl_chain.source,
            "source_toman": iran_chain.source,
            "usd_status": intl_chain.status,
            "toman_status": iran_chain.status,
            "stale_minutes": stale_minutes,
            "chart_error": iran_chain.status != "live" or intl_chain.status != "live",
            "chart_error_message": CHART_ERROR_MESSAGE,
        }

    async def _fetch_chain(self, client: httpx.AsyncClient, asset_id: str, region: str) -> ChainResult:
        return await self.fetcher.fetch_chain(client, asset_id, region)

    def _build_chain_health(self, asset_id: str, region: str, chain: ChainResult) -> dict[str, Any]:
        payload = chain_result_payload(chain)
        payload["providers"] = self._provider_statuses(asset_id, region, chain)
        return payload

    def _provider_statuses(self, asset_id: str, region: str, chain: ChainResult) -> list[dict[str, Any]]:
        providers = sorted(PRICE_REGISTRY[asset_id][region]["providers"], key=lambda provider: provider.get("priority", 99))
        selected_source = self._extract_source_id(chain.source)

        source_priority: int | None = None
        for provider in providers:
            if provider["id"] == selected_source:
                source_priority = int(provider.get("priority", 99))
                break

        provider_statuses: list[dict[str, Any]] = []
        for provider in providers:
            provider_id = str(provider["id"])
            status = "unavailable"
            last_success_time: str | None = None

            if chain.status == "live":
                if provider_id == selected_source:
                    status = "connected"
                    last_success_time = (
                        chain.updated_at.replace(microsecond=0).isoformat()
                        if chain.updated_at
                        else None
                    )
                elif source_priority is not None and int(provider.get("priority", 99)) < source_priority:
                    status = "fallback"
            elif chain.status == "cached":
                if provider_id == selected_source:
                    status = "cache"
                    last_success_time = (
                        chain.updated_at.replace(microsecond=0).isoformat()
                        if chain.updated_at
                        else None
                    )
                else:
                    status = "fallback"

            key_source = (provider.get("auth") or {}).get("key_source")
            has_api_key = bool(getattr(settings, key_source, None)) if key_source else True

            provider_statuses.append(
                {
                    "provider_id": provider_id,
                    "provider_name": provider_id,
                    "status": status,
                    "last_success_time": last_success_time,
                    "has_api_key": has_api_key,
                }
            )

        return provider_statuses

    def _extract_source_id(self, source: str) -> str:
        if source.startswith("cache (") and source.endswith(")"):
            return source[len("cache (") : -1]
        return source

    def _append_history(self, asset_id: str, price_usd: float | None, price_toman: float | None) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        self._history[asset_id].append(
            {
                "timestamp": now,
                "price_usd": price_usd,
                "price_toman": price_toman,
            }
        )
        self._history[asset_id] = self._history[asset_id][-HISTORY_MAX_POINTS:]
        self._cache.set_history(asset_id, self._history[asset_id])

    def _history_points(self, asset_key: str) -> list[dict[str, str | float | None]]:
        return [
            {
                "timestamp": str(point["timestamp"]),
                "value_usd": self._to_float(point.get("price_usd")),
                "value_toman": self._to_float(point.get("price_toman")),
            }
            for point in self._history[asset_key]
        ]

    def _calc_change_percent(self, asset_key: str) -> float:
        history = self._history[asset_key]
        if len(history) < 2:
            return 0.0

        latest = history[-1]
        previous = history[-2]

        latest_value = self._to_float(latest.get("price_usd"))
        prev_value = self._to_float(previous.get("price_usd"))
        if latest_value is None or prev_value is None:
            latest_value = self._to_float(latest.get("price_toman"))
            prev_value = self._to_float(previous.get("price_toman"))

        if latest_value is None or prev_value in (None, 0):
            return 0.0

        return round(((latest_value - prev_value) / prev_value) * 100, 2)

    def _build_global_sources(self, snapshots: list[dict[str, Any]]) -> dict[str, str]:
        usd_sources = sorted({str(snapshot["source_usd"]) for snapshot in snapshots})
        toman_sources = sorted({str(snapshot["source_toman"]) for snapshot in snapshots})
        return {
            "usd": ", ".join(usd_sources),
            "toman": ", ".join(toman_sources),
        }

    def _stale_minutes(self, updated_at: datetime | None) -> int | None:
        if not updated_at:
            return None
        delta = datetime.now(UTC) - updated_at
        minutes = int(delta.total_seconds() // 60)
        return max(minutes, 0)

    def _resolve_cache_file(self) -> Path:
        if Path("backend").exists():
            return Path("backend") / "price_cache.json"
        return Path(settings.price_cache_file)

    def _load_history_from_cache(self) -> None:
        for asset_id in self._history:
            points = self._cache.get_history(asset_id)
            normalized: list[dict[str, float | str | None]] = []
            for point in points[-HISTORY_MAX_POINTS:]:
                if not isinstance(point, dict):
                    continue
                timestamp = point.get("timestamp")
                if not isinstance(timestamp, str):
                    continue
                normalized.append(
                    {
                        "timestamp": timestamp,
                        "price_usd": self._to_float(point.get("price_usd")),
                        "price_toman": self._to_float(point.get("price_toman")),
                    }
                )
            self._history[asset_id] = normalized

    def _build_startup_checks(self) -> dict[str, Any]:
        checks = build_startup_checks(settings, PRICE_REGISTRY)
        if checks["missing_env_keys"]:
            message = "Pricing providers are missing API keys: " + ", ".join(checks["missing_env_keys"])
            if checks["strict_mode"]:
                raise RuntimeError(message)
            logger.warning("%s. Falling back to backup/cached chains when needed.", message)
        if checks["missing_optional_env_keys"]:
            logger.warning(
                "Optional pricing keys are not set: %s",
                ", ".join(checks["missing_optional_env_keys"]),
            )
        return checks

    def startup_checks(self) -> dict[str, Any]:
        return dict(self._startup_checks)

    def refresh_startup_checks(self) -> dict[str, Any]:
        self._startup_checks = self._build_startup_checks()
        return self.startup_checks()

    def has_refreshed(self) -> bool:
        return self._last_refresh is not None

    def get_chain_health(self) -> dict[str, Any]:
        return {
            "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "last_refresh_at": (
                self._last_refresh.replace(microsecond=0).isoformat() if self._last_refresh else None
            ),
            "startup": self.startup_checks(),
            "chains": self._chain_health,
        }

    def _to_float(self, value: object) -> float | None:
        return self.fetcher.to_float(value)

    # Compatibility helpers used in tests.
    def _set_cached_value(
        self,
        asset_id: str,
        region: str,
        value: float,
        source: str,
        updated_at: datetime,
    ) -> None:
        self._cache.set_chain(asset_id, region, value, source, updated_at)

    def _get_cached_value(self, asset_id: str, region: str) -> tuple[float, str, datetime] | None:
        return self._cache.get_chain(asset_id, region)


pricing_service = PricingService()
