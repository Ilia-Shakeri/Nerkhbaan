from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update

from ..config import settings
from ..db import SessionLocal
from ..models import Alert, AlertDeliveryJob, AlertTriggerEvent
from ..observability import alert_delivery_total, background_failures_total
from .alert_engine import PermanentDeliveryError
from .alert_delivery_state import finalize_trigger_event, lock_trigger_event
from .communication_delivery import PAID_CHANNELS, dispatch_manual_events

logger = logging.getLogger(__name__)
def _safe_error(exc: Exception) -> str:
    # Provider exceptions can contain URLs, credentials, or response bodies.
    return f"{type(exc).__name__}: delivery attempt failed"


class DLQWorker:
    def __init__(self, alert_engine) -> None:
        self.alert_engine = alert_engine
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Durable alert delivery worker started")
        while self._running:
            try:
                await dispatch_manual_events(10)
                job_ids = await asyncio.to_thread(self._claim_jobs, 10)
                if not job_ids:
                    await asyncio.sleep(settings.alert_worker_poll_seconds)
                    continue
                for job_id, attempt in job_ids:
                    await self._process_job(job_id, attempt)
            except asyncio.CancelledError:
                raise
            except Exception:
                background_failures_total.labels(loop="alert_delivery").inc()
                logger.exception("Alert delivery worker cycle failed")
                await asyncio.sleep(settings.alert_worker_poll_seconds)

    async def stop(self) -> None:
        self._running = False

    def _claim_jobs(self, limit: int) -> list[tuple[int, int]]:
        db = SessionLocal()
        now = datetime.now(UTC)
        try:
            # A paid request can have been accepted before the worker died.
            # Its outcome must be reconciled by an operator, never sent again blindly.
            uncertain_events = list(db.scalars(
                update(AlertDeliveryJob)
                .where(
                    AlertDeliveryJob.channel.in_(PAID_CHANNELS),
                    AlertDeliveryJob.status == "sending",
                    AlertDeliveryJob.updated_at < now - timedelta(minutes=5),
                )
                .values(status="unknown", last_error="worker_completion_unknown", updated_at=now)
                .returning(AlertDeliveryJob.trigger_event_id)
            ))
            if uncertain_events:
                db.execute(update(AlertTriggerEvent).where(AlertTriggerEvent.id.in_(uncertain_events))
                           .values(status="delivery_unknown"))
            db.execute(
                update(AlertDeliveryJob)
                .where(
                    or_(AlertDeliveryJob.status == "processing",
                        (AlertDeliveryJob.status == "sending") & ~AlertDeliveryJob.channel.in_(PAID_CHANNELS)),
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
            return [(job.id, job.attempt_count) for job in jobs]
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _process_job(self, job_id: int, attempt: int | None = None) -> None:
        try:
            summary = await self.alert_engine.deliver_job(job_id, expected_attempt=attempt)
        except Exception as exc:
            channel = await asyncio.to_thread(self._job_channel, job_id)
            alert_delivery_total.labels(channel=channel, status="failed").inc()
            await asyncio.to_thread(self._mark_failed, job_id, exc, attempt)
            return
        if summary.get("skipped"):
            return
        alert_delivery_total.labels(channel=str(summary.get("channel", "unknown")),
                                    status=str(summary.get("status", "delivered"))).inc()
        await asyncio.to_thread(self._mark_delivered, job_id, summary, attempt)

    @staticmethod
    def _job_channel(job_id: int) -> str:
        db = SessionLocal()
        try:
            job = db.get(AlertDeliveryJob, job_id)
            return job.channel if job else "unknown"
        finally:
            db.close()

    def _mark_delivered(self, job_id: int, summary: dict, attempt: int | None = None) -> None:
        db = SessionLocal()
        now = datetime.now(UTC)
        try:
            job = db.scalar(select(AlertDeliveryJob).where(AlertDeliveryJob.id == job_id).with_for_update())
            if not job or job.status != "sending" or (attempt is not None and job.attempt_count != attempt):
                return
            # Different channels lock different jobs; the shared event serializes
            # their terminal state checks so the last one sees committed peers.
            event = lock_trigger_event(db, job.trigger_event_id)
            paid = job.channel in PAID_CHANNELS
            job.status = summary.get("status", "unknown") if paid else "delivered"
            if paid and job.status not in {"accepted", "unknown", "failed"}:
                job.status = "unknown"
            job.provider_response_summary = summary
            job.last_error = None
            if paid and job.status in {"unknown", "failed"}:
                code = summary.get("error_code")
                job.last_error = code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,80}", code) else (
                    "provider_result_unknown" if job.status == "unknown" else "provider_rejected")
            job.delivered_at = None if paid else now
            job.updated_at = now
            finalize_trigger_event(db, event)
            db.commit()
        finally:
            db.close()

    def _mark_failed(self, job_id: int, exc: Exception, attempt: int | None = None) -> None:
        db = SessionLocal()
        now = datetime.now(UTC)
        try:
            job = db.scalar(select(AlertDeliveryJob).where(AlertDeliveryJob.id == job_id).with_for_update())
            if not job or job.status not in {"processing", "sending"} or (attempt is not None and job.attempt_count != attempt):
                return
            event = lock_trigger_event(db, job.trigger_event_id)
            alert = db.get(Alert, job.alert_id)
            retry_enabled = bool(alert and alert.enable_dlq)
            permanent = isinstance(exc, PermanentDeliveryError)
            job.last_error = _safe_error(exc)
            job.updated_at = now
            if job.channel in PAID_CHANNELS:
                job.status = "unknown" if job.status == "sending" else "failed"
                job.next_retry_at = None
                job.provider_response_summary = {**(job.provider_response_summary or {}),
                    "status": job.status, "error_code": "provider_result_unknown" if job.status == "unknown" else "delivery_preflight_failed",
                    "accepted": False, "delivered": False, "answered": False}
            elif permanent:
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
            if event:
                event.status = "delivery_unknown" if job.status == "unknown" else "delivery_failed"
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
