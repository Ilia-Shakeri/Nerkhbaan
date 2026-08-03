from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

os.environ["DEBUG"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-key-with-32-characters"

from app import health
from app.admin.models import AdminAuditLog
from app.admin.routers import health_jobs, pricing
from app.admin.schemas import AnomalyReviewRequest
from app.pricing.db_models import PricingAnomalyRecord


FROZEN_CREATED_AT = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class _Session:
    def __init__(
        self,
        anomaly: PricingAnomalyRecord | None,
        *,
        fail_commit: bool = False,
        mutate_on_commit: bool = False,
    ) -> None:
        self.anomaly = anomaly
        self.fail_commit = fail_commit
        self.mutate_on_commit = mutate_on_commit
        self.added: list[object] = []
        self.statements: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0

    def scalar(self, statement):
        self.statements.append(statement)
        return self.anomaly

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("forced commit failure")
        if self.mutate_on_commit and self.anomaly is not None:
            self.anomaly.status = "expired-instance"
            self.anomaly.reviewed_by_admin_id = None
            self.anomaly.review_note = None

    def rollback(self) -> None:
        self.rollback_count += 1


class _HealthResult:
    def __init__(self, value: dict[str, int]) -> None:
        self.value = value

    def mappings(self) -> "_HealthResult":
        return self

    def one(self) -> dict[str, int]:
        return self.value


class _HealthConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "_HealthConnection":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "pricing_backfill_jobs" in sql:
            return _HealthResult(
                {"backfill": 1, "persistence": 2, "dead_letters": 3, "anomalies": 4}
            )
        return _HealthResult({})


class _HealthEngine:
    def __init__(self, connection: _HealthConnection) -> None:
        self.connection = connection

    def connect(self) -> _HealthConnection:
        return self.connection


def _anomaly(*, anomaly_status: str = "open") -> PricingAnomalyRecord:
    return PricingAnomalyRecord(
        id=73,
        instrument_id="BTC_USD",
        candidate_quote_id=811,
        previous_canonical_quote_id=701,
        deviation_percent=Decimal("5.250000"),
        dynamic_threshold_percent=Decimal("2.000000"),
        severity="high",
        status=anomaly_status,
        reason="candidate outside threshold",
        reviewed_by_admin_id=None,
        reviewed_at=None,
        review_note=None,
        created_at=FROZEN_CREATED_AT,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/pricing/anomalies/73/review",
            "headers": [(b"user-agent", b"anomaly-review-test")],
            "client": ("127.0.0.1", 5000),
        }
    )


class AdminAnomalyReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = SimpleNamespace(user=SimpleNamespace(id=42))

    def test_all_allowed_transitions_update_real_row_and_append_audit(self) -> None:
        for target in ("reviewed", "dismissed", "resolved"):
            with self.subTest(target=target):
                anomaly = _anomaly()
                db = _Session(anomaly)
                response = pricing.review_anomaly(
                    "73",
                    AnomalyReviewRequest(status=target, note="  checked against source  "),
                    _request(),
                    self.principal,
                    db,
                )

                self.assertEqual(anomaly.status, target)
                self.assertEqual(anomaly.reviewed_by_admin_id, 42)
                self.assertEqual(anomaly.review_note, "checked against source")
                self.assertIsNotNone(anomaly.reviewed_at)
                self.assertEqual(response["anomaly_id"], "73")
                self.assertEqual(response["review_status"], target)
                self.assertEqual(db.commit_count, 1)
                self.assertEqual(db.rollback_count, 0)
                self.assertIn("FOR UPDATE", str(db.statements[0]))
                self.assertEqual(len(db.added), 1)
                audit = db.added[0]
                self.assertIsInstance(audit, AdminAuditLog)
                self.assertEqual(audit.action, "admin.pricing.anomaly_reviewed")
                self.assertEqual(audit.resource_id, "73")
                self.assertEqual(audit.before_data["status"], "open")
                self.assertEqual(audit.after_data["status"], target)
                self.assertEqual(audit.after_data["reviewed_by_admin_id"], 42)
                self.assertEqual(audit.after_data["review_note"], "checked against source")

    def test_missing_anomaly_has_stable_not_found_error(self) -> None:
        db = _Session(None)
        with self.assertRaises(HTTPException) as raised:
            pricing.review_anomaly(
                "73",
                AnomalyReviewRequest(status="reviewed", note="checked source"),
                _request(),
                self.principal,
                db,
            )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Pricing anomaly not found")
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.added, [])

    def test_invalid_anomaly_id_has_same_stable_not_found_error(self) -> None:
        db = _Session(_anomaly())
        with self.assertRaises(HTTPException) as raised:
            pricing.review_anomaly(
                "bad-id",
                AnomalyReviewRequest(status="reviewed", note="checked source"),
                _request(),
                self.principal,
                db,
            )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Pricing anomaly not found")
        self.assertEqual(db.statements, [])

    def test_out_of_range_anomaly_id_has_same_stable_not_found_error(self) -> None:
        db = _Session(_anomaly())
        with self.assertRaises(HTTPException) as raised:
            pricing.review_anomaly(
                "9223372036854775808",
                AnomalyReviewRequest(status="reviewed", note="checked source"),
                _request(),
                self.principal,
                db,
            )
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Pricing anomaly not found")
        self.assertEqual(db.statements, [])

    def test_terminal_anomaly_cannot_be_reviewed_again(self) -> None:
        anomaly = _anomaly(anomaly_status="dismissed")
        anomaly.reviewed_by_admin_id = 8
        anomaly.reviewed_at = FROZEN_CREATED_AT
        anomaly.review_note = "prior review"
        db = _Session(anomaly)
        with self.assertRaises(HTTPException) as raised:
            pricing.review_anomaly(
                "73",
                AnomalyReviewRequest(status="resolved", note="second review"),
                _request(),
                self.principal,
                db,
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Pricing anomaly must be open for review")
        self.assertEqual(anomaly.status, "dismissed")
        self.assertEqual(anomaly.reviewed_by_admin_id, 8)
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.added, [])

    def test_commit_failure_rolls_back_anomaly_and_audit_transaction(self) -> None:
        db = _Session(_anomaly(), fail_commit=True)
        with self.assertRaisesRegex(RuntimeError, "forced commit failure"):
            pricing.review_anomaly(
                "73",
                AnomalyReviewRequest(status="reviewed", note="checked source"),
                _request(),
                self.principal,
                db,
            )
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(db.rollback_count, 1)
        self.assertEqual(len(db.added), 1)

    def test_response_does_not_reload_expired_row_after_commit(self) -> None:
        db = _Session(_anomaly(), mutate_on_commit=True)
        response = pricing.review_anomaly(
            "73",
            AnomalyReviewRequest(status="reviewed", note="checked source"),
            _request(),
            self.principal,
            db,
        )
        self.assertEqual(response["review_status"], "reviewed")
        self.assertEqual(response["reviewed_by_admin_id"], 42)
        self.assertEqual(response["review_note"], "checked source")

    def test_review_persists_real_anomaly_and_audit_rows(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            PricingAnomalyRecord.__table__.create(engine)
            AdminAuditLog.__table__.create(engine)
            with OrmSession(engine) as db:
                db.add(_anomaly())
                db.commit()
                response = pricing.review_anomaly(
                    "73",
                    AnomalyReviewRequest(status="resolved", note="checked source"),
                    _request(),
                    self.principal,
                    db,
                )

            with OrmSession(engine) as db:
                stored = db.get(PricingAnomalyRecord, 73)
                audits = db.scalars(select(AdminAuditLog)).all()

            self.assertEqual(response["review_status"], "resolved")
            self.assertIsNotNone(stored)
            self.assertEqual(stored.status, "resolved")
            self.assertEqual(stored.reviewed_by_admin_id, 42)
            self.assertEqual(stored.review_note, "checked source")
            self.assertIsNotNone(stored.reviewed_at)
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].before_data["status"], "open")
            self.assertEqual(audits[0].after_data["status"], "resolved")
        finally:
            engine.dispose()

    def test_request_rejects_candidate_promotion_and_blank_note(self) -> None:
        with self.assertRaises(ValidationError):
            AnomalyReviewRequest(status="confirmed", note="checked source")
        with self.assertRaises(ValidationError):
            AnomalyReviewRequest(status="reviewed", note="   ")

    def test_list_fields_match_real_record_and_review_is_compatible(self) -> None:
        self.assertEqual(
            set(pricing._ANOMALY_COLUMNS),
            set(PricingAnomalyRecord.__table__.columns.keys()),
        )
        reviewed_at = datetime(2026, 8, 2, 11, 0, tzinfo=UTC)
        row = {
            "id": 73,
            "instrument_id": "BTC_USD",
            "candidate_quote_id": 811,
            "previous_canonical_quote_id": 701,
            "deviation_percent": Decimal("5.25"),
            "dynamic_threshold_percent": Decimal("2.00"),
            "severity": "high",
            "status": "reviewed",
            "reason": "candidate outside threshold",
            "reviewed_by_admin_id": 42,
            "reviewed_at": reviewed_at,
            "review_note": "checked source",
            "created_at": FROZEN_CREATED_AT,
        }
        with patch.object(pricing, "safe_rows", return_value=[row]) as safe_rows:
            response = pricing.list_anomalies("", 100, self.principal, object())

        self.assertEqual(safe_rows.call_args.args[2], pricing._ANOMALY_COLUMNS)
        self.assertNotIn("candidate_price", pricing._ANOMALY_COLUMNS)
        self.assertNotIn("decision_reason", pricing._ANOMALY_COLUMNS)
        self.assertEqual(response["items"][0]["reason"], "candidate outside threshold")
        self.assertEqual(
            response["items"][0]["admin_review"],
            {
                "status": "reviewed",
                "note": "checked source",
                "reviewed_by": 42,
                "reviewed_at": reviewed_at.isoformat(),
            },
        )


