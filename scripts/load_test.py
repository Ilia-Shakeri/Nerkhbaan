#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import statistics
import time

import httpx


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def measure(
    base_url: str, requests: int, concurrency: int, *,
    duration_seconds: float = 0, requests_per_second: float = 0,
    paths: tuple[str, ...] = ("/api/prices",), maximum_p95_ms: float = 1000,
    transport=None,
) -> dict:
    latencies: list[float] = []
    failures: Counter = Counter()
    statuses: Counter = Counter()
    path_counts: Counter = Counter()
    started_count = 0
    started = 0.0
    deadline = 0.0
    admission = asyncio.Lock()
    timeout = httpx.Timeout(10.0)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout, limits=limits, transport=transport) as client:
        ready = await client.get("/api/health/ready")
        ready.raise_for_status()
        if ready.json().get("ready") is not True:
            raise RuntimeError("target is not ready")

        async def worker() -> None:
            nonlocal started_count
            while True:
                async with admission:
                    now = time.perf_counter()
                    if (duration_seconds and now >= deadline) or (not duration_seconds and started_count >= requests):
                        return
                    if requests_per_second:
                        scheduled = started + started_count / requests_per_second
                        if duration_seconds and scheduled >= deadline:
                            return
                        await asyncio.sleep(max(0, scheduled - now))
                        if duration_seconds and time.perf_counter() >= deadline:
                            return
                    path = paths[started_count % len(paths)]
                    started_count += 1
                request_started = time.perf_counter()
                try:
                    response = await client.get(path)
                    statuses[str(response.status_code)] += 1
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("invalid response contract")
                    if path.split("?", 1)[0] == "/api/prices" and not isinstance(payload.get("assets"), list):
                        raise ValueError("invalid prices contract")
                    if "/history" in path and not isinstance(payload.get("points"), list):
                        raise ValueError("invalid history contract")
                except Exception as exc:
                    failures[type(exc).__name__] += 1
                finally:
                    latencies.append(time.perf_counter() - request_started)
                    path_counts[path] += 1

        started = time.perf_counter()
        deadline = started + duration_seconds
        # Only concurrency workers are scheduled, even for a long soak run.
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        elapsed = time.perf_counter() - started

    p95_ms = percentile(latencies, 0.95) * 1000
    achieved_rate = len(latencies) / max(elapsed, 0.001)
    rate_passed = not requests_per_second or achieved_rate >= requests_per_second * 0.95
    return {
        "checked_at": datetime.now(UTC).isoformat(), "requests": len(latencies),
        "concurrency": concurrency, "elapsed_seconds": round(elapsed, 3),
        "requested_duration_seconds": duration_seconds,
        "target_requests_per_second": requests_per_second,
        "requests_per_second": round(achieved_rate, 3),
        "minimum_rate_fraction": 0.95, "rate_passed": rate_passed,
        "failures": sum(failures.values()), "failure_types": dict(failures),
        "http_statuses": dict(statuses), "path_counts": dict(path_counts),
        "p50_ms": round(statistics.median(latencies) * 1000, 3) if latencies else 0,
        "p95_ms": round(p95_ms, 3), "p99_ms": round(percentile(latencies, 0.99) * 1000, 3),
        "maximum_p95_ms": maximum_p95_ms,
        "passed": bool(latencies) and not failures and rate_passed and p95_ms <= maximum_p95_ms,
    }


async def run(base_url: str, requests: int, concurrency: int) -> int:
    result = await measure(base_url, requests, concurrency)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--duration-seconds", type=float, default=0)
    parser.add_argument("--rps", type=float, default=0)
    parser.add_argument("--maximum-p95-ms", type=float, default=1000)
    parser.add_argument("--paths", default="/api/prices")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or (not args.duration_seconds and args.concurrency > args.requests):
        parser.error("requests and concurrency must be positive; concurrency cannot exceed requests")
    if any(not math.isfinite(v) for v in (args.duration_seconds, args.rps, args.maximum_p95_ms)) or args.duration_seconds < 0 or args.rps < 0 or args.maximum_p95_ms <= 0:
        parser.error("duration/rate must be finite and nonnegative; latency budget must be positive")
    paths = tuple(path.strip() for path in args.paths.split(",") if path.strip())
    if not paths or any(not path.startswith("/api/") or path.startswith("//") for path in paths):
        parser.error("paths must be relative API paths")
    result = asyncio.run(measure(args.base_url.rstrip("/"), args.requests, args.concurrency,
                                duration_seconds=args.duration_seconds, requests_per_second=args.rps,
                                paths=paths, maximum_p95_ms=args.maximum_p95_ms))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_suffix(args.report.suffix + ".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.report)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
