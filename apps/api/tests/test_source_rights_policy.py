from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from fastapi import Response

os.environ.setdefault("JWT_SECRET_KEY", "rights-test-only-key-not-for-runtime-000000000")

from app.config import settings
from app.pricing import rights
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.compatibility import LegacyPricingAdapter
from app.pricing.instruments import get_instrument
from app.pricing.models import CanonicalQuote, CanonicalStatus, ProviderQuote, ProviderRuntimeState, RequestPurpose
from app.pricing.persistence import InvalidPersistenceEvent, PricingPersistence
from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector, QuoteFetchOutcome
from app.pricing.registry import PROVIDERS
from app.pricing.telegram import StoredTelegramQuoteRepository
from app.routers.prices import get_price_history


def summary(name="gold_api_free_xau"):
    return {"primary_provider_id": name, "provider_ids": [name], "derived": False}


class StrictFixture:
    def setUp(self):
        super().setUp()
        active = patch.multiple(settings, pricing_rights_enforced=True, pricing_rights_manifest_path=None)
        active.start()
        self.addCleanup(active.stop)


class RightsPolicyTests(StrictFixture, unittest.TestCase):
    def test_default_requires_explicit_application_permission(self):
        self.assertTrue(rights.provider_allowed("gold_api_free_xau", "display"))
        for name in ("coinbase_btc_usd", "coingecko_btc", "bitpin_usdt_toman", "unlisted", "telegram:unknown"):
            self.assertFalse(rights.provider_allowed(name, "collect"), name)
            self.assertFalse(rights.provider_allowed(name, "display"), name)

    def test_application_permission_does_not_grant_external_processing_or_relay(self):
        self.assertFalse(rights.provider_allowed("gold_api_free_xau", "external_processing"))
        self.assertFalse(rights.provider_allowed("gold_api_free_xau", "relay"))
        self.assertTrue(rights.provider_allowed("gold_api_free_xau", "own_app_transport"))

    def test_permission_also_binds_network_destination(self):
        self.assertTrue(rights.endpoint_allowed("gold_api_free_xau", "https://api.gold-api.com/price/XAU"))
        for url in ("http://api.gold-api.com/price/XAU", "https://example.org/price/XAU", "https://api.gold-api.com:8443/price/XAU", "https://user@api.gold-api.com/price/XAU"):
            self.assertFalse(rights.endpoint_allowed("gold_api_free_xau", url), url)

    def test_malformed_manifest_hosts_cannot_use_substring_matching(self):
        grant = dict(rights._BUILTIN["gold_api_free_xau"], hosts="not-api.gold-api.com")
        with patch.object(rights, "grants", return_value={"gold_api_free_xau": grant}):
            self.assertFalse(rights.endpoint_allowed("gold_api_free_xau", "https://api.gold-api.com/price/XAU"))
        self.assertFalse(rights.provider_allowed(["gold_api_free_xau"]))

    def test_missing_unknown_or_mixed_lineage_is_withheld(self):
        for value in ({}, None, {"provider_ids": []}, summary("coingecko_btc"),
                      {**summary(), "provider_ids": ["gold_api_free_xau", "coinbase_btc_usd"]}):
            self.assertFalse(rights.canonical_allowed(value))

    def test_candidate_and_previous_prices_are_not_hidden_dependencies(self):
        for field in ("candidate_provider_id", "previous_provider_id"):
            self.assertFalse(rights.canonical_allowed({**summary(), field: "coinbase_btc_usd"}))

    def test_derived_values_need_full_approved_parent_lineage(self):
        value = {"primary_provider_id": "derived:test", "provider_ids": ["derived:test"],
                 "derived": True, "inputs": [{"source_summary": summary()}]}
        self.assertTrue(rights.canonical_allowed(value))
        self.assertEqual(rights.stamp_summary(value)["rights_provider_ids"], ["gold_api_free_xau"])
        value["inputs"].append({"source_summary": summary("coingecko_btc")})
        self.assertFalse(rights.canonical_allowed(value))
        self.assertNotIn("rights_provider_ids", rights.stamp_summary(value))

    def test_legacy_formula_cannot_claim_an_approved_leaf_without_proof(self):
        value = {"primary_provider_id": "derived:test", "provider_ids": ["derived:test"],
                 "derived": True, "rights_provenance_version": 1, "rights_provider_ids": ["gold_api_free_xau"],
                 "inputs": [{"instrument_id": "XAU_USD_OZ"}]}
        self.assertFalse(rights.canonical_allowed(value))

    def test_malformed_flags_depth_and_ids_fail_closed(self):
        self.assertFalse(rights.canonical_allowed({**summary(), "derived": "false"}))
        self.assertFalse(rights.canonical_allowed({**summary(), "provider_ids": [7]}))
        value = summary()
        for _ in range(9):
            value = {"primary_provider_id": "derived:test", "provider_ids": ["derived:test"],
                     "derived": True, "inputs": [{"source_summary": value}]}
        self.assertFalse(rights.canonical_allowed(value))

    def test_expired_grant_is_not_used(self):
        expired = dict(rights._BUILTIN["gold_api_free_xau"], expires_at="2026-01-01T00:00:00Z")
        with patch.object(rights, "grants", return_value={"gold_api_free_xau": expired}):
            self.assertFalse(rights.provider_allowed("gold_api_free_xau"))

    def test_history_requires_display_permission(self):
        grant = dict(rights._BUILTIN["gold_api_free_xau"], permissions=["history"])
        with patch.object(rights, "grants", return_value={"gold_api_free_xau": grant}):
            self.assertFalse(rights.provider_allowed("gold_api_free_xau", "history"))

    def test_manifest_revocation_and_invalid_file_are_immediate(self):
        with tempfile.TemporaryDirectory(prefix="nerkhbaan-rights-") as owned:
            path = Path(owned) / "rights.json"
            path.write_text(json.dumps({"schema_version": 1, "environment": "production", "providers": rights._BUILTIN}))
            with patch.object(settings, "pricing_rights_manifest_path", str(path)):
                before = rights.revision()
                self.assertTrue(rights.provider_allowed("gold_api_free_xau"))
                replacement = path.with_suffix(".new")
                replacement.write_text(json.dumps({"schema_version": 1, "environment": "production", "providers": {}}))
                replacement.replace(path)
                self.assertFalse(rights.provider_allowed("gold_api_free_xau"))
                self.assertNotEqual(before, rights.revision())
                path.write_text(json.dumps({"schema_version": True, "environment": "production", "providers": rights._BUILTIN}))
                self.assertFalse(rights.provider_allowed("gold_api_free_xau"))
                path.write_text("{")
                self.assertEqual(rights.allowed_provider_ids(), ())
                path.unlink()
                self.assertEqual(rights.allowed_provider_ids(), ())

    def test_bad_sql_column_or_unknown_action_cannot_weaken_policy(self):
        with self.assertRaises(ValueError):
            rights.sql_filter(column="source_summary; SELECT 1")
        with self.assertRaises(ValueError):
            rights.sql_filter(action="unknown")
        self.assertFalse(rights.provider_allowed("gold_api_free_xau", "unknown"))

    def test_attribution_is_safe_and_not_full_provenance(self):
        self.assertEqual(rights.attribution(summary()), [{"label": "Gold API", "url": "https://gold-api.com/"}])
        self.assertEqual(rights.attribution(summary("coingecko_btc")), [])

    def test_catalogue_registration_does_not_make_rights_coverage_healthy(self):
        health = LegacyPricingAdapter.startup_checks()
        self.assertFalse(health["ok"])
        self.assertIn("USDT_USD", health["instruments_without_permitted_configured_source"])
        self.assertEqual(health["source_rights"]["approved_display_sources"],
                         ["gold_api_free_btc", "gold_api_free_xag", "gold_api_free_xau"])

    def test_revoked_cached_outcome_cannot_still_be_usable_or_expose_raw_payload(self):
        quote = Mock(spec=ProviderQuote, provider_id="coingecko_btc")
        result = QuoteFetchOutcome(quote, True, True, False, None, sanitized_payload="old-price")
        self.assertIsNone(result.quote)
        self.assertIsNone(result.sanitized_payload)
        self.assertFalse(result.usable)
        self.assertFalse(result.from_fresh_cache)
        self.assertEqual(result.failure_reason, "provider_rights_denied")


