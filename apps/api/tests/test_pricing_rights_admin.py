from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "rights-test-key-not-for-runtime-000000000000000")

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, Numeric, String, Table, create_engine, text
from sqlalchemy.orm import Session

from app.admin.routers import pricing
from app.config import settings
from app.pricing import rights


class AdminRightsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        now = datetime.now(UTC)
        self.grants = {"approved": {"permissions": ["collect", "display", "store", "history", "derive"], "checked_at": (now-timedelta(days=1)).isoformat(), "expires_at": (now+timedelta(days=1)).isoformat(), "evidence_ref": "https://fixture.example.invalid/terms"}}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        # SQLite exercises predicate placement; the separate backend tests use the real JSON filter.
        self.enterContext(patch.object(rights, "sql_filter", return_value=("json_extract(source_summary, '$.primary_provider_id') = :owned_source", {"owned_source": "approved"})))
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        self.canonical = Table("canonical_quotes", metadata, Column("id", Integer, primary_key=True), Column("instrument_id", String), Column("price", Numeric), Column("source_summary", JSON), Column("candidate_provider_id", String), Column("canonical_at", DateTime), Column("change_24h", Numeric))
        self.providers = Table("provider_quotes", metadata, Column("id", Integer, primary_key=True), Column("instrument_id", String), Column("provider_id", String), Column("price", Numeric), Column("observed_at", DateTime))
        self.anomalies = Table("pricing_anomalies", metadata, Column("id", Integer, primary_key=True), Column("instrument_id", String), Column("candidate_quote_id", Integer), Column("previous_canonical_quote_id", Integer), Column("deviation_percent", Numeric), Column("severity", String), Column("status", String), Column("reason", String), Column("review_note", String), Column("created_at", DateTime))
        self.verifications = Table("pricing_verifications", metadata, Column("id", Integer, primary_key=True), Column("instrument_id", String), Column("anomaly_id", Integer), Column("candidate_quote_id", Integer), Column("verifier_quote_ids", JSON), Column("difference_percent", Numeric), Column("decision", String), Column("created_at", DateTime))
        metadata.create_all(self.engine)
        self.db = self.enterContext(Session(self.engine))
        self.db.execute(self.canonical.insert(), [{"id": 1, "instrument_id": "BTC_USD", "price": 100, "source_summary": {"provider_ids": ["approved"], "primary_provider_id": "approved"}, "canonical_at": now-timedelta(minutes=1), "change_24h": 99}, {"id": 2, "instrument_id": "BTC_USD", "price": 999, "source_summary": {"provider_ids": ["restricted"], "primary_provider_id": "restricted"}, "canonical_at": now, "change_24h": 99}])
        self.db.execute(self.providers.insert(), [{"id": 10, "instrument_id": "BTC_USD", "provider_id": "approved", "price": 100, "observed_at": now-timedelta(minutes=1)}, {"id": 11, "instrument_id": "BTC_USD", "provider_id": "restricted", "price": 999, "observed_at": now}])
        self.db.execute(self.anomalies.insert(), {"id": 20, "instrument_id": "BTC_USD", "candidate_quote_id": 11, "previous_canonical_quote_id": 1, "deviation_percent": 899, "severity": "critical", "status": "open", "reason": "price rose from 100 to 999", "review_note": "operator review", "created_at": now})
        self.db.execute(self.verifications.insert(), {"id": 30, "instrument_id": "BTC_USD", "anomaly_id": 20, "candidate_quote_id": 10, "verifier_quote_ids": [11], "difference_percent": 899, "decision": "rejected", "created_at": now})
        self.db.commit()

    def test_canonical_filter_precedes_limit_and_clears_unproved_changes(self):
        rows = pricing._rows_for(self.db, "canonical_quotes", pricing._CANONICAL_COLUMNS, identity_fields=("instrument_id",), identity="BTC_USD", limit=1)
        self.assertEqual([row["id"] for row in rows], [1])
        self.assertIsNone(rows[0]["change_24h"])

    def test_latest_canonical_filters_before_window_rank(self):
        result = pricing.list_instruments(principal=None, db=self.db)
        row = next(row for row in result["items"] if row["instrument_id"] == "BTC_USD")
        self.assertEqual(row["latest_canonical"]["id"], 1)

    def test_provider_filter_precedes_limit(self):
        rows = pricing._rows_for(self.db, "provider_quotes", pricing._PROVIDER_QUOTE_COLUMNS, identity_fields=("instrument_id",), identity="BTC_USD", limit=1, order_fields=("observed_at",))
        self.assertEqual([row["id"] for row in rows], [10])

    def test_anomaly_keeps_review_metadata_but_hides_restricted_derived_data(self):
        result = pricing.list_anomalies(anomaly_status="", limit=10, offset=0, principal=None, db=self.db)
        row = result["items"][0]
        self.assertEqual((row["id"], row["status"], result["total"]), (20, "open", 1))
        for key in ("deviation_percent", "severity", "reason", "candidate_price", "previous_price"):
            self.assertNotIn(key, row)
        self.assertEqual(self.db.scalar(text("SELECT deviation_percent FROM pricing_anomalies WHERE id=20")), 899)

    def test_verification_resolves_each_verifier_before_exposing_decision(self):
        rows = pricing._rows_for(self.db, "pricing_verifications", pricing._VERIFICATION_COLUMNS, identity_fields=("instrument_id",), identity="BTC_USD")
        self.assertEqual(rows[0]["id"], 30)
        self.assertNotIn("difference_percent", rows[0])
        self.assertNotIn("decision", rows[0])
