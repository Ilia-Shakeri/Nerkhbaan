from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.pricing.budgets import BudgetDecision
from app.pricing.canonical import CanonicalPricePolicy
from app.pricing.health import PricingHealthService
from app.pricing.instruments import get_instrument
from app.pricing.models import PersistenceStatus, ProviderQuote, ProviderRuntimeState, RequestPurpose, utc_now
from app.pricing.parsers.base import ParserContext, ParserError
from app.pricing.parsers.local_reference import ArzbinMarketParser, NerkhIoLiteParser, TalaRatesParser, TicaroPricesParser
from app.pricing.providers import ProviderQuoteCollector
from app.pricing.registry import PROVIDERS
from app.pricing.service import operational_pricing_settings


class _Locks:
    @asynccontextmanager
    async def provider_lock(self, *_args):
        yield object()


class PerAttemptBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, decisions):
        provider = PROVIDERS['coinbase_btc_usd']
        store, persistence, budgets = AsyncMock(), AsyncMock(), AsyncMock()
        store.get_provider_quote.return_value = None
        store.get_provider_runtime.return_value = ProviderRuntimeState(provider.provider_id, provider.instrument_id)
        persistence.persist_provider_quote.return_value = SimpleNamespace(persisted=True, queued=False)
        budgets.consume.side_effect = decisions
        requests = []

        def response(request):
            requests.append(request)
            return httpx.Response(503, json={}) if len(requests) == 1 else httpx.Response(200, json={'price': '77000'})

        collector = ProviderQuoteCollector(store=store, persistence=persistence, budgets=budgets, locks=_Locks())
        with patch('app.pricing.providers.settings.pricing_provider_backoff_base_seconds', Decimal('0')):
            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
                result = await collector.quote(provider, RequestPurpose.FALLBACK, client=client)
        return result, budgets, requests, persistence, store

    async def test_each_retry_requires_its_own_budget_with_original_purpose(self):
        result, budgets, requests, _persistence, _store = await self.fetch([
            BudgetDecision(True, 'allowed', 1), BudgetDecision(True, 'allowed', 0),
        ])
        self.assertTrue(result.usable)
        self.assertEqual(len(requests), 2)
        self.assertEqual(budgets.consume.await_count, 2)
        self.assertTrue(all(call.args[1] is RequestPurpose.FALLBACK for call in budgets.consume.await_args_list))

    async def test_retry_stops_when_shared_budget_or_minimum_interval_denies_it(self):
        for reason in ('budget_limit_2', 'budget_limit_1'):
            with self.subTest(reason=reason):
                result, budgets, requests, persistence, store = await self.fetch([
                    BudgetDecision(True, 'allowed', 0), BudgetDecision(False, reason, 0),
                ])
                self.assertFalse(result.usable)
                self.assertEqual(len(requests), 1)
                self.assertEqual(budgets.consume.await_count, 2)
                self.assertEqual(store.get_provider_runtime.return_value.failure_count, 1)
                self.assertEqual(result.failure_reason, 'http_error')
                self.assertEqual(result.quote.http_status, 503)
                self.assertEqual(persistence.record_runtime_event.await_args.kwargs['http_status'], 503)

    async def test_denied_first_attempt_does_not_call_or_persist_a_provider_failure(self):
        result, budgets, requests, persistence, store = await self.fetch([BudgetDecision(False, 'provider_budget_disabled', 0)])
        self.assertFalse(result.external_called)
        self.assertEqual(result.failure_reason, 'provider_budget_disabled')
        self.assertEqual(len(requests), 0)
        self.assertEqual(budgets.consume.await_count, 1)
        persistence.persist_provider_quote.assert_not_awaited()
        persistence.record_runtime_event.assert_not_awaited()
        self.assertEqual(store.get_provider_runtime.return_value.failure_count, 0)


