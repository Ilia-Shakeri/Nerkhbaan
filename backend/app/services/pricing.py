from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 20
HISTORY_MAX_POINTS = 48
REQUEST_TIMEOUT_SECONDS = 8
RETRY_ATTEMPTS = 1

CHART_ERROR_MESSAGE = {
    "fa": "امکان دریافت اطلاعات وجود ندارد",
    "en": "Unable to fetch data",
}

ASSET_LABELS: dict[str, dict[str, str]] = {
    "gold": {"fa": "طلا", "en": "Gold"},
    "silver": {"fa": "نقره", "en": "Silver"},
    "usdt": {"fa": "تتر", "en": "Tether"},
    "btc": {"fa": "بیت کوین", "en": "Bitcoin"},
}

PRICE_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "gold": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "tgju_gold",
                    "priority": 1,
                    "url": "https://api.tgju.org/v1/data/sana/json",
                    "method": "GET",
                    "response_path": "gold",
                    "unit": "gram",
                },
                {
                    "id": "bonbast_gold",
                    "priority": 2,
                    "url": "https://www.bonbast.com/json",
                    "method": "GET",
                    "auth": {"type": "header_simulation"},
                    "response_path": "gold",
                    "unit": "gram",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "metals_dev_gold",
                    "priority": 1,
                    "url": "https://api.metals.dev/v1/latest",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "query_params": {"currency": "USD", "unit": "toz"},
                    "response_path": "metals.gold",
                    "unit": "troy_ounce",
                },
                {
                    "id": "goldapi_gold",
                    "priority": 2,
                    "url": "https://www.goldapi.io/api/XAU/USD",
                    "method": "GET",
                    "auth": {"type": "header_api_key", "key_source": "goldapi_api_key", "header_name": "x-access-token"},
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
            ],
        },
    },
    "silver": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "tgju_silver",
                    "priority": 1,
                    "url": "https://api.tgju.org/v1/data/sana/json",
                    "method": "GET",
                    "response_path": "silver",
                    "unit": "gram",
                },
                {
                    "id": "tetherland_silver",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "silver",
                    "unit": "gram",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "metals_dev_silver",
                    "priority": 1,
                    "url": "https://api.metals.dev/v1/latest",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "query_params": {"currency": "USD", "unit": "toz"},
                    "response_path": "metals.silver",
                    "unit": "troy_ounce",
                },
                {
                    "id": "goldapi_silver",
                    "priority": 2,
                    "url": "https://www.goldapi.io/api/XAG/USD",
                    "method": "GET",
                    "auth": {"type": "header_api_key", "key_source": "goldapi_api_key", "header_name": "x-access-token"},
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
            ],
        },
    },
    "usdt": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "nobitex_usdt",
                    "priority": 1,
                    "url": "https://api.nobitex.ir/market/stats",
                    "method": "POST",
                    "body": {"srcCurrency": "usdt", "dstCurrency": "rls"},
                    "response_path": "stats.usdt-rls.latest",
                    "unit": "rial",
                    "convert_to_toman": True,
                },
                {
                    "id": "tetherland_usdt",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "usdt",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "coingecko_usdt",
                    "priority": 1,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "tether.usd",
                    "unit": "usd",
                },
                {
                    "id": "coincap_usdt",
                    "priority": 2,
                    "url": "https://api.coincap.io/v2/assets/tether",
                    "method": "GET",
                    "response_path": "data.priceUsd",
                    "unit": "usd",
                },
            ],
        },
    },
    "btc": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "nobitex_btc",
                    "priority": 1,
                    "url": "https://api.nobitex.ir/market/stats",
                    "method": "POST",
                    "body": {"srcCurrency": "btc", "dstCurrency": "rls"},
                    "response_path": "stats.btc-rls.latest",
                    "unit": "rial",
                    "convert_to_toman": True,
                },
                {
                    "id": "tetherland_btc",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "btc",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "coingecko_btc",
                    "priority": 1,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "bitcoin.usd",
                    "unit": "usd",
                },
                {
                    "id": "coincap_btc",
                    "priority": 2,
                    "url": "https://api.coincap.io/v2/assets/bitcoin",
                    "method": "GET",
                    "response_path": "data.priceUsd",
                    "unit": "usd",
                },
            ],
        },
    },
}


