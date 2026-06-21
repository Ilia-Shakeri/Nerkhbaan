from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class DLQEntry:
    def __init__(
        self,
        alert_id: int,
        delivery_method: int,
        error: str,
        enqueued_at: datetime,
        retry_count: int = 0,
        next_retry_at: datetime | None = None,
    ):
        self.alert_id = alert_id
        self.delivery_method = delivery_method
        self.error = error
        self.enqueued_at = enqueued_at
        self.retry_count = retry_count
        self.next_retry_at = next_retry_at or datetime.now(UTC)


class DLQWorker:
    def __init__(self, alert_engine):
        self.alert_engine = alert_engine
        self.queue: list[DLQEntry] = []
        self.max_retries = 5
        self.backoff_base = 60
        self._running = False

    async def enqueue(self, alert, delivery_method: int, error: Exception) -> None:
        entry = DLQEntry(
            alert_id=alert.id,
            delivery_method=delivery_method,
            error=str(error),
            enqueued_at=datetime.now(UTC),
            retry_count=0,
            next_retry_at=datetime.now(UTC) + timedelta(seconds=self.backoff_base)
        )
        self.queue.append(entry)
        logger.info(f"Enqueued failed alert delivery: alert_id={alert.id}, method={delivery_method}")

    async def start(self) -> None:
        self._running = True
        logger.info("DLQ worker started")
        
        while self._running:
            await self._process_queue()
            await asyncio.sleep(30)

    async def stop(self) -> None:
        self._running = False
        logger.info("DLQ worker stopped")

    async def _process_queue(self) -> None:
        now = datetime.now(UTC)
        pending = [e for e in self.queue if e.next_retry_at <= now]
        
        for entry in pending:
            if entry.retry_count >= self.max_retries:
                logger.warning(f"Max retries exceeded for alert_id={entry.alert_id}, dropping from DLQ")
                self.queue.remove(entry)
                continue
            
            try:
                await self._retry_delivery(entry)
                self.queue.remove(entry)
                logger.info(f"DLQ retry succeeded for alert_id={entry.alert_id}")
            except Exception as e:
                entry.retry_count += 1
                backoff_delay = self.backoff_base * (2 ** entry.retry_count)
                entry.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_delay)
                logger.error(f"DLQ retry failed for alert_id={entry.alert_id}, attempt={entry.retry_count}: {e}")

    async def _retry_delivery(self, entry: DLQEntry) -> None:
        await asyncio.sleep(0.1)
        logger.info(f"Retrying delivery for alert_id={entry.alert_id}, method={entry.delivery_method}")
