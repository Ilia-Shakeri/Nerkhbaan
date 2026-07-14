from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import PushSubscription
from ..security import decode_access_token, get_client_ip, rate_limit_hit, validate_public_https_url

router = APIRouter(prefix="/api/push", tags=["push"])

_optional_bearer = HTTPBearer(auto_error=False)


def _optional_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
) -> int | None:
    """Resolve the user id when a valid token is present, otherwise None.

    Subscriptions may be created before sign-in, so authentication is optional
    here; an associated user simply lets us target deliveries later.
    """
    token = credentials.credentials if credentials else request.cookies.get(settings.auth_cookie_name)
    if not token:
        return None
    subject = decode_access_token(token)
    if subject and subject.isdigit():
        return int(subject)
    return None


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    auth: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=12, max_length=2048)
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_be_trusted(cls, value: str) -> str:
        allowed_hosts = {
            item.strip().lower()
            for item in settings.push_allowed_hosts.split(",")
            if item.strip()
        }
        return validate_public_https_url(value, allowed_hosts=allowed_hosts)


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe(
    payload: PushSubscriptionPayload,
    request: Request,
    user_id: int | None = Depends(_optional_user_id),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    rate_identity = str(user_id) if user_id is not None else get_client_ip(request)
    rate_state = rate_limit_hit("push-subscribe", rate_identity, 20, 60)
    if rate_state.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many subscription requests. Please retry later.",
            headers={"Retry-After": str(rate_state.retry_after)},
        )
    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if existing:
        if existing.user_id is not None and existing.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Subscription is already registered.",
            )
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
