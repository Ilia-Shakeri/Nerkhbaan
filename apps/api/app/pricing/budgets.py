from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .cache import PricingRedisStore, pricing_redis
from .models import RequestPurpose
from .registry import INSTRUMENT_BUDGETS, ProviderDefinition

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
    ) -> BudgetDecision:
        cooldown = await self.cooldown_remaining(provider.provider_id)
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
        if purpose in {RequestPurpose.NORMAL, RequestPurpose.BACKFILL}:
            provider_limits[0] = max(1, math.floor(provider_limits[0] * 0.8))
            provider_limits[1] = max(1, math.floor(provider_limits[1] * 0.8))
            provider_limits[2] = max(
                1,
                provider_limits[2]
                - budget.reserved_anomaly_requests
                - budget.reserved_fallback_requests,
            )

        key_limits: list[tuple[str, int, int]] = [
            (
                f"pricing:budget:{provider.provider_id}:minimum_interval",
                1,
                max(1, budget.minimum_interval_seconds),
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
        elif purpose is RequestPurpose.FALLBACK:
            if budget.reserved_fallback_requests <= 0:
                return BudgetDecision(False, "no_reserved_fallback_budget", 0)
            key_limits.append(
                (
                    f"pricing:budget:{provider.provider_id}:fallback:day:{day_bucket}",
                    budget.reserved_fallback_requests,
                    172800,
                )
            )

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

    async def record_rate_limit(self, provider: ProviderDefinition) -> None:
        key = f"pricing:budget:{provider.provider_id}:cooldown"
        await self.store.client().setex(
            key,
            provider.budget.cooldown_after_429_seconds,
            "1",
        )

    async def cooldown_remaining(self, provider_id: str) -> int:
        key = f"pricing:budget:{provider_id}:cooldown"
        ttl = await self.store.client().ttl(key)
        return max(0, int(ttl))

    async def pressure(self, provider: ProviderDefinition) -> float:
        day_bucket = int(time.time()) // 86400
        key = f"pricing:budget:{provider.provider_id}:all:day:{day_bucket}"
        current = await self.store.client().get(key)
        used = int(current or 0)
        return min(1.0, used / max(1, provider.budget.requests_per_day))


pricing_budget = RedisRequestBudget()
