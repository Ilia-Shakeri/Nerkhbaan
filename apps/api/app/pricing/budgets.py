from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .cache import PricingRedisStore, pricing_redis
from .models import RequestPurpose
from .registry import INSTRUMENT_BUDGETS, PROVIDERS, ProviderDefinition
from .source_snapshots import SourceSnapshotUnavailable, source_url_digest

_CONSUME_SCRIPT = """
local count = #KEYS
for index = 1, count do
  local limit = tonumber(ARGV[(index - 1) * 2 + 1])
  local current = tonumber(redis.call('get', KEYS[index]) or '0')
  if current >= limit then
    return {0, index, current}
  end
end
local minimum_remaining = 2147483647
for index = 1, count do
  local limit = tonumber(ARGV[(index - 1) * 2 + 1])
  local ttl = tonumber(ARGV[(index - 1) * 2 + 2])
  local current = redis.call('incr', KEYS[index])
  if current == 1 then
    redis.call('expire', KEYS[index], ttl)
  end
  local remaining = limit - current
  if remaining < minimum_remaining then
    minimum_remaining = remaining
  end
end
return {1, minimum_remaining, 0}
"""

_EXTEND_COOLDOWN_SCRIPT = """
local current = redis.call('pttl', KEYS[1])
local requested = tonumber(ARGV[1]) * 1000
if current ~= -1 and current < requested then
  redis.call('set', KEYS[1], '1', 'PX', requested)
end
return 1
"""


def _source_scope(provider: ProviderDefinition, source_url: str | None) -> str | None:
    if provider.source_family == "nerkhsanj":
        return f"pricing:budget:source:nerkhsanj:{source_url_digest(source_url or provider.url)}"
    if provider.source_family == "gta_silver":
        source = urlsplit(source_url or provider.url)
        if (source.scheme != "https" or source.hostname != "gtasilver.com"
                or source.path != "/api/silver-price" or source.query or source.fragment
                or source.username or source.password or source.port not in (None, 443)):
            raise ValueError("provider_endpoint_not_allowed")
        digest = hashlib.sha256(b"https://gtasilver.com/api/silver-price").hexdigest()
        return f"pricing:budget:source:gta_silver:{digest}"
    return None


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason: str
    minimum_remaining: int


