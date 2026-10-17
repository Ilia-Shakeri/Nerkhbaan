from __future__ import annotations

import os
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing.backfill import HistoryBudgetDeferred, PricingBackfillQueue, _history_request_options
from app.pricing.budgets import BudgetDecision
from app.pricing.instruments import get_instrument
from app.pricing.models import RequestPurpose
from app.pricing.parsers.history import build_history_parser
from app.pricing.registry import PROVIDERS
from app.pricing.source_snapshots import SourceSnapshotUnavailable
from tests.test_source_snapshots import _Redis


NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


class _Locks:
    @asynccontextmanager
    async def backfill_lock(self, _instrument):
        yield object()


class IranianHistoryRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.operational = AsyncMock()
        self.operational.feature_enabled.return_value = True
        self.operational.instrument.side_effect = get_instrument
        self.store = AsyncMock()
        self.redis = _Redis()
        self.store.client = Mock(return_value=self.redis)
        self.store.ping.return_value = True
        self.store.get_canonical.return_value = None
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        self.persistence = AsyncMock()
        self.quotes, self.canonicals = [], []

        async def save_quote(quote):
            quote.id = len(self.quotes) + 1
            self.quotes.append(quote)
            return SimpleNamespace(persisted=True)

        async def save_canonical(quote):
            self.canonicals.append(quote)
            return SimpleNamespace(persisted=True)

        self.persistence.persist_provider_quote.side_effect = save_quote
        self.persistence.persist_canonical.side_effect = save_canonical
        self.queue = PricingBackfillQueue(store=self.store, budgets=self.budgets, locks=_Locks(),
            persistence=self.persistence, operational=self.operational)
        self.enterContext(patch("app.pricing.backfill.rights.provider_allowed", return_value=True))
        self.enterContext(patch("app.pricing.backfill.rights.endpoint_allowed", return_value=True))
        self.enterContext(patch.object(settings, "pricing_provider_allowed_hosts", "nerkh.jahankhahan.shop,api.wallgold.ir"))
        self.enterContext(patch("app.pricing.source_snapshots.utc_now", return_value=NOW))
        self.enterContext(patch("app.pricing.backfill.utc_now", return_value=NOW))
        self.daily = PROVIDERS["nerkhsanj_silver999_history"]
        self.intraday = PROVIDERS["nerkhsanj_silver999_toman"]
        self.hourly925 = PROVIDERS["wallgold_silver925_hourly_history"]
        self.daily925 = PROVIDERS["wallgold_silver925_daily_history"]

    async def select(self, providers, days, instrument="SILVER_999_TOMAN_GRAM", **kwargs):
        self.operational.providers_for.return_value = providers
        return await self.queue._history_provider(instrument, range_start=NOW-timedelta(days=days),
                                                   range_end=NOW, **kwargs)

    def job(self, instrument="SILVER_999_TOMAN_GRAM", days=30):
        return {"id": 1, "instrument_id": instrument, "range_start": NOW-timedelta(days=days),
                "range_end": NOW, "attempt_count": 1}

    async def execute(self, provider, source, *, job=None, requests=None):
        calls = requests if requests is not None else []

        def respond(request):
            calls.append(request)
            return httpx.Response(200, json=source)

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch("app.pricing.backfill.httpx.AsyncClient", return_value=client):
            count = await self.queue._execute_history_job(job or self.job(provider.instrument_id), provider)
        return count, calls

    async def test_subday_uses_intraday_and_daily_window_uses_daily_source(self):
        for days, expected in ((1/24, self.intraday), (1, self.daily), (30, self.daily), (365, self.daily)):
            with self.subTest(days=days):
                self.assertEqual(await self.select((self.daily, self.intraday), days), expected)

    async def test_daily_only_source_cannot_claim_subday_support(self):
        self.assertIsNone(await self.select((self.daily,), 1/24))
        self.assertIsNone(await self.select((self.intraday,), 30))

    async def test_925_prefers_hourly_below_31_days_and_daily_for_long_ranges(self):
        for days, expected in ((1/24, self.hourly925), (1, self.hourly925), (30, self.hourly925),
                               (31, self.daily925), (365, self.daily925)):
            with self.subTest(days=days):
                self.assertEqual(await self.select((self.daily925, self.hourly925), days,
                    instrument="SILVER_925_TOMAN_GRAM"), expected)

    async def test_unavailable_short_archive_does_not_masquerade_as_year_coverage(self):
        self.assertIsNone(await self.select((self.hourly925,), 365, instrument="SILVER_925_TOMAN_GRAM"))

    async def test_selection_preserves_enable_config_rights_and_live_independence_gates(self):
        self.assertIsNone(await self.select((replace(self.intraday, enabled=False), self.daily), 1/24))
        with patch("app.pricing.backfill.rights.provider_allowed", return_value=False):
            self.assertIsNone(await self.select((self.daily, self.intraday), 30))
        self.assertIsNone(await self.select((replace(self.daily, history_requires_live_quote=True),), 30,
                                           independent_of_live=True))

    async def test_readiness_selection_without_range_keeps_existing_priority_contract(self):
        self.operational.providers_for.return_value = (self.intraday, self.daily)
        self.assertEqual(await self.queue._history_provider("SILVER_999_TOMAN_GRAM"), self.daily)

    async def test_partial_or_nonpositive_selection_ranges_are_rejected(self):
        for kwargs in ({"range_start": NOW}, {"range_end": NOW},
                       {"range_start": NOW, "range_end": NOW},
                       {"range_start": NOW, "range_end": NOW-timedelta(days=1)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.queue._history_provider("SILVER_999_TOMAN_GRAM", **kwargs)

    async def test_daily_two_instrument_jobs_share_one_request_budget_and_original_fetch_clock(self):
        source = {"series": [
            {"key": "silver", "name": "Silver 999", "days": [["1405/07/23", 517260]]},
            {"key": "gold", "name": "Gold 18", "days": [["1405/07/23", 26236700]]},
        ]}
        count, calls = await self.execute(self.daily, source)
        self.assertEqual(count, 1)
        gold = PROVIDERS["nerkhsanj_gold18_toman_history"]
        with patch("app.pricing.source_snapshots.utc_now", return_value=NOW+timedelta(seconds=40)), \
             patch("app.pricing.backfill.utc_now", return_value=NOW+timedelta(seconds=40)):
            count, calls = await self.execute(gold, source, requests=calls)
        self.assertEqual(count, 1)
        self.assertEqual(len(calls), 1)
        self.budgets.consume.assert_awaited_once_with(self.daily,
            RequestPurpose.BACKFILL, source_url=self.daily.history_url)
        self.assertEqual([q.received_at for q in self.quotes], [NOW, NOW])
        self.assertEqual([str(q.price) for q in self.quotes], ["517260", "26236700"])
        self.store.set_canonical.assert_not_awaited()
        self.store.set_provider_quote.assert_not_awaited()

    async def test_intraday_uses_shared_bounded_url_and_published_point_times(self):
        source = {"date": "1405/07/25", "time": "15:20", "series": {"silver": {
            "points": [["15:10", 504840]], "low": 500000, "high": 510000}}}
        count, calls = await self.execute(self.intraday, source, job=self.job(days=1/24))
        self.assertEqual(count, 1)
        self.assertEqual(str(calls[0].url), self.intraday.history_url)
        self.assertEqual(self.quotes[0].observed_at, datetime(2026, 10, 17, 11, 40, tzinfo=UTC))
        self.assertEqual(self.quotes[0].received_at, NOW)

    async def test_source_quota_cooldown_and_cache_denials_defer_without_http(self):
        for code in ("budget_limit_1", "provider_cooldown", "provider_budget_disabled",
                     "snapshot_locked", "snapshot_cache_unavailable", "snapshot_lease_lost"):
            with self.subTest(code=code):
                self.queue.source_snapshots.get = AsyncMock(side_effect=SourceSnapshotUnavailable(code))
                with self.assertRaises(HistoryBudgetDeferred):
                    await self.execute(self.daily, {"series": []})
        self.persistence.persist_provider_quote.assert_not_awaited()

    async def test_worker_does_not_precharge_shared_snapshot_or_burn_deferred_attempt(self):
        job = self.job()
        self.operational.providers_for.return_value = (self.daily,)
        self.queue._drain_redis_jobs = AsyncMock()
        self.queue._eligible_instruments = AsyncMock(return_value=(job["instrument_id"],))
        self.queue._claim_job = Mock(return_value=job)
        self.queue._finish_job = Mock()
        self.queue._execute_history_job = AsyncMock(side_effect=HistoryBudgetDeferred("budget_limit_1"))
        result = await self.queue.process_jobs(1)
        self.assertEqual(result, {"completed": 0, "deferred": 1, "failed": 0})
        self.budgets.consume.assert_not_awaited()
        self.queue._finish_job.assert_called_once_with(1, "deferred", "history_page_budget_deferred", 1)

    async def test_fixed_wallgold_query_is_preserved_without_udf_or_page_parameters(self):
        source = {"success": True, "result": {"chart": {"data": [{"date": "2026-10-16T00:00:00Z",
            "open": "475000", "low": "465000", "high": "480000", "close": "467000"}]}}}
        parser = build_history_parser(self.daily925.history_parser_id)
        params, headers = _history_request_options(self.daily925, parser, NOW-timedelta(days=365), NOW)
        self.assertEqual(params, {})
        self.assertEqual(headers, {})
        count, calls = await self.execute(self.daily925, source)
        self.assertEqual(count, 1)
        self.assertEqual(str(calls[0].url), self.daily925.history_url)
        self.assertEqual(dict(calls[0].url.params), {"symbol": "SLV_925TMN", "chartType": "YEARLY"})
        self.assertEqual(self.quotes[0].metadata["source_timezone"], "UTC")

    async def test_automatic_intraday_request_keeps_subday_buckets_instead_of_daily_coalescing(self):
        self.operational.providers_for.return_value = (self.daily, self.intraday)
        self.queue._insert_job = Mock(return_value=1)
        first = await self.queue.enqueue_automatic(instrument_id="SILVER_999_TOMAN_GRAM",
            range_start=NOW-timedelta(hours=1), range_end=NOW, bucket_seconds=900)
        second = await self.queue.enqueue_automatic(instrument_id="SILVER_999_TOMAN_GRAM",
            range_start=NOW-timedelta(minutes=45), range_end=NOW+timedelta(minutes=15), bucket_seconds=900)
        self.assertEqual((first.status, second.status), ("queued", "queued"))
        self.assertNotEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(self.queue._insert_job.call_count, 2)


if __name__ == "__main__":
    unittest.main()