@dataclass
class ChainResult:
    value: float | None
    source: str
    status: str
    updated_at: datetime | None
    error: str | None = None


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
        self._cache_file = self._resolve_cache_file()
        self._disk_cache = self._load_cache()
        self._load_history_from_cache()
        self._cache_dirty = False
        self._chain_health: dict[str, dict[str, dict[str, Any]]] = {}
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
            asset_ids = list(ASSET_LABELS.keys())
            snapshots = await asyncio.gather(
                *(self._build_asset_snapshot(client, asset_id) for asset_id in asset_ids)
            )

        payload = {
            "refreshed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "source": self._build_global_sources(snapshots),
            "assets": snapshots,
        }
        self._latest = LivePrices(payload=payload)
        self._last_refresh = datetime.now(UTC)
        if self._cache_dirty:
            self._persist_cache()

    async def _build_asset_snapshot(self, client: httpx.AsyncClient, asset_id: str) -> dict[str, Any]:
        iran_chain, intl_chain = await asyncio.gather(
            self._fetch_chain(client, asset_id, "iran"),
            self._fetch_chain(client, asset_id, "international"),
        )
        self._chain_health[asset_id] = {
            "iran": self._chain_result_payload(iran_chain),
            "international": self._chain_result_payload(intl_chain),
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

    def _chain_result_payload(self, chain_result: ChainResult) -> dict[str, Any]:
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

    async def _fetch_chain(
        self,
        client: httpx.AsyncClient,
        asset_id: str,
        region: str,
    ) -> ChainResult:
        providers = sorted(
            PRICE_REGISTRY[asset_id][region]["providers"], key=lambda provider: provider.get("priority", 99)
        )
        failure_messages: list[str] = []

        for provider in providers:
            try:
                value = await self._call_provider(client, asset_id, region, provider)
                if value is None:
                    raise RuntimeError("empty value")

                now = datetime.now(UTC)
                self._set_cached_value(asset_id, region, value, provider["id"], now)
                return ChainResult(
                    value=value,
                    source=provider["id"],
                    status="live",
                    updated_at=now,
                )
            except Exception as exc:
                failure_messages.append(f"{provider['id']}: {exc}")

        cached = self._get_cached_value(asset_id, region)
        if cached:
            value, source, updated_at = cached
            return ChainResult(
                value=value,
                source=f"cache ({source})",
                status="cached",
                updated_at=updated_at,
                error="; ".join(failure_messages) if failure_messages else None,
            )

        return ChainResult(
            value=None,
            source="unavailable",
            status="unavailable",
            updated_at=None,
            error="; ".join(failure_messages) if failure_messages else None,
        )

    async def _call_provider(
        self,
        client: httpx.AsyncClient,
        asset_id: str,
        region: str,
        provider: dict[str, Any],
    ) -> float | None:
        method = provider.get("method", "GET").upper()
        url = str(provider["url"])
        auth = provider.get("auth") or {}
        headers = dict(provider.get("headers") or {})
        params = dict(provider.get("query_params") or {})
        body = provider.get("body")

        if auth.get("type") == "api_key":
            key_source = auth.get("key_source")
            key_param = auth.get("key_param")
            key = getattr(settings, key_source, None) if key_source else None
            if not key:
                raise RuntimeError(f"{key_source} is not configured")
            if key_param:
                params[key_param] = key
        elif auth.get("type") == "header_api_key":
            key_source = auth.get("key_source")
            header_name = auth.get("header_name")
            key = getattr(settings, key_source, None) if key_source else None
            if not key:
                raise RuntimeError(f"{key_source} is not configured")
            if header_name:
                headers[header_name] = key
        elif auth.get("type") == "header_simulation":
            headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    ),
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://www.bonbast.com/",
                }
            )

        last_error: Exception | None = None
        attempts = 1 + RETRY_ATTEMPTS

        for _ in range(attempts):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params if method == "GET" else None,
                    json=body if method != "GET" and body is not None else None,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                raw_value = self._extract_provider_value(payload, provider, asset_id)
                if raw_value is None:
                    raise RuntimeError("could not parse numeric value")
                return self._normalize_chain_value(asset_id, region, provider, raw_value)
            except Exception as exc:  # noqa: PERF203 - keep retry logic explicit
                last_error = exc

        raise RuntimeError(str(last_error) if last_error else "provider failed")

    def _normalize_chain_value(
        self,
        asset_id: str,
        region: str,
        provider: dict[str, Any],
        value: float,
    ) -> float:
        if region != "iran":
            return value

        if provider.get("convert_to_toman"):
            return value / 10

        chain_currency = str(PRICE_REGISTRY[asset_id][region].get("currency", "")).upper()
        provider_unit = str(provider.get("unit", "")).lower()
        if chain_currency == "IRR" and "toman" not in provider_unit:
            return value / 10
        return value

    def _extract_provider_value(
        self,
        payload: Any,
        provider: dict[str, Any],
        asset_id: str,
    ) -> float | None:
        response_path = provider.get("response_path")
        if response_path:
            value_node = self._resolve_path(payload, str(response_path))
            direct_number = self._to_float(value_node)
            if direct_number is not None:
                return direct_number

            nested_number = self._extract_numeric_candidate(value_node)
            if nested_number is not None:
                return nested_number

        records = list(self._iter_dict_records(payload))
        keywords = self._asset_keywords(asset_id)
        return self._extract_value_by_keywords(records, include_keywords=keywords)

    def _resolve_path(self, payload: Any, path: str) -> Any:
        cursor: Any = payload
        for token in path.split("."):
            if isinstance(cursor, dict):
                if token not in cursor:
                    return None
                cursor = cursor[token]
                continue

            if isinstance(cursor, list):
                if token.isdigit():
                    index = int(token)
                    if index >= len(cursor):
                        return None
                    cursor = cursor[index]
                    continue
                return None

            return None
        return cursor

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
        self._set_cached_history(asset_id)

    def _history_points(self, asset_key: str) -> list[dict[str, str | float | None]]:
        points: list[dict[str, str | float | None]] = []
        for point in self._history[asset_key]:
            points.append(
                {
                    "timestamp": str(point["timestamp"]),
                    "value_usd": self._to_float(point.get("price_usd")),
                    "value_toman": self._to_float(point.get("price_toman")),
                }
            )
        return points

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

    def _asset_keywords(self, asset_id: str) -> list[str]:
        if asset_id == "gold":
            return ["gold", "xau", "طلا", "طلای", "18", "عیار"]
        if asset_id == "silver":
            return ["silver", "xag", "نقره"]
        if asset_id == "usdt":
            return ["usdt", "tether", "تتر", "usd"]
        if asset_id == "btc":
            return ["btc", "bitcoin", "بیت", "کوین"]
        return [asset_id]

    def _extract_value_by_keywords(
        self,
        records: list[dict],
        include_keywords: list[str],
    ) -> float | None:
        best_value: float | None = None
        for record in records:
            text = " ".join(
                str(record.get(key, ""))
                for key in ("symbol", "name", "title", "label", "slug", "id")
            ).lower()
            if not any(keyword in text for keyword in include_keywords):
                continue

            number = self._extract_numeric_candidate(record)
            if number is None:
                continue

            unit = str(record.get("unit", "")).lower()
            currency = str(record.get("currency", "")).lower()
            if "rial" in unit or "ريال" in unit or "rial" in currency or "ريال" in currency:
                number = number / 10

            # Prefer larger values when both gram and ounce exist and local-currency quote is usually larger.
            if best_value is None or number > best_value:
                best_value = number

        return best_value

    def _extract_numeric_candidate(self, record: Any) -> float | None:
        if isinstance(record, (int, float, str)):
            return self._to_float(record)
        if not isinstance(record, dict):
            return None

        for key in ("price", "value", "last", "rate", "buy", "sell", "close"):
            if key in record:
                number = self._to_float(record.get(key))
                if number is not None:
                    return number

        for value in record.values():
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                number = self._to_float(value)
                if number is not None:
                    return number

        return None

    def _iter_dict_records(self, value: object) -> Iterable[dict]:
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from self._iter_dict_records(nested)
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_dict_records(item)

    def _to_float(self, value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.replace(",", "").replace(" ", "").replace("_", "")
            try:
                return float(normalized)
            except ValueError:
                return None
        return None

    def _resolve_cache_file(self) -> Path:
        if Path("backend").exists():
            return Path("backend") / "price_cache.json"
        return Path(settings.price_cache_file)

    def _load_cache(self) -> dict[str, Any]:
        if not self._cache_file.exists():
            return {"chains": {}, "history": {}}
        try:
            payload = json.loads(self._cache_file.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {"chains": {}, "history": {}}
            payload.setdefault("chains", {})
            payload.setdefault("history", {})
            return payload
        except Exception:
            return {"chains": {}, "history": {}}

    def _persist_cache(self) -> None:
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._cache_file.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._disk_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._cache_file)
        self._cache_dirty = False

    def _set_cached_value(
        self,
        asset_id: str,
        region: str,
        value: float,
        source: str,
        updated_at: datetime,
    ) -> None:
        chains = self._disk_cache.setdefault("chains", {})
        asset_chain = chains.setdefault(asset_id, {})
        asset_chain[region] = {
            "value": value,
            "source": source,
            "updated_at": updated_at.replace(microsecond=0).isoformat(),
        }
        self._cache_dirty = True

    def _get_cached_value(self, asset_id: str, region: str) -> tuple[float, str, datetime] | None:
        chain_payload = (
            self._disk_cache.get("chains", {})
            .get(asset_id, {})
            .get(region, {})
        )
        if not isinstance(chain_payload, dict):
            return None

        value = self._to_float(chain_payload.get("value"))
        source = chain_payload.get("source")
        updated_raw = chain_payload.get("updated_at")
        if value is None or not isinstance(source, str) or not isinstance(updated_raw, str):
            return None

        try:
            updated_at = datetime.fromisoformat(updated_raw)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
        except ValueError:
            return None

        return (value, source, updated_at.astimezone(UTC))

    def _set_cached_history(self, asset_id: str) -> None:
        history_payload = self._disk_cache.setdefault("history", {})
        history_payload[asset_id] = self._history[asset_id][-HISTORY_MAX_POINTS:]
        self._cache_dirty = True

    def _load_history_from_cache(self) -> None:
        cached_history = self._disk_cache.get("history", {})
        if not isinstance(cached_history, dict):
            return

        for asset_id in self._history:
            points = cached_history.get(asset_id)
            if not isinstance(points, list):
                continue

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
        required_env_keys = sorted(self._required_provider_keys())
        missing_env_keys = sorted(
            key_name
            for key_name in required_env_keys
            if not getattr(settings, key_name, None)
        )

        checks = {
            "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "required_env_keys": required_env_keys,
            "missing_env_keys": missing_env_keys,
            "strict_mode": settings.pricing_require_provider_keys,
            "ok": len(missing_env_keys) == 0,
        }

        if missing_env_keys:
            message = (
                "Pricing providers are missing API keys: "
                + ", ".join(missing_env_keys)
            )
            if settings.pricing_require_provider_keys:
                raise RuntimeError(message)
            logger.warning("%s. Falling back to backup/cached chains when needed.", message)

        return checks

    def _required_provider_keys(self) -> set[str]:
        required: set[str] = set()
        for asset in PRICE_REGISTRY.values():
            for region in asset.values():
                providers = region.get("providers", [])
                for provider in providers:
                    auth = provider.get("auth") or {}
                    key_source = auth.get("key_source")
                    if key_source:
                        required.add(str(key_source))
        return required

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
                self._last_refresh.replace(microsecond=0).isoformat()
                if self._last_refresh
                else None
            ),
            "startup": self.startup_checks(),
            "chains": self._chain_health,
        }


pricing_service = PricingService()
