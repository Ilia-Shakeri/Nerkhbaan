from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AlertDeliveryJob, AlertTriggerEvent


def lock_trigger_event(db: Session, event_id: int) -> AlertTriggerEvent | None:
    """Call after locking the job, before changing any delivery state."""
    return db.scalar(select(AlertTriggerEvent).where(AlertTriggerEvent.id == event_id).with_for_update())


def finalize_trigger_event(db: Session, event: AlertTriggerEvent | None) -> None:
    if event is None:
        return
    db.flush()
    statuses = list(db.scalars(select(AlertDeliveryJob.status).where(AlertDeliveryJob.trigger_event_id == event.id)))
    if statuses and all(status in {"delivered", "cancelled"} for status in statuses):
        event.status = "delivered" if "delivered" in statuses else "cancelled"
