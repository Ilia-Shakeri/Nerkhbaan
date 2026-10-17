from __future__ import annotations

import os
import asyncio
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "rights-test-key-not-for-runtime-000000000000000")

from app.config import settings
from app.pricing import rights
from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.derived import DerivedPriceEngine, DerivedPriceUnavailable
from app.pricing.history import InternalPriceHistory
from app.pricing.instruments import get_instrument
from app.pricing.models import CanonicalQuote, CanonicalStatus, PersistenceStatus, ProviderQuote
from app.pricing.quote_visibility import allowed_current_quote
from app.pricing.registry import PROVIDERS
from app.pricing.service import InstrumentPricingService, PricingRefreshSuspended


def _summary(provider: str) -> dict:
    return {"primary_provider_id": provider, "provider_ids": [provider], "derived": False}


def _canonical(instrument_id="BTC_USD", provider="restricted_source", *, summary=None, price="100000"):
    now = datetime.now(UTC)
    return CanonicalQuote.create(instrument_id=instrument_id, price=Decimal(price), status=CanonicalStatus.LIVE, primary_quote_id=1, verification_quote_ids=[], source_summary=_summary(provider) if summary is None else summary, observed_at=now, canonical_at=now, valid_until=now + timedelta(seconds=60), stale_at=now + timedelta(seconds=120), expires_at=now + timedelta(seconds=300), is_persisted=True, decision_reason="owned_rights_fixture")


def _candidate(provider="approved_fx"):
    instrument = get_instrument("BTC_USD")
    now = datetime.now(UTC)
    return ProviderQuote.create(instrument_id="BTC_USD", provider_id=provider, source_type="http", price=Decimal("105000"), currency=instrument.quote_currency, weight_unit=instrument.weight_unit, purity=instrument.purity, observed_at=now, received_at=now, parser_version="owned/1", validation_status="accepted", persistence_status=PersistenceStatus.PERSISTED)


class _Operational:
    async def instrument(self, instrument_id):
        return get_instrument(instrument_id)

    async def instruments(self, instrument_ids):
        return {key: get_instrument(key) for key in instrument_ids}

    async def feature_enabled(self, *_args, **_kwargs):
        return True


class _StrictFixture:
    def strict(self):
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        now = datetime.now(UTC)
        grant = {"permissions": ["collect", "store", "display", "history", "derive"], "checked_at": (now - timedelta(days=1)).isoformat(), "expires_at": (now + timedelta(days=30)).isoformat(), "evidence_ref": "https://fixture.example.invalid/terms", "hosts": ["fixture.example.invalid"]}
        self.grants = {name: deepcopy(grant) for name in ("approved_source", "approved_fx")}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))


