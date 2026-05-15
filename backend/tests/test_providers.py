from __future__ import annotations

import tempfile
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import patch

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
            if provider['id'] == 'nobitex_btc':
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

    async def test_primary_backup_failure_without_cache(self) -> None:
        async def always_fail(*_args, **_kwargs):
            raise RuntimeError('provider down')

        with patch.object(self.fetcher, '_call_provider', side_effect=always_fail):
            result = await self.fetcher.fetch_chain(object(), 'gold', 'iran')

        self.assertEqual(result.status, 'unavailable')
        self.assertIsNone(result.value)


if __name__ == '__main__':
    unittest.main()
