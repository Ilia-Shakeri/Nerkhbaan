from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ["DEBUG"] = "false"

from app.pricing.freshness import (
    FreshnessPolicy,
    FreshnessStatus,
    cache_retention_until,
    expired_after,
    freshness_boundaries,
    live_eligible_until,
    stale_display_until,
)
from app.pricing.cache import PricingRedisStore
from app.pricing.instruments import get_instrument
from app.pricing.models import (
    Currency,
    PersistenceStatus,
    PriceSemantic,
    ProviderQuote,
    ProviderRuntimeState,
    RequestPurpose,
    SourceSemantic,
    SourceType,
    ValidationStatus,
)
from app.pricing.parsers.base import ParserContext, ParserError, optional_timestamp
from app.pricing.providers import ProviderQuoteCollector
from app.pricing.persistence import PersistenceResult
from app.pricing.registry import PROVIDERS


FROZEN_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _policy() -> FreshnessPolicy:
    return FreshnessPolicy(
        maximum_source_age_seconds=60,
        provider_live_ttl_seconds=120,
        instrument_operational_ttl_seconds=60,
        instrument_stale_after_seconds=300,
        instrument_expire_after_seconds=600,
        future_clock_skew_seconds=30,
    )


def _quote(**overrides) -> ProviderQuote:
    values = {
        "instrument_id": "BTC_USD",
        "provider_id": "coincap_btc",
        "source_type": SourceType.HTTP,
        "price": Decimal("64000"),
        "currency": Currency.USD,
        "weight_unit": get_instrument("BTC_USD").weight_unit,
        "purity": None,
        "observed_at": FROZEN_NOW,
        "received_at": FROZEN_NOW,
        "parser_version": "phase2-semantics/1",
        "validation_status": ValidationStatus.ACCEPTED,
        "persistence_status": PersistenceStatus.PERSISTED,
    }
    values.update(overrides)
    return ProviderQuote.create(**values)


class FreshnessBoundaryTests(unittest.TestCase):
    def test_all_boundaries_use_source_age_without_refreshing_it(self) -> None:
        source_time = FROZEN_NOW - timedelta(seconds=40)
        policy = _policy()

        self.assertEqual(
            live_eligible_until(source_time, FROZEN_NOW, policy),
            source_time + timedelta(seconds=60),
        )
        self.assertEqual(
            stale_display_until(source_time, FROZEN_NOW, policy),
            source_time + timedelta(seconds=300),
        )
        self.assertEqual(
            expired_after(source_time, FROZEN_NOW, policy),
            source_time + timedelta(seconds=600),
        )
        self.assertEqual(
            cache_retention_until(source_time, FROZEN_NOW, policy),
            FROZEN_NOW + timedelta(seconds=600),
        )

    def test_live_and_expired_edges_are_inclusive_then_flip(self) -> None:
        boundaries = freshness_boundaries(
            FROZEN_NOW - timedelta(seconds=40),
            FROZEN_NOW,
            _policy(),
        )

        self.assertIs(
            boundaries.status_at(boundaries.live_eligible_until),
            FreshnessStatus.LIVE,
        )
        self.assertIs(
            boundaries.status_at(
                boundaries.live_eligible_until + timedelta(microseconds=1)
            ),
            FreshnessStatus.STALE,
        )
        self.assertIs(
            boundaries.status_at(boundaries.expired_after),
            FreshnessStatus.STALE,
        )
        self.assertIs(
            boundaries.status_at(boundaries.expired_after + timedelta(microseconds=1)),
            FreshnessStatus.EXPIRED,
        )

    def test_future_skew_is_kept_but_cannot_extend_live_window(self) -> None:
        source_time = FROZEN_NOW + timedelta(seconds=30)
        boundaries = freshness_boundaries(source_time, FROZEN_NOW, _policy())

        self.assertEqual(
            boundaries.live_eligible_until,
            FROZEN_NOW + timedelta(seconds=60),
        )
        with self.assertRaises(ValueError):
            freshness_boundaries(
                source_time + timedelta(microseconds=1),
                FROZEN_NOW,
                _policy(),
            )

    def test_parser_keeps_allowed_future_source_timestamp(self) -> None:
        instrument = get_instrument("BTC_USD")
        context = ParserContext(
            instrument=instrument,
            received_at=FROZEN_NOW,
            maximum_timestamp_age_seconds=60,
            maximum_future_clock_skew_seconds=30,
        )
        allowed = FROZEN_NOW + timedelta(seconds=30)

        self.assertEqual(optional_timestamp(allowed.isoformat(), context, "source"), allowed)
        with self.assertRaises(ParserError):
            optional_timestamp(
                (allowed + timedelta(microseconds=1)).isoformat(),
                context,
                "source",
            )


class _QuoteStore:
    def __init__(self, quote: ProviderQuote) -> None:
        self.quote = quote
        self.runtime = ProviderRuntimeState(
            provider_id=quote.provider_id,
            instrument_id=quote.instrument_id,
        )

    async def get_provider_quote(self, _provider_id: str, _instrument_id: str):
        return self.quote

    async def get_provider_runtime(self, _provider_id: str, _instrument_id: str):
        return self.runtime

    async def set_provider_runtime(self, runtime: ProviderRuntimeState) -> None:
        self.runtime = runtime


class RetainedCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_retained_old_cache_returns_stale_status_and_same_time(self) -> None:
        instrument = replace(
            get_instrument("BTC_USD"),
            operational_ttl_seconds=60,
        )
        provider = replace(
            PROVIDERS["coinbase_btc_usd"],
            enabled=False,
            api_key_setting=None,
            operational_ttl_seconds=120,
        )
        observed_at = FROZEN_NOW - timedelta(seconds=61)
        quote = _quote(observed_at=observed_at, received_at=observed_at)
        collector = ProviderQuoteCollector(
            store=_QuoteStore(quote),
            budgets=object(),
            locks=object(),
            persistence=object(),
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            outcome = await collector.quote(
                provider,
                RequestPurpose.NORMAL,
                instrument=instrument,
            )

        self.assertFalse(outcome.usable)
        self.assertIs(outcome.cache_status, FreshnessStatus.STALE)
        self.assertEqual(outcome.quote.observed_at, observed_at)

    async def test_cache_storage_ttl_reaches_retention_boundary(self) -> None:
        class CaptureStore(PricingRedisStore):
            def __init__(self) -> None:
                super().__init__(redis_url="redis://unused")
                self.ttl_seconds: int | None = None

            async def _set_json(self, _key, _payload, ttl_seconds) -> None:
                self.ttl_seconds = ttl_seconds

        store = CaptureStore()
        quote = _quote(observed_at=FROZEN_NOW, received_at=FROZEN_NOW)
        provider = PROVIDERS[quote.provider_id]
        instrument = get_instrument(quote.instrument_id)

        with patch("app.pricing.cache.datetime") as clock:
            clock.now.return_value = FROZEN_NOW
            await store.set_provider_quote(quote, provider.operational_ttl_seconds)

        self.assertEqual(store.ttl_seconds, instrument.expire_after_seconds)
        self.assertGreater(store.ttl_seconds, provider.operational_ttl_seconds)

    async def test_queued_source_save_cannot_return_usable_live_quote(self) -> None:
        class CaptureStore:
            def __init__(self) -> None:
                self.quote = None
                self.runtime = None

            async def set_provider_quote(self, quote, _ttl_seconds) -> None:
                self.quote = quote

            async def set_provider_runtime(self, runtime) -> None:
                self.runtime = runtime

        class QueuedPersistence:
            async def persist_provider_quote(self, quote):
                quote.persistence_status = PersistenceStatus.QUEUED
                return PersistenceResult(False, True, "stream-1", None)

            async def record_runtime_event(self, **_values) -> None:
                return None

        class Parser:
            parser_version = "phase2-save-gate/1"

            def parse(self, _payload, context):
                return SimpleNamespace(
                    price=Decimal("64000"),
                    currency=context.instrument.quote_currency,
                    weight_unit=context.instrument.weight_unit,
                    purity=context.instrument.purity,
                    bid=None,
                    ask=None,
                    volume=None,
                    observed_at=FROZEN_NOW,
                    metadata={},
                )

        provider = PROVIDERS["coinbase_btc_usd"]
        instrument = get_instrument(provider.instrument_id)
        store = CaptureStore()
        collector = ProviderQuoteCollector(
            store=store,
            budgets=object(),
            locks=object(),
            persistence=QueuedPersistence(),
        )
        runtime = ProviderRuntimeState(
            provider_id=provider.provider_id,
            instrument_id=provider.instrument_id,
        )

        with (
            patch.object(
                collector,
                "_request_payload",
                new=AsyncMock(return_value=({"data": {}}, "application/json", 200)),
            ),
            patch("app.pricing.providers.build_parser", return_value=Parser()),
            patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW),
        ):
            outcome = await collector._call_and_parse(
                provider,
                RequestPurpose.NORMAL,
                runtime,
                client=object(),
                instrument=instrument,
            )

        self.assertFalse(outcome.usable)
        self.assertEqual(outcome.failure_reason, "source_persistence_queued")
        self.assertIs(outcome.quote.persistence_status, PersistenceStatus.QUEUED)
        self.assertIs(store.quote, outcome.quote)


