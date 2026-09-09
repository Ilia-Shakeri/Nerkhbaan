from __future__ import annotations

import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Gauge, Histogram


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="background"
)

pricing_refresh_total = Counter(
    "nerkhbaan_pricing_refresh_total",
    "Pricing refresh outcomes.",
    ["instrument", "status"],
)
pricing_refresh_duration_seconds = Histogram(
    "nerkhbaan_pricing_refresh_duration_seconds",
    "Pricing refresh duration.",
    ["instrument"],
)
canonical_age_seconds = Gauge(
    "nerkhbaan_canonical_age_seconds",
    "Age of the latest canonical quote.",
    ["instrument"],
)
canonical_status = Gauge(
    "nerkhbaan_canonical_status",
    "Current canonical status; one active status per instrument.",
    ["instrument", "status"],
)
CANONICAL_STATUSES = (
    "live", "confirmed", "fresh_cache", "verifying", "suspicious",
    "suspicious_unconfirmed", "derived_fallback", "stale", "expired",
    "unpersisted", "unavailable", "failed",
)


def set_canonical_status(instrument: str, status: str) -> None:
    normalized = status if status in CANONICAL_STATUSES else "failed"
    for candidate in CANONICAL_STATUSES:
        canonical_status.labels(instrument=instrument, status=candidate).set(
            1 if candidate == normalized else 0
        )


provider_request_total = Counter(
    "nerkhbaan_provider_request_total",
    "Provider request outcomes.",
    ["provider", "instrument", "status"],
)
provider_request_duration_seconds = Histogram(
    "nerkhbaan_provider_request_duration_seconds",
    "Provider request duration.",
    ["provider", "instrument"],
)
alert_delivery_total = Counter(
    "nerkhbaan_alert_delivery_total",
    "Alert delivery outcomes.",
    ["channel", "status"],
)
background_failures_total = Counter(
    "nerkhbaan_background_failures_total",
    "Background loop failures.",
    ["loop"],
)
queue_depth = Gauge(
    "nerkhbaan_queue_depth",
    "Known durable queue and review backlogs.",
    ["queue"],
)


class JsonFormatter(logging.Formatter):
    _fields = (
        "instrument_id",
        "provider_id",
        "status",
        "channel",
        "job_id",
        "error_type",
        "duration_seconds",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for field in self._fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def set_queue_depths(values: dict[str, int | None]) -> None:
    for name, value in values.items():
        if value is not None:
            queue_depth.labels(queue=name).set(max(0, int(value)))
