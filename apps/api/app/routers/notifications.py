from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import NotificationPreference, OtpVerification, User, UserNotification
from ..security import hash_password, rate_limit_clear, rate_limit_hit, send_email, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

OTP_TTL_MINUTES = 10
PHONE_RE = re.compile(r"^\+98\d{10}$")
TELEGRAM_RE = re.compile(r"^(?:@?[A-Za-z][A-Za-z0-9_]{4,31}|-?\d{5,20})$")
EMAIL_ADAPTER = TypeAdapter(EmailStr)


class NotificationPreferencesResponse(BaseModel):
    push_app: bool
    sms_enabled: bool
    sms_phone: str | None
    sms_verified: bool
    email_enabled: bool
    email_address: str | None
    email_verified: bool
    telegram_enabled: bool
    telegram_id: str | None
    telegram_verified: bool
    silent_mode: bool
    aggressive_alerts: bool
    push_available: bool
    email_available: bool
    sms_available: bool
    telegram_available: bool


class BasicPreferenceRequest(BaseModel):
    enabled: bool


class OtpStartRequest(BaseModel):
    channel: Literal["sms", "email"]
    destination: str = Field(min_length=3, max_length=255)


class OtpConfirmRequest(OtpStartRequest):
    code: str = Field(pattern=r"^\d{6}$")


class TelegramRequest(BaseModel):
    telegram_id: str = Field(min_length=5, max_length=32)


class TelegramConfirmRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class NotificationItem(BaseModel):
    id: int
    title: str
    message: str
    severity: str
    resource_type: str | None
    resource_id: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _prefs_for(db: Session, user_id: int) -> NotificationPreference:
    prefs = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if prefs:
        return prefs
    prefs = NotificationPreference(user_id=user_id)
    db.add(prefs)
    db.commit()
    db.refresh(prefs)
    return prefs


def _to_response(prefs: NotificationPreference) -> NotificationPreferencesResponse:
    return NotificationPreferencesResponse(
        push_app=prefs.push_app,
        sms_enabled=prefs.sms_enabled,
        sms_phone=prefs.sms_phone,
        sms_verified=prefs.sms_verified,
        email_enabled=prefs.email_enabled,
        email_address=prefs.email_address,
        email_verified=prefs.email_verified,
        telegram_enabled=prefs.telegram_enabled,
        telegram_id=prefs.telegram_id,
        telegram_verified=prefs.telegram_verified,
        silent_mode=prefs.silent_mode,
        aggressive_alerts=prefs.aggressive_alerts,
        push_available=bool(settings.vapid_public_key and settings.vapid_private_key),
        email_available=bool(settings.smtp_host),
        sms_available=False,
        telegram_available=bool(
            settings.telegram_alert_delivery_enabled and settings.telegram_bot_token
        ),
    )


def _normalize_destination(channel: str, destination: str) -> str:
    value = destination.strip()
    if channel == "sms":
        if value.startswith("0"):
            value = "+98" + value[1:]
        if not value.startswith("+98"):
            value = "+98" + value.lstrip("+")
        if not PHONE_RE.match(value):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid phone number")
        return value
    try:
        return str(EMAIL_ADAPTER.validate_python(value)).lower()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email address") from exc


def _normalize_telegram(destination: str) -> str:
    value = destination.strip()
    if not TELEGRAM_RE.fullmatch(value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Telegram destination")
    if value.lstrip("-").isdigit():
        return value
    return value if value.startswith("@") else f"@{value}"


def _send_telegram_verification(destination: str, code: str) -> None:
    if not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram alert delivery is not configured.",
        )
    try:
        with httpx.Client(timeout=8.0, follow_redirects=False) as client:
            response = client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": destination,
                    "text": f"Nerkhbaan verification code: {code}",
                },
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The bot could not reach this Telegram destination. Start the bot, then retry.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram verification is temporarily unavailable.",
        ) from exc


@router.get("", response_model=list[NotificationItem])
def list_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UserNotification]:
    return list(
        db.scalars(
            select(UserNotification)
            .where(UserNotification.user_id == current_user.id)
            .order_by(UserNotification.created_at.desc())
            .limit(100)
        ).all()
    )


@router.patch("/{notification_id}/read", response_model=NotificationItem)
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserNotification:
    notification = db.scalar(
        select(UserNotification).where(
            UserNotification.id == notification_id,
            UserNotification.user_id == current_user.id,
        )
    )
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.read_at = datetime.now(UTC)
    db.commit()
    db.refresh(notification)
    return notification


