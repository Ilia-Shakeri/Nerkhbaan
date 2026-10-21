from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings
from .models import AdminSecret, OperationalSetting


DEFAULT_POLICY = {
    "enabled": False, "critical_only": True, "persist_seconds": 60,
    "max_attempts": 1, "cooldown_seconds": 900, "max_calls_per_day": 3,
    "quiet_hours": {"enabled": True, "start": "22:00", "end": "08:00",
                    "timezone": "Asia/Tehran", "critical_bypass": False},
}
PROVIDER_CATALOG = [
    {"id": "kavenegar", "label": "کاوه‌نگار", "channels": ["sms"],
     "config_fields": [{"key": "sender", "label": "شماره فرستنده", "type": "text", "required": True},
                       {"key": "template_id", "label": "الگوی تأیید شماره", "type": "text", "required": False}],
     "credential_fields": [{"key": "api_key", "label": "کلید سرویس", "type": "secret", "required": True}]},
    {"id": "asterisk_ari", "label": "مرکز تماس استریسک / ایزابل", "channels": ["voip"],
     "config_fields": [{"key": key, "label": label, "type": kind, "required": required} for key, label, kind, required in (
         ("endpoint", "نشانی امن مرکز تلفن", "url", True), ("trunk", "ترانک", "text", True),
         ("ari_app", "برنامه تماس", "text", False), ("caller_id", "شماره تماس‌گیرنده", "text", False),
         ("context", "بافت شماره‌گیری", "text", False), ("extension", "داخلی", "text", False))],
     "credential_fields": [{"key": "username", "label": "نام کاربری", "type": "secret", "required": True},
                           {"key": "password", "label": "رمز عبور", "type": "secret", "required": True}]},
]


def _cipher() -> Fernet:
    configured = settings.communications_encryption_key
    try:
        if not configured:
            raise ValueError("missing")
        key = configured.get_secret_value() if hasattr(configured, "get_secret_value") else str(configured)
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(503, "Communications encryption key is not configured") from exc


def encryption_ready() -> bool:
    try:
        _cipher()
        return True
    except HTTPException:
        return False


def encrypt_value(value: str) -> str:
    return _cipher().encrypt(value.encode("utf8")).decode("ascii")


def decrypt_value(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise HTTPException(503, "Communications secret is unavailable") from exc


def normalize_phone(value: str) -> str:
    value = str(value).strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if value.startswith("0098"):
        value = "+98" + value[4:]
    elif value.startswith("0"):
        value = "+98" + value[1:]
    elif value.startswith("98"):
        value = "+" + value
    if not re.fullmatch(r"\+989[0-9]{9}", value):
        raise HTTPException(422, "A valid Iranian mobile number is required")
    return value


def mask_phone(value: str) -> str:
    return "***" + normalize_phone(value)[-4:]


def setting_key(channel: str) -> str:
    if channel not in {"sms", "voip"}:
        raise HTTPException(422, "Unsupported communications channel")
    return "communications.provider." + channel


def secret_key(channel: str) -> str:
    setting_key(channel)
    return "communications." + channel + ".credentials"


def read_secret(db: Session, channel: str) -> dict[str, str]:
    row = db.scalar(select(AdminSecret).where(AdminSecret.key == secret_key(channel)))
    if row is None:
        return {}
    try:
        value = json.loads(decrypt_value(row.ciphertext))
        if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
            raise ValueError("shape")
        return value
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "Communications secret is unavailable") from exc


def credentials_valid(provider_id: str, values: dict[str, Any]) -> bool:
    required = {"kavenegar": {"api_key"}, "asterisk_ari": {"username", "password"}}.get(provider_id)
    if required is None or set(values) != required:
        return False
    for key, value in values.items():
        if not isinstance(value, str) or not value.strip() or len(value) > 1024 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            return False
        if key == "username" and (":" in value or len(value) > 256):
            return False
        if key == "api_key" and not re.fullmatch(r"[A-Za-z0-9]{8,256}", value):
            return False
    return True


def read_provider(db: Session, channel: str) -> dict[str, Any]:
    from ..services.communication_transport import TransportConfigurationError, validate_provider_config
    row = db.scalar(select(OperationalSetting).where(OperationalSetting.key == setting_key(channel), OperationalSetting.scope_id == "global"))
    value = row.value if row and isinstance(row.value, dict) else {}
    provider_id = str(value.get("provider_id", "none"))
    config = value.get("config", {})
    if not isinstance(config, dict):
        config = {}
    secret = db.scalar(select(AdminSecret).where(AdminSecret.key == secret_key(channel)))
    configured = False
    if secret is not None and encryption_ready():
        try:
            validate_provider_config(channel, provider_id, config)
            configured = credentials_valid(provider_id, read_secret(db, channel))
        except (HTTPException, TransportConfigurationError):
            pass
    return {"channel": channel, "provider_id": provider_id, "enabled": value.get("enabled") is True,
            "config": deepcopy(config), "version": row.version if row else 0,
            "secret_configured": secret is not None, "secret_hint": "••••" if secret else None,
            "credentials": {"configured": secret is not None, "masked": "••••" if secret else None},
            "configured": configured, "ready": configured and value.get("enabled") is True,
            "automatic_retry": False,
            "last_error": None}


def read_policy(db: Session) -> dict[str, Any]:
    row = db.scalar(select(OperationalSetting).where(OperationalSetting.key == "communications.call_policy", OperationalSetting.scope_id == "global"))
    policy = deepcopy(DEFAULT_POLICY)
    if row and isinstance(row.value, dict):
        policy.update(deepcopy(row.value))
    policy["version"] = row.version if row else 0
    policy["automatic_retry"] = False
    return policy


def lock_setting(db: Session, key: str) -> OperationalSetting | None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    return db.scalar(select(OperationalSetting).where(OperationalSetting.key == key, OperationalSetting.scope_id == "global").with_for_update())


def check_version(row: OperationalSetting | None, expected: int) -> None:
    if expected != (row.version if row else 0):
        raise HTTPException(409, "Communications settings changed; reload before writing")


def save_setting(db: Session, key: str, value: dict, actor: int, row: OperationalSetting | None) -> OperationalSetting:
    if row is None:
        row = OperationalSetting(key=key, scope_id="global", value=deepcopy(value), version=1, updated_by=actor)
        db.add(row)
    else:
        row.value = deepcopy(value)
        row.version += 1
        row.updated_by = actor
    return row
