from __future__ import annotations

import asyncio
import logging

from .alert_engine import AlertEngine
from .dlq_worker import DLQWorker
from .pricing import pricing_service

logger = logging.getLogger(__name__)

# Cadence for the price refresh + alert evaluation loop, in seconds.
EVALUATION_INTERVAL_SECONDS = 20


class BackgroundRunner:
    """Owns the long-running tasks that turn stored alerts into deliveries.

    A single loop refreshes prices and evaluates alerts; a companion DLQ worker
    drains failed deliveries with exponential backoff.
    """

    def __init__(self, interval: int = EVALUATION_INTERVAL_SECONDS) -> None:
        self.interval = interval
        self.dlq_worker = DLQWorker(alert_engine=None)
        self.alert_engine = AlertEngine(dlq_callback=self.dlq_worker.enqueue)
        # Resolve the circular reference now that both objects exist.
        self.dlq_worker.alert_engine = self.alert_engine
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._dlq_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_evaluation_loop())
        self._dlq_task = asyncio.create_task(self.dlq_worker.start())
        logger.info("Background alert runner started")

    async def _run_evaluation_loop(self) -> None:
        while self._running:
            try:
                prices = await pricing_service.get_prices()
                await self.alert_engine.evaluate_alerts(prices)
            except Exception as exc:
                logger.error(f"Alert evaluation cycle failed: {exc}")
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        self._running = False
        await self.dlq_worker.stop()
        for task in (self._loop_task, self._dlq_task):
            if task is not None:
                task.cancel()
        logger.info("Background alert runner stopped")


background_runner = BackgroundRunner()