@router.post(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    db.execute(
        update(UserNotification)
        .where(UserNotification.user_id == current_user.id, UserNotification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences", response_model=NotificationPreferencesResponse)
def get_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    return _to_response(_prefs_for(db, current_user.id))


@router.patch("/preferences/{key}", response_model=NotificationPreferencesResponse)
def set_basic_preference(
    key: Literal["push_app", "silent_mode", "aggressive_alerts"],
    payload: BasicPreferenceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    prefs = _prefs_for(db, current_user.id)
    setattr(prefs, key, payload.enabled)
    db.commit()
    db.refresh(prefs)
    return _to_response(prefs)


@router.post("/otp/start")
def start_otp(
    payload: OtpStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rate_state = rate_limit_hit(
        "notification-otp-start",
        f"{current_user.id}:{payload.channel}",
        5,
        10 * 60,
    )
    if rate_state.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification requests. Please retry later.",
            headers={"Retry-After": str(rate_state.retry_after)},
        )
    destination = _normalize_destination(payload.channel, payload.destination)
    if payload.channel == "sms":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS delivery is not configured.",
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    verification = OtpVerification(
        user_id=current_user.id,
        channel=payload.channel,
        destination=destination,
        code_hash=hash_password(code),
        expires_at=datetime.now(UTC) + timedelta(minutes=OTP_TTL_MINUTES),
    )
    db.add(verification)
    db.commit()
    if not send_email(
        destination,
        "Nerkhbaan verification code",
        f"Your verification code is {code}. It expires in {OTP_TTL_MINUTES} minutes.",
    ):
        db.delete(verification)
        db.commit()
        logger.warning("Notification email delivery is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email delivery is temporarily unavailable.",
        )
    return {"message": "Verification code sent.", "destination": destination, "ttl_minutes": OTP_TTL_MINUTES}


@router.post("/otp/confirm", response_model=NotificationPreferencesResponse)
def confirm_otp(
    payload: OtpConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    destination = _normalize_destination(payload.channel, payload.destination)
    confirmation_identity = f"{current_user.id}:{payload.channel}:{destination}"
    rate_state = rate_limit_hit(
        "notification-otp-confirm",
        confirmation_identity,
        10,
        10 * 60,
    )
    if rate_state.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification attempts. Please retry later.",
            headers={"Retry-After": str(rate_state.retry_after)},
        )
    verification = db.scalar(
        select(OtpVerification)
        .where(
            OtpVerification.user_id == current_user.id,
            OtpVerification.channel == payload.channel,
            OtpVerification.destination == destination,
            OtpVerification.used.is_(False),
        )
        .order_by(OtpVerification.created_at.desc())
    )
    if not verification or verification.expires_at <= datetime.now(UTC) or not verify_password(payload.code, verification.code_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    prefs = _prefs_for(db, current_user.id)
    if payload.channel == "sms":
        prefs.sms_enabled = True
        prefs.sms_phone = destination
        prefs.sms_verified = True
    else:
        prefs.email_enabled = True
        prefs.email_address = destination
        prefs.email_verified = True
    verification.used = True
    db.commit()
    rate_limit_clear("notification-otp-confirm", confirmation_identity)
    db.refresh(prefs)
    return _to_response(prefs)


@router.post("/telegram", response_model=NotificationPreferencesResponse)
def set_telegram(
    payload: TelegramRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    if not settings.telegram_alert_delivery_enabled or not settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram alert delivery is not configured.",
        )
    telegram_id = _normalize_telegram(payload.telegram_id)
    limit = rate_limit_hit(
        "notification-telegram-start",
        f"{current_user.id}:{telegram_id}",
        5,
        10 * 60,
    )
    if limit.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification requests. Please retry later.",
            headers={"Retry-After": str(limit.retry_after)},
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(
        update(OtpVerification)
        .where(
            OtpVerification.user_id == current_user.id,
            OtpVerification.channel == "telegram",
            OtpVerification.used.is_(False),
        )
        .values(used=True)
    )
    db.add(
        OtpVerification(
            user_id=current_user.id,
            channel="telegram",
            destination=telegram_id,
            code_hash=hash_password(code),
            expires_at=datetime.now(UTC) + timedelta(minutes=OTP_TTL_MINUTES),
        )
    )
    _send_telegram_verification(telegram_id, code)
    prefs = _prefs_for(db, current_user.id)
    prefs.telegram_enabled = False
    prefs.telegram_id = telegram_id
    prefs.telegram_verified = False
    db.commit()
    db.refresh(prefs)
    return _to_response(prefs)


@router.post("/telegram/confirm", response_model=NotificationPreferencesResponse)
def confirm_telegram(
    payload: TelegramConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    if (
        key == "push_app"
        and payload.enabled
        and not (settings.vapid_public_key and settings.vapid_private_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push delivery is not configured.",
        )
    prefs = _prefs_for(db, current_user.id)
    if not prefs.telegram_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Telegram verification was not started")
    identity = f"{current_user.id}:{prefs.telegram_id}"
    limit = rate_limit_hit("notification-telegram-confirm", identity, 10, 10 * 60)
    if limit.blocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification attempts. Please retry later.",
            headers={"Retry-After": str(limit.retry_after)},
        )
    verification = db.scalar(
        select(OtpVerification)
        .where(
            OtpVerification.user_id == current_user.id,
            OtpVerification.channel == "telegram",
            OtpVerification.destination == prefs.telegram_id,
            OtpVerification.used.is_(False),
        )
        .order_by(OtpVerification.created_at.desc())
    )
    if (
        verification is None
        or verification.expires_at <= datetime.now(UTC)
        or not verify_password(payload.code, verification.code_hash)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")
    verification.used = True
    prefs.telegram_enabled = True
    prefs.telegram_verified = True
    db.commit()
    rate_limit_clear("notification-telegram-confirm", identity)
    db.refresh(prefs)
    return _to_response(prefs)


@router.delete("/{channel}", response_model=NotificationPreferencesResponse)
def disable_channel(
    channel: Literal["sms", "email", "telegram"],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesResponse:
    prefs = _prefs_for(db, current_user.id)
    if channel == "sms":
        prefs.sms_enabled = False
        prefs.sms_verified = False
    elif channel == "email":
        prefs.email_enabled = False
        prefs.email_verified = False
    else:
        prefs.telegram_enabled = False
        prefs.telegram_verified = False
    db.commit()
    db.refresh(prefs)
    return _to_response(prefs)
