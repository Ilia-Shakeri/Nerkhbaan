from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import PushSubscription
from ..security import decode_access_token

router = APIRouter(prefix="/api/push", tags=["push"])

_optional_bearer = HTTPBearer(auto_error=False)


def _optional_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> int | None:
    """Resolve the user id when a valid token is present, otherwise None.

    Subscriptions may be created before sign-in, so authentication is optional
    here; an associated user simply lets us target deliveries later.
    """
    if not credentials:
        return None
    subject = decode_access_token(credentials.credentials)
    if subject and subject.isdigit():
        return int(subject)
    return None


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: PushKeys


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe(
    payload: PushSubscriptionPayload,
    user_id: int | None = Depends(_optional_user_id),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if existing:
        # Keep the stored keys and ownership current on re-subscription.
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
        if user_id is not None:
            existing.user_id = user_id
    else:
        db.add(
            PushSubscription(
                user_id=user_id,
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
            )
        )
    db.commit()
    return {"status": "subscribed"}