class RightsBoundaryTests(StrictFixture, unittest.IsolatedAsyncioTestCase):
    async def test_relay_destination_also_requires_own_application_transport_permission(self):
        provider = replace(PROVIDERS["gold_api_free_xau"], url="https://relay.example.org/gold-api/price/XAU")
        grant = dict(rights._BUILTIN[provider.provider_id],
                     permissions=["collect", "store", "display"], hosts=["relay.example.org"])
        collector = ProviderQuoteCollector()
        client = Mock()
        with patch.object(rights, "grants", return_value={provider.provider_id: grant}), patch.multiple(settings,
                pricing_relay_base_url="https://relay.example.org",
                pricing_relay_shared_token="relay-fixture-only-not-for-runtime-0000000000",
                pricing_provider_allowed_hosts="relay.example.org"):
            with self.assertRaisesRegex(ProviderCallFailure, "Application transport"):
                await collector._request_payload(client, provider)
        client.stream.assert_not_called()

    async def test_strict_history_cannot_be_served_from_shared_http_cache(self):
        response = Response()
        with patch("app.routers.prices.legacy_pricing_adapter.get_history", AsyncMock(return_value={"asset": "gold", "points": []})):
            await get_price_history("gold", response, "1h")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
    async def test_unapproved_stored_channel_is_withheld_before_reading_price_rows(self):
        repository = StoredTelegramQuoteRepository()
        with patch.object(repository, "_rows") as read:
            result = await repository.latest(get_instrument("BTC_USD"), roles=["fallback"])
        self.assertEqual(result, [])
        read.assert_not_called()
    async def test_revocation_in_flight_does_not_cache_or_return_response(self):
        store = AsyncMock()
        collector = ProviderQuoteCollector(store=store)
        provider = PROVIDERS["gold_api_free_xau"]
        grants = dict(rights._BUILTIN)

        async def response(*_args, **_kwargs):
            grants.clear()
            return {"symbol": "XAU", "currency": "USD", "price": 4000}, "application/json", 200

        with patch.object(rights, "grants", side_effect=lambda: grants), patch.object(collector, "_request_payload", side_effect=response):
            result = await collector._call_and_parse(provider, RequestPurpose.NORMAL,
                ProviderRuntimeState(provider.provider_id, provider.instrument_id), Mock(), get_instrument(provider.instrument_id))
        self.assertIsNone(result.quote)
        self.assertIsNone(result.sanitized_payload)
        self.assertEqual(result.failure_reason, "provider_rights_denied")
        store.set_provider_quote.assert_not_awaited()

    async def test_unapproved_outer_candidate_cannot_enter_storage(self):
        persistence = PricingPersistence(store=AsyncMock())
        quote = Mock(spec=CanonicalQuote, source_summary=summary(), candidate_provider_id="coingecko_btc")
        with patch.object(persistence, "_persist_canonical") as write:
            result = await persistence.persist_canonical(quote)
        self.assertFalse(result.persisted)
        self.assertFalse(result.queued)
        write.assert_not_called()

    async def test_backfill_replay_still_needs_history_permission(self):
        grant = dict(rights._BUILTIN["gold_api_free_xau"], permissions=["collect", "store", "display"])
        persistence = PricingPersistence(store=AsyncMock())
        quote = Mock(spec=CanonicalQuote, source_summary={**summary(), "historical_backfill": True}, candidate_provider_id=None, candidate_price=None, status=CanonicalStatus.CONFIRMED)
        with patch.object(rights, "grants", return_value={"gold_api_free_xau": grant}), patch.object(persistence, "_persist_canonical") as write:
            result = await persistence.persist_canonical(quote)
        self.assertFalse(result.persisted)
        self.assertFalse(result.queued)
        write.assert_not_called()

    async def test_unapproved_quote_cannot_use_old_cache_or_network(self):
        store = AsyncMock()
        result = await ProviderQuoteCollector(store=store).quote(PROVIDERS["coingecko_btc"], RequestPurpose.NORMAL)
        self.assertFalse(result.usable)
        self.assertIsNone(result.quote)
        self.assertEqual(result.failure_reason, "provider_rights_denied")
        store.get_provider_quote.assert_not_awaited()

    async def test_direct_request_method_cannot_skip_permission(self):
        client = Mock()
        with self.assertRaises(ProviderCallFailure):
            await ProviderQuoteCollector()._request_once(client, PROVIDERS["coinbase_btc_usd"], {}, {})
        client.stream.assert_not_called()

    async def test_denied_storage_never_enters_retry_queue(self):
        persistence = PricingPersistence(store=AsyncMock())
        quote = Mock(spec=ProviderQuote, is_derived=False, provider_id="coingecko_btc")
        with patch.object(persistence, "_queue", new_callable=AsyncMock) as queue, patch.object(persistence, "_persist_provider_quote") as write:
            result = await persistence.persist_provider_quote(quote)
        self.assertFalse(result.persisted)
        self.assertFalse(result.queued)
        queue.assert_not_awaited()
        write.assert_not_called()

    async def test_revocation_during_write_is_not_relabelled_retryable(self):
        persistence = PricingPersistence(store=AsyncMock())
        quote = Mock(spec=ProviderQuote, is_derived=False, provider_id="gold_api_free_xau")
        with patch.object(persistence, "_queue", new_callable=AsyncMock) as queue, patch.object(persistence, "_persist_provider_quote", side_effect=InvalidPersistenceEvent("revoked")):
            result = await persistence.persist_provider_quote(quote)
        self.assertFalse(result.queued)
        queue.assert_not_awaited()

    async def test_unproved_canonical_is_not_persisted_or_queued(self):
        persistence = PricingPersistence(store=AsyncMock())
        quote = Mock(spec=CanonicalQuote, source_summary={})
        with patch.object(persistence, "_queue", new_callable=AsyncMock) as queue, patch.object(persistence, "_persist_canonical") as write:
            result = await persistence.persist_canonical(quote)
        self.assertFalse(result.persisted)
        queue.assert_not_awaited()
        write.assert_not_called()

    async def test_history_denial_happens_before_parser_or_request(self):
        queue = PricingBackfillQueue(store=AsyncMock())
        result = await queue._execute_history_job({}, PROVIDERS["coingecko_btc"])
        self.assertEqual(result, 0)

    async def test_static_replay_and_raw_storage_cannot_skip_policy(self):
        quote = Mock(spec=ProviderQuote, is_derived=False, provider_id="coingecko_btc")
        with patch("app.pricing.persistence.SessionLocal") as session:
            with self.assertRaises(InvalidPersistenceEvent):
                PricingPersistence._persist_provider_quote(quote)
            with self.assertRaises(InvalidPersistenceEvent):
                PricingPersistence()._store_raw_payload("coingecko_btc", "BTC_USD", "test", "{}", "application/json")
        session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
