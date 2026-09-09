#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse


RULES = {
    "provider_rights_signoff": (365, False),
    "provider_live_canary_schedule": (7, False),
    "secret_manager_activation": (90, False),
    "navasan_transport_signoff": (90, True),
    "brsapi_tsetmc_future_domain": (365, True),
    "production_restore_proof": (90, False),
    "production_deployment_proof": (7, False),
    "browser_smoke_proof": (7, False),
}
PLACEHOLDER_OWNERS = {"owner", "team", "example", "unknown", "tbd"}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]"),
    re.compile(r"Bearer\s+[A-Za-z0-9]{16,}"),
    re.compile(r"api[_-]?key[=:]\s*[A-Za-z0-9]{8,}", re.I),
    re.compile(r"password[=:]\s*[^,\s\"]{8,}", re.I),
    re.compile(r"BEGIN (?:RSA|OPENSSH|PRIVATE KEY)"),
)


def validate(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version: must be 1")
    if payload.get("environment") != "production":
        errors.append("environment: must be production")

    now = datetime.now(UTC)
    for name, (max_age_days, allow_na) in RULES.items():
        gate = payload.get(name)
        if not isinstance(gate, dict):
            errors.append(f"{name}: missing")
            continue
        status = gate.get("status")
        if status not in {"passed", "not_applicable"}:
            errors.append(f"{name}: status must be passed or not_applicable")
        if status == "not_applicable" and not allow_na:
            errors.append(f"{name}: this production gate cannot be not_applicable")
        if status == "not_applicable" and not str(gate.get("reason", "")).strip():
            errors.append(f"{name}: not_applicable needs reason")
        owner = str(gate.get("owner", "")).strip()
        if not owner or owner.lower() in PLACEHOLDER_OWNERS:
            errors.append(f"{name}: real owner missing")
        evidence_ref = str(gate.get("evidence_ref", "")).strip()
        parsed_ref = urlparse(evidence_ref)
        if not parsed_ref.scheme or not parsed_ref.path or any(char.isspace() for char in evidence_ref):
            errors.append(f"{name}: evidence_ref must be one typed URI with no spaces")
        try:
            checked_at = datetime.fromisoformat(str(gate.get("checked_at", "")).replace("Z", "+00:00"))
            checked_at = checked_at.astimezone(UTC)
            if checked_at > now + timedelta(minutes=5):
                errors.append(f"{name}: checked_at is in the future")
            if checked_at < now - timedelta(days=max_age_days):
                errors.append(f"{name}: evidence is too old")
        except (ValueError, TypeError):
            errors.append(f"{name}: checked_at must be a valid UTC timestamp")

    serialized = json.dumps(payload, separators=(",", ":"))
    if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
        errors.append("evidence contains secret-like value")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    if not args.evidence.is_file():
        print(f"Evidence file not found: {args.evidence}")
        return 1
    errors = validate(args.evidence)
    if errors:
        print("\n".join(errors))
        return 1
    print("operator gates evidence valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
