from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..db import SessionLocal
from ..pricing.service import instrument_pricing_service
from .jobs import claim_admin_job, complete_admin_job, fail_admin_job
from .models import AdminJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedAdminJob:
    id: int
    job_type: str
    resource_id: str | None
    payload: dict[str, Any]
    attempt_count: int


class AdminOperationsWorker:
    def __init__(self, poll_seconds: float = 3.0) -> None:
        self.poll_seconds = poll_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self.last_heartbeat_at: datetime | None = None
        self.last_error_type: str | None = None

    async def start(self) -> None:
        if self._running and self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        try:
            while self._running:
                self.last_heartbeat_at = datetime.now(UTC)
                try:
                    claimed = await asyncio.to_thread(self._claim)
                    if claimed is None:
                        await asyncio.sleep(self.poll_seconds)
                        continue
                    try:
                        if claimed.job_type == "instrument_refresh" and claimed.resource_id:
                            await asyncio.wait_for(instrument_pricing_service.refresh_instrument(claimed.resource_id), timeout=180)
                        else:
                            raise RuntimeError("Unsupported administrator job type")
                    except Exception as exc:
                        await asyncio.to_thread(self._fail, claimed.id, exc, claimed.attempt_count)
                    else:
                        await asyncio.to_thread(self._complete, claimed.id, claimed.attempt_count)
                    self.last_error_type = None
                except Exception as exc:
                    self.last_error_type = type(exc).__name__
                    logger.error("Administrator worker cycle failed error_type=%s", self.last_error_type)
                    await asyncio.sleep(self.poll_seconds)
        finally:
            self._running = False

    def health(self) -> dict[str, Any]:
        active = self._running and self._task is not None and not self._task.done()
        age = (datetime.now(UTC) - self.last_heartbeat_at).total_seconds() if self.last_heartbeat_at else None
        fresh = age is not None and age <= max(240, self.poll_seconds * 4)
        return {"status": "active" if active and fresh else "stalled" if active else "stopped", "last_heartbeat_at": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None, "heartbeat_age_seconds": age, "last_error_type": self.last_error_type}

    @staticmethod
    def _claim() -> ClaimedAdminJob | None:
        db = SessionLocal()
        try:
            job = claim_admin_job(db, {"instrument_refresh"})
            if job is None:
                return None
            return ClaimedAdminJob(
                id=job.id,
                job_type=job.job_type,
                resource_id=job.resource_id,
                payload=dict(job.payload),
                attempt_count=job.attempt_count,
            )
        finally:
            db.close()

    @staticmethod
    def _complete(job_id: int, attempt_count: int) -> None:
        db = SessionLocal()
        try:
            job = db.get(AdminJob, job_id)
            if job is not None and job.status == "processing" and job.attempt_count == attempt_count:
                complete_admin_job(db, job, expected_attempt=attempt_count)
        finally:
            db.close()

    @staticmethod
    def _fail(job_id: int, error: Exception, attempt_count: int) -> None:
        db = SessionLocal()
        try:
            job = db.get(AdminJob, job_id)
            if job is not None and job.status == "processing" and job.attempt_count == attempt_count:
                fail_admin_job(db, job, f"{type(error).__name__}: operation failed", expected_attempt=attempt_count)
        finally:
            db.close()


admin_operations_worker = AdminOperationsWorker()