class HealthPolicyTests(unittest.IsolatedAsyncioTestCase):
    def quote(self, age=0):
        now = utc_now()
        definition = get_instrument('BTC_USD')
        provider = PROVIDERS['coinbase_btc_usd']
        source = ProviderQuote.create(
            instrument_id='BTC_USD', provider_id=provider.provider_id, source_type='http',
            price=Decimal('77000'), currency=definition.quote_currency, weight_unit=definition.weight_unit,
            purity=definition.purity, observed_at=now-timedelta(seconds=age), received_at=now,
            parser_version='health-test/1', validation_status='accepted',
            persistence_status=PersistenceStatus.PERSISTED, source_semantic=provider.source_semantic,
            source_family=provider.source_family, venue=provider.venue,
        )
        return CanonicalPricePolicy().select(instrument=definition, primary=source, previous=None,
                                             assessment=None, verifier_quotes=[], now=now).canonical

    async def health(self, cached, stored, definition):
        store, history = AsyncMock(), AsyncMock()
        store.ping.return_value = True
        store.get_canonical.return_value = cached
        store.persistence_backlog.return_value = 0
        history.latest_canonical.return_value = stored
        service = PricingHealthService(store=store, history=history)
        with patch.object(service, '_database_probe', return_value={'connected': True, 'migration_version': None}), \
             patch.object(operational_pricing_settings, 'instrument', AsyncMock(return_value=definition)):
            return await service.instrument_health('BTC_USD')

    async def test_disabled_instrument_is_not_reported_live_from_cached_quote(self):
        result = await self.health(self.quote(), None, replace(get_instrument('BTC_USD'), enabled=False))
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['observed_at'])

    async def test_newer_database_quote_wins_over_old_cache_like_public_prices(self):
        old, new = self.quote(age=30), self.quote()
        result = await self.health(old, new, get_instrument('BTC_USD'))
        self.assertEqual(result['observed_at'], new.observed_at.isoformat())

    async def test_tightened_live_window_applies_to_health(self):
        definition = replace(get_instrument('BTC_USD'), operational_ttl_seconds=1, stale_after_seconds=2)
        result = await self.health(self.quote(age=10), None, definition)
        self.assertNotIn(result['status'], {'live', 'fresh_cache', 'confirmed'})


class ExplicitCurrencyTests(unittest.TestCase):
    def test_foreign_currency_never_becomes_toman_by_context(self):
        now = utc_now()
        context = ParserContext(get_instrument('USD_TOMAN'), now, 60)
        for currency in ('USD', 'USDT'):
            cases = [
                (TalaRatesParser('USD'), {'data': [{'key': 'USD', 'unit': currency, 'value': '100000', 'updated_at': now.isoformat()}]}),
                (TicaroPricesParser('USD'), {'data': [{'pair': 'USD', 'quote_currency': currency, 'price': '100000', 'fetched_at': now.isoformat()}]}),
                (NerkhIoLiteParser('USD', currency), {'data': [{'symbol': 'USD', 'price': '100000', 'timestamp': now.isoformat()}]}),
                (ArzbinMarketParser('USD', 'sell', currency), {'data': [{'code': 'USD', 'sell': '100000', 'updated_at': now.isoformat()}]}),
            ]
            for parser, payload in cases:
                with self.subTest(parser=type(parser).__name__, currency=currency):
                    with self.assertRaises(ParserError) as raised:
                        parser.parse(payload, context)
                    self.assertEqual(raised.exception.code, 'currency_mismatch')

    def test_rial_conversion_and_toman_identity_keep_exact_original_unit(self):
        now = utc_now()
        context = ParserContext(get_instrument('USD_TOMAN'), now, 60)
        for unit, value in (('IRR', '1000000'), ('TOMAN', '100000')):
            parsed = TalaRatesParser('USD').parse({'data': [{'key': 'USD', 'unit': unit, 'value': value}]}, context)
            self.assertEqual(parsed.price, Decimal('100000'))
            self.assertEqual(parsed.currency, context.instrument.quote_currency)
            self.assertEqual(parsed.metadata['original_value'], value)


if __name__ == '__main__':
    unittest.main()