class RightsReadBoundaryTests(_StrictFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.strict()

    def service(self, *, cached=None, stored=None):
        store = SimpleNamespace(get_canonical=AsyncMock(return_value=cached), get_all_canonical=AsyncMock(return_value=cached or {}), next_sequence=AsyncMock(return_value=1), set_canonical=AsyncMock(), append_short_history=AsyncMock(), publish_canonical=AsyncMock())
        history = SimpleNamespace(latest_canonical=AsyncMock(return_value=stored), latest_all=AsyncMock(return_value=stored or {}), latest_sources=AsyncMock(return_value=[]), provider_history=AsyncMock(return_value={"sources": []}))
        persistence = SimpleNamespace(persist_canonical=AsyncMock())
        return InstrumentPricingService(store=store, history=history, persistence=persistence, operational=_Operational())

    def test_unknown_and_missing_source_cannot_be_current(self):
        self.assertFalse(allowed_current_quote(_canonical(summary={})))
        self.assertFalse(allowed_current_quote(_canonical(provider="unknown")))
        self.assertTrue(allowed_current_quote(_canonical(provider="approved_source")))

    def test_retired_current_sources_stay_hidden_even_when_old_history_is_permitted(self):
        retired = "servix_btc_usd"
        self.grants[retired] = deepcopy(self.grants["approved_source"])
        summaries = [
            _summary(retired),
            {**_summary("approved_source"), "previous_provider_id": retired},
            {"provider_ids": ["derived:old"], "primary_provider_id": "derived:old", "derived": True,
             "inputs": [{"source_summary": _summary(retired)}]},
        ]
        for summary in summaries:
            with self.subTest(summary=summary):
                self.assertTrue(rights.canonical_allowed(summary, "history"))
                self.assertFalse(allowed_current_quote(_canonical(summary=summary)))
        quote = _canonical(provider="approved_source")
        quote.candidate_provider_id = retired
        self.assertFalse(allowed_current_quote(quote))
        self.assertTrue(allowed_current_quote(_canonical(provider="approved_source")))

    def test_retired_current_source_exclusion_also_applies_to_legacy_fixture_mode(self):
        with patch.object(settings, "pricing_rights_enforced", False):
            self.assertFalse(allowed_current_quote(_canonical(provider="servix_btc_usd")))

    async def test_restricted_cached_and_stored_quotes_are_hidden_without_deleting_evidence(self):
        quote = _canonical()
        service = self.service(cached=quote, stored=quote)
        self.assertIsNone(await service.get_canonical("BTC_USD"))
        self.assertEqual(quote.price, Decimal("100000"))
        self.grants["restricted_source"] = deepcopy(self.grants["approved_source"])
        self.assertIsNotNone(await service.get_canonical("BTC_USD"))
        self.grants.pop("restricted_source")
        self.assertIsNone(await service.get_canonical("BTC_USD"))

    async def test_aggregate_checks_cached_and_database_rows_against_current_grants(self):
        good = _canonical("XAG_USD_OZ", "approved_source", price="30")
        bad = _canonical()
        service = self.service(cached={"BTC_USD": bad, "XAG_USD_OZ": good}, stored={"BTC_USD": bad})
        self.assertEqual(set(await service.get_all_canonical()), {"XAG_USD_OZ"})

    async def test_source_rows_and_anonymous_counts_exclude_restricted_sources(self):
        service = self.service()
        service.history.latest_sources.return_value = [{"provider_id": provider, "price": 100, "validation_status": "accepted"} for provider in ("restricted_source", "approved_source", "unknown")]
        public = await service.sources("BTC_USD", authenticated=False)
        self.assertEqual((public["source_count"], public["usable_source_count"]), (1, 1))
        private = await service.sources("BTC_USD", authenticated=True)
        self.assertEqual([row["provider_id"] for row in private["sources"]], ["approved_source"])

    async def test_denied_explicit_source_history_never_reaches_history_adapter(self):
        service = self.service()
        result = await service.source_history("BTC_USD", "1h", "restricted_source")
        self.assertEqual(result["sources"], [])
        service.history.provider_history.assert_not_awaited()

    async def test_denied_commit_cannot_publish_or_write_a_live_cache(self):
        service = self.service()
        with self.assertRaises(PricingRefreshSuspended):
            await service._commit(_canonical(), None)
        service.store.set_canonical.assert_not_awaited()
        service.store.publish_canonical.assert_not_awaited()
        service.persistence.persist_canonical.assert_not_awaited()

    async def test_display_permission_does_not_authorize_new_cache_storage(self):
        service = self.service()
        quote = _canonical(provider="approved_source")
        self.grants["approved_source"]["permissions"].remove("store")
        with self.assertRaises(PricingRefreshSuspended):
            await service._commit(quote, None)
        service.persistence.persist_canonical.assert_not_awaited()
        service.store.set_canonical.assert_not_awaited()

    async def test_candidate_storage_permission_is_checked_outside_summary(self):
        service = self.service()
        quote = _canonical(provider="approved_source")
        quote.candidate_provider_id = "approved_fx"
        quote.candidate_price = Decimal("200000")
        self.grants["approved_fx"]["permissions"].remove("store")
        with self.assertRaises(PricingRefreshSuspended):
            await service._commit(quote, None)
        service.store.set_canonical.assert_not_awaited()

    async def test_revocation_during_sql_write_cannot_publish_into_cache(self):
        service = self.service()
        quote = _canonical(provider="approved_source")
        async def revoke(_quote):
            self.grants.clear()
        service.persistence.persist_canonical.side_effect = revoke
        with self.assertRaises(PricingRefreshSuspended):
            await service._commit(quote, None)
        service.store.set_canonical.assert_not_awaited()
        service.store.publish_canonical.assert_not_awaited()

    async def test_strict_anomaly_uses_base_policy_without_unproved_recent_prices(self):
        service = self.service()
        service.store.recent_canonical = AsyncMock(return_value=[_canonical(price=str(value)) for value in (1000, 999999, 1000)])
        service.history.recent_prices = AsyncMock(return_value=[Decimal(1000), Decimal(999999), Decimal(1000)])
        service.store.get_provider_runtime = AsyncMock(return_value=SimpleNamespace(success_rate=Decimal(1)))
        candidate, previous = _candidate(), _canonical(provider="approved_source")
        assessment = await service._assess_candidate(candidate, previous, get_instrument("BTC_USD"))
        from app.pricing.anomaly import DynamicAnomalyDetector
        expected = DynamicAnomalyDetector().assess(instrument=get_instrument("BTC_USD"), candidate_price=candidate.price, previous_price=previous.price, previous_observed_at=previous.observed_at, recent_prices=[], provider_success_rate=Decimal(1))
        self.assertEqual(assessment.volatility_percent, Decimal(0))
        self.assertLess(abs(assessment.dynamic_threshold_percent-expected.dynamic_threshold_percent), Decimal("0.001"))
        service.store.recent_canonical.assert_not_awaited()
        service.history.recent_prices.assert_not_awaited()

    async def test_anomaly_requires_derive_permission_for_both_current_inputs(self):
        service = self.service()
        service.store.recent_canonical = AsyncMock(return_value=[])
        service.history.recent_prices = AsyncMock(return_value=[])
        service.store.get_provider_runtime = AsyncMock(return_value=SimpleNamespace(success_rate=Decimal(1)))
        self.grants["approved_source"]["permissions"].remove("derive")
        with self.assertRaises(PricingRefreshSuspended):
            await service._assess_candidate(_candidate(), _canonical(provider="approved_source"), get_instrument("BTC_USD"))

    async def test_anomaly_revocation_during_runtime_read_stops_before_calculation(self):
        service = self.service()
        service.store.recent_canonical = AsyncMock(return_value=[])
        service.history.recent_prices = AsyncMock(return_value=[])
        async def revoke(*_args):
            self.grants.clear()
            return SimpleNamespace(success_rate=Decimal(1))
        service.store.get_provider_runtime = AsyncMock(side_effect=revoke)
        with self.assertRaises(PricingRefreshSuspended):
            await service._assess_candidate(_candidate(), _canonical(provider="approved_source"), get_instrument("BTC_USD"))

    async def test_visible_cached_quote_does_not_expose_unproved_baseline_changes(self):
        quote = _canonical(provider="approved_source")
        quote.change_1h = Decimal("500")
        quote.change_24h = Decimal("600")
        current = await self.service(cached=quote).get_canonical("BTC_USD")
        self.assertIsNotNone(current)
        self.assertIsNone(current.change_1h)
        self.assertIsNone(current.change_24h)

    def test_unknown_or_restricted_candidate_cannot_hide_behind_approved_primary(self):
        quote = _canonical(provider="approved_source")
        quote.candidate_price = Decimal("200000")
        self.assertFalse(allowed_current_quote(quote))
        quote.candidate_provider_id = "restricted_source"
        self.assertFalse(allowed_current_quote(quote))

    async def test_revocation_during_shared_history_read_cannot_return_old_permission_result(self):
        history = InternalPriceHistory()
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args, **kwargs):
            from app.pricing.history import HistoryResult
            started.set()
            await release.wait()
            now = datetime.now(UTC)
            return HistoryResult("BTC_USD", "1h", "complete", now-timedelta(hours=1), now, [{"timestamp": now.isoformat(), "value": 100}])

        with patch.object(history, "_read_canonical_history", side_effect=delayed):
            first = asyncio.create_task(history.canonical_history("BTC_USD", "1h"))
            await started.wait()
            self.grants.clear()
            release.set()
            self.assertEqual((await first).points, [])

    async def test_fast_provider_cache_cannot_bypass_collection_permission(self):
        provider = next(provider for provider in PROVIDERS.values() if provider.instrument_id == "BTC_USD" and provider.enabled)
        instrument = get_instrument(provider.instrument_id)
        now = datetime.now(UTC)
        quote = ProviderQuote.create(instrument_id=provider.instrument_id, provider_id=provider.provider_id, source_type="http", price=Decimal("100000"), currency=instrument.quote_currency, weight_unit=instrument.weight_unit, purity=instrument.purity, observed_at=now, received_at=now, parser_version="owned/1", validation_status="accepted", persistence_status=PersistenceStatus.PERSISTED, source_semantic=provider.source_semantic, source_family=provider.source_family, venue=provider.venue)
        service = self.service()
        service.store.get_provider_quote = AsyncMock(return_value=quote)
        service.collector = SimpleNamespace(quote=AsyncMock(return_value=SimpleNamespace(usable=False, external_called=False, quote=None, failure_reason="denied")))
        outcome = await service._first_usable([provider], None, None, maximum_external_calls=1, instrument=instrument)
        self.assertTrue(outcome is None or not outcome.usable)
        service.collector.quote.assert_not_awaited()

    def test_legacy_history_without_provenance_is_not_queried_in_strict_mode(self):
        with patch("app.pricing.history.SessionLocal") as sessions:
            self.assertEqual(InternalPriceHistory._query_legacy_history("BTC_USD", datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC), "1 minute"), [])
        sessions.assert_not_called()


