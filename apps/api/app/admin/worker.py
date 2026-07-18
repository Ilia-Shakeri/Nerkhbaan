from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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


class AdminOperationsWorker:
    def __init__(self, poll_seconds: float = 3.0) -> None:
        self.poll_seconds = poll_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
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
        while self._running:
            claimed = await asyncio.to_thread(self._claim)
            if claimed is None:
                await asyncio.sleep(self.poll_seconds)
                continue
            try:
                if claimed.job_type == "instrument_refresh" and claimed.resource_id:
                    await instrument_pricing_service.refresh_instrument(claimed.resource_id)
                else:
                    raise RuntimeError("Unsupported administrator job type")
            except Exception as exc:
                await asyncio.to_thread(self._fail, claimed.id, exc)
            else:
                await asyncio.to_thread(self._complete, claimed.id)

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
            )
        finally:
            db.close()

    @staticmethod
    def _complete(job_id: int) -> None:
        db = SessionLocal()
        try:
            job = db.get(AdminJob, job_id)
            if job is not None:
                complete_admin_job(db, job)
        finally:
            db.close()

    @staticmethod
    def _fail(job_id: int, error: Exception) -> None:
        db = SessionLocal()
        try:
            job = db.get(AdminJob, job_id)
            if job is not None:
                fail_admin_job(db, job, f"{type(error).__name__}: operation failed")
        finally:
            db.close()


admin_operations_worker = AdminOperationsWorker()
