from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

import httpx

from app.pricing.backfill import HistoryBudgetDeferred, PricingBackfillQueue, _history_request_options
from app.pricing.budgets import BudgetDecision
from app.pricing.instruments import get_instrument
from app.pricing.parsers import ParserContext, ParserError, build_parser
from app.pricing.parsers.history import build_history_parser
from app.pricing.persistence import PersistenceResult
from app.pricing.registry import PROVIDERS, RETIRED_PROVIDERS

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def candles(start: datetime, count: int) -> dict:
    return {"s": "ok", "t": [int((start + timedelta(hours=i)).timestamp()) for i in range(count)],
            "o": ["100000"] * count, "h": ["100500"] * count,
            "l": ["99500"] * count, "c": ["100100"] * count, "v": ["0"] * count}


class WallexHistoryContractTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_history_parser("wallex_udf_usdt_toman_v1")
        self.instrument = get_instrument("USDT_TOMAN")
        self.start = NOW - timedelta(hours=2)

    def parse(self, payload):
        with patch("app.pricing.parsers.history.utc_now", return_value=NOW):
            return self.parser.parse(payload, self.instrument, self.start, NOW)

    def test_complete_hourly_closes_keep_toman_without_division_and_drop_open_bar(self):
        points = self.parse(candles(self.start, 3))
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].price, Decimal("100100"))
        self.assertEqual(points[0].observed_at, self.start)

    def test_no_data_is_empty_and_gaps_are_never_filled(self):
        self.assertEqual(self.parse({"s": "no_data"}), [])
        row = candles(self.start, 2)
        row["t"][1] += 3600
        self.assertEqual(len(self.parse(row)), 1)

    def test_wrong_instrument_is_rejected(self):
        with self.assertRaises(ParserError):
            self.parser.parse(candles(self.start, 2), get_instrument("BTC_TOMAN"), self.start, NOW)

    def test_malformed_lengths_status_numbers_and_ohlc_are_rejected(self):
        for field, value in (("s", "error"), ("c", []), ("h", ["90000"] * 2),
                             ("v", ["-1"] * 2), ("o", ["NaN"] * 2)):
            with self.subTest(field=field), self.assertRaises(ParserError):
                self.parse({**candles(self.start, 2), field: value})

    def test_bool_fractional_millisecond_and_duplicate_source_times_are_rejected(self):
        for timestamp in (True, 123.5, "not-a-time", 1792152000000):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                self.parse({**candles(self.start, 1), "t": [timestamp]})
        row = candles(self.start, 2)
        row["t"][1] = row["t"][0]
        with self.assertRaises(ParserError):
            self.parse(row)


class IranianSourceRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_keyless_wallex_history_is_preferred_without_changing_live_price_priority(self):
        for kind in ("usdt", "btc"):
            with self.subTest(kind=kind):
                provider = PROVIDERS["wallex_" + kind + "_toman"]
                primary = PROVIDERS["nobitex_stats_" + kind]
                operational = SimpleNamespace(providers_for=AsyncMock(return_value=(primary, provider)))
                selected = await PricingBackfillQueue(operational=operational)._history_provider(provider.instrument_id)
                self.assertEqual(selected.provider_id, provider.provider_id)
                self.assertLess(primary.priority, provider.priority)
                self.assertIsNone(provider.api_key_setting)
                self.assertFalse(provider.history_requires_live_quote)

    async def test_disabled_wallex_history_respects_operator_policy(self):
        wallex = replace(PROVIDERS["wallex_usdt_toman"], enabled=False)
        primary = replace(PROVIDERS["nobitex_stats_usdt"], enabled=False)
        operational = SimpleNamespace(providers_for=AsyncMock(return_value=(primary, wallex)))
        self.assertIsNone(await PricingBackfillQueue(operational=operational)._history_provider("USDT_TOMAN"))
        primary = replace(primary, enabled=True)
        operational.providers_for.return_value = (primary, wallex)
        selected = await PricingBackfillQueue(operational=operational)._history_provider("USDT_TOMAN")
        self.assertEqual(selected.provider_id, primary.provider_id)

    async def test_servix_sources_require_key_and_exact_unit_contract_and_stay_disabled(self):
        for name, gate in (("xau_usd", "servix_metals_unit"), ("xag_usd", "servix_metals_unit"),
                           ("gold18_toman", "servix_gold18_unit"), ("gold24_toman", "servix_gold24_unit")):
            provider = RETIRED_PROVIDERS["servix_" + name]
            with self.subTest(name=name):
                self.assertFalse(provider.enabled)
                self.assertFalse(provider.configured(SimpleNamespace(servix_api_key="test-key")))
                self.assertIn(gate, provider.required_settings)
                self.assertTrue(provider.history_url.endswith("/history"))
                self.assertFalse(provider.history_requires_live_quote)

    async def test_default_servix_account_total_is_below_fifty_calls(self):
        routes = list(RETIRED_PROVIDERS.values())
        self.assertEqual(len(routes), 9)
        self.assertLessEqual(sum(provider.budget.requests_per_day for provider in routes), 48)
        self.assertTrue(all(provider.budget.minimum_interval_seconds >= 14400 for provider in routes))

    async def test_tala_prices_use_selected_key_and_matching_parser_provenance(self):
        for name in ("gold18", "gold24", "usdt", "silver999"):
            provider = PROVIDERS["tala_" + name + "_toman"]
            self.assertIn("/v1/rates/", provider.url)
            self.assertEqual(provider.parser_version, build_parser(provider.parser_id).parser_version)
            self.assertFalse(provider.enabled)


class ServixHistoricalContractTests(unittest.TestCase):
    def test_history_rejects_naive_missing_time_and_cross_instrument(self):
        parser = build_history_parser("servix_btc_usd_history_v1")
        row = {"code": "BTC_USD", "quoteUnit": "USD", "value": "77000", "businessTime": NOW.isoformat()}
        for timestamp in (None, "", "2026-10-16T12:00:00"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ParserError):
                parser.parse([{**row, "businessTime": timestamp}], get_instrument("BTC_USD"), NOW-timedelta(days=1), NOW)
        with self.assertRaises(ParserError):
            parser.parse([row], get_instrument("XAU_USD_OZ"), NOW-timedelta(days=1), NOW)

    def test_daily_ranges_over_thirty_one_dates_fail_before_any_request(self):
        provider = RETIRED_PROVIDERS["servix_btc_usd"]
        parser = build_history_parser(provider.history_parser_id)
        with patch("app.pricing.backfill.settings.servix_api_key", "test-key"):
            params, headers = _history_request_options(provider, parser, NOW-timedelta(days=30), NOW)
            self.assertEqual(headers, {"X-API-Key": "test-key"})
            self.assertNotIn("test-key", str(params))
            with self.assertRaisesRegex(ValueError, "31_calendar_days"):
                _history_request_options(provider, parser, NOW-timedelta(days=31), NOW)

    def test_registered_metals_and_physical_gold_history_keep_exact_symbols_and_units(self):
        for name, symbol, unit, value, iid in (
            ("xau_usd", "GOLD_OUNCE_USD", "USD", "4000", "XAU_USD_OZ"),
            ("xag_usd", "SILVER_OUNCE_USD", "USD", "45", "XAG_USD_OZ"),
            ("gold18_toman", "GOLD_18_RLS", "RLS", "80000000", "GOLD_18K_TOMAN_GRAM"),
            ("gold24_toman", "GOLD_24_RLS", "RLS", "110000000", "GOLD_24K_TOMAN_GRAM"),
        ):
            row = {"code": symbol, "quoteUnit": unit, "value": value, "businessTime": NOW.isoformat()}
            with self.subTest(name=name):
                points = build_history_parser("servix_"+name+"_history_v1").parse([row], get_instrument(iid), NOW-timedelta(days=1), NOW)
                self.assertEqual(len(points), 1)
                factor = Decimal("0.1") if unit == "RLS" else Decimal(1)
                self.assertEqual(points[0].price, Decimal(value)*factor)

    def test_current_quote_cannot_relabel_one_instrument_as_another(self):
        parser = build_parser("servix_gold24_toman_v1")
        with self.assertRaises(ParserError):
            parser.parse({"code": "GOLD_24_RLS", "quoteUnit": "RLS", "value": "100000000", "businessTime": NOW.isoformat()},
                         ParserContext(get_instrument("GOLD_18K_TOMAN_GRAM"), NOW, 3600))


class WallexWindowedBackfillTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = PROVIDERS["wallex_usdt_toman"]
        self.persistence = AsyncMock()
        self.persistence.persist_provider_quote.return_value = PersistenceResult(True, False, None, None)
        self.persistence.persist_canonical.return_value = PersistenceResult(True, False, None, None)
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        operational = AsyncMock()
        operational.instrument.return_value = get_instrument("USDT_TOMAN")
        self.queue = PricingBackfillQueue(persistence=self.persistence, budgets=self.budgets, operational=operational)
        self.queue._renew_job = Mock(return_value=True)
        self.job = {"id": 92, "attempt_count": 1, "range_start": NOW-timedelta(days=14), "range_end": NOW,
                    "instrument_id": "USDT_TOMAN"}

    async def execute(self, payloads):
        client = AsyncMock()
        client.get.side_effect = [httpx.Response(200, json=p, request=httpx.Request("GET", "https://example.invalid")) for p in payloads]
        with patch("app.pricing.backfill.httpx.AsyncClient") as factory, \
             patch("app.pricing.backfill.asyncio.sleep", AsyncMock()), \
             patch("app.pricing.parsers.history.utc_now", return_value=NOW):
            factory.return_value.__aenter__.return_value = client
            count = await self.queue._execute_history_job(self.job, self.provider)
        return count, client

    async def test_two_weeks_are_two_bounded_requests_without_page_parameter(self):
        start = self.job["range_start"]
        count, client = await self.execute([candles(start, 169), candles(start+timedelta(days=7), 169)])
        self.assertEqual(count, 336)
        self.assertEqual(client.get.await_count, 2)
        self.budgets.consume.assert_awaited_once()
        for call in client.get.await_args_list:
            self.assertNotIn("page", call.kwargs["params"])
            self.assertLessEqual(call.kwargs["params"]["to"]-call.kwargs["params"]["from"], 7*86400)
        self.assertTrue(all(c.args[0].metadata["history_point_kind"] == "hourly_candle_close"
                            for c in self.persistence.persist_provider_quote.await_args_list))

    async def test_bad_later_window_never_persists_a_partial_success(self):
        with self.assertRaises(ParserError):
            await self.execute([candles(self.job["range_start"], 169), {"s": "error"}])
        self.persistence.persist_provider_quote.assert_not_called()

    async def test_unaligned_range_does_not_lose_internal_boundary_candle(self):
        self.job["range_start"] += timedelta(minutes=30)
        self.job["range_end"] += timedelta(minutes=30)
        start = self.job["range_start"].replace(minute=0)
        count, client = await self.execute([candles(start, 169), candles(start+timedelta(days=7), 169),
                                            candles(start+timedelta(days=14), 1)])
        self.assertEqual(count, 335)
        times = [call.args[0].observed_at for call in self.persistence.persist_provider_quote.await_args_list]
        self.assertIn(start+timedelta(days=7), times)
        self.assertEqual(len(times), len(set(times)))
        self.assertEqual(client.get.await_count, 3)

    async def test_later_window_quota_denial_defers_without_partial_writes(self):
        self.budgets.consume.return_value = BudgetDecision(False, "quota", 0)
        with self.assertRaises(HistoryBudgetDeferred):
            await self.execute([candles(self.job["range_start"], 169)])
        self.persistence.persist_provider_quote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