class SourceSemanticTests(unittest.TestCase):
    def test_aggregator_derives_legacy_flags_and_round_trips_all_fields(self) -> None:
        quote = _quote(
            source_semantic=SourceSemantic.AGGREGATOR,
            source_family="coincap",
            venue="coincap",
            last=Decimal("64000"),
            selected_price_semantic=PriceSemantic.LAST,
            original_currency="USD",
            original_value=Decimal("64000"),
            conversion_factor=Decimal("1"),
            route_id="coincap_rest",
            derivation_depth=0,
            provenance=("coincap",),
            is_direct=True,
        )

        self.assertIs(quote.source_type, SourceType.HTTP)
        self.assertFalse(quote.is_direct)
        self.assertFalse(quote.is_derived)
        payload = quote.to_dict(authenticated=True)
        restored = ProviderQuote.from_dict(payload)
        self.assertIs(restored.source_semantic, SourceSemantic.AGGREGATOR)
        self.assertIs(restored.selected_price_semantic, PriceSemantic.LAST)
        self.assertEqual(restored.source_family, "coincap")
        self.assertEqual(restored.venue, "coincap")
        self.assertEqual(restored.last, Decimal("64000"))
        self.assertEqual(restored.original_currency, "USD")
        self.assertEqual(restored.original_value, Decimal("64000"))
        self.assertEqual(restored.conversion_factor, Decimal("1"))
        self.assertEqual(restored.route_id, "coincap_rest")
        self.assertEqual(restored.derivation_depth, 0)
        self.assertEqual(restored.provenance, ("coincap",))
        self.assertEqual(payload["source_timestamp"], FROZEN_NOW.isoformat())
        self.assertEqual(payload["receive_timestamp"], FROZEN_NOW.isoformat())

    def test_orderbook_derives_direct_flag_and_spread(self) -> None:
        quote = _quote(
            price=Decimal("100"),
            source_semantic=SourceSemantic.EXCHANGE_ORDERBOOK,
            bid=Decimal("99"),
            ask=Decimal("101"),
            selected_price_semantic=PriceSemantic.MIDPOINT,
            is_direct=False,
        )

        self.assertTrue(quote.is_direct)
        self.assertEqual(quote.spread_bps, Decimal("200"))

    def test_derived_semantic_overrides_ambiguous_legacy_flags(self) -> None:
        quote = _quote(
            source_semantic=SourceSemantic.DERIVED,
            derivation_depth=1,
            provenance=("BTC_USD", "USDT_TOMAN"),
            is_direct=True,
            is_derived=False,
        )

        self.assertIs(quote.source_type, SourceType.DERIVED)
        self.assertFalse(quote.is_direct)
        self.assertTrue(quote.is_derived)

    def test_old_payload_without_new_fields_remains_readable(self) -> None:
        payload = _quote().to_dict(authenticated=True)
        for key in (
            "source_semantic",
            "source_family",
            "venue",
            "last",
            "selected_price_semantic",
            "original_currency",
            "original_value",
            "conversion_factor",
            "route_id",
            "spread_bps",
            "derivation_depth",
            "provenance",
            "source_timestamp",
            "receive_timestamp",
        ):
            payload.pop(key, None)
        payload["metadata"] = {}

        restored = ProviderQuote.from_dict(payload)

        self.assertIs(restored.source_semantic, SourceSemantic.EXCHANGE_TRADE)
        self.assertIs(restored.source_type, SourceType.HTTP)
        self.assertTrue(restored.is_direct)

    def test_metadata_only_normalized_fields_restore_without_new_columns(self) -> None:
        payload = _quote(
            source_semantic=SourceSemantic.AGGREGATOR,
            source_family="local_family",
            venue="local_venue",
            selected_price_semantic=PriceSemantic.PROVIDER_SELECTED,
            original_currency="RIAL",
            original_value=Decimal("640000"),
            conversion_factor=Decimal("0.1"),
            route_id="local_route",
            derivation_depth=0,
            provenance=("raw_feed",),
        ).to_dict(authenticated=True)
        for key in (
            "source_semantic",
            "source_family",
            "venue",
            "last",
            "selected_price_semantic",
            "original_currency",
            "original_value",
            "conversion_factor",
            "route_id",
            "spread_bps",
            "derivation_depth",
            "provenance",
            "source_timestamp",
            "receive_timestamp",
        ):
            payload.pop(key, None)

        restored = ProviderQuote.from_dict(payload)

        self.assertEqual(restored.source_family, "local_family")
        self.assertEqual(restored.venue, "local_venue")
        self.assertEqual(restored.original_currency, "RIAL")
        self.assertEqual(restored.original_value, Decimal("640000"))
        self.assertEqual(restored.conversion_factor, Decimal("0.1"))
        self.assertEqual(restored.route_id, "local_route")
        self.assertEqual(restored.provenance, ("raw_feed", "local_family"))

    def test_registry_marks_same_venue_as_one_source_family(self) -> None:
        trade = PROVIDERS["nobitex_stats_btc"]
        book = PROVIDERS["nobitex_orderbook_btc"]

        self.assertIs(trade.source_semantic, SourceSemantic.EXCHANGE_TRADE)
        self.assertIs(book.source_semantic, SourceSemantic.EXCHANGE_ORDERBOOK)
        self.assertEqual(trade.source_family, book.source_family)
        self.assertEqual(trade.venue, book.venue)

    def test_every_registry_source_has_explicit_normalized_classification(self) -> None:
        for provider_id, provider in PROVIDERS.items():
            with self.subTest(provider_id=provider_id):
                self.assertIsInstance(provider.source_semantic, SourceSemantic)
                self.assertIsInstance(provider.selected_price_semantic, PriceSemantic)
                self.assertTrue(provider.source_family)
                self.assertTrue(provider.venue)
                self.assertTrue(provider.route_id)


if __name__ == "__main__":
    unittest.main()
