from __future__ import annotations

import os
import json
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

import httpcore
import httpx
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.admin.models import OperationalSetting
from app.models import Alert as AlertModel, AlertDeliveryJob, AlertTriggerEvent, User
from app.observability import canonical_age_seconds, observe_canonical
from app.pricing.anomaly import AnomalyAssessment
from app.pricing.backfill import PricingBackfillQueue
from app.pricing.budgets import RedisRequestBudget
from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.db_models import InstrumentRecord, InstrumentProviderConfigRecord, PricingProviderRecord, PricingBackfillJobRecord
from app.pricing.freshness import FreshnessPolicy, live_eligible_until
from app.pricing.history import InternalPriceHistory
from app.pricing.instruments import get_instrument
from app.pricing.locks import DistributedPricingLocks, LockLease, PricingLeaseLost
from app.pricing.models import CanonicalStatus, PersistenceStatus, ProviderQuote, ProviderRole, SourceSemantic, SourceType, ValidationStatus, ProviderRuntimeState, RequestPurpose
from app.pricing.operational import OperationalPricingSettings
from app.pricing.parsers.history import HistoricalPricePoint
from app.pricing.parsers import build_parser
from app.pricing.persistence import PersistenceResult, PricingPersistence
from app.pricing.registry import PROVIDERS
from app.pricing.providers import QuoteFetchOutcome
from app.pricing.service import InstrumentPricingService
from app.pricing.websocket import PriceWebSocketHub
from app.routers.alerts import update_alert
from app.schemas import AlertUpdate
from app.services.alert_engine import AlertEngine, validate_webhook_url
from app.services.dlq_worker import DLQWorker, _safe_error
from app.services.webhook_transport import PinnedWebhookBackend

NOW = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)


def quote(provider_id="coingecko_btc", price="90000", age=0, *, instrument_id="BTC_USD", **fields):
    instrument = get_instrument(instrument_id)
    provider = PROVIDERS.get(provider_id, PROVIDERS["coingecko_btc"])
    return ProviderQuote.create(
        instrument_id=instrument_id, provider_id=provider_id, source_type="http",
        price=Decimal(price), currency=instrument.quote_currency,
        weight_unit=instrument.weight_unit, purity=instrument.purity,
        observed_at=NOW-timedelta(seconds=age), received_at=NOW,
        parser_version="repair-test/1", validation_status=ValidationStatus.ACCEPTED,
        persistence_status=PersistenceStatus.PERSISTED, id=1,
        source_semantic=provider.source_semantic, source_family=provider.source_family,
        venue=provider.venue, **fields,
    )


def canonical(provider_id="coingecko_btc", price="90000", age=1):
    return CanonicalPricePolicy().select(instrument=get_instrument("BTC_USD"),
        primary=quote(provider_id, price, age), previous=None, assessment=None,
        verifier_quotes=[], now=NOW).canonical


class _Locks:
    @asynccontextmanager
    async def refresh_lock(self, _instrument):
        yield object()


class PricingRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_refresh_lease_stops_owner_before_publication(self):
        import asyncio
        locks = DistributedPricingLocks()
        locks.acquire = AsyncMock(return_value=LockLease("pricing:lock:test","owner",3000))
        locks.extend = AsyncMock(return_value=False)
        locks.release = AsyncMock(return_value=False)
        published = False
        with patch("app.pricing.locks.asyncio.sleep",new=AsyncMock()):
            with self.assertRaises(PricingLeaseLost):
                async with locks.refresh_lock("BTC_USD"):
                    await asyncio.Event().wait()
                    published = True
        self.assertFalse(published)
        self.assertEqual(asyncio.current_task().cancelling(),0)

    async def test_newer_database_quote_wins_over_old_redis_cache(self):
        store, history = AsyncMock(), AsyncMock()
        old, new = canonical(age=10), canonical(age=1)
        store.get_canonical.return_value = old
        history.latest_canonical.return_value = new
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        service = InstrumentPricingService(store=store, history=history, operational=operational)
        self.assertIs(await service.get_canonical("btc_usd"), new)
        history.latest_canonical.side_effect = RuntimeError("database unavailable")
        self.assertIs(await service.get_canonical("BTC_USD"), old)

    async def test_history_near_now_cannot_replace_current_snapshot(self):
        store, history = AsyncMock(), AsyncMock()
        live, historical = canonical(age=10), canonical(age=1)
        historical.source_summary["historical_backfill"] = True
        store.get_canonical.return_value = live
        history.latest_canonical.return_value = historical
        store.get_all_canonical.return_value = {"BTC_USD":live}
        history.latest_all.return_value = {"BTC_USD":historical}
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        service = InstrumentPricingService(store=store,history=history,operational=operational)
        self.assertIs(await service.get_canonical("BTC_USD"),live)
        self.assertIs((await service.get_all_canonical())["BTC_USD"],live)

    async def test_older_canonical_never_writes_or_publishes(self):
        store, persistence = AsyncMock(), AsyncMock()
        service = InstrumentPricingService(store=store, persistence=persistence)
        previous = canonical(age=1)
        self.assertIs(await service._commit(canonical(age=2), previous), previous)
        store.next_sequence.assert_not_called()
        persistence.persist_canonical.assert_not_called()

    def test_same_price_new_observation_still_publishes_freshness(self):
        self.assertTrue(InstrumentPricingService._publication_changed(canonical(age=2), canonical(age=1)))

    def test_delivery_errors_never_store_external_exception_secrets(self):
        error = RuntimeError("https://example.test/?key=private-key body=private-body")
        self.assertEqual(_safe_error(error), "RuntimeError: delivery attempt failed")

    def test_nonfinite_alert_target_is_rejected(self):
        for value in (float("inf"),float("nan")):
            with self.assertRaises(ValidationError):
                AlertUpdate(target_price=value)

    async def test_corrupt_provider_override_only_disables_affected_source(self):
        operational = OperationalPricingSettings()
        async def value(key, scope_id="global", default=None):
            return {"trust_score":"NaN"} if key=="provider.config" and scope_id=="coingecko_btc" else default
        with patch.object(operational,"_provider_rows",return_value=[]), patch.object(operational,"value",side_effect=value):
            providers = await operational.providers_for("BTC_USD")
        self.assertFalse(next(item for item in providers if item.provider_id=="coingecko_btc").enabled)
        self.assertTrue(any(item.enabled for item in providers if item.provider_id!="coingecko_btc"))

    async def test_scoped_backfill_runs_despite_disabled_global_default(self):
        store, operational = AsyncMock(), AsyncMock()
        store.ping.return_value = True
        operational.instrument.return_value = get_instrument("BTC_USD")
        operational.feature_enabled.side_effect = lambda _key, **kwargs: kwargs.get("scope_id")=="BTC_USD"
        queue = PricingBackfillQueue(store=store,operational=operational)
        queue._drain_redis_jobs = AsyncMock()
        queue._claim_job = Mock(return_value={"id":1,"instrument_id":"BTC_USD","attempt_count":1})
        queue._history_provider = AsyncMock(return_value=None)
        queue._finish_job = Mock()
        with patch("app.pricing.backfill.PROVIDERS_BY_INSTRUMENT", {"BTC_USD":(PROVIDERS["coingecko_btc"],)}):
            counts = await queue.process_jobs(maximum_jobs=1)
        self.assertEqual(counts,{"completed":0,"deferred":0,"failed":0})
        self.assertEqual(operational.feature_enabled.call_args.kwargs["scope_id"],"BTC_USD")
        queue._history_provider.assert_awaited_once()
        queue._claim_job.assert_not_called()
        queue._finish_job.assert_not_called()

    async def test_disabled_instrument_backfill_does_not_fetch_history(self):
        store, operational = AsyncMock(), AsyncMock()
        store.ping.return_value = True
        operational.feature_enabled.return_value = True
        operational.instrument.return_value = replace(get_instrument("BTC_USD"),enabled=False)
        queue = PricingBackfillQueue(store=store,operational=operational)
        queue._drain_redis_jobs = AsyncMock()
        queue._claim_job = Mock(return_value={"id":1,"instrument_id":"BTC_USD","attempt_count":1})
        queue._history_provider = AsyncMock()
        queue._finish_job = Mock()
        self.assertEqual(await queue.process_jobs(maximum_jobs=1),{"completed":0,"deferred":0,"failed":0})
        queue._history_provider.assert_not_called()
        queue._claim_job.assert_not_called()

    async def test_zero_hourly_budget_blocks_all_external_calls(self):
        store = Mock()
        provider = PROVIDERS["coingecko_btc"]
        provider = replace(provider, budget=replace(provider.budget, requests_per_hour=0))
        result = await RedisRequestBudget(store).consume(provider, RequestPurpose.NORMAL)
        self.assertFalse(result.allowed)
        store.client.assert_not_called()

    def test_parser_reads_loaded_settings_without_environment_export(self):
        with patch("app.pricing.parsers.settings.nerkh_io_currency_unit", "TOMAN"), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(build_parser("nerkh_io_usd_v1").source_unit, "TOMAN")

    async def test_stale_external_primary_is_returned_unusable(self):
        provider = PROVIDERS["coingecko_btc"]
        store = AsyncMock()
        store.get_provider_quote.return_value = None
        collector = AsyncMock()
        collector.quote.return_value = QuoteFetchOutcome(quote(age=600), True, False, True, None)
        service = InstrumentPricingService(store=store, collector=collector)
        with patch("app.pricing.service.utc_now", return_value=NOW):
            outcome = await service._first_usable((provider,), RequestPurpose.NORMAL, object(),
                maximum_external_calls=1, instrument=get_instrument("BTC_USD"))
        self.assertFalse(outcome.usable)
        self.assertEqual(outcome.failure_reason, "source_not_live")

    async def test_independent_fallback_is_available_for_anomaly_verification(self):
        candidate = quote("nobitex_stats_btc", "90000", instrument_id="BTC_TOMAN")
        provider = PROVIDERS["bitpin_btc_toman"]
        self.assertEqual(provider.role, ProviderRole.FALLBACK)
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_TOMAN")
        async def providers_for(_instrument_id, *roles):
            return (provider,) if provider.role in roles else ()
        operational.providers_for.side_effect = providers_for
        store = AsyncMock()
        store.get_provider_runtime.return_value = ProviderRuntimeState(provider_id=provider.provider_id, instrument_id=provider.instrument_id)
        budgets = AsyncMock()
        budgets.pressure.return_value = 0
        collector = AsyncMock()
        verifier = quote(provider.provider_id, "90000", instrument_id="BTC_TOMAN")
        collector.quote.return_value = QuoteFetchOutcome(verifier, True, False, True, None)
        service = InstrumentPricingService(store=store, budgets=budgets, collector=collector, operational=operational)
        assessment = AnomalyAssessment(True, Decimal(10), Decimal(2), Decimal(0), "high", "jump")
        with patch("app.pricing.service.utc_now", return_value=NOW):
            verifiers = await service._verification_quotes("BTC_TOMAN", candidate, assessment, object())
        self.assertEqual(verifiers, [verifier])

    def test_receive_anchor_cannot_extend_maximum_source_age(self):
        policy = FreshnessPolicy(maximum_source_age_seconds=600,
            provider_live_ttl_seconds=360, instrument_operational_ttl_seconds=360,
            instrument_stale_after_seconds=600, instrument_expire_after_seconds=900,
            anchor_live_window_at_receive_time=True)
        self.assertEqual(live_eligible_until(NOW-timedelta(seconds=599), NOW, policy), NOW+timedelta(seconds=1))

    def test_zero_volume_survives_cache_roundtrip(self):
        original = quote(volume=0)
        self.assertEqual(ProviderQuote.from_dict(original.to_dict(authenticated=True)).volume, Decimal(0))
        with self.assertRaises(ValueError):
            quote(volume=-1)

    async def test_sparse_history_is_partial_even_with_first_point(self):
        with patch.object(InternalPriceHistory, "_query_canonical_history", return_value=[
            {"timestamp": (NOW-timedelta(days=365)).isoformat(), "price": 90000},
        ]):
            result = await InternalPriceHistory().canonical_history("BTC_USD", "1y", end=NOW)
        self.assertEqual(result.status, "partial")
        self.assertIsNone(result.missing_before)

    async def test_internal_history_gap_requests_whole_range(self):
        points = [{"timestamp": (NOW-timedelta(minutes=i)).isoformat(), "price": 90000}
                  for i in range(61) if not 20 <= i <= 40]
        with patch.object(InternalPriceHistory, "_query_canonical_history", return_value=sorted(points, key=lambda p:p["timestamp"])):
            result = await InternalPriceHistory().canonical_history("BTC_USD", "1h", end=NOW)
        self.assertEqual(result.status, "partial")

    def test_observation_age_increases_without_refresh(self):
        current = canonical()
        observe_canonical(current)
        with patch("app.observability.time.time", return_value=NOW.timestamp()+10):
            first = next(item.value for item in canonical_age_seconds.collect()[0].samples
                         if item.labels["instrument"] == "BTC_USD")
        with patch("app.observability.time.time", return_value=NOW.timestamp()+20):
            second = next(item.value for item in canonical_age_seconds.collect()[0].samples
                          if item.labels["instrument"] == "BTC_USD")
        with patch("app.observability.time.time", return_value=NOW.timestamp()+30):
            samples = canonical_age_seconds.collect()[0].samples
        self.assertEqual(next(item.value for item in samples if item.labels["instrument"] == "BTC_USD"), 31)
        self.assertEqual(second-first, 10)

    async def test_worker_ignores_older_observation_under_lock_before_write(self):
        store = AsyncMock()
        store.ping.return_value = True
        persistence = AsyncMock()
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        service = InstrumentPricingService(store=store, persistence=persistence, locks=_Locks(), operational=operational)
        service.get_canonical = AsyncMock(return_value=canonical(age=0))
        with patch("app.pricing.service.utc_now", return_value=NOW):
            outcome = await service.ingest_worker_quote(instrument_id="BTC_USD", provider_id="coingecko_btc",
                price=Decimal("20000"), observed_at=NOW-timedelta(seconds=599), historical=False)
        self.assertEqual(outcome, "ignored_older")
        persistence.persist_provider_quote.assert_not_called()

    async def test_ignored_live_quote_does_not_block_next_batch_instrument(self):
        from app.routers import pricing_worker
        request = Mock()
        request.body = AsyncMock(return_value=json.dumps({"quotes":[
            {"instrument_id":"BTC_USD","provider_id":"coingecko_btc","price":90000,"observed_at":NOW.isoformat()},
            {"instrument_id":"USDT_USD","provider_id":"coingecko_usdt","price":1,"observed_at":NOW.isoformat()},
        ]}).encode())
        with patch.object(pricing_worker, "_authenticate", new=AsyncMock()), \
             patch.object(pricing_worker.instrument_pricing_service, "ingest_worker_quote", new=AsyncMock(side_effect=["ignored_older","accepted"])) as ingest:
            result = await pricing_worker.ingest(request)
        self.assertEqual(ingest.await_count,2)
        self.assertEqual(result,{"accepted":2,"published":1,"history_persisted":0,"ignored":1})

    async def test_worker_jump_keeps_previous_when_not_independently_confirmed(self):
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        operational.providers_for.return_value = (PROVIDERS["coingecko_btc"],)
        persistence = AsyncMock()
        async def persist(candidate):
            candidate.persistence_status = PersistenceStatus.PERSISTED
            return PersistenceResult(True, False, None, None)
        persistence.persist_provider_quote.side_effect = persist
        persistence.persist_anomaly.return_value = 1
        service = InstrumentPricingService(store=AsyncMock(), operational=operational,
            persistence=persistence, locks=_Locks())
        previous = canonical(price="90000", age=1)
        service.get_canonical = AsyncMock(return_value=previous)
        service._assess_candidate = AsyncMock(return_value=AnomalyAssessment(
            True, Decimal("77"), Decimal("2"), Decimal(0), "critical", "large_jump"))
        service._verification_quotes = AsyncMock(return_value=[])
        service._attach_changes = AsyncMock()
        service._commit = AsyncMock()
        with patch("app.pricing.service.utc_now", return_value=NOW):
            await service.ingest_worker_quote(instrument_id="BTC_USD", provider_id="coingecko_btc",
                price=Decimal("20000"), observed_at=NOW, historical=False)
        committed = service._commit.call_args.args[0]
        self.assertEqual(committed.price, previous.price)
        self.assertEqual(committed.status, CanonicalStatus.SUSPICIOUS_UNCONFIRMED)
        service._verification_quotes.assert_awaited_once()

    async def test_worker_verifier_cannot_publish_and_public_silver_fallback_can(self):
        self.assertEqual(PROVIDERS["gold_api_free_xag"].role,ProviderRole.FALLBACK)
        operational, persistence, store = AsyncMock(), AsyncMock(), AsyncMock()
        operational.instrument.return_value = get_instrument("XAG_USD_OZ")
        provider = replace(PROVIDERS["gold_api_free_xag"],role=ProviderRole.VERIFIER)
        operational.providers_for.return_value = (provider,)
        service = InstrumentPricingService(store=store,operational=operational,persistence=persistence,locks=_Locks())
        service.get_canonical = AsyncMock(return_value=None)
        service._assess_candidate = AsyncMock(return_value=None)
        service._attach_changes = AsyncMock()
        service._commit = AsyncMock()
        async def persist(candidate):
            candidate.persistence_status = PersistenceStatus.PERSISTED
            return PersistenceResult(True,False,None,None)
        persistence.persist_provider_quote.side_effect = persist
        args = dict(instrument_id="XAG_USD_OZ",provider_id="gold_api_free_xag",price=Decimal("50"),observed_at=NOW,historical=False)
        with patch("app.pricing.service.utc_now",return_value=NOW):
            self.assertEqual(await service.ingest_worker_quote(**args),"ignored_role")
            persistence.persist_provider_quote.assert_not_called()
            operational.providers_for.return_value = (replace(provider,role=ProviderRole.FALLBACK),)
            self.assertEqual(await service.ingest_worker_quote(**args),"accepted")
        service._commit.assert_awaited_once()

    async def test_current_cache_honors_runtime_instrument_disable_and_expiry(self):
        operational, store, history = AsyncMock(), AsyncMock(), AsyncMock()
        definition = get_instrument("BTC_USD")
        operational.instrument.return_value = replace(definition,enabled=False)
        store.get_canonical.return_value = canonical(age=40)
        store.get_all_canonical.return_value = {"BTC_USD":canonical(age=40)}
        history.latest_canonical.return_value = None
        history.latest_all.return_value = {}
        service = InstrumentPricingService(store=store,history=history,operational=operational)
        self.assertIsNone(await service.get_canonical("BTC_USD"))
        self.assertEqual(await service.get_all_canonical(),{})
        operational.instrument.return_value = replace(definition,operational_ttl_seconds=10,stale_after_seconds=20,expire_after_seconds=30)
        current = await service.get_canonical("BTC_USD")
        self.assertEqual(current.effective_status(NOW),CanonicalStatus.EXPIRED)
        self.assertEqual(current.expires_at,current.observed_at+timedelta(seconds=30))

    async def test_worker_history_requires_durable_both_writes_and_stays_historical(self):
        operational, persistence = AsyncMock(), AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        operational.providers_for.return_value = (PROVIDERS["coingecko_btc"],)
        async def persist(candidate):
            candidate.persistence_status = PersistenceStatus.PERSISTED
            return PersistenceResult(True,False,None,None)
        persistence.persist_provider_quote.side_effect = persist
        persistence.persist_canonical.return_value = PersistenceResult(False,True,"queued",None)
        service = InstrumentPricingService(store=AsyncMock(),operational=operational,persistence=persistence)
        from app.pricing.service import PricingRefreshSuspended
        with patch("app.pricing.service.utc_now",return_value=NOW):
            with self.assertRaises(PricingRefreshSuspended):
                await service.ingest_worker_quote(instrument_id="BTC_USD",provider_id="coingecko_btc",price=Decimal("90000"),observed_at=NOW-timedelta(days=1),historical=True)
            persistence.persist_canonical.return_value = PersistenceResult(True,False,None,None)
            outcome = await service.ingest_worker_quote(instrument_id="BTC_USD",provider_id="coingecko_btc",price=Decimal("90000"),observed_at=NOW-timedelta(days=1),historical=True)
        self.assertEqual(outcome,"historical_persisted")
        self.assertTrue(persistence.persist_canonical.call_args.args[0].source_summary["historical_backfill"])
        service.store.set_canonical.assert_not_called()

    def test_approved_telegram_can_confirm_but_unapproved_cannot(self):
        primary = quote(price="100000")
        telegram = quote("telegram:1", "100000")
        telegram.source_type = SourceType.TELEGRAM
        telegram.source_semantic = SourceSemantic.TELEGRAM_OBSERVATION
        telegram.source_family = telegram.venue = "telegram:1"
        telegram.metadata.update(source_identity="telegram:1", trust_score="0.9", minimum_confidence="0.5",
            confidence_score="0.9", maximum_message_age_seconds=60, maximum_deviation_percent=2,
            whitelisted=True, source_role="verifier", approved_verifier=True)
        telegram.confidence_score = Decimal("0.9")
        assessment = AnomalyAssessment(True, Decimal(10), Decimal(2), Decimal(0), "high", "jump")
        policy = CanonicalPricePolicy()
        decision = policy.select(instrument=get_instrument("BTC_USD"), primary=primary,
            previous=canonical(), assessment=assessment, verifier_quotes=[telegram], now=NOW)
        self.assertEqual(decision.canonical.status, CanonicalStatus.CONFIRMED)
        telegram.metadata["approved_verifier"] = False
        decision = policy.select(instrument=get_instrument("BTC_USD"), primary=primary,
            previous=canonical(), assessment=assessment, verifier_quotes=[telegram], now=NOW)
        self.assertEqual(decision.canonical.status, CanonicalStatus.SUSPICIOUS_UNCONFIRMED)

    async def test_backfill_does_not_truncate_at_batch_boundary(self):
        provider = PROVIDERS["coingecko_btc"]
        persistence = AsyncMock()
        persistence.persist_provider_quote.return_value = PersistenceResult(True, False, None, None)
        persistence.persist_canonical.return_value = PersistenceResult(True, False, None, None)
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        queue = PricingBackfillQueue(persistence=persistence, operational=operational)
        queue.batch_size = 2
        queue._renew_job = Mock(return_value=True)
        parser = SimpleNamespace(parser_version="coingecko-history/1", parse=Mock(return_value=[
            HistoricalPricePoint(NOW-timedelta(minutes=i), Decimal("90000"), Decimal(0)) for i in range(5)
        ]))
        response = httpx.Response(200, json={}, request=httpx.Request("GET", "https://example.test"))
        client = AsyncMock()
        client.get.return_value = response
        with patch("app.pricing.backfill.utc_now", return_value=NOW), \
             patch("app.pricing.backfill.build_history_parser", return_value=parser), \
             patch("app.pricing.backfill._history_request_options", return_value=({}, {})), \
             patch("app.pricing.backfill.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            count = await queue._execute_history_job({"id": 1, "instrument_id":"BTC_USD", "range_start":NOW-timedelta(hours=1), "range_end":NOW}, provider)
        self.assertEqual(count, 5)
        self.assertEqual(persistence.persist_canonical.await_count, 5)

    async def test_backfill_failed_write_cannot_complete(self):
        persistence = AsyncMock()
        persistence.persist_provider_quote.return_value = PersistenceResult(False, True, "1-0", None)
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_USD")
        queue = PricingBackfillQueue(persistence=persistence, operational=operational)
        parser = SimpleNamespace(parser_version="coingecko-history/1", parse=Mock(return_value=[
            HistoricalPricePoint(NOW, Decimal("90000"), Decimal(0))]))
        client = AsyncMock()
        client.get.return_value = httpx.Response(200, json={}, request=httpx.Request("GET", "https://example.test"))
        with patch("app.pricing.backfill.utc_now", return_value=NOW), \
             patch("app.pricing.backfill.build_history_parser", return_value=parser), \
             patch("app.pricing.backfill._history_request_options", return_value=({}, {})), \
             patch("app.pricing.backfill.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            with self.assertRaisesRegex(RuntimeError, "persistence"):
                await queue._execute_history_job({"id":1, "instrument_id":"BTC_USD", "range_start":NOW-timedelta(hours=1), "range_end":NOW}, PROVIDERS["coingecko_btc"])
        persistence.persist_canonical.assert_not_called()

    async def test_webhook_pins_literal_ip_before_any_http_write(self):
        stream = Mock()
        stream.get_extra_info.return_value = ("8.8.8.8", 443)
        stream.aclose = AsyncMock()
        delegate = AsyncMock()
        delegate.connect_tcp.return_value = stream
        backend = PinnedWebhookBackend("example.test", {"8.8.8.8"}, backend=delegate)
        self.assertIs(await backend.connect_tcp("example.test", 443), stream)
        self.assertEqual(delegate.connect_tcp.call_args.args[0], "8.8.8.8")
        stream.get_extra_info.return_value = ("127.0.0.1", 443)
        with self.assertRaises(httpcore.ConnectError):
            await backend.connect_tcp("example.test", 443)
        stream.aclose.assert_awaited_once()
        stream.get_extra_info.return_value = None
        with self.assertRaises(httpcore.ConnectError):
            await backend.connect_tcp("example.test", 443)

    def test_webhook_rejects_zero_out_of_range_and_noninteger_ports(self):
        for port in ("0", "65536", "bad"):
            with self.assertRaisesRegex(ValueError,"port"):
                validate_webhook_url(f"https://example.test:{port}/hook")

    async def test_resync_discards_backlog_and_marks_snapshot(self):
        hub = PriceWebSocketHub()
        import asyncio
        queue = asyncio.Queue(maxsize=2)
        queue.put_nowait({"event_type":"old"})
        hub._clients["client"] = queue
        await hub._request_resync("reconnected")
        self.assertEqual(queue.get_nowait(), {"event_type":"resync", "reason":"reconnected"})
        self.assertTrue(queue.empty())

    def test_websocket_quote_has_complete_currency_unit_and_change_fields(self):
        for instrument_id in ("BTC_USD", "GOLD_18K_TOMAN_GRAM"):
            instrument = get_instrument(instrument_id)
            current = replace(canonical(), instrument_id=instrument_id, change_24h=Decimal("3.2"))
            payload = PriceWebSocketHub._public_event(current)
            self.assertEqual(payload["currency"], instrument.quote_currency.value)
            self.assertEqual(payload["market"], instrument.market.value)
            self.assertEqual(payload["unit"], instrument.weight_unit.value)
            self.assertEqual(payload["purity"], float(instrument.purity) if instrument.purity is not None else None)
            self.assertEqual(payload["display_decimals"], instrument.display_decimals)
            self.assertEqual(payload["change_24h"], 3.2)

    async def test_websocket_resync_reads_current_policy_snapshot(self):
        import asyncio
        from fastapi import WebSocketDisconnect
        store, reader = AsyncMock(), AsyncMock(return_value={})
        hub = PriceWebSocketHub(store=store,snapshot_reader=reader)
        websocket = Mock()
        async def receive():
            await asyncio.Event().wait()
        websocket.receive_text = receive
        websocket.send_json = AsyncMock(side_effect=WebSocketDisconnect)
        queue = asyncio.Queue()
        queue.put_nowait({"event_type":"resync","reason":"reconnected"})
        with self.assertRaises(WebSocketDisconnect):
            await hub._event_loop(websocket,queue,{"BTC_USD"})
        reader.assert_awaited_once()
        store.get_all_canonical.assert_not_called()
        self.assertEqual(websocket.send_json.call_args.args[0]["prices"],[])


class DatabaseRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread":False})
        @event.listens_for(self.engine, "connect")
        def register_lock(connection, _record):
            connection.create_function("pg_advisory_xact_lock", 1, lambda _value:1)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    async def test_operational_scopes_and_restart_preserve_policy(self):
        with patch("app.pricing.persistence.SessionLocal", self.session):
            PricingPersistence._sync_provider_catalog()
        with self.session() as db:
            db.get(PricingProviderRecord, "coingecko_btc").enabled = False
            db.get(InstrumentProviderConfigRecord, {"instrument_id":"BTC_USD", "provider_id":"coingecko_btc"}).enabled = False
            db.get(InstrumentRecord, "BTC_USD").base_anomaly_threshold_percent = Decimal("4")
            db.add_all([
                OperationalSetting(id=1,key="anomaly_threshold_percent",scope_id="global",value=5,description="test",is_sensitive=False),
                OperationalSetting(id=2,key="anomaly_threshold_percent",scope_id="BTC_USD",value=2,description="test",is_sensitive=False),
                OperationalSetting(id=3,key="canonical_expiry_seconds",scope_id="BTC_USD",value=30,description="test",is_sensitive=False),
                OperationalSetting(id=4,key="provider_budget_requests_per_hour",scope_id="coingecko_btc",value=0,description="test",is_sensitive=False),
            ])
            db.commit()
        with patch("app.pricing.persistence.SessionLocal", self.session):
            PricingPersistence._sync_provider_catalog()
        with patch("app.pricing.operational.SessionLocal", self.session):
            operational = OperationalPricingSettings()
            instrument = await operational.instrument("BTC_USD")
            self.assertEqual(instrument.base_anomaly_threshold_percent, Decimal(2))
            self.assertEqual(instrument.expire_after_seconds, 30)
            provider = next(item for item in await operational.providers_for("BTC_USD") if item.provider_id=="coingecko_btc")
            self.assertFalse(provider.enabled)
            self.assertEqual(provider.budget.requests_per_hour, 0)

    async def test_deferred_backfill_is_claimable_again(self):
        with self.session() as db:
            db.add(InstrumentRecord(instrument_id="BTC_USD",base_asset="BTC",quote_currency="USD",market="global",region="global",display_decimals=2,operational_ttl_seconds=60,stale_after_seconds=120,expire_after_seconds=600,base_anomaly_threshold_percent=2,maximum_dynamic_threshold_percent=5,minimum_sanity_price=1,maximum_sanity_price=10000000,importance=10,enabled=True,allow_derived_fallback=False))
            db.add(PricingBackfillJobRecord(id=1,instrument_id="BTC_USD",range_start=NOW-timedelta(hours=1),range_end=NOW,status="deferred",priority=100,attempt_count=0,idempotency_key="test",next_attempt_at=NOW-timedelta(seconds=1)))
            db.commit()
        with patch("app.pricing.backfill.SessionLocal",self.session), patch("app.pricing.backfill.utc_now",return_value=NOW):
            job = PricingBackfillQueue._claim_job(("BTC_USD",))
        self.assertEqual(job["id"],1)

    async def test_cancelled_delivery_never_sends_and_completion_cannot_overwrite(self):
        with self.session() as db:
            db.add(User(id=1,username="test",email="test@example.test",password_hash="test",full_name="Test",is_active=True))
            db.add(AlertModel(id=1,user_id=1,asset="btc",target_price=100000,alert_type="price",currency_mode="usd",condition="above",notify_app=False,notify_email=False,notify_webhook=True,webhook_url="https://example.test",enable_dlq=True,is_active=True))
            db.add(AlertTriggerEvent(id=1,alert_id=1,condition_snapshot={"assets":[]},status="queued",idempotency_key="event"))
            db.add(AlertDeliveryJob(id=1,alert_id=1,trigger_event_id=1,channel="webhook",destination_reference="test",status="cancelled",attempt_count=1,idempotency_key="job"))
            db.commit()
        engine = AlertEngine()
        engine._send_webhook = AsyncMock()
        with patch("app.services.alert_engine.SessionLocal",self.session):
            result = await engine.deliver_job(1,expected_attempt=1)
        self.assertTrue(result["skipped"])
        engine._send_webhook.assert_not_called()
        worker = DLQWorker(engine)
        with patch("app.services.dlq_worker.SessionLocal",self.session):
            worker._mark_delivered(1,{"accepted":True},1)
            worker._mark_failed(1,RuntimeError("test"),1)
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob,1).status,"cancelled")

    async def test_null_formula_rejected_before_persist_and_instrument_is_used(self):
        with self.session() as db:
            db.add(User(id=1,username="test",email="test@example.test",password_hash="test",full_name="Test",is_active=True))
            db.add(AlertModel(id=1,user_id=1,asset="formula",alert_type="formula",formula="btc > 100",currency_mode="usd",condition="above",notify_app=False,notify_email=False,notify_webhook=False,enable_dlq=False,is_active=True))
            db.commit()
            user = db.get(User,1)
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as raised:
                update_alert(1,AlertUpdate(formula=None),user,db)
            self.assertEqual(raised.exception.status_code,422)
            self.assertEqual(db.get(AlertModel,1).formula,"btc > 100")
        with self.assertRaises(ValidationError):
            AlertUpdate(notify_app=None)
        asset = {"asset":"GOLD_24K_TOMAN_GRAM","price_toman":100,"toman_status":"live",
                 "toman_source_semantic":"physical_market_quote","toman_is_persisted":True,
                 "toman_persistence_status":"persisted","toman_is_suspicious":False,"toman_expired":False,
                 "toman_live_eligible":True,"toman_derivation_depth":0}
        alert = AlertModel(asset="gold",instrument_id="GOLD_24K_TOMAN_GRAM",alert_type="price",currency_mode="toman",target_price=90,condition="above",price_source_mode="ordinary")
        self.assertTrue(AlertEngine()._should_trigger_model(alert,{"assets":[asset]}))

    async def test_alert_instrument_patch_is_saved_normalized_and_currency_is_validated(self):
        from fastapi import HTTPException
        with self.session() as db:
            db.add(User(id=1,username="test",email="test@example.test",password_hash="test",full_name="Test",is_active=True))
            db.add(AlertModel(id=1,user_id=1,asset="btc",alert_type="price",target_price=100,currency_mode="usd",condition="above",notify_app=True,notify_email=False,notify_webhook=False,enable_dlq=False,is_active=True))
            db.commit()
            user = db.get(User,1)
            updated = update_alert(1,AlertUpdate(instrument_id=" btc_usd "),user,db)
            self.assertEqual(updated.instrument_id,"BTC_USD")
            with self.assertRaises(HTTPException) as raised:
                update_alert(1,AlertUpdate(currency_mode="toman"),user,db)
            self.assertEqual(raised.exception.status_code,422)
            self.assertEqual(updated.currency_mode,"usd")
            updated = update_alert(1,AlertUpdate(alert_type="formula",formula="btc > 100",instrument_id=None),user,db)
            self.assertEqual(updated.alert_type,"formula")

    async def test_reclaimed_delivery_attempt_cannot_be_completed_by_old_worker(self):
        with self.session() as db:
            db.add(User(id=1,username="test",email="test@example.test",password_hash="test",full_name="Test",is_active=True))
            db.add(AlertModel(id=1,user_id=1,asset="btc",target_price=100,alert_type="price",currency_mode="usd",condition="above",notify_app=True,notify_email=False,notify_webhook=False,enable_dlq=True,is_active=True))
            db.add(AlertTriggerEvent(id=1,alert_id=1,condition_snapshot={"assets":[]},status="queued",idempotency_key="event"))
            db.add(AlertDeliveryJob(id=1,alert_id=1,trigger_event_id=1,channel="push",destination_reference="test",status="sending",attempt_count=2,idempotency_key="job"))
            db.commit()
        worker = DLQWorker(AlertEngine())
        with patch("app.services.dlq_worker.SessionLocal",self.session):
            worker._mark_delivered(1,{"accepted":True},1)
            worker._mark_failed(1,RuntimeError("late failure"),1)
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob,1).status,"sending")
        with patch("app.services.dlq_worker.SessionLocal",self.session):
            worker._mark_delivered(1,{"accepted":True},2)
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob,1).status,"delivered")

    async def test_backfill_finish_preserves_cancel_and_new_attempt(self):
        with self.session() as db:
            db.add(PricingBackfillJobRecord(id=1,instrument_id="BTC_USD",range_start=NOW-timedelta(hours=1),range_end=NOW,status="cancelled",priority=100,attempt_count=1,idempotency_key="test"))
            db.commit()
        with patch("app.pricing.backfill.SessionLocal",self.session):
            PricingBackfillQueue._finish_job(1,"completed",None,1)
        with self.session() as db:
            job = db.get(PricingBackfillJobRecord,1)
            self.assertEqual(job.status,"cancelled")
            job.status, job.attempt_count = "processing", 2
            db.commit()
        with patch("app.pricing.backfill.SessionLocal",self.session):
            PricingBackfillQueue._finish_job(1,"completed",None,1)
        with self.session() as db:
            self.assertEqual(db.get(PricingBackfillJobRecord,1).status,"processing")


if __name__ == "__main__":
    unittest.main()
