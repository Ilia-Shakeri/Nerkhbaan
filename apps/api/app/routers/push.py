from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import PushSubscription, User, UserSession
from ..security import decode_access_claims, get_client_ip, rate_limit_hit, validate_public_https_url

router = APIRouter(prefix="/api/push", tags=["push"])

_optional_bearer = HTTPBearer(auto_error=False)


def _optional_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> int | None:
    """Resolve the user id when a valid token is present, otherwise None.

    Subscriptions may be created before sign-in, so authentication is optional
    here; an associated user simply lets us target deliveries later.
    """
    token = credentials.credentials if credentials else request.cookies.get(settings.auth_cookie_name)
    if not token:
        return None
    claims = decode_access_claims(token)
    if not claims:
        return None
    subject = str(claims.get("sub") or "")
    if not subject.isdigit():
        return None
    # A subscription binds future alert deliveries to an account, so it must be
    # checked against the same revocation state as any other authenticated
    # call rather than trusting an unexpired signature alone.
    user = db.get(User, int(subject))
    if not user or not user.is_active:
        return None
    if int(claims.get("sv", 1)) != user.security_version:
        return None
    session_id = claims.get("sid")
    if session_id:
        session = db.scalar(
            select(UserSession).where(
                UserSession.id == str(session_id),
                UserSession.user_id == user.id,
            )
        )
        if not session or session.revoked_at is not None or session.expires_at <= datetime.now(UTC):
            return None
    return user.id


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    auth: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class PushSubscriptionPayload(BaseModel):
    # Bounded by the push_subscriptions.endpoint column; accepting more only
    # moved the failure to a 500 at insert time.
    endpoint: str = Field(min_length=12, max_length=500)
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


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=12, max_length=500)


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
        # A browser endpoint belongs to the device, not to an account. Refusing
        # to re-bind it left the second user of a shared device permanently
        # unable to enable push, and left anonymous subscriptions - created
        # before sign-in - orphaned so alerts never reached them.
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
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


@router.post(
    "/unsubscribe",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def unsubscribe(
    payload: PushUnsubscribeRequest,
    db: Session = Depends(get_db),
) -> Response:
    """Drop a browser subscription.

    Signing out has to be able to detach the endpoint, otherwise the next user
    of the device inherits the previous account's notifications.
    """
    subscription = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if subscription is not None:
        db.delete(subscription)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
