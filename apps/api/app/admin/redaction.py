from __future__ import annotations

from datetime import UTC, date, datetime
import re
from typing import Any


_SECRET_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "otp",
    "totp",
    "recovery",
    "backup_code",
    "session_string",
    "private_key",
)
_PERSONAL_MARKERS = ("email", "phone", "destination", "telegram_id")


def _masked_personal(value: Any) -> str:
    text = str(value or "")
    if "@" in text:
        local, domain = text.split("@", 1)
        return f"{local[:2]}***@{domain}"
    if len(text) <= 4:
        return "***"
    return f"***{text[-4:]}"


def redact(value: Any, *, mask_personal: bool = False) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                clean[key] = "[REDACTED]"
            elif mask_personal and any(marker in lowered for marker in _PERSONAL_MARKERS):
                clean[key] = _masked_personal(item)
            else:
                clean[key] = redact(item, mask_personal=mask_personal)
        return clean
    if isinstance(value, (list, tuple, set)):
        return [redact(item, mask_personal=mask_personal) for item in value]
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return "[BINARY REDACTED]"
    if isinstance(value, str):
        return sanitize_error(value, limit=None)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def masked_secret_status(value: str | None) -> dict[str, bool | str | None]:
    if not value:
        return {"configured": False, "masked_suffix": None}
    suffix = value[-4:] if len(value) >= 8 else None
    return {
        "configured": True,
        "masked_suffix": f"••••{suffix}" if suffix else None,
    }


def sanitize_error(value: str | None, *, limit: int | None = 500) -> str | None:
    if not value:
        return None
    clean = value.replace("\r", " ").replace("\n", " ").strip()
    clean = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", clean)
    clean = re.sub(r"(?i)((?:password|secret|token|api[_-]?key|authorization|cookie|otp|totp|session_string)\s*[=:]\s*)[^\s,;&]+", r"\1[REDACTED]", clean)
    clean = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", clean)
    clean = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", clean)
    return clean[:limit] if limit is not None else clean
