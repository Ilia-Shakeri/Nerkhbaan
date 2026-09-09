from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import text

from .config import settings
from .db import engine
from .migrations.state import migration_state
from .pricing.cache import PricingRedisStore


#: Backlog counts are cached: health is polled every few seconds by Docker and
#: by monitoring, and four unbounded COUNT(*) queries per probe is real load.
_BACKLOG_CACHE_SECONDS = 15
_backlog_cache: dict[str, Any] = {"at": 0.0, "value": None}
_backlog_lock = threading.Lock()


def _backlog_counts(connection: Any) -> dict[str, int]:
    now = time.monotonic()
    with _backlog_lock:
        cached = _backlog_cache["value"]
        if cached is not None and now - _backlog_cache["at"] < _BACKLOG_CACHE_SECONDS:
            return cached
    row = connection.execute(
        text(
            """
            SELECT
                (SELECT count(*) FROM pricing_backfill_jobs WHERE status IN ('pending','retrying')) AS backfill,
                (SELECT count(*) FROM alert_delivery_jobs WHERE status = 'dead') AS dead_letters,
                (SELECT count(*) FROM pricing_anomalies WHERE status = 'open') AS anomalies,
                -- Bounded: the exact size of a large backlog does not change
                -- the decision, only whether one exists.
                (SELECT count(*) FROM (
                    SELECT 1 FROM pricing_persistence_events
                    WHERE status IN ('pending','retrying') LIMIT 10000
                ) AS capped) AS persistence
            """
        )
    ).mappings().one()
    value = {
        "backfill": int(row["backfill"]),
        "persistence": int(row["persistence"]),
        "dead_letters": int(row["dead_letters"]),
        "anomalies": int(row["anomalies"]),
    }
    with _backlog_lock:
        _backlog_cache["at"] = now
        _backlog_cache["value"] = value
    return value


def _database_health() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            migration = migration_state(engine)
            backlog = _backlog_counts(connection)
        return {
            "status": "connected",
            "migration": migration,
            "backlog": backlog,
        }
    except Exception:
        return {
            "status": "disconnected",
            "migration": {"current": False, "version": None},
            "backlog": {},
        }


_redis_probe: Any | None = None


def _redis_probe_client() -> Any:
    """One reusable client for health probes.

    Building a client per probe opened a fresh TCP connection on every
    liveness check, which at the container healthcheck interval is a steady
    churn of connections against a Redis that has a connection ceiling.
    """
    global _redis_probe
    if _redis_probe is None:
        import redis

        _redis_probe = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            health_check_interval=30,
        )
    return _redis_probe


def _redis_health() -> dict[str, Any]:
    if not settings.redis_url:
        return {"status": "disabled", "persistence_stream": None, "event_stream": None}
    try:
        client = _redis_probe_client()
        client.ping()
        return {
            "status": "connected",
            "persistence_stream": int(
                client.xlen(PricingRedisStore.persistence_stream)
            ),
            # "pricing:events" is the pub/sub channel, which has no length;
            # the stream is a separate key.
            "event_stream": int(client.xlen(PricingRedisStore.events_stream)),
        }
    except Exception:
        return {"status": "disconnected", "persistence_stream": None, "event_stream": None}


def health_snapshot() -> dict[str, Any]:
    database = _database_health()
    cache = _redis_health()
    migration_ok = bool(database["migration"].get("current"))
    database_ok = database["status"] == "connected"
    cache_ok = cache["status"] == "connected"
    fully_operational = database_ok and cache_ok and migration_ok
    # Readiness requires the database. Authentication, alerts and admin all go
    # through PostgreSQL, so a cache-only instance cannot serve the product and
    # must not be handed traffic.
    ready = database_ok and migration_ok
    return {
        "status": "ok" if fully_operational else "degraded",
        "ready": ready,
        "database": database["status"],
        "redis": cache["status"],
        "migration_version": database["migration"].get("version"),
        "migration_current": migration_ok,
        "persistence_backlog": database["backlog"].get("persistence", cache["persistence_stream"]),
        "backfill_backlog": database["backlog"].get("backfill"),
        "dead_letter_backlog": database["backlog"].get("dead_letters"),
        "anomaly_count": database["backlog"].get("anomalies"),
        "websocket_fanout": "operational" if cache_ok else "degraded_polling_only",
    }
