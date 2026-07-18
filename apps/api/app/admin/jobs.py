from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import AdminJob
from .redaction import sanitize_error


def claim_admin_job(
    db: Session,
    supported_types: set[str],
) -> AdminJob | None:
    now = datetime.now(UTC)
    abandoned_before = now - timedelta(minutes=5)
    job = db.scalar(
        select(AdminJob)
        .where(
            AdminJob.job_type.in_(supported_types),
            or_(
                and_(
                    AdminJob.status.in_({"pending", "retrying"}),
                    (AdminJob.next_attempt_at.is_(None)) | (AdminJob.next_attempt_at <= now),
                ),
                and_(
                    AdminJob.status == "processing",
                    AdminJob.updated_at < abandoned_before,
                ),
            ),
        )
        .order_by(AdminJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "processing"
    job.attempt_count += 1
    db.commit()
    db.refresh(job)
    return job


def complete_admin_job(db: Session, job: AdminJob) -> None:
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    job.last_error = None
    db.commit()


def fail_admin_job(db: Session, job: AdminJob, error: str, *, retryable: bool = True) -> None:
    job.last_error = sanitize_error(error)
    if retryable and job.attempt_count < 5:
        job.status = "retrying"
        job.next_attempt_at = datetime.now(UTC) + timedelta(
            seconds=min(3600, 30 * (2 ** max(0, job.attempt_count - 1)))
        )
    else:
        job.status = "dead"
        job.completed_at = datetime.now(UTC)
    db.commit()
