from __future__ import annotations

from collections.abc import Iterable
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
            try:
                value = await self._call_provider(client, asset_id, region, provider)
                if value is None:
                    raise RuntimeError("empty value")

                now = datetime.now(UTC)
                self.cache.set_chain(asset_id, region, value, provider["id"], now)
                return ChainResult(
                    value=value,
                    source=provider["id"],
                    status="live",
                    updated_at=now,
                )
            except Exception as exc:
                failures.append(f"{provider['id']}: {exc}")

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

        attempts = 1 + self.retry_attempts
        last_error: Exception | None = None

        for _ in range(attempts):
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
                raw_value = self._extract_provider_value(payload, provider, asset_id)
                if raw_value is None:
                    raise RuntimeError("could not parse numeric value")
                return self._normalize_chain_value(asset_id, region, provider, raw_value)
            except Exception as exc:
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
        if response_path:
            value_node = self._resolve_path(payload, str(response_path))
            direct_number = self.to_float(value_node)
            if direct_number is not None:
                return direct_number

            nested_number = self._extract_numeric_candidate(value_node)
            if nested_number is not None:
                return nested_number

        records = list(self._iter_dict_records(payload))
        return self._extract_value_by_keywords(records, include_keywords=self._asset_keywords(asset_id))

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

    def _extract_value_by_keywords(self, records: list[dict], include_keywords: list[str]) -> float | None:
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

            if best_value is None or number > best_value:
                best_value = number

        return best_value

    def _extract_numeric_candidate(self, record: Any) -> float | None:
        if isinstance(record, (int, float, str)):
            return self.to_float(record)
        if not isinstance(record, dict):
            return None

        for key in ("price", "value", "last", "rate", "buy", "sell", "close"):
            if key in record:
                number = self.to_float(record.get(key))
                if number is not None:
                    return number

        for value in record.values():
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                number = self.to_float(value)
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
