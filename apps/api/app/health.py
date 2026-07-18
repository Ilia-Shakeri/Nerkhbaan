from __future__ import annotations

from typing import Any

from sqlalchemy import text

from .config import settings
from .db import engine
from .migrations.state import migration_state


def _database_health() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            migration = migration_state(engine)
            backlog = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM pricing_backfill_jobs WHERE status IN ('pending','retrying')) AS backfill,
                        (SELECT count(*) FROM pricing_persistence_events WHERE status IN ('pending','retrying')) AS persistence,
                        (SELECT count(*) FROM alert_delivery_jobs WHERE status = 'dead') AS dead_letters,
                        (SELECT count(*) FROM pricing_anomalies WHERE status = 'open') AS anomalies
                    """
                )
            ).mappings().one()
        return {
            "status": "connected",
            "migration": migration,
            "backlog": {
                "backfill": int(backlog["backfill"]),
                "persistence": int(backlog["persistence"]),
                "dead_letters": int(backlog["dead_letters"]),
                "anomalies": int(backlog["anomalies"]),
            },
        }
    except Exception:
        return {
            "status": "disconnected",
            "migration": {"current": False, "version": None},
            "backlog": {},
        }


def _redis_health() -> dict[str, Any]:
    if not settings.redis_url:
        return {"status": "disabled", "persistence_stream": None, "event_stream": None}
    try:
        import redis

        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        return {
            "status": "connected",
            "persistence_stream": int(client.xlen("pricing:persistence-stream")),
            "event_stream": int(client.xlen("pricing:events")),
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
    ready = (database_ok and migration_ok) or cache_ok
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
