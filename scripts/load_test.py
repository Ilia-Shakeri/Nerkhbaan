#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def run(base_url: str, requests: int, concurrency: int) -> int:
    latencies: list[float] = []
    failures: list[str] = []
    semaphore = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        ready = await client.get("/api/health/ready")
        ready.raise_for_status()
        if ready.json().get("ready") is not True:
            raise RuntimeError("target is not ready")

        async def one() -> None:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get("/api/prices")
                    response.raise_for_status()
                    if not isinstance(response.json().get("assets"), list):
                        raise RuntimeError("invalid prices contract")
                except Exception as exc:
                    failures.append(type(exc).__name__)
                finally:
                    latencies.append(time.perf_counter() - started)

        started = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(requests)))
        elapsed = time.perf_counter() - started

    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    rate = requests / max(elapsed, 0.001)
    print(f"requests={requests} failures={len(failures)} rps={rate:.2f} p50_ms={statistics.median(ordered) * 1000:.1f} p95_ms={p95 * 1000:.1f}")
    return 1 if failures or p95 > 1.0 else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=25)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.concurrency > args.requests:
        parser.error("requests and concurrency must be positive; concurrency cannot exceed requests")
    return asyncio.run(run(args.base_url.rstrip("/"), args.requests, args.concurrency))


if __name__ == "__main__":
    raise SystemExit(main())
