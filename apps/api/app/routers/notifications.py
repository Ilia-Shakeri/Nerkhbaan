from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import NotificationPreference, OtpVerification, User
from ..security import hash_password, rate_limit_clear, rate_limit_hit, send_email, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

OTP_TTL_MINUTES = 10
PHONE_RE = re.compile(r"^\+98\d{10}$")
TELEGRAM_RE = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")
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


class BasicPreferenceRequest(BaseModel):
    enabled: bool


class OtpStartRequest(BaseModel):
    channel: Literal["sms", "email"]
    destination: str = Field(min_length=3, max_length=255)


class OtpConfirmRequest(OtpStartRequest):
    code: str = Field(pattern=r"^\d{6}$")


class TelegramRequest(BaseModel):
    telegram_id: str = Field(min_length=5, max_length=32)


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
    telegram_id = payload.telegram_id.strip()
    if not TELEGRAM_RE.match(telegram_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid Telegram ID")
    prefs = _prefs_for(db, current_user.id)
    prefs.telegram_enabled = True
    prefs.telegram_id = telegram_id if telegram_id.startswith("@") else f"@{telegram_id}"
    prefs.telegram_verified = False
    db.commit()
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
