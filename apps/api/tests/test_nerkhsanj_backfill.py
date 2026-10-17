from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing.backfill import PricingBackfillQueue, _history_request_options
from app.pricing.budgets import BudgetDecision
from app.pricing.compatibility import LegacyPricingAdapter
from app.pricing.instruments import get_instrument
from app.pricing.parsers.history import build_history_parser
from app.pricing.registry import PROVIDERS
from app.schemas import PriceHistoryResponse
from tests.test_source_snapshots import _Redis


class NerkhsanjBackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = PROVIDERS["nerkhsanj_silver999_history"]
        self.parser = build_history_parser(self.provider.history_parser_id)
        self.payload = {"series": [{"key": "silver", "name": "Silver 999",
                                    "days": [["1405/07/22", 502340], ["1405/07/23", 517260]]}]}
        self.job = {"id": 1, "instrument_id": self.provider.instrument_id,
                    "range_start": datetime(2026, 10, 1, tzinfo=UTC),
                    "range_end": datetime(2026, 10, 16, tzinfo=UTC), "attempt_count": 1}
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        self.enterContext(patch.object(settings, "pricing_rights_manifest_path", None))

    def test_bulk_archive_request_has_no_synthetic_date_query_or_key(self):
        params, headers = _history_request_options(self.provider, self.parser,
                                                  self.job["range_start"], self.job["range_end"])
        self.assertEqual(params, {})
        self.assertEqual(headers, {})

    async def execute(self, provider=None, response=None):
        provider = provider or self.provider
        quotes, canonicals, requests = [], [], []
        persistence, operational, store = AsyncMock(), AsyncMock(), AsyncMock()
        store.client = Mock(return_value=_Redis())
        budgets = AsyncMock()
        budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        operational.instrument.return_value = get_instrument(provider.instrument_id)

        async def save_quote(quote):
            quote.id = len(quotes) + 1
            quotes.append(quote)
            return SimpleNamespace(persisted=True)

        async def save_canonical(quote):
            canonicals.append(quote)
            return SimpleNamespace(persisted=True)

        persistence.persist_provider_quote.side_effect = save_quote
        persistence.persist_canonical.side_effect = save_canonical

        def respond(request):
            requests.append(request)
            return response or httpx.Response(200, json=self.payload)

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        queue = PricingBackfillQueue(store=store, budgets=budgets, persistence=persistence, operational=operational)
        with patch("app.pricing.backfill.httpx.AsyncClient", return_value=client):
            count = await queue._execute_history_job(self.job, provider)
        return count, quotes, canonicals, requests, store

    async def test_streamed_daily_archive_persists_dates_and_precision_without_live_cache(self):
        count, quotes, canonicals, requests, store = await self.execute()
        self.assertEqual(count, 2)
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), self.provider.history_url)
        self.assertNotIn("x-api-key", requests[0].headers)
        self.assertEqual([str(quote.price) for quote in quotes], ["502340", "517260"])
        for quote, canonical in zip(quotes, canonicals):
            self.assertEqual(quote.metadata["timestamp_precision"], "day")
            self.assertIs(quote.metadata["source_observation_time_known"], False)
            self.assertEqual(canonical.source_summary["timestamp_role"], "day_bucket_start")
            self.assertEqual(canonical.source_summary["source_timezone"], "Asia/Tehran")
            self.assertTrue(canonical.source_summary["historical_backfill"])
            self.assertFalse(canonical.source_summary["derived"])
            self.assertEqual(canonical.source_summary["source_date"], quote.metadata["source_date"])
        store.set_canonical.assert_not_awaited()
        store.set_provider_quote.assert_not_awaited()

    async def test_archive_body_bound_is_enforced_before_json_parse_or_persistence(self):
        provider = replace(self.provider, maximum_payload_bytes=16)
        with patch("app.pricing.backfill.json.loads") as decode:
            with self.assertRaisesRegex(ValueError, "history_payload_too_large"):
                await self.execute(provider)
        decode.assert_not_called()

    async def test_chunked_archive_has_same_preparse_bound(self):
        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b" " * 100
                yield b" " * 100

        response = httpx.Response(200, headers={"Content-Type": "application/json"}, stream=Chunks())
        with patch("app.pricing.backfill.json.loads") as decode:
            with self.assertRaisesRegex(ValueError, "history_payload_too_large"):
                await self.execute(replace(self.provider, maximum_payload_bytes=120), response)
        decode.assert_not_called()

    async def test_revoked_history_right_stops_before_transport(self):
        with patch("app.pricing.backfill.rights.provider_allowed", return_value=False):
            with patch("app.pricing.backfill.httpx.AsyncClient") as client:
                queue = PricingBackfillQueue()
                self.assertEqual(await queue._execute_history_job(self.job, self.provider), 0)
                client.assert_not_called()

    def test_legacy_api_preserves_per_currency_time_precision(self):
        time_info = {"timestamp_precision": "day", "timestamp_role": "day_bucket_start",
                     "source_observation_time_known": False, "source_timezone": "Asia/Tehran",
                     "source_calendar": "jalali", "source_date": "1405/07/23"}
        stamp = "2026-10-14T20:30:00+00:00"
        points = LegacyPricingAdapter._merge_history(
            [{"timestamp": stamp, "value": 56.0}],
            [{"timestamp": stamp, "value": 517260, **time_info}])
        result = PriceHistoryResponse.model_validate({"asset": "silver", "points": points}).model_dump()
        point = result["points"][0]
        self.assertEqual(point["timestamp_precision"], "day")
        self.assertEqual(point["time_info_usd"]["timestamp_precision"], "instant")
        self.assertEqual(point["time_info_toman"], time_info)
        self.assertEqual(point["value_usd"], 56.0)
        self.assertEqual(point["value_toman"], 517260)


if __name__ == "__main__":
    unittest.main()
