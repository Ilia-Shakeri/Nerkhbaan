from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import settings
from .instruments import get_instrument
from .models import (
    CanonicalQuote,
    ProviderQuote,
    ProviderRuntimeState,
    canonical_json,
)

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - dependency is required in deployment
    Redis = Any  # type: ignore[misc,assignment]


class PricingRedisUnavailable(RuntimeError):
    pass


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _component(value: str) -> str:
    if not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError("Redis key component contains unsupported characters")
    return value


class PricingRedisStore:
    provider_prefix = "pricing:provider"
    canonical_prefix = "pricing:canonical"
    canonical_all_key = "pricing:canonical:all"
    history_prefix = "pricing:history-short"
    events_channel = "pricing:events"
    events_stream = "pricing:event-stream"
    persistence_stream = "pricing:persistence-stream"

    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_url = redis_url if redis_url is not None else settings.redis_url
        self._client: Redis | None = None

    def client(self) -> Redis:
        if not self.redis_url:
            raise PricingRedisUnavailable("Redis is not configured")
        if self._client is None:
            try:
                from redis.asyncio import Redis as AsyncRedis
            except ImportError as exc:
                raise PricingRedisUnavailable("Redis dependency is unavailable") from exc
            self._client = AsyncRedis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=3,
                health_check_interval=30,
            )
        return self._client

    async def ping(self) -> bool:
        try:
            return bool(await self.client().ping())
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_provider_quote(
        self, provider_id: str, instrument_id: str
    ) -> ProviderQuote | None:
        key = self.provider_quote_key(provider_id, instrument_id)
        payload = await self._get_json(key)
        return ProviderQuote.from_dict(payload) if payload else None

    async def set_provider_quote(
        self,
        quote: ProviderQuote,
        operational_ttl_seconds: int,
    ) -> None:
        instrument = get_instrument(quote.instrument_id)
        retention = max(operational_ttl_seconds, instrument.expire_after_seconds)
        key = self.provider_quote_key(quote.provider_id, quote.instrument_id)
        await self._set_json(key, quote.to_dict(authenticated=True), retention)

    async def get_canonical(self, instrument_id: str) -> CanonicalQuote | None:
        payload = await self._get_json(self.canonical_key(instrument_id))
        return CanonicalQuote.from_dict(payload) if payload else None

    async def set_canonical(self, quote: CanonicalQuote) -> None:
        instrument = get_instrument(quote.instrument_id)
        retention = max(instrument.expire_after_seconds * 4, instrument.stale_after_seconds)
        payload = quote.to_dict(authenticated=True, evaluate_status=False)
        encoded = canonical_json(payload)
        client = self.client()
        async with client.pipeline(transaction=True) as pipe:
            pipe.setex(self.canonical_key(quote.instrument_id), retention, encoded)
            pipe.hset(self.canonical_all_key, quote.instrument_id, encoded)
            pipe.expire(
                self.canonical_all_key,
                max(item.expire_after_seconds for item in _instrument_values()) * 4,
            )
            await pipe.execute()

    async def get_all_canonical(self) -> dict[str, CanonicalQuote]:
        try:
            payloads = await self.client().hgetall(self.canonical_all_key)
        except Exception as exc:
            raise PricingRedisUnavailable("Canonical cache read failed") from exc
        result: dict[str, CanonicalQuote] = {}
        for instrument_id, raw in payloads.items():
            try:
                result[instrument_id] = CanonicalQuote.from_dict(json.loads(raw))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    async def append_short_history(self, quote: CanonicalQuote) -> None:
        key = self.history_key(quote.instrument_id)
        score = quote.canonical_at.timestamp()
        cutoff = (datetime.now(UTC) - timedelta(days=31)).timestamp()
        encoded = canonical_json(
            quote.to_dict(authenticated=True, evaluate_status=False)
        )
        client = self.client()
        async with client.pipeline(transaction=True) as pipe:
            pipe.zadd(key, {encoded: score})
            pipe.zremrangebyscore(key, "-inf", cutoff)
            pipe.expire(key, 32 * 24 * 60 * 60)
            await pipe.execute()

    async def recent_canonical(
        self, instrument_id: str, *, limit: int = 120
    ) -> list[CanonicalQuote]:
        key = self.history_key(instrument_id)
        try:
            rows = await self.client().zrevrange(key, 0, max(0, limit - 1))
        except Exception as exc:
            raise PricingRedisUnavailable("Short history read failed") from exc
        quotes: list[CanonicalQuote] = []
        for row in rows:
            try:
                quotes.append(CanonicalQuote.from_dict(json.loads(row)))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return quotes

    async def get_provider_runtime(
        self, provider_id: str, instrument_id: str
    ) -> ProviderRuntimeState:
        payload = await self._get_json(self.provider_runtime_key(provider_id, instrument_id))
        if payload is None:
            return ProviderRuntimeState(provider_id=provider_id, instrument_id=instrument_id)
        return ProviderRuntimeState.from_dict(payload)

    async def set_provider_runtime(
        self, runtime: ProviderRuntimeState, ttl_seconds: int = 7 * 24 * 60 * 60
    ) -> None:
        await self._set_json(
            self.provider_runtime_key(runtime.provider_id, runtime.instrument_id),
            runtime.to_dict(),
            ttl_seconds,
        )

    async def next_sequence(self) -> int:
        try:
            return int(await self.client().incr("pricing:events:sequence"))
        except Exception as exc:
            raise PricingRedisUnavailable("Price sequence allocation failed") from exc

    async def publish_canonical(self, quote: CanonicalQuote) -> str:
        payload = quote.to_dict(authenticated=True)
        payload["event_type"] = "canonical_update"
        encoded = canonical_json(payload)
        try:
            client = self.client()
            stream_id = await client.xadd(
                self.events_stream,
                {"payload": encoded, "instrument_id": quote.instrument_id},
                maxlen=10_000,
                approximate=True,
            )
            await client.publish(self.events_channel, encoded)
            return str(stream_id)
        except Exception as exc:
            raise PricingRedisUnavailable("Price publication failed") from exc

    async def append_persistence_event(
        self,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
        maximum_length: int,
    ) -> str:
        try:
            return str(
                await self.client().xadd(
                    self.persistence_stream,
                    {
                        "event_type": event_type,
                        "idempotency_key": idempotency_key,
                        "payload": canonical_json(payload),
                    },
                    maxlen=max(1000, maximum_length),
                    approximate=True,
                )
            )
        except Exception as exc:
            raise PricingRedisUnavailable("Persistence queue write failed") from exc

    async def persistence_backlog(self) -> int | None:
        try:
            return int(await self.client().xlen(self.persistence_stream))
        except Exception:
            return None

    async def subscribe(self) -> Any:
        pubsub = self.client().pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(self.events_channel)
        return pubsub

    async def _get_json(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self.client().get(key)
        except Exception as exc:
            raise PricingRedisUnavailable("Pricing cache read failed") from exc
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PricingRedisUnavailable("Pricing cache payload is invalid") from exc
        if not isinstance(payload, dict):
            raise PricingRedisUnavailable("Pricing cache payload has invalid shape")
        return payload

    async def _set_json(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        try:
            await self.client().setex(
                key,
                max(1, int(ttl_seconds)),
                canonical_json(payload),
            )
        except Exception as exc:
            raise PricingRedisUnavailable("Pricing cache write failed") from exc

    @classmethod
    def provider_quote_key(cls, provider_id: str, instrument_id: str) -> str:
        return f"{cls.provider_prefix}:{_component(provider_id)}:{_component(instrument_id)}:quote"

    @classmethod
    def provider_runtime_key(cls, provider_id: str, instrument_id: str) -> str:
        return f"{cls.provider_prefix}:{_component(provider_id)}:{_component(instrument_id)}:runtime"

    @classmethod
    def canonical_key(cls, instrument_id: str) -> str:
        return f"{cls.canonical_prefix}:{_component(instrument_id)}"

    @classmethod
    def history_key(cls, instrument_id: str) -> str:
        return f"{cls.history_prefix}:{_component(instrument_id)}"


def _instrument_values() -> tuple[Any, ...]:
    from .instruments import INSTRUMENTS

    return tuple(INSTRUMENTS.values())


pricing_redis = PricingRedisStore()
