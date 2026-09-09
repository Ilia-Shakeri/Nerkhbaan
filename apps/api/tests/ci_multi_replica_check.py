from __future__ import annotations

import asyncio
import uuid

from app.pricing.cache import PricingRedisStore
from app.pricing.locks import DistributedPricingLocks


async def check() -> None:
    store_a = PricingRedisStore()
    store_b = PricingRedisStore()
    locks_a = DistributedPricingLocks(store_a)
    locks_b = DistributedPricingLocks(store_b)
    instrument = f"CI_{uuid.uuid4().hex}"
    try:
        async with locks_a.refresh_lock(instrument, ttl_ms=2_000) as first:
            if first is None:
                raise RuntimeError("first replica failed to acquire lease")
            async with locks_b.refresh_lock(instrument, ttl_ms=2_000) as second:
                if second is not None:
                    raise RuntimeError("two replicas acquired one refresh lease")
        async with locks_b.refresh_lock(instrument, ttl_ms=2_000) as handover:
            if handover is None:
                raise RuntimeError("lease handover failed after release")
    finally:
        await store_a.close()
        await store_b.close()
    print("Multi-replica refresh lease exclusion and handover passed")


if __name__ == "__main__":
    asyncio.run(check())
