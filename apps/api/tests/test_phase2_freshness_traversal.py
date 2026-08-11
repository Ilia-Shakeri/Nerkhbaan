from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DEBUG"] = "false"

from app.pricing.instruments import get_instrument
from app.pricing.anomaly import AnomalyAssessment
from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.freshness import FreshnessStatus
from app.pricing.models import (
    PersistenceStatus,
    ProviderQuote,
    ProviderRuntimeState,
    RequestPurpose,
    SourceType,
    ValidationStatus,
)
from app.pricing.providers import ProviderQuoteCollector, QuoteFetchOutcome
from app.pricing.registry import PROVIDERS
from app.pricing.service import InstrumentPricingService


FROZEN_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


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


class _OperationalProviders:
    def __init__(self, providers) -> None:
        self.providers = tuple(providers)

    async def providers_for(self, _instrument_id: str, *_roles):
        return self.providers

    async def instrument(self, instrument_id: str):
        return get_instrument(instrument_id)


class _OutcomeCollector:
    def __init__(self, outcomes: dict[str, QuoteFetchOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    async def quote(self, provider, _purpose, **_kwargs):
        self.calls.append(provider.provider_id)
        return self.outcomes[provider.provider_id]


class _RankingStore:
    def __init__(self, quotes=None) -> None:
        self.quotes = quotes or {}

    async def get_provider_quote(self, _provider_id: str, _instrument_id: str):
        return self.quotes.get(_provider_id)

    async def get_provider_runtime(self, provider_id: str, instrument_id: str):
        return ProviderRuntimeState(
            provider_id=provider_id,
            instrument_id=instrument_id,
        )


class _ZeroPressureBudget:
    async def pressure(self, _provider) -> float:
        return 0.0


def _provider_quote(
    *,
    observed_at: datetime,
    instrument_id: str = "XAU_USD_OZ",
    provider_id: str = "goldapi_xau",
) -> ProviderQuote:
    instrument = get_instrument(instrument_id)
    return ProviderQuote.create(
        instrument_id=instrument.instrument_id,
        provider_id=provider_id,
        source_type=SourceType.HTTP,
        price=Decimal("2400"),
        currency=instrument.quote_currency,
        weight_unit=instrument.weight_unit,
        purity=instrument.purity,
        observed_at=observed_at,
        received_at=observed_at,
        parser_version="phase2-test/1",
        validation_status=ValidationStatus.ACCEPTED,
        persistence_status=PersistenceStatus.PERSISTED,
    )


class ProviderFreshnessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.instrument = replace(
            get_instrument("XAU_USD_OZ"),
            operational_ttl_seconds=60,
        )
        self.provider = replace(
            PROVIDERS["goldapi_xau"],
            enabled=False,
            api_key_setting=None,
            operational_ttl_seconds=600,
        )

    def test_live_cache_is_eligible_at_operational_ttl_boundary(self) -> None:
        quote = _provider_quote(observed_at=FROZEN_NOW - timedelta(seconds=60))

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            fresh = ProviderQuoteCollector._is_fresh(
                quote,
                self.provider,
                self.instrument,
            )

        self.assertTrue(fresh)

    async def test_retained_cache_after_operational_ttl_is_not_live_usable(self) -> None:
        observed_at = FROZEN_NOW - timedelta(seconds=61)
        quote = _provider_quote(observed_at=observed_at)
        store = _QuoteStore(quote)
        collector = ProviderQuoteCollector(
            store=store,
            budgets=object(),
            locks=object(),
            persistence=object(),
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            outcome = await collector.quote(
                self.provider,
                RequestPurpose.NORMAL,
                instrument=self.instrument,
            )

        self.assertFalse(outcome.usable)
        self.assertFalse(outcome.from_fresh_cache)
        self.assertIs(outcome.quote, quote)
        self.assertEqual(outcome.failure_reason, "provider_disabled")
        self.assertEqual(outcome.quote.observed_at, observed_at)

    async def test_disabled_provider_cannot_serve_live_cache(self) -> None:
        quote = _provider_quote(observed_at=FROZEN_NOW)
        collector = ProviderQuoteCollector(
            store=_QuoteStore(quote),
            budgets=object(),
            locks=object(),
            persistence=object(),
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            outcome = await collector.quote(
                self.provider,
                RequestPurpose.NORMAL,
                instrument=self.instrument,
            )

        self.assertFalse(outcome.usable)
        self.assertEqual(outcome.failure_reason, "provider_disabled")
        self.assertIs(outcome.cache_status, FreshnessStatus.LIVE)


class ProviderTraversalTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_first_external_primary_reaches_later_allowed_primary(self) -> None:
        base = PROVIDERS["coinbase_btc_usd"]
        first = replace(base, provider_id="phase2_primary_first", priority=1)
        second = replace(base, provider_id="phase2_primary_second", priority=2)
        failed = QuoteFetchOutcome(
            quote=None,
            usable=False,
            from_fresh_cache=False,
            external_called=True,
            failure_reason="transport_error",
        )
        accepted_quote = SimpleNamespace(provider_id=second.provider_id)
        accepted = QuoteFetchOutcome(
            quote=accepted_quote,
            usable=True,
            from_fresh_cache=False,
            external_called=True,
            failure_reason=None,
        )
        collector = _OutcomeCollector(
            {
                first.provider_id: failed,
                second.provider_id: accepted,
            }
        )
        service = InstrumentPricingService(
            store=_RankingStore(),
            budgets=_ZeroPressureBudget(),
            collector=collector,
            operational=_OperationalProviders((first, second)),
        )

        result = await service._normal_quote(
            get_instrument("BTC_USD"),
            client=object(),
        )

        self.assertIs(result, accepted)
        self.assertEqual(
            collector.calls,
            [first.provider_id, second.provider_id],
        )

    async def test_failed_first_fallback_reaches_later_allowed_fallback(self) -> None:
        base = PROVIDERS["coinbase_btc_usd"]
        first = replace(base, provider_id="phase2_fallback_first", priority=1)
        second = replace(base, provider_id="phase2_fallback_second", priority=2)
        failed = QuoteFetchOutcome(
            quote=None,
            usable=False,
            from_fresh_cache=False,
            external_called=True,
            failure_reason="transport_error",
        )
        accepted = QuoteFetchOutcome(
            quote=SimpleNamespace(provider_id=second.provider_id),
            usable=True,
            from_fresh_cache=False,
            external_called=True,
            failure_reason=None,
        )
        collector = _OutcomeCollector(
            {
                first.provider_id: failed,
                second.provider_id: accepted,
            }
        )
        service = InstrumentPricingService(
            store=_RankingStore(),
            budgets=_ZeroPressureBudget(),
            collector=collector,
            operational=_OperationalProviders((first, second)),
        )

        result = await service._fallback_quote(
            get_instrument("BTC_USD"),
            client=object(),
        )

        self.assertIs(result, accepted)
        self.assertEqual(collector.calls, [first.provider_id, second.provider_id])

    async def test_later_live_cache_wins_before_any_external_call(self) -> None:
        base = PROVIDERS["coinbase_btc_usd"]
        first = replace(base, provider_id="phase2_external_first", priority=1)
        second = replace(base, provider_id="phase2_cached_second", priority=2)
        cached = _provider_quote(
            observed_at=FROZEN_NOW,
            instrument_id="BTC_USD",
            provider_id=second.provider_id,
        )
        collector = _OutcomeCollector(
            {
                first.provider_id: QuoteFetchOutcome(
                    quote=None,
                    usable=False,
                    from_fresh_cache=False,
                    external_called=True,
                    failure_reason="transport_error",
                ),
                second.provider_id: QuoteFetchOutcome(
                    quote=None,
                    usable=False,
                    from_fresh_cache=False,
                    external_called=True,
                    failure_reason="transport_error",
                ),
            }
        )
        service = InstrumentPricingService(
            store=_RankingStore({second.provider_id: cached}),
            budgets=_ZeroPressureBudget(),
            collector=collector,
            operational=_OperationalProviders((first, second)),
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            result = await service._normal_quote(
                get_instrument("BTC_USD"),
                client=object(),
            )

        self.assertIs(result.quote, cached)
        self.assertTrue(result.from_fresh_cache)
        self.assertEqual(collector.calls, [])
        self.assertEqual(result.selection_trace[-1]["result"], "selected_live_cache")

    async def test_current_lower_provider_ttl_caps_cached_canonical_window(self) -> None:
        provider = replace(
            PROVIDERS["coinbase_btc_usd"],
            operational_ttl_seconds=10,
        )
        cached = _provider_quote(
            observed_at=FROZEN_NOW - timedelta(seconds=5),
            instrument_id="BTC_USD",
            provider_id=provider.provider_id,
        )
        cached.metadata["provider_live_ttl_seconds"] = 600
        service = InstrumentPricingService(
            store=_RankingStore({provider.provider_id: cached}),
            budgets=_ZeroPressureBudget(),
            collector=_OutcomeCollector({}),
            operational=_OperationalProviders((provider,)),
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            outcome = await service._normal_quote(
                get_instrument("BTC_USD"),
                client=object(),
            )

        decision = CanonicalPricePolicy().select(
            instrument=get_instrument("BTC_USD"),
            primary=outcome.quote,
            previous=None,
            assessment=None,
            verifier_quotes=[],
            now=FROZEN_NOW,
        )
        expected_live_until = cached.observed_at + timedelta(seconds=10)
        self.assertEqual(
            cached.metadata["effective_live_eligible_until"],
            expected_live_until.isoformat(),
        )
        self.assertEqual(decision.canonical.valid_until, expected_live_until)

    async def test_queued_live_cache_has_true_skip_reason(self) -> None:
        provider = PROVIDERS["coinbase_btc_usd"]
        cached = _provider_quote(
            observed_at=FROZEN_NOW,
            instrument_id="BTC_USD",
            provider_id=provider.provider_id,
        )
        cached.persistence_status = PersistenceStatus.QUEUED
        collector = _OutcomeCollector(
            {
                provider.provider_id: QuoteFetchOutcome(
                    quote=None,
                    usable=False,
                    from_fresh_cache=False,
                    external_called=True,
                    failure_reason="transport_error",
                )
            }
        )
        service = InstrumentPricingService(
            store=_RankingStore({provider.provider_id: cached}),
            budgets=_ZeroPressureBudget(),
            collector=collector,
            operational=_OperationalProviders((provider,)),
        )

        with patch("app.pricing.providers.utc_now", return_value=FROZEN_NOW):
            result = await service._normal_quote(
                get_instrument("BTC_USD"),
                client=object(),
            )

        self.assertFalse(result.usable)
        self.assertEqual(
            result.selection_trace[0],
            {
                "provider_id": provider.provider_id,
                "stage": "cache",
                "result": "ineligible",
                "reason": "source_not_persisted",
            },
        )

    async def test_external_bound_records_untried_provider_reason(self) -> None:
        base = PROVIDERS["coinbase_btc_usd"]
        providers = tuple(
            replace(base, provider_id=f"phase2_bound_{index}", priority=index)
            for index in (1, 2, 3)
        )
        collector = _OutcomeCollector(
            {
                provider.provider_id: QuoteFetchOutcome(
                    quote=None,
                    usable=False,
                    from_fresh_cache=False,
                    external_called=True,
                    failure_reason="transport_error",
                )
                for provider in providers
            }
        )
        service = InstrumentPricingService(
            store=_RankingStore(),
            budgets=_ZeroPressureBudget(),
            collector=collector,
            operational=_OperationalProviders(providers),
        )

        result = await service._normal_quote(
            get_instrument("BTC_USD"),
            client=object(),
        )

        self.assertEqual(collector.calls, [p.provider_id for p in providers[:2]])
        self.assertEqual(
            result.selection_trace[-1],
            {
                "provider_id": providers[2].provider_id,
                "stage": "external",
                "result": "skipped",
                "reason": "external_call_budget_exhausted",
            },
        )

    async def test_same_family_verifier_does_not_stop_independent_walk(self) -> None:
        candidate = _provider_quote(
            observed_at=FROZEN_NOW,
            instrument_id="BTC_TOMAN",
            provider_id="nobitex_stats_btc",
        )
        candidate.source_family = "nobitex"
        candidate.venue = "nobitex"
        same_family = PROVIDERS["nobitex_orderbook_btc"]
        independent = replace(
            same_family,
            provider_id="phase2_independent_verifier",
            source_family="other_exchange",
            venue="other_exchange",
            priority=2,
        )
        same_quote = SimpleNamespace(provider_id=same_family.provider_id, price=candidate.price)
        independent_quote = SimpleNamespace(
            provider_id=independent.provider_id,
            price=candidate.price,
        )
        collector = _OutcomeCollector(
            {
                same_family.provider_id: QuoteFetchOutcome(
                    quote=same_quote,
                    usable=True,
                    from_fresh_cache=False,
                    external_called=True,
                    failure_reason=None,
                ),
                independent.provider_id: QuoteFetchOutcome(
                    quote=independent_quote,
                    usable=True,
                    from_fresh_cache=False,
                    external_called=True,
                    failure_reason=None,
                ),
            }
        )
        service = InstrumentPricingService(
            store=_RankingStore(),
            budgets=_ZeroPressureBudget(),
            collector=collector,
            operational=_OperationalProviders((same_family, independent)),
        )
        assessment = AnomalyAssessment(
            is_suspicious=True,
            deviation_percent=Decimal("5"),
            dynamic_threshold_percent=Decimal("1"),
            volatility_percent=Decimal("0"),
            severity="high",
            reason="phase2_independent_walk",
        )

        quotes = await service._verification_quotes(
            "BTC_TOMAN",
            candidate,
            assessment,
            client=object(),
        )

        self.assertEqual(collector.calls, [independent.provider_id])
        self.assertEqual(quotes, [independent_quote])


if __name__ == "__main__":
    unittest.main()
