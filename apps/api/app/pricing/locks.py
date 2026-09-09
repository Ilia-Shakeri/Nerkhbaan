from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from ..config import settings
from .cache import PricingRedisStore, pricing_redis

logger = logging.getLogger(__name__)

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_EXTEND_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class LockLease:
    key: str
    owner_token: str
    ttl_ms: int


class DistributedPricingLocks:
    def __init__(self, store: PricingRedisStore = pricing_redis) -> None:
        self.store = store

    async def acquire(self, key: str, ttl_ms: int) -> LockLease | None:
        if ttl_ms < 1000:
            raise ValueError("Lock TTL must be at least one second")
        owner = uuid.uuid4().hex
        acquired = await self.store.client().set(key, owner, nx=True, px=ttl_ms)
        if not acquired:
            return None
        return LockLease(key=key, owner_token=owner, ttl_ms=ttl_ms)

    async def release(self, lease: LockLease) -> bool:
        result = await self.store.client().eval(
            _RELEASE_SCRIPT, 1, lease.key, lease.owner_token
        )
        return bool(result)

    async def extend(self, lease: LockLease, ttl_ms: int | None = None) -> bool:
        extension = ttl_ms or lease.ttl_ms
        result = await self.store.client().eval(
            _EXTEND_SCRIPT,
            1,
            lease.key,
            lease.owner_token,
            extension,
        )
        return bool(result)

    @asynccontextmanager
    async def _renewing(self, lease: LockLease | None) -> AsyncIterator[None]:
        """Hold a lease for as long as the body runs.

        A fixed TTL is a bet on how long the critical section takes. Refresh
        work is bounded by third-party HTTP, so that bet loses regularly and
        two workers then refresh the same instrument at once. Renewing at a
        third of the TTL keeps the lease alive while the body is running and
        still lets it lapse quickly if the worker dies.
        """
        if lease is None:
            yield
            return
        interval = max(1.0, lease.ttl_ms / 3000)

        async def renew() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    if not await self.extend(lease):
                        logger.warning("Lost pricing lease for %s", lease.key)
                        return
                except Exception:
                    logger.warning("Could not extend pricing lease for %s", lease.key)
                    return

        task = asyncio.create_task(renew())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @asynccontextmanager
    async def refresh_lock(
        self, instrument_id: str, ttl_ms: int | None = None
    ) -> AsyncIterator[LockLease | None]:
        key = f"pricing:lock:refresh:{instrument_id}"
        lease = await self.acquire(
            key, ttl_ms or settings.pricing_lock_ttl_seconds * 1000
        )
        try:
            async with self._renewing(lease):
                yield lease
        finally:
            if lease is not None:
                await self.release(lease)

    @asynccontextmanager
    async def provider_lock(
        self, provider_id: str, instrument_id: str, ttl_ms: int = 15_000
    ) -> AsyncIterator[LockLease | None]:
        key = f"pricing:lock:provider:{provider_id}:{instrument_id}"
        lease = await self.acquire(key, ttl_ms)
        try:
            yield lease
        finally:
            if lease is not None:
                await self.release(lease)

    @asynccontextmanager
    async def backfill_lock(
        self, instrument_id: str, ttl_ms: int = 120_000
    ) -> AsyncIterator[LockLease | None]:
        key = f"pricing:lock:backfill:{instrument_id}"
        lease = await self.acquire(key, ttl_ms)
        try:
            async with self._renewing(lease):
                yield lease
        finally:
            if lease is not None:
                await self.release(lease)


pricing_locks = DistributedPricingLocks()