class AnomalyHealthCountTests(unittest.TestCase):
    def test_public_health_query_counts_only_open_anomalies(self) -> None:
        connection = _HealthConnection()
        engine = _HealthEngine(connection)
        with (
            patch.object(health, "engine", engine),
            patch.object(
                health,
                "migration_state",
                return_value={"current": True, "version": "20260718_001"},
            ),
        ):
            payload = health._database_health()

        backlog_sql = next(sql for sql in connection.statements if "pricing_backfill_jobs" in sql)
        self.assertIn("pricing_anomalies WHERE status = 'open'", backlog_sql)
        self.assertNotIn("reviewed", backlog_sql)
        self.assertNotIn("dismissed", backlog_sql)
        self.assertNotIn("resolved", backlog_sql)
        self.assertEqual(payload["backlog"]["anomalies"], 4)

    def test_admin_health_count_uses_only_open_status(self) -> None:
        count_calls: list[tuple[str, set[str] | None]] = []

        def fake_count(_db, table_name: str, statuses: set[str] | None = None) -> int:
            count_calls.append((table_name, statuses))
            return 4 if table_name == "pricing_anomalies" else 0

        with (
            patch.object(health_jobs, "_database_state", return_value={"status": "ok"}),
            patch.object(
                health_jobs,
                "_redis_state",
                return_value=({"status": "disabled", "persistence_backlog": None}, None),
            ),
            patch.object(health_jobs, "safe_rows", return_value=[]),
            patch.object(health_jobs, "safe_count", side_effect=fake_count),
        ):
            payload = health_jobs._health_payload(object())

        self.assertIn(("pricing_anomalies", {"open"}), count_calls)
        self.assertEqual(payload["anomaly_count"], 4)


if __name__ == "__main__":
    unittest.main()