class RedisRequestBudget:
    def __init__(self, store: PricingRedisStore = pricing_redis) -> None:
        self.store = store

    async def consume(
        self,
        provider: ProviderDefinition,
        purpose: RequestPurpose,
        *,
        source_url: str | None = None,
    ) -> BudgetDecision:
        if min(provider.budget.requests_per_minute, provider.budget.requests_per_hour,
               provider.budget.requests_per_day) <= 0:
            return BudgetDecision(False, "provider_budget_disabled", 0)
        try:
            source_scope = _source_scope(provider, source_url)
        except (ValueError, SourceSnapshotUnavailable):
            return BudgetDecision(False, "provider_endpoint_not_allowed", 0)
        cooldown = await self.cooldown_remaining(provider, source_url=source_url)
        if cooldown > 0:
            return BudgetDecision(False, "provider_cooldown", 0)

        instrument_policy = INSTRUMENT_BUDGETS[provider.instrument_id]
        now = int(time.time())
        minute_bucket = now // 60
        hour_bucket = now // 3600
        day_bucket = now // 86400
        budget = provider.budget

        provider_limits = [
            budget.requests_per_minute,
            budget.requests_per_hour,
            budget.requests_per_day,
        ]
        if purpose in {
            RequestPurpose.NORMAL,
            RequestPurpose.BACKFILL,
            RequestPurpose.FALLBACK,
        }:
            provider_limits[0] = max(1, math.floor(provider_limits[0] * 0.8))
            provider_limits[1] = max(1, math.floor(provider_limits[1] * 0.8))
            provider_limits[2] = max(
                1,
                provider_limits[2]
                - budget.reserved_anomaly_requests
                - budget.reserved_fallback_requests,
            )

        interval_key = f"pricing:budget:{provider.provider_id}:minimum_interval"
        interval = max(1, budget.minimum_interval_seconds)
        if source_scope:
            interval_key = f"{source_scope}:minimum_interval"
            interval = max(60, interval)
        key_limits: list[tuple[str, int, int]] = [
            (
                interval_key,
                1,
                interval,
            ),
            (
                f"pricing:budget:{provider.provider_id}:all:minute:{minute_bucket}",
                provider_limits[0],
                120,
            ),
            (
                f"pricing:budget:{provider.provider_id}:all:hour:{hour_bucket}",
                provider_limits[1],
                7200,
            ),
            (
                f"pricing:budget:{provider.provider_id}:all:day:{day_bucket}",
                provider_limits[2],
                172800,
            ),
            (
                f"pricing:budget:instrument:{provider.instrument_id}:minute:{minute_bucket}",
                instrument_policy.requests_per_minute,
                120,
            ),
            (
                f"pricing:budget:instrument:{provider.instrument_id}:hour:{hour_bucket}",
                instrument_policy.requests_per_hour,
                7200,
            ),
        ]
        if purpose is RequestPurpose.ANOMALY:
            if budget.reserved_anomaly_requests <= 0:
                return BudgetDecision(False, "no_reserved_anomaly_budget", 0)
            key_limits.append(
                (
                    f"pricing:budget:{provider.provider_id}:anomaly:day:{day_bucket}",
                    budget.reserved_anomaly_requests,
                    172800,
                )
            )
        # A route with the FALLBACK role is often the only reachable route
        # during an upstream outage. Its normal refresh must use the bounded
        # provider budget, not stop after the small reserve was consumed.

        keys = [item[0] for item in key_limits]
        arguments: list[int] = []
        for _key, limit, ttl in key_limits:
            arguments.extend((limit, ttl))
        result = await self.store.client().eval(
            _CONSUME_SCRIPT,
            len(keys),
            *keys,
            *arguments,
        )
        allowed = bool(int(result[0]))
        if not allowed:
            return BudgetDecision(False, f"budget_limit_{int(result[1])}", 0)
        return BudgetDecision(True, "allowed", max(0, int(result[1])))

    async def record_rate_limit(
        self,
        provider: ProviderDefinition,
        *,
        source_url: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        scope = _source_scope(provider, source_url)
        key = f"{scope}:cooldown" if scope else f"pricing:budget:{provider.provider_id}:cooldown"
        retry_after = (
            min(retry_after_seconds, 86_400)
            if type(retry_after_seconds) is int and retry_after_seconds >= 0
            else 0
        )
        seconds = max(1, provider.budget.cooldown_after_429_seconds, retry_after)
        await self.store.client().eval(_EXTEND_COOLDOWN_SCRIPT, 1, key, seconds)

    async def cooldown_remaining(
        self,
        provider: ProviderDefinition | str,
        *,
        source_url: str | None = None,
    ) -> int:
        definition = PROVIDERS.get(provider) if isinstance(provider, str) else provider
        provider_id = provider if isinstance(provider, str) else provider.provider_id
        redis = self.store.client()
        # Keep an existing route cooldown while older workers are being replaced.
        ttl = int(await redis.ttl(f"pricing:budget:{provider_id}:cooldown"))
        remaining = 1 if ttl == -1 else max(0, ttl)
        scope = _source_scope(definition, source_url) if definition is not None else None
        if scope:
            milliseconds = int(await redis.pttl(f"{scope}:cooldown"))
            shared = 1 if milliseconds == -1 else max(0, math.ceil(milliseconds / 1000))
            remaining = max(remaining, shared)
        return remaining

    async def pressure(self, provider: ProviderDefinition) -> float:
        day_bucket = int(time.time()) // 86400
        key = f"pricing:budget:{provider.provider_id}:all:day:{day_bucket}"
        current = await self.store.client().get(key)
        used = int(current or 0)
        return min(1.0, used / max(1, provider.budget.requests_per_day))


pricing_budget = RedisRequestBudget()
