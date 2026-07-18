from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from ..db import SessionLocal
from ..config import settings
from ..models import AssistantChatMessage, AssistantChatSession
from ..pricing.compatibility import legacy_pricing_adapter
from ..pricing.service import instrument_pricing_service
from .alert_engine import AlertEngine
from .dlq_worker import DLQWorker

logger = logging.getLogger(__name__)

# Cadence for the price refresh + alert evaluation loop, in seconds.
EVALUATION_INTERVAL_SECONDS = 20
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
        self._loop_task: asyncio.Task | None = None
        self._dlq_task: asyncio.Task | None = None
        self._chat_purge_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_evaluation_loop())
        self._dlq_task = asyncio.create_task(self.dlq_worker.start())
        self._chat_purge_task = asyncio.create_task(self._run_chat_purge_loop())
        logger.info("Background alert runner started")

    async def _run_evaluation_loop(self) -> None:
        while self._running:
            try:
                refresh = await instrument_pricing_service.refresh_cycle()
                redis_suspended = refresh and all(
                    result == "suspended_redis_unavailable"
                    for result in refresh.values()
                )
                if not redis_suspended:
                    prices = await legacy_pricing_adapter.get_prices()
                    await self.alert_engine.evaluate_alerts(prices)
                    await instrument_pricing_service.flush_persistence_backlog(
                        settings.pricing_persistence_flush_batch_size
                    )
                    if settings.pricing_backfill_enabled:
                        await instrument_pricing_service.process_backfill_jobs(
                            settings.pricing_backfill_max_jobs_per_cycle
                        )
            except Exception as exc:
                logger.error(
                    "Pricing cycle failed error_type=%s",
                    type(exc).__name__,
                )
            await asyncio.sleep(self.interval)

    async def _run_chat_purge_loop(self) -> None:
        while self._running:
            try:
                await asyncio.to_thread(self._purge_expired_chat_history)
            except Exception as exc:
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
        for task in (self._loop_task, self._dlq_task, self._chat_purge_task):
            if task is not None:
                task.cancel()
        logger.info("Background alert runner stopped")


background_runner = BackgroundRunner()
