from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .pricing_cache import PricingCacheStore


@dataclass
class ChainResult:
    value: float | None
    source: str
    status: str
    updated_at: datetime | None
    error: str | None = None


class PricingFetcher:
    CIRCUIT_FAILURE_THRESHOLD = 3
    CIRCUIT_OPEN_SECONDS = 60

    def __init__(
        self,
        *,
        settings: Any,
        cache: PricingCacheStore,
        registry: dict[str, dict[str, dict[str, Any]]],
        timeout_seconds: int,
        retry_attempts: int,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.registry = registry
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self._provider_failures: dict[str, int] = {}
        self._circuit_open_until: dict[str, float] = {}

    async def fetch_chain(
        self,
        client: httpx.AsyncClient,
        asset_id: str,
        region: str,
    ) -> ChainResult:
        providers = sorted(
            self.registry[asset_id][region]["providers"], key=lambda provider: provider.get("priority", 99)
        )
        failures: list[str] = []

        for provider in providers:
            provider_id = str(provider["id"])
            try:
                if self._is_circuit_open(provider_id):
                    raise RuntimeError("circuit open")
                fresh_cached = self._fresh_provider_cache(asset_id, region, provider)
                if fresh_cached is not None:
                    value, source, updated_at = fresh_cached
                    return ChainResult(
                        value=value,
                        source=f"cache ({source})",
                        status="cached",
                        updated_at=updated_at,
                    )

                value = await self._call_provider(client, asset_id, region, provider)
                if value is None:
                    raise RuntimeError("empty value")

                now = datetime.now(UTC)
                self._record_provider_success(provider_id)
                self.cache.set_chain(asset_id, region, value, provider["id"], now)
                return ChainResult(
                    value=value,
                    source=provider["id"],
                    status="live",
                    updated_at=now,
                )
            except Exception as exc:
                if str(exc) != "circuit open":
                    self._record_provider_failure(provider_id)
                failures.append(f"{provider_id}: {exc}")

        cached = self.cache.get_chain(asset_id, region)
        if cached:
            value, source, updated_at = cached
            return ChainResult(
                value=value,
                source=f"cache ({source})",
                status="cached",
                updated_at=updated_at,
                error="; ".join(failures) if failures else None,
            )

        return ChainResult(
            value=None,
            source="unavailable",
            status="unavailable",
            updated_at=None,
            error="; ".join(failures) if failures else None,
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
        fixed_value = provider.get("fixed_value")
        if fixed_value is not None:
            return self._normalize_chain_value(asset_id, region, provider, float(fixed_value))

        if auth.get("type") == "api_key":
            key_source = auth.get("key_source")
            key_param = auth.get("key_param")
            key = getattr(self.settings, key_source, None) if key_source else None
            if not key:
                raise RuntimeError(f"{key_source} is not configured")
            if key_param:
                params[key_param] = key
        elif auth.get("type") == "header_api_key":
            key_source = auth.get("key_source")
            header_name = auth.get("header_name")
            key = getattr(self.settings, key_source, None) if key_source else None
            if not key:
                raise RuntimeError(f"{key_source} is not configured")
            if header_name:
                header_value = key
                if header_name.lower() == "authorization" and not str(key).lower().startswith("bearer "):
                    header_value = f"Bearer {key}"
                headers[header_name] = header_value
        elif auth.get("type") == "path_api_key":
            key_source = auth.get("key_source")
            path_token = str(auth.get("path_token") or "")
            key = getattr(self.settings, key_source, None) if key_source else None
            if not key:
                raise RuntimeError(f"{key_source} is not configured")
            if path_token:
                url = url.replace(f"/{path_token}/", f"/{key}/{path_token}/")
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

        attempts = 1 + self.retry_attempts
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params if method == "GET" else None,
                    json=body if method != "GET" and body is not None else None,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                raw_value = self._extract_orderbook_value(payload, provider) or self._extract_provider_value(
                    payload, provider, asset_id
                )
                if raw_value is None:
                    raise RuntimeError("could not parse numeric value")
                return self._normalize_chain_value(asset_id, region, provider, raw_value)
            except Exception as exc:
                last_error = exc
                # Only retry transient faults. Deterministic client errors such as
                # 404 or a geo-block 451 will never succeed, so fail over to the
                # next provider immediately instead of burning the cycle budget.
                if not self._is_retryable(exc) or attempt >= attempts - 1:
                    break
                # Exponential backoff to recover from rate limiting and timeouts.
                await asyncio.sleep(1.5 ** attempt)

        raise RuntimeError(str(last_error) if last_error else "provider failed")

    def _is_circuit_open(self, provider_id: str) -> bool:
        open_until = self._circuit_open_until.get(provider_id, 0)
        if open_until <= time.monotonic():
            self._circuit_open_until.pop(provider_id, None)
            return False
        return True

    def _record_provider_success(self, provider_id: str) -> None:
        self._provider_failures.pop(provider_id, None)
        self._circuit_open_until.pop(provider_id, None)

    def _record_provider_failure(self, provider_id: str) -> None:
        failures = self._provider_failures.get(provider_id, 0) + 1
        self._provider_failures[provider_id] = failures
        if failures >= self.CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until[provider_id] = time.monotonic() + self.CIRCUIT_OPEN_SECONDS

    def _fresh_provider_cache(
        self,
        asset_id: str,
        region: str,
        provider: dict[str, Any],
    ) -> tuple[float, str, datetime] | None:
        min_interval = self.to_float(provider.get("min_interval_seconds"))
        if not min_interval:
            return None

        cached = self.cache.get_chain(asset_id, region)
        if not cached:
            return None

        value, source, updated_at = cached
        if source != provider.get("id"):
            return None

        age_seconds = (datetime.now(UTC) - updated_at).total_seconds()
        if age_seconds > min_interval:
            return None
        return value, source, updated_at

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        # Network/timeout errors are worth retrying.
        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
        # Among HTTP status errors, retry only rate limiting (429) and 5xx.
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            return status_code == 429 or status_code >= 500
        # Parse/empty-value errors are deterministic for a given response.
        return False

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

        chain_currency = str(self.registry[asset_id][region].get("currency", "")).upper()
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
        if not response_path:
            return None
        value_node = self._resolve_path(payload, str(response_path))
        return self.to_float(value_node)

    def _extract_orderbook_value(self, payload: Any, provider: dict[str, Any]) -> float | None:
        symbol = provider.get("orderbook_symbol")
        if not symbol or not isinstance(payload, dict):
            return None

        book = payload.get(symbol)
        if not isinstance(book, dict):
            return None

        bid = self._first_orderbook_price(book.get("bids"))
        ask = self._first_orderbook_price(book.get("asks"))
        side = provider.get("orderbook_side", "mid")

        if side == "bid":
            return bid
        if side == "ask":
            return ask
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return bid if bid is not None else ask

    def _first_orderbook_price(self, levels: Any) -> float | None:
        if not isinstance(levels, list) or not levels:
            return None
        first_level = levels[0]
        if isinstance(first_level, list) and first_level:
            return self.to_float(first_level[0])
        if isinstance(first_level, dict):
            return self.to_float(first_level.get("price"))
        return None

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

    @staticmethod
    def to_float(value: object) -> float | None:
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
