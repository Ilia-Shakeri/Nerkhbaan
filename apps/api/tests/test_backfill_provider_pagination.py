from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

import httpx

from app.pricing.backfill import HistoryBudgetDeferred, PricingBackfillQueue
from app.pricing.budgets import BudgetDecision
from app.pricing.instruments import get_instrument
from app.pricing.parsers.base import ParserError
from app.pricing.parsers.history import build_history_parser
from app.pricing.persistence import PersistenceResult
from app.pricing.registry import PROVIDERS

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def payload(start: int, count: int):
    return {"s": "ok", "t": [int((NOW - timedelta(hours=720-index)).timestamp())
                              for index in range(start, start + count)],
            "o": ["8000000000"] * count, "h": ["8100000000"] * count,
            "l": ["7900000000"] * count,
            "c": ["8000000000"] * count, "v": [0] * count}


class UdfNoDataTests(unittest.TestCase):
    def test_explicit_no_data_is_empty_not_transport_or_parser_failure(self):
        parser = build_history_parser("nobitex_udf_usdtirt_v1")
        self.assertEqual(parser.parse({"s": "no_data"}, get_instrument("USDT_TOMAN"),
                                     NOW-timedelta(days=1), NOW), [])

    def test_udf_error_remains_failure(self):
        parser = build_history_parser("nobitex_udf_usdtirt_v1")
        with self.assertRaises(ParserError):
            parser.parse({"s": "error"}, get_instrument("USDT_TOMAN"),
                         NOW-timedelta(days=1), NOW)


class BackfillPaginationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = PROVIDERS["nobitex_stats_btc"]
        self.persistence = AsyncMock()
        self.persistence.persist_provider_quote.return_value = PersistenceResult(True, False, None, None)
        self.persistence.persist_canonical.return_value = PersistenceResult(True, False, None, None)
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("BTC_TOMAN")
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        self.queue = PricingBackfillQueue(persistence=self.persistence, operational=operational,
                                          budgets=self.budgets)
        self.queue._renew_job = Mock(return_value=True)
        self.job = {"id": 91, "attempt_count": 2, "instrument_id": "BTC_TOMAN",
                    "range_start": NOW-timedelta(hours=720), "range_end": NOW}
        self.client = AsyncMock()

    async def execute(self, pages):
        self.client.get.side_effect = [httpx.Response(200, json=p,
                                      request=httpx.Request("GET", "https://example.invalid")) for p in pages]
        with patch("app.pricing.backfill.httpx.AsyncClient") as factory, \
             patch("app.pricing.backfill.asyncio.sleep", AsyncMock()), \
             patch("app.pricing.backfill.utc_now", return_value=NOW):
            factory.return_value.__aenter__.return_value = self.client
            return await self.queue._execute_history_job(self.job, self.provider)

    async def test_month_fetches_500_plus_220_before_any_complete_result(self):
        count = await self.execute([payload(220, 500), payload(0, 220)])
        self.assertEqual(count, 720)
        self.assertEqual(self.client.get.await_count, 2)
        self.assertEqual([call.kwargs["params"]["page"] for call in self.client.get.await_args_list], [1, 2])
        self.budgets.consume.assert_awaited_once()
        self.assertEqual(self.persistence.persist_canonical.await_count, 720)
        timestamps = [call.args[0].observed_at for call in self.persistence.persist_canonical.await_args_list]
        self.assertEqual(timestamps, sorted(set(timestamps)))
        self.assertTrue(all(call.args[0].source_summary["historical_backfill"]
                            for call in self.persistence.persist_canonical.await_args_list))

    async def test_exact_page_boundary_checks_next_page_no_data(self):
        count = await self.execute([payload(220, 500), {"s": "no_data"}])
        self.assertEqual(count, 500)
        self.assertEqual(self.client.get.await_count, 2)

    async def test_first_no_data_does_not_write_or_fabricate_quotes(self):
        self.assertEqual(await self.execute([{"s": "no_data"}]), 0)
        self.persistence.persist_provider_quote.assert_not_called()
        self.persistence.persist_canonical.assert_not_called()
        self.budgets.consume.assert_not_called()

    async def test_repeat_page_cannot_complete_range(self):
        page = payload(220, 500)
        with self.assertRaisesRegex(ValueError, "did_not_advance"):
            await self.execute([page, page])
        self.persistence.persist_provider_quote.assert_not_called()

    async def test_conflicting_boundary_cannot_persist_partial_success(self):
        second = payload(220, 1)
        second["c"][0] = "9000000000"
        second["h"][0] = "9000000000"
        with self.assertRaisesRegex(ValueError, "conflicting"):
            await self.execute([payload(220, 500), second])
        self.persistence.persist_provider_quote.assert_not_called()

    async def test_additional_page_has_no_quota_then_defers_without_writes(self):
        self.budgets.consume.return_value = BudgetDecision(False, "budget_limit_1", 0)
        with self.assertRaises(HistoryBudgetDeferred):
            await self.execute([payload(220, 500)])
        self.assertEqual(self.client.get.await_count, 1)
        self.persistence.persist_provider_quote.assert_not_called()

    async def test_lost_database_claim_cannot_fetch_or_persist_next_page(self):
        self.queue._renew_job.return_value = False
        with self.assertRaisesRegex(RuntimeError, "no_longer_owned"):
            await self.execute([payload(220, 500)])
        self.assertEqual(self.client.get.await_count, 1)
        self.budgets.consume.assert_not_called()
        self.persistence.persist_provider_quote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
