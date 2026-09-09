from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from verify_operator_gates import RULES, validate


def evidence() -> dict:
    checked_at = datetime.now(UTC).isoformat()
    payload = {"schema_version": 1, "environment": "production"}
    for name, (_days, allow_na) in RULES.items():
        payload[name] = {
            "status": "not_applicable" if allow_na else "passed",
            "owner": "real-ops-owner",
            "checked_at": checked_at,
            "evidence_ref": f"file:///evidence/{name}.json",
            "reason": "provider is disabled" if allow_na else "",
        }
    return payload


class OperatorGateTests(unittest.TestCase):
    def validate_payload(self, payload: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "evidence.json")
            path.write_text(json.dumps(payload), encoding="utf-8")
            return validate(path)

    def test_complete_current_evidence_passes(self) -> None:
        self.assertEqual(self.validate_payload(evidence()), [])

    def test_stale_evidence_fails(self) -> None:
        payload = evidence()
        payload["production_deployment_proof"]["checked_at"] = (
            datetime.now(UTC) - timedelta(days=8)
        ).isoformat()
        self.assertTrue(any("too old" in item for item in self.validate_payload(payload)))

    def test_secret_like_evidence_fails(self) -> None:
        payload = evidence()
        payload["provider_rights_signoff"]["note"] = "Bearer abcdefghijklmnop"
        self.assertTrue(any("secret-like" in item for item in self.validate_payload(payload)))


if __name__ == "__main__":
    unittest.main()
