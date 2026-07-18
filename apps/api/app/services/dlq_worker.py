from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update

from ..config import settings
from ..db import SessionLocal
from ..models import Alert, AlertDeliveryJob, AlertTriggerEvent
from .alert_engine import PermanentDeliveryError

logger = logging.getLogger(__name__)
_SECRET_PATTERN = re.compile(r"(?i)(token|secret|password|authorization|cookie)=?[^\s,;]*")


def _safe_error(exc: Exception) -> str:
    message = _SECRET_PATTERN.sub(r"\1=[redacted]", str(exc).replace("\r", " ").replace("\n", " "))
    return f"{type(exc).__name__}: {message}"[:500]


class DLQWorker:
    def __init__(self, alert_engine) -> None:
        self.alert_engine = alert_engine
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Durable alert delivery worker started")
        while self._running:
            try:
                job_ids = await asyncio.to_thread(self._claim_jobs, 10)
                if not job_ids:
                    await asyncio.sleep(settings.alert_worker_poll_seconds)
                    continue
                for job_id in job_ids:
                    await self._process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Alert delivery worker cycle failed")
                await asyncio.sleep(settings.alert_worker_poll_seconds)

    async def stop(self) -> None:
        self._running = False

    def _claim_jobs(self, limit: int) -> list[int]:
        db = SessionLocal()
        now = datetime.now(UTC)
        try:
            db.execute(
                update(AlertDeliveryJob)
                .where(
                    AlertDeliveryJob.status == "processing",
                    AlertDeliveryJob.updated_at < now - timedelta(minutes=5),
                )
                .values(status="retrying", next_retry_at=now, updated_at=now)
            )
            jobs = db.scalars(
                select(AlertDeliveryJob)
                .where(
                    AlertDeliveryJob.status.in_(("pending", "retrying")),
                    or_(
                        AlertDeliveryJob.next_retry_at.is_(None),
                        AlertDeliveryJob.next_retry_at <= now,
                    ),
                )
                .order_by(AlertDeliveryJob.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for job in jobs:
                job.status = "processing"
                job.attempt_count += 1
                job.updated_at = now
            db.commit()
            return [job.id for job in jobs]
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _process_job(self, job_id: int) -> None:
        try:
            summary = await self.alert_engine.deliver_job(job_id)
        except Exception as exc:
            await asyncio.to_thread(self._mark_failed, job_id, exc)
            return
        await asyncio.to_thread(self._mark_delivered, job_id, summary)

    def _mark_delivered(self, job_id: int, summary: dict) -> None:
        db = SessionLocal()
        now = datetime.now(UTC)
        try:
            job = db.get(AlertDeliveryJob, job_id)
            if not job:
                return
            job.status = "delivered"
            job.provider_response_summary = summary
            job.last_error = None
            job.delivered_at = now
            job.updated_at = now
            db.flush()
            remaining = db.scalar(
                select(func.count(AlertDeliveryJob.id)).where(
                    AlertDeliveryJob.trigger_event_id == job.trigger_event_id,
                    AlertDeliveryJob.status.not_in(("delivered", "cancelled")),
                )
            )
            if remaining == 0:
                event = db.get(AlertTriggerEvent, job.trigger_event_id)
                if event:
                    event.status = "delivered"
            db.commit()
        finally:
            db.close()

    def _mark_failed(self, job_id: int, exc: Exception) -> None:
        db = SessionLocal()
        now = datetime.now(UTC)
        try:
            job = db.get(AlertDeliveryJob, job_id)
            if not job:
                return
            alert = db.get(Alert, job.alert_id)
            retry_enabled = bool(alert and alert.enable_dlq)
            permanent = isinstance(exc, PermanentDeliveryError)
            job.last_error = _safe_error(exc)
            job.updated_at = now
            if permanent:
                job.status = "dead"
                job.dead_at = now
            elif not retry_enabled:
                job.status = "failed"
            elif job.attempt_count >= settings.alert_delivery_max_attempts:
                job.status = "dead"
                job.dead_at = now
            else:
                delay = min(
                    settings.alert_delivery_backoff_max_seconds,
                    settings.alert_delivery_backoff_base_seconds * (2 ** max(0, job.attempt_count - 1)),
                )
                job.status = "retrying"
                job.next_retry_at = now + timedelta(seconds=delay + random.randint(0, max(1, delay // 5)))
            event = db.get(AlertTriggerEvent, job.trigger_event_id)
            if event:
                event.status = "delivery_failed"
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
