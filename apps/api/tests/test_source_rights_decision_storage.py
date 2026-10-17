from __future__ import annotations

import asyncio
import copy
import os
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "decision-rights-test-secret-not-for-runtime-000000")

from app.pricing import rights
from app.pricing.db_models import CanonicalQuoteRecord, PricingAnomalyRecord, ProviderQuoteRecord
from app.pricing.models import CanonicalStatus, VerificationDecision, VerificationStatus
from app.pricing.persistence import InvalidPersistenceEvent, PricingPersistence


PRIMARY = "reviewed_candidate_fixture"
PREVIOUS = "reviewed_previous_fixture"
VERIFIER = "reviewed_verifier_fixture"
INSTRUMENT = "XAU_USD_OZ"


def _summary(provider):
    return {"provider_ids": [provider], "primary_provider_id": provider, "derived": False}


def _grant(*permissions):
    now = datetime.now(UTC)
    return {"permissions": list(permissions or ("store", "derive", "display")),
            "checked_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "evidence_ref": "https://rights.fixture.invalid/terms"}


class _Session:
    def __init__(self):
        self.records = {
            ProviderQuoteRecord: [SimpleNamespace(id=11, instrument_id=INSTRUMENT, provider_id=PRIMARY,
                                                 is_derived=False, source_type="http", extra={}),
                                  SimpleNamespace(id=12, instrument_id=INSTRUMENT, provider_id=VERIFIER,
                                                  is_derived=False, source_type="http", extra={})],
            CanonicalQuoteRecord: [SimpleNamespace(id=21, instrument_id=INSTRUMENT,
                source_summary=_summary(PREVIOUS), candidate_provider_id=None, candidate_price=None,
                status="live")],
            PricingAnomalyRecord: [SimpleNamespace(id=31, instrument_id=INSTRUMENT,
                candidate_quote_id=11, previous_canonical_quote_id=21)],
        }
        self.added, self.commits, self.rollbacks, self.queries = [], 0, 0, []
        self.on_add = lambda: None

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        values = statement.compile().params
        self.queries.append(statement)
        # A source ID alone must never resolve another instrument's evidence.
        assert "instrument_id" in str(statement) and INSTRUMENT in values.values()
        requested = next(value for key, value in values.items() if key.startswith("id_"))
        requested = set(requested) if isinstance(requested, (list, tuple, set)) else {requested}
        rows = [row for row in self.records[entity] if row.instrument_id == INSTRUMENT and row.id in requested]
        return SimpleNamespace(all=lambda: rows)

    def add(self, row):
        self.added.append(row)
        self.on_add()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    @staticmethod
    def refresh(row):
        row.id = 99

    def close(self):
        pass


class DecisionStorageRightsTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(rights.settings, "pricing_rights_enforced", True))
        self.grants = {provider: _grant() for provider in (PRIMARY, PREVIOUS, VERIFIER)}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.db = _Session()
        self.enterContext(patch("app.pricing.persistence.SessionLocal", return_value=self.db))

    def anomaly(self, candidate=11, previous=21):
        return PricingPersistence._persist_anomaly(INSTRUMENT, candidate, previous,
            Decimal("10"), Decimal("2"), "high", "Candidate moved from the previous quote")

    @staticmethod
    def decision(candidate=11, verifiers=(12,)):
        return VerificationDecision(status=VerificationStatus.CONFIRMED,
            candidate_quote_id=candidate, verification_quote_ids=verifiers,
            deviation_percent=Decimal("10"), threshold_percent=Decimal("2"),
            decision_reason="Independent source confirms candidate")

    def verification(self, anomaly=31, candidate=11, verifiers=(12,)):
        return PricingPersistence._persist_verification(anomaly, INSTRUMENT, self.decision(candidate, verifiers))

    def assert_withheld(self, operation):
        with self.assertRaises(InvalidPersistenceEvent):
            operation()
        self.assertEqual(self.db.added, [])
        self.assertEqual(self.db.commits, 0)

    def test_known_candidate_and_previous_sources_are_resolved_before_anomaly_insert(self):
        self.assertEqual(self.anomaly(), 99)
        self.assertGreaterEqual(len(self.db.queries), 2)
        self.assertEqual(self.db.commits, 1)

    def test_unknown_candidate_id_cannot_store_a_calculated_decision(self):
        self.assert_withheld(lambda: self.anomaly(candidate=999))

    def test_candidate_from_another_instrument_does_not_prove_rights(self):
        self.db.records[ProviderQuoteRecord][0].instrument_id = "XAG_USD_OZ"
        self.assert_withheld(self.anomaly)

    def test_composite_provider_id_with_multiple_rows_is_ambiguous(self):
        self.db.records[ProviderQuoteRecord].append(copy.copy(self.db.records[ProviderQuoteRecord][0]))
        self.assert_withheld(self.anomaly)

    def test_non_integer_or_missing_source_ids_are_not_reinterpreted(self):
        for candidate in (None, True, "11", 0, -1, 2**63):
            with self.subTest(candidate=candidate):
                self.assert_withheld(lambda: self.anomaly(candidate=candidate))

    def test_previous_record_from_another_instrument_does_not_prove_rights(self):
        self.db.records[CanonicalQuoteRecord][0].instrument_id = "XAG_USD_OZ"
        self.assert_withheld(self.anomaly)

    def test_missing_previous_canonical_id_is_not_invented_or_accepted(self):
        self.assert_withheld(lambda: self.anomaly(previous=None))

    def test_revoked_previous_source_cannot_create_a_new_decision(self):
        del self.grants[PREVIOUS]
        self.assert_withheld(self.anomaly)

    def test_store_permission_without_derive_permission_cannot_store_deviation(self):
        self.grants[PRIMARY] = _grant("store", "display")
        self.assert_withheld(self.anomaly)

    def test_derived_previous_status_requires_derived_recursive_proof(self):
        self.db.records[CanonicalQuoteRecord][0].status = "derived_fallback"
        self.assert_withheld(self.anomaly)

    def test_flat_stamp_cannot_replace_recursive_previous_source_permission(self):
        previous = self.db.records[CanonicalQuoteRecord][0]
        previous.status = "derived_fallback"
        previous.source_summary = {"derived": True, "provider_ids": ["derived:fixture"],
            "primary_provider_id": "derived:fixture", "rights_provenance_version": 1,
            "rights_provider_ids": [PREVIOUS], "inputs": [{"source_summary": _summary("unknown_leaf")} ]}
        self.assert_withheld(self.anomaly)

    def test_derived_candidate_uses_recursive_leaves_without_a_synthetic_provider_grant(self):
        candidate = self.db.records[ProviderQuoteRecord][0]
        candidate.provider_id, candidate.is_derived, candidate.source_type = "derived:fixture", True, "derived"
        candidate.extra = {"inputs": [{"source_summary": _summary(PRIMARY)}]}
        self.assertEqual(self.anomaly(), 99)

    def test_derived_candidate_flat_stamp_cannot_hide_unknown_leaf(self):
        candidate = self.db.records[ProviderQuoteRecord][0]
        candidate.provider_id, candidate.is_derived, candidate.source_type = "derived:fixture", True, "derived"
        candidate.extra = {"rights_provider_ids": [PRIMARY], "rights_provenance_version": 1,
                           "inputs": [{"source_summary": _summary("unknown_leaf")}]}
        self.assert_withheld(self.anomaly)

    def test_known_verifiers_candidate_and_linked_previous_are_all_resolved(self):
        self.assertEqual(self.verification(), 99)
        self.assertGreaterEqual(len(self.db.queries), 3)
        self.assertEqual(self.db.commits, 1)

    def test_missing_or_revoked_verifier_does_not_create_verification(self):
        self.assert_withheld(lambda: self.verification(verifiers=(999,)))

    def test_revoked_verifier_record_cannot_create_verification(self):
        del self.grants[VERIFIER]
        self.assert_withheld(self.verification)

    def test_verifier_store_without_derive_is_not_a_permission_for_the_decision(self):
        self.grants[VERIFIER] = _grant("store", "display")
        self.assert_withheld(self.verification)

    def test_verification_cannot_reuse_anomaly_for_a_different_candidate(self):
        self.assert_withheld(lambda: self.verification(candidate=12, verifiers=(11,)))

    def test_verification_without_linked_anomaly_cannot_invent_previous_source(self):
        self.assert_withheld(lambda: self.verification(anomaly=None))

    def test_anomaly_from_another_instrument_is_not_reused(self):
        self.db.records[PricingAnomalyRecord][0].instrument_id = "XAG_USD_OZ"
        self.assert_withheld(self.verification)

    def test_duplicate_or_candidate_verifier_ids_do_not_claim_independent_evidence(self):
        for verifiers in ((12, 12), (11,)):
            with self.subTest(verifiers=verifiers):
                self.assert_withheld(lambda: self.verification(verifiers=verifiers))

    def test_revocation_after_add_is_rechecked_before_commit(self):
        self.db.on_add = self.grants.clear
        with self.assertRaises(InvalidPersistenceEvent):
            self.anomaly()
        self.assertEqual(self.db.commits, 0)
        self.assertEqual(self.db.rollbacks, 1)

    def test_verification_revocation_after_add_rolls_back_before_commit(self):
        self.db.on_add = self.grants.clear
        with self.assertRaises(InvalidPersistenceEvent):
            self.verification()
        self.assertEqual(self.db.commits, 0)
        self.assertEqual(self.db.rollbacks, 1)

    def test_async_denial_after_thread_dispatch_returns_none_without_queueing(self):
        persistence = PricingPersistence(store=SimpleNamespace(enqueue_persistence_event=AsyncMock()))

        async def delayed(function, *args):
            self.grants.clear()
            return function(*args)

        with patch("app.pricing.persistence.asyncio.to_thread", side_effect=delayed):
            result = asyncio.run(persistence.persist_anomaly(instrument_id=INSTRUMENT,
                candidate_quote_id=11, previous_canonical_quote_id=21, deviation_percent=Decimal("10"),
                dynamic_threshold_percent=Decimal("2"), severity="high", reason="fixture"))
        self.assertIsNone(result)
        persistence.store.enqueue_persistence_event.assert_not_awaited()
        self.assertEqual(self.db.commits, 0)

    def test_async_verification_denial_after_thread_dispatch_returns_none(self):
        persistence = PricingPersistence(store=SimpleNamespace(enqueue_persistence_event=AsyncMock()))

        async def delayed(function, *args):
            self.grants.clear()
            return function(*args)

        with patch("app.pricing.persistence.asyncio.to_thread", side_effect=delayed):
            result = asyncio.run(persistence.persist_verification(anomaly_id=31,
                instrument_id=INSTRUMENT, decision=self.decision()))
        self.assertIsNone(result)
        persistence.store.enqueue_persistence_event.assert_not_awaited()
        self.assertEqual(self.db.commits, 0)

    def test_canonical_candidate_price_without_provider_proof_is_not_storable(self):
        quote = copy.copy(self.db.records[CanonicalQuoteRecord][0])
        quote.candidate_price = Decimal("9999")
        self.assertFalse(PricingPersistence._canonical_storage_allowed(quote))

    def test_canonical_derived_status_with_direct_summary_is_not_storable(self):
        quote = copy.copy(self.db.records[CanonicalQuoteRecord][0])
        quote.status = CanonicalStatus.DERIVED_FALLBACK
        self.assertFalse(PricingPersistence._canonical_storage_allowed(quote))

    def test_explicit_legacy_test_mode_preserves_old_unproved_fixture_behavior(self):
        with patch.object(rights.settings, "pricing_rights_enforced", False):
            self.assertEqual(self.anomaly(candidate=None, previous=None), 99)


if __name__ == "__main__":
    unittest.main()
