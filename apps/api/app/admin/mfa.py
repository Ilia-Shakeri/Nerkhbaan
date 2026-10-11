from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User
from .models import AdminMfaProfile


def _cipher() -> Fernet:
    key = hmac.new(settings.jwt_secret_key.encode(), b"admin-totp-encryption-v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=503, detail="MFA key unavailable; restore the configured encryption key") from exc


def totp_code(secret: str, step: int) -> str:
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return f"{value % 1_000_000:06d}"


def backup_digest(value: str) -> str:
    return hashlib.sha256(value.strip().upper().encode()).hexdigest()


def new_backup_codes() -> tuple[list[str], list[str]]:
    codes = [secrets.token_hex(10).upper() for _ in range(10)]
    return codes, [backup_digest(code) for code in codes]


def verify_mfa(db: Session, user_id: int, code: str | None, *, enrollment: bool = False) -> AdminMfaProfile | None:
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    profile = db.scalar(select(AdminMfaProfile).where(AdminMfaProfile.user_id == user_id).with_for_update().execution_options(populate_existing=True))
    if enrollment and profile is not None and profile.totp_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    if profile is None or (not enrollment and not profile.totp_enabled):
        if enrollment:
            raise HTTPException(status_code=409, detail="Start MFA enrollment first")
        return profile
    if not code or not profile.encrypted_totp_secret:
        raise HTTPException(status_code=401, detail="MFA code required")
    if not enrollment:
        digest = backup_digest(code)
        codes = list(profile.backup_code_digests or [])
        for index, saved in enumerate(codes):
            if hmac.compare_digest(saved, digest):
                codes.pop(index)
                profile.backup_code_digests = codes
                return profile
    secret = decrypt_secret(profile.encrypted_totp_secret)
    step = int(time.time()) // 30
    for candidate in (step, step - 1, step + 1):
        if candidate <= (profile.last_totp_step if profile.last_totp_step is not None else -1):
            continue
        if hmac.compare_digest(totp_code(secret, candidate), code.strip()):
            profile.last_totp_step = candidate
            return profile
    raise HTTPException(status_code=401, detail="MFA code invalid or already used")
