"""Fail-closed source grants for the standalone Telegram collector."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


_ACTIONS = frozenset({"collect", "store", "display", "history", "derive",
                      "own_app_transport", "external_processing", "relay"})
_SOURCE_ID = re.compile(r"[1-9][0-9]{0,18}\Z")
_MAX_MANIFEST_BYTES = 262_144


def _providers() -> dict:
    path = os.getenv("PRICING_RIGHTS_MANIFEST_PATH")
    if not path:
        return {}
    try:
        selected = Path(path)
        if not selected.is_absolute():
            return {}
        with selected.open("rb") as stream:
            contents = stream.read(_MAX_MANIFEST_BYTES + 1)
        if len(contents) > _MAX_MANIFEST_BYTES:
            return {}
        document = json.loads(contents)
        if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
                or document["schema_version"] != 1 or document.get("environment") != "production"
                or not isinstance(document.get("providers"), dict)):
            return {}
        return document["providers"]
    except (OSError, ValueError, TypeError):
        return {}


def _source_id(value: object) -> str | None:
    if type(value) is int:
        value = str(value)
    if isinstance(value, str) and _SOURCE_ID.fullmatch(value) and int(value) <= 2**63-1:
        return value
    return None


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Permission timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Permission timestamp requires a timezone")
    return parsed.astimezone(UTC)


def _allowed(grant: object, actions: tuple[str, ...]) -> bool:
    if (not isinstance(grant, dict)
            or any(not isinstance(action, str) or action not in _ACTIONS for action in actions)):
        return False
    try:
        checked, expires = _time(grant.get("checked_at")), _time(grant.get("expires_at"))
        ref = urlsplit(str(grant.get("evidence_ref", "")))
        permissions = grant.get("permissions")
        if (not checked <= datetime.now(UTC) < expires
                or (expires-checked).total_seconds() > 366*86400
                or ref.scheme != "https" or not ref.hostname or ref.username or ref.password
                or not isinstance(permissions, list) or not permissions
                or any(not isinstance(item, str) or item not in _ACTIONS for item in permissions)):
            return False
        required = set(actions)
        if "history" in required:
            required.add("display")
        return required <= set(permissions)
    except (ValueError, TypeError, OverflowError):
        return False


def source_allowed(source_id: object, *actions: str) -> bool:
    """Read current evidence for this DB source ID; environment toggles cannot grant access."""
    selected = _source_id(source_id)
    if selected is None:
        return False
    return _allowed(_providers().get(f"telegram:{selected}"), actions or ("collect", "store"))


def allowed_source_ids(*actions: str) -> tuple[int, ...]:
    required = actions or ("collect", "store")
    result = []
    for name, grant in _providers().items():
        if not isinstance(name, str) or not name.startswith("telegram:"):
            continue
        selected = _source_id(name.removeprefix("telegram:"))
        if selected is not None and _allowed(grant, required):
            result.append(int(selected))
    return tuple(sorted(result))
