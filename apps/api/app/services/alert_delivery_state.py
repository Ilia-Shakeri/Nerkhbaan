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
    if not statuses:
        return
    if "unknown" in statuses:
        event.status = "delivery_unknown"
    elif any(status in {"failed", "dead"} for status in statuses):
        event.status = "delivery_failed"
    elif all(status in {"accepted", "delivered", "cancelled"} for status in statuses):
        if "accepted" in statuses:
            event.status = "accepted"
        else:
            event.status = "delivered" if "delivered" in statuses else "cancelled"
