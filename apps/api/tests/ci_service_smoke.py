from __future__ import annotations

import uuid

from redis import Redis
from sqlalchemy import text

from app.config import settings
from app.db import engine


def check_timescale() -> None:
    with engine.connect() as connection:
        extension_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar_one()
        preload_libraries = connection.execute(text("SHOW shared_preload_libraries")).scalar_one()
        hypertables = set(
            connection.execute(
                text(
                    "SELECT hypertable_name FROM timescaledb_information.hypertables "
                    "WHERE hypertable_schema = 'public'"
                )
            ).scalars()
        )

    required = {"market_prices", "provider_quotes", "canonical_quotes"}
    missing = sorted(required - hypertables)
    if missing:
        raise RuntimeError(f"Timescale hypertables missing: {missing}")
    if "timescaledb" not in preload_libraries:
        raise RuntimeError("TimescaleDB is not preloaded")
    print(f"TimescaleDB ready: version={extension_version}, hypertables={len(hypertables)}")


def check_redis() -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for the integration smoke test")

    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    key = f"nerkhbaan:ci:smoke:{uuid.uuid4().hex}"
    try:
        if not client.ping():
            raise RuntimeError("Redis ping failed")
        client.set(key, "ok", ex=30)
        if client.get(key) != "ok":
            raise RuntimeError("Redis round trip failed")
    finally:
        client.delete(key)
        client.close()
    print("Redis ready: ping and round trip passed")


def main() -> None:
    try:
        check_timescale()
        check_redis()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