class DerivedRightsBoundaryTests(_StrictFixture, unittest.TestCase):
    def setUp(self):
        self.strict()

    def inputs(self):
        return {"USDT_TOMAN": _canonical("USDT_TOMAN", "approved_source", price="60000"), "USDT_USD": _canonical("USDT_USD", "approved_fx", price="1")}

    def test_formula_input_requires_derive_permission_even_when_visible(self):
        self.grants["approved_fx"]["permissions"].remove("derive")
        with self.assertRaises(DerivedPriceUnavailable):
            DerivedPriceEngine().derive("USD_TOMAN", self.inputs())

    def test_new_formula_preserves_full_independent_parent_summaries(self):
        inputs = self.inputs()
        derived = DerivedPriceEngine().derive("USD_TOMAN", inputs)
        parents = {value["instrument_id"]: value for value in derived.metadata["inputs"]}
        self.assertEqual(parents["USDT_TOMAN"].get("source_summary"), inputs["USDT_TOMAN"].source_summary)
        inputs["USDT_TOMAN"].source_summary["provider_ids"].append("restricted_source")
        self.assertNotIn("restricted_source", parents["USDT_TOMAN"]["source_summary"]["provider_ids"])

    def test_canonical_builder_cannot_activate_a_restricted_primary(self):
        instrument = get_instrument("BTC_USD")
        now = datetime.now(UTC)
        quote = ProviderQuote.create(instrument_id=instrument.instrument_id, provider_id="restricted_source", source_type="http", price=Decimal("100000"), currency=instrument.quote_currency, weight_unit=instrument.weight_unit, purity=instrument.purity, observed_at=now, received_at=now, parser_version="owned/1", validation_status="accepted", persistence_status=PersistenceStatus.PERSISTED)
        with self.assertRaises(ValueError):
            CanonicalPricePolicy().select(instrument=instrument, primary=quote, previous=None, assessment=None, verifier_quotes=[], now=now)
