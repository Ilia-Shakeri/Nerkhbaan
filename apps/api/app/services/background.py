from __future__ import annotations

import asyncio
import logging
import secrets
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from ..db import SessionLocal
from ..config import settings
from ..models import AssistantChatMessage, AssistantChatSession
from ..pricing.compatibility import legacy_pricing_adapter
from ..pricing.service import instrument_pricing_service
from ..observability import background_failures_total
from .alert_engine import AlertEngine
from .dlq_worker import DLQWorker

logger = logging.getLogger(__name__)

CHAT_RETENTION_DAYS = 31
CHAT_PURGE_INTERVAL_SECONDS = 60 * 60 * 24


class BackgroundRunner:
    """Owns the long-running tasks that turn stored alerts into deliveries.

    A single loop refreshes prices and evaluates alerts; a companion DLQ worker
    drains failed deliveries with exponential backoff.
    """

    def __init__(self, interval: int | None = None) -> None:
        self.interval = interval or settings.pricing_refresh_interval_seconds
        self.alert_engine = AlertEngine()
        self.dlq_worker = DLQWorker(alert_engine=self.alert_engine)
        self._running = False
        self._refresh_task: asyncio.Task | None = None
        self._alert_task: asyncio.Task | None = None
        self._maintenance_task: asyncio.Task | None = None
        self._dlq_task: asyncio.Task | None = None
        self._chat_purge_task: asyncio.Task | None = None
        self._pricing_available = True
        self._refresh_state: dict[str, object] = {
            "state": "not_started",
            "last_started_at": None,
            "last_completed_at": None,
            "last_error_type": None,
            "result_counts": {},
        }

    def refresh_health(self) -> dict[str, object]:
        """Small safe state snapshot for health routes and deployment checks."""
        return {
            "enabled": settings.background_tasks_enabled,
            **self._refresh_state,
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Refresh, alert evaluation and maintenance run as independent loops.
        # Chaining them meant a slow upstream provider stalled alert delivery
        # for as long as the refresh took, which on a price-alert product is
        # the one thing that must not happen.
        self._refresh_task = asyncio.create_task(self._run_refresh_loop())
        self._alert_task = asyncio.create_task(self._run_alert_loop())
        self._maintenance_task = asyncio.create_task(self._run_maintenance_loop())
        self._dlq_task = asyncio.create_task(self.dlq_worker.start())
        self._chat_purge_task = asyncio.create_task(self._run_chat_purge_loop())
        logger.info("Background alert runner started")

    def _next_delay(self, base: int) -> float:
        """Spread workers out so replicas do not all wake in lockstep."""
        jitter = max(0, settings.pricing_refresh_jitter_seconds)
        return max(1.0, base + (secrets.randbelow(jitter * 2 + 1) - jitter if jitter else 0))

    async def _run_refresh_loop(self) -> None:
        while self._running:
            self._refresh_state.update(
                {
                    "state": "running",
                    "last_started_at": datetime.now(UTC).isoformat(),
                    "last_error_type": None,
                }
            )
            try:
                refresh = await instrument_pricing_service.refresh_cycle()
                self._pricing_available = not (
                    refresh
                    and all(
                        result == "suspended_redis_unavailable"
                        for result in refresh.values()
                    )
                )
                counts = Counter(
                    "failed" if result.startswith("failed:") else result
                    for result in refresh.values()
                )
                usable = sum(
                    count
                    for status, count in counts.items()
                    if status in {"live", "confirmed", "fresh_cache", "derived_fallback"}
                )
                self._refresh_state.update(
                    {
                        "state": "healthy" if usable else "degraded",
                        "last_completed_at": datetime.now(UTC).isoformat(),
                        "result_counts": dict(sorted(counts.items())),
                    }
                )
            except Exception as exc:
                background_failures_total.labels(loop="pricing_refresh").inc()
                self._refresh_state.update(
                    {
                        "state": "failed",
                        "last_completed_at": datetime.now(UTC).isoformat(),
                        "last_error_type": type(exc).__name__,
                    }
                )
                logger.error("Pricing refresh failed error_type=%s", type(exc).__name__)
            await asyncio.sleep(self._next_delay(self.interval))

    async def _run_alert_loop(self) -> None:
        while self._running:
            try:
                if self._pricing_available:
                    prices = await legacy_pricing_adapter.get_prices()
                    await self.alert_engine.evaluate_alerts(prices)
            except Exception as exc:
                background_failures_total.labels(loop="alert_evaluation").inc()
                logger.error(
                    "Alert evaluation failed error_type=%s", type(exc).__name__
                )
            await asyncio.sleep(max(1, settings.alert_worker_poll_seconds))

    async def _run_maintenance_loop(self) -> None:
        while self._running:
            try:
                if self._pricing_available:
                    await instrument_pricing_service.flush_persistence_backlog(
                        settings.pricing_persistence_flush_batch_size
                    )
                    if settings.pricing_backfill_enabled:
                        await instrument_pricing_service.process_backfill_jobs(
                            settings.pricing_backfill_max_jobs_per_cycle
                        )
            except Exception as exc:
                background_failures_total.labels(loop="pricing_maintenance").inc()
                logger.error(
                    "Pricing maintenance failed error_type=%s", type(exc).__name__
                )
            await asyncio.sleep(
                max(1, settings.pricing_persistence_flush_interval_seconds)
            )

    async def _run_chat_purge_loop(self) -> None:
        while self._running:
            try:
                await asyncio.to_thread(self._purge_expired_chat_history)
            except Exception as exc:
                background_failures_total.labels(loop="chat_purge").inc()
                logger.error(f"Chat history purge failed: {exc}")
            await asyncio.sleep(CHAT_PURGE_INTERVAL_SECONDS)

    def _purge_expired_chat_history(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=CHAT_RETENTION_DAYS)
        db = SessionLocal()
        try:
            expired_ids = db.scalars(
                select(AssistantChatSession.id).where(AssistantChatSession.updated_at < cutoff)
            ).all()
            if not expired_ids:
                return
            db.execute(delete(AssistantChatMessage).where(AssistantChatMessage.session_id.in_(expired_ids)))
            db.execute(delete(AssistantChatSession).where(AssistantChatSession.id.in_(expired_ids)))
            db.commit()
        finally:
            db.close()

    async def stop(self) -> None:
        self._running = False
        await self.dlq_worker.stop()
        tasks = [
            task
            for task in (
                self._refresh_task,
                self._alert_task,
                self._maintenance_task,
                self._dlq_task,
                self._chat_purge_task,
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        # Await the cancellations so shutdown does not race in-flight database
        # work against the connection pool being torn down.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Background alert runner stopped")


background_runner = BackgroundRunner()
