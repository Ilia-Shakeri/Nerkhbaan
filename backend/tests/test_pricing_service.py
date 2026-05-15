from __future__ import annotations

import tempfile
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

# Allow running these tests in minimal environments where backend deps are not installed.
if 'httpx' not in sys.modules:
    sys.modules['httpx'] = types.SimpleNamespace(AsyncClient=object)

from app.services.pricing import PricingService


class TempPricingService(PricingService):
    def __init__(self, cache_file: Path) -> None:
        self._test_cache_file = cache_file
        super().__init__()

    def _resolve_cache_file(self) -> Path:
        return self._test_cache_file


class PricingServiceFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        cache_file = Path(self.temp_dir.name) / 'price_cache.json'
        self.service = TempPricingService(cache_file=cache_file)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_chain_uses_backup_when_primary_fails(self) -> None:
        async def fake_call_provider(
            _client: Any,
            _asset_id: str,
            _region: str,
            provider: dict,
        ) -> float:
            if provider['id'] == 'tgju_gold':
                raise RuntimeError('primary unavailable')
            if provider['id'] == 'bonbast_gold':
                return 12_345_678.0
            raise AssertionError(f"Unexpected provider: {provider['id']}")

        with patch.object(self.service.fetcher, '_call_provider', side_effect=fake_call_provider):
            result = await self.service._fetch_chain(object(), 'gold', 'iran')

        self.assertEqual(result.status, 'live')
        self.assertEqual(result.source, 'bonbast_gold')
        self.assertEqual(result.value, 12_345_678.0)

        cached = self.service._get_cached_value('gold', 'iran')
        self.assertIsNotNone(cached)
        if cached is None:
            return
        cached_value, cached_source, _cached_updated_at = cached
        self.assertEqual(cached_value, 12_345_678.0)
        self.assertEqual(cached_source, 'bonbast_gold')

    async def test_chain_returns_cached_value_when_all_providers_fail(self) -> None:
        self.service._set_cached_value(
            asset_id='btc',
            region='international',
            value=100_001.25,
            source='coingecko_btc',
            updated_at=datetime.now(UTC),
        )

        async def always_fail(*_args, **_kwargs) -> float:
            raise RuntimeError('provider down')

        with patch.object(self.service.fetcher, '_call_provider', side_effect=always_fail):
            result = await self.service._fetch_chain(object(), 'btc', 'international')

        self.assertEqual(result.status, 'cached')
        self.assertEqual(result.value, 100_001.25)
        self.assertIn('cache (coingecko_btc)', result.source)


if __name__ == '__main__':
    unittest.main()
