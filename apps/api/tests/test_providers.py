from __future__ import annotations

import tempfile
import types
import unittest
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

if importlib.util.find_spec("httpx") is None:
    if 'httpx' not in sys.modules:
        sys.modules['httpx'] = types.SimpleNamespace(AsyncClient=object)

from app.services.pricing_cache import PricingCacheStore
from app.services.pricing_fetcher import PricingFetcher
from app.services.pricing_health import build_startup_checks
from app.services.pricing_registry import PRICE_REGISTRY


class StartupValidationTests(unittest.TestCase):
    def test_missing_required_and_optional_keys_are_reported(self) -> None:
        settings = SimpleNamespace(
            pricing_require_provider_keys=False,
            metals_dev_api_key=None,
            goldapi_api_key=None,
            exchangerate_api_key=None,
            alanchand_api_token=None,
        )

        checks = build_startup_checks(settings, PRICE_REGISTRY)

        self.assertIn('metals_dev_api_key', checks['missing_env_keys'])
        self.assertIn('goldapi_api_key', checks['missing_env_keys'])
        self.assertIn('alanchand_api_token', checks['missing_optional_env_keys'])
        self.assertFalse(checks['ok'])

    def test_alanchand_optional_path_when_required_keys_exist(self) -> None:
        settings = SimpleNamespace(
            pricing_require_provider_keys=False,
            metals_dev_api_key='metals-key',
            goldapi_api_key='gold-key',
            exchangerate_api_key=None,
            alanchand_api_token=None,
        )

        checks = build_startup_checks(settings, PRICE_REGISTRY)

        self.assertEqual(checks['missing_env_keys'], [])
        self.assertEqual(checks['missing_optional_env_keys'], ['alanchand_api_token'])
        self.assertTrue(checks['ok'])


class ProviderFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        cache_file = Path(self.temp_dir.name) / 'price_cache.json'
        self.cache = PricingCacheStore(cache_file)
        self.settings = SimpleNamespace(
            metals_dev_api_key=None,
            goldapi_api_key=None,
            exchangerate_api_key=None,
        )
        self.fetcher = PricingFetcher(
            settings=self.settings,
            cache=self.cache,
            registry=PRICE_REGISTRY,
            timeout_seconds=8,
            retry_attempts=1,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_primary_failure_then_backup_success(self) -> None:
        async def fake_call_provider(_client, _asset_id, _region, provider):
            if provider['id'] in {'nobitex_stats_btc', 'nobitex_btc'}:
                raise RuntimeError('primary failed')
            if provider['id'] == 'tetherland_btc':
                return 9_999_999.0
            raise AssertionError('unexpected provider')

        with patch.object(self.fetcher, '_call_provider', side_effect=fake_call_provider):
            result = await self.fetcher.fetch_chain(object(), 'btc', 'iran')

        self.assertEqual(result.status, 'live')
        self.assertEqual(result.source, 'tetherland_btc')

    async def test_primary_backup_failure_with_cache_hit(self) -> None:
        self.cache.set_chain(
            asset_id='usdt',
            region='international',
            value=1.0,
            source='coingecko_usdt',
            updated_at=datetime.now(UTC),
        )

        async def always_fail(*_args, **_kwargs):
            raise RuntimeError('provider down')

        with patch.object(self.fetcher, '_call_provider', side_effect=always_fail):
            result = await self.fetcher.fetch_chain(object(), 'usdt', 'international')

        self.assertEqual(result.status, 'cached')
        self.assertEqual(result.value, 1.0)
        self.assertEqual(result.source, 'cache (coingecko_usdt)')

    async def test_nobitex_orderbook_all_extracts_mid_price(self) -> None:
        payload = {
            "USDTIRT": {
                "bids": [["61000", "10"]],
                "asks": [["61200", "8"]],
            }
        }
        provider = {
            "id": "nobitex_usdt",
            "orderbook_symbol": "USDTIRT",
            "orderbook_side": "mid",
            "unit": "toman",
        }

        value = self.fetcher._extract_orderbook_value(payload, provider)

        self.assertEqual(value, 61100.0)

    def test_nobitex_stats_is_primary_and_orderbook_is_fallback(self) -> None:
        expected_paths = {
            'usdt': 'stats.usdt-rls.latest',
            'btc': 'stats.btc-rls.latest',
        }
        for asset, response_path in expected_paths.items():
            providers = sorted(
                PRICE_REGISTRY[asset]['iran']['providers'],
                key=lambda provider: provider['priority'],
            )
            self.assertEqual(providers[0]['url'], 'https://apiv2.nobitex.ir/market/stats')
            self.assertEqual(providers[0]['response_path'], response_path)
            self.assertTrue(providers[0]['convert_to_toman'])
            self.assertEqual(providers[1]['orderbook_side'], 'mid')

    async def test_provider_circuit_opens_after_repeated_failures(self) -> None:
        async def always_fail(*_args, **_kwargs):
            raise RuntimeError('provider down')

        provider_count = len(PRICE_REGISTRY['btc']['iran']['providers'])
        with patch.object(self.fetcher, '_call_provider', side_effect=always_fail) as call:
            for _ in range(self.fetcher.CIRCUIT_FAILURE_THRESHOLD):
                await self.fetcher.fetch_chain(object(), 'btc', 'iran')
            calls_before_open_check = call.await_count
            await self.fetcher.fetch_chain(object(), 'btc', 'iran')

        self.assertEqual(calls_before_open_check, provider_count * self.fetcher.CIRCUIT_FAILURE_THRESHOLD)
        self.assertEqual(call.await_count, calls_before_open_check)

    async def test_primary_backup_failure_without_cache(self) -> None:
        async def always_fail(*_args, **_kwargs):
            raise RuntimeError('provider down')

        with patch.object(self.fetcher, '_call_provider', side_effect=always_fail):
            result = await self.fetcher.fetch_chain(object(), 'gold', 'iran')

        self.assertEqual(result.status, 'unavailable')
        self.assertIsNone(result.value)


if __name__ == '__main__':
    unittest.main()
