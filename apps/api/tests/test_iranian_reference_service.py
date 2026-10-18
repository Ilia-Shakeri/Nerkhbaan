from __future__ import annotations

import asyncio
import json
import os
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.config import settings
from app.pricing import rights
from app.pricing.budgets import BudgetDecision
from app.pricing.instruments import INSTRUMENTS
from app.pricing.reference_rates import (
    HISTORY_PROVIDER_ID, REFERENCE_IDS, SNAPSHOT_PROVIDER_ID,
    build_reference_history, build_reference_snapshot,
)
from app.pricing.reference_service import IranianReferenceService, _transports
from app.pricing.registry import PROVIDERS
from app.pricing.source_snapshots import SharedSourceSnapshots
from tests.test_source_snapshots import _Redis

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
LIVE = "https://nerkh.jahankhahan.shop/data/live.json"
DAILY = "https://nerkh.jahankhahan.shop/data/rates.json"
LIVE_PAYLOAD = {"date": "1405/07/25", "time": "15:30", "rates": {
    "gold24": 35000000, "bitcoin": 21516000000, "tether": 266640, "dollar": 264000,
}}
HISTORY_PAYLOAD = {"updated": "1405/07/25", "series": [
    {"key": key, "name": key, "days": [["1405/07/23", value], ["1405/07/24", value]]}
    for key, value in LIVE_PAYLOAD["rates"].items()
]}


class _Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"padding":"' + b"a" * 150000
        yield b"b" * 150000 + b'"}'


class IranianReferenceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now, self.revision = NOW, "review-one"
        self.permissions = {}
        self.requests = []
        self.redis = _Redis()
        self.store = SimpleNamespace(client=lambda: self.redis)
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        self.repository = SimpleNamespace(save_snapshot=AsyncMock(return_value=3),
                                          save_history=AsyncMock(return_value=6), load=AsyncMock())
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        self.enterContext(patch.object(settings, "pricing_provider_allowed_hosts", "nerkh.jahankhahan.shop"))
        self.enterContext(patch.object(rights, "provider_allowed", side_effect=lambda provider, action="display":
                                     self.permissions.get((provider, action), True)))
        self.enterContext(patch.object(rights, "endpoint_allowed", return_value=True))
        self.enterContext(patch.object(rights, "revision", side_effect=lambda: self.revision))
        self.enterContext(patch.object(rights, "attribution", return_value=[
            {"label": "Nerkhsanj", "url": "https://nerkh.jahankhahan.shop/developers"}]))
        for module in ("reference_service", "reference_rates", "source_snapshots"):
            self.enterContext(patch(f"app.pricing.{module}.utc_now", side_effect=lambda: self.now))
        self.saved_snapshot = build_reference_snapshot(deepcopy(LIVE_PAYLOAD), received_at=NOW, now=NOW)
        self.saved_history = build_reference_history(deepcopy(HISTORY_PAYLOAD),
                                                     range_start=NOW - timedelta(days=30), range_end=NOW)
        self.repository.load.side_effect = lambda **_kwargs: {
            "snapshots": deepcopy(self.saved_snapshot), "histories": deepcopy(self.saved_history)}
        self.service = IranianReferenceService(store=self.store, budgets=self.budgets, repository=self.repository)

    def client(self, handler=None):
        async def handle(request):
            self.requests.append(str(request.url))
            if handler is not None:
                result = handler(request)
                return await result if asyncio.iscoroutine(result) else result
            return httpx.Response(200, json=deepcopy(LIVE_PAYLOAD if request.url.path.endswith("live.json") else HISTORY_PAYLOAD))
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)

    async def get(self, handler=None, **kwargs):
        async with self.client(handler) as client:
            return await self.service.get(client=client, **kwargs)

    @staticmethod
    def by_id(response):
        return {item["instrument_id"]: item for item in response["references"]}

    async def test_three_explicit_references_do_not_enter_native_quote_registry(self):
        native_ids = set(INSTRUMENTS)
        response = await self.get()
        entries = self.by_id(response)
        self.assertEqual(set(entries), set(REFERENCE_IDS))
        self.assertEqual(set(INSTRUMENTS), native_ids)
        self.assertFalse(set(REFERENCE_IDS) & native_ids)
        self.assertEqual(entries[REFERENCE_IDS[1]]["current"]["price"], 81500)
        self.assertEqual(entries[REFERENCE_IDS[2]]["current"]["price"], 1.01)
        self.assertTrue(all(item["market"] == "reference" and item["region"] == "iran" for item in entries.values()))
        self.assertTrue(all(item["purity"] is None and not item["physical_purity_confirmed"] for item in entries.values()))
        self.assertTrue(all(len(item["history"]) == 2 for item in entries.values()))
        self.assertTrue(all(item["current"]["persistence_status"] == "persisted" for item in entries.values()))
        self.assertEqual(set(self.requests), {LIVE, DAILY})
        self.assertEqual(self.budgets.consume.await_count, 2)

    async def test_twelve_consumers_share_parent_file_cache_and_actual_network_budget(self):
        async def delayed(request):
            await asyncio.sleep(0.02)
            return httpx.Response(200, json=LIVE_PAYLOAD if request.url.path.endswith("live.json") else HISTORY_PAYLOAD)
        services = [IranianReferenceService(store=self.store, budgets=self.budgets, repository=self.repository)
                    for _index in range(12)]
        async with self.client(delayed) as client:
            responses = await asyncio.gather(*(service.get(client=client) for service in services))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.budgets.consume.await_count, 2)
        self.assertTrue(all(len(response["references"]) == 3 for response in responses))
        no_request = AsyncMock(side_effect=AssertionError("Parent collectors must reuse the same files"))
        old_consumer = SharedSourceSnapshots(self.store, self.budgets)
        for provider_id, url in (("nerkhsanj_usd_toman", LIVE), ("nerkhsanj_usd_toman_history", DAILY)):
            snapshot = await old_consumer.get(PROVIDERS[provider_id], url, no_request)
            self.assertEqual(snapshot.fetched_at, NOW)
            self.assertFalse(snapshot.network_called)
        no_request.assert_not_awaited()

    async def test_shared_cache_never_renews_reference_receipt_or_age(self):
        await self.get()
        self.now += timedelta(seconds=45)
        response = await self.get()
        entries = self.by_id(response)
        bitcoin = entries[REFERENCE_IDS[1]]["current"]
        self.assertEqual(bitcoin["received_at"], NOW.isoformat())
        self.assertEqual(bitcoin["age_seconds"], 45)
        self.assertEqual(bitcoin["status"], "delayed_reference")
        self.assertEqual(entries[REFERENCE_IDS[0]]["status"], "fresh_reference")
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.repository.save_snapshot.await_args.kwargs["received_at"], NOW)

    async def test_transient_failure_uses_original_persisted_clock_without_http_retry(self):
        self.now += timedelta(minutes=5)
        response = await self.get(lambda _request: httpx.Response(503))
        self.assertEqual(len(self.requests), 2)
        self.repository.load.assert_awaited_once()
        for item in response["references"]:
            self.assertEqual(item["current"]["received_at"], NOW.isoformat())
            self.assertEqual(item["current"]["observed_at"], NOW.isoformat())
            self.assertEqual(item["current"]["age_seconds"], 300)
            self.assertTrue(item["current"]["storage_fallback"])
            self.assertEqual(item["history_status"], "partial")
        self.assertEqual(self.by_id(response)[REFERENCE_IDS[1]]["status"], "delayed_reference")

    async def test_expired_stored_reference_does_not_remove_permitted_older_history(self):
        self.now += timedelta(days=2)
        response = await self.get(lambda _request: httpx.Response(503))
        self.assertTrue(all(item["current"]["price"] is None for item in response["references"]))
        self.assertTrue(all(len(item["history"]) == 2 for item in response["references"]))

    async def test_unusable_stored_clocks_are_never_replaced_with_receipt_or_now(self):
        for bad_clock in (None, "2026-10-17T12:00:00", (NOW + timedelta(minutes=5)).isoformat()):
            with self.subTest(clock=bad_clock):
                self.saved_snapshot = [{**item, "observed_at": bad_clock} for item in self.saved_snapshot]
                response = await self.get(lambda _request: httpx.Response(503))
                self.assertTrue(all(item["current"]["price"] is None for item in response["references"]))

    async def test_collection_or_storage_withdrawal_retains_authorized_stored_history(self):
        for provider in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID):
            for action in ("collect", "store"):
                self.permissions[provider, action] = False
        response = await self.get(lambda _request: self.fail("Collection is disabled"))
        self.assertEqual(self.requests, [])
        self.budgets.consume.assert_not_awaited()
        self.repository.save_snapshot.assert_not_awaited()
        self.repository.save_history.assert_not_awaited()
        self.assertTrue(all(item["current"]["price"] is not None and item["history"] for item in response["references"]))
        self.assertTrue(all(item["history_status"] == "partial" for item in response["references"]))

    async def test_source_disabled_keeps_permitted_persisted_reference_and_history(self):
        transports = tuple(replace(provider, enabled=False) for provider in _transports())
        with patch("app.pricing.reference_service._transports", return_value=transports):
            response = await self.get(lambda _request: self.fail("Disabled sources must not fetch"))
        self.assertTrue(all(item["current"]["storage_fallback"] for item in response["references"]))
        self.assertTrue(all(item["history"] for item in response["references"]))
        self.assertEqual(self.requests, [])

    async def test_display_withdrawal_withholds_both_fresh_and_stored_data(self):
        for provider in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID):
            self.permissions[provider, "display"] = False
        response = await self.get(lambda _request: self.fail("No readable references"))
        self.assertTrue(all(item["current"]["price"] is None and not item["history"] for item in response["references"]))
        self.repository.load.assert_not_awaited()
        self.assertEqual(response["attributions"], [])

    async def test_derivation_withdrawal_withholds_usd_references_but_keeps_published_gold(self):
        for provider in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID):
            self.permissions[provider, "derive"] = False
        response = await self.get()
        entries = self.by_id(response)
        self.assertIsNotNone(entries[REFERENCE_IDS[0]]["current"]["price"])
        self.assertTrue(entries[REFERENCE_IDS[0]]["history"])
        for reference_id in REFERENCE_IDS[1:]:
            self.assertIsNone(entries[reference_id]["current"]["price"])
            self.assertEqual(entries[reference_id]["history"], [])
        saved = self.repository.save_snapshot.await_args.args[0]
        self.assertEqual([item["instrument_id"] for item in saved], [REFERENCE_IDS[0]])

    async def test_history_permission_withdrawal_does_not_hide_allowed_current_reference(self):
        self.permissions[HISTORY_PROVIDER_ID, "history"] = False
        response = await self.get()
        self.assertEqual(self.requests, [LIVE])
        self.assertTrue(all(item["current"]["price"] is not None and not item["history"] for item in response["references"]))

    async def test_display_withdrawal_during_network_never_falls_back_to_stored_data(self):
        def withdraw(_request):
            self.revision = "review-two"
            for provider in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID):
                self.permissions[provider, "display"] = False
            return httpx.Response(200, json=LIVE_PAYLOAD)
        response = await self.get(withdraw)
        self.assertTrue(all(item["current"]["price"] is None and not item["history"] for item in response["references"]))
        self.assertEqual(response["rights_revision"], "review-two")
        self.repository.load.assert_not_awaited()
        self.repository.save_snapshot.assert_not_awaited()
        self.assertIsNone(await self.redis.get(self.service.source_snapshots.cache_key(LIVE)))

    async def test_collection_withdrawal_during_network_preserves_only_stored_allowed_values(self):
        def withdraw(_request):
            self.revision = "review-two"
            for provider in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID):
                self.permissions[provider, "collect"] = False
            return httpx.Response(200, json={**LIVE_PAYLOAD, "rates": {**LIVE_PAYLOAD["rates"], "bitcoin": 999}})
        response = await self.get(withdraw)
        entries = self.by_id(response)
        self.assertEqual(entries[REFERENCE_IDS[1]]["current"]["price"], 81500)
        self.assertTrue(entries[REFERENCE_IDS[1]]["current"]["storage_fallback"])
        self.assertEqual(response["rights_revision"], "review-two")
        self.repository.save_snapshot.assert_not_awaited()

    async def test_withdrawal_during_persistence_withholds_prepared_output(self):
        async def withdraw(*_args, **_kwargs):
            self.revision = "review-two"
            for provider in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID):
                self.permissions[provider, "display"] = False
            return 0
        self.repository.save_snapshot.side_effect = withdraw
        response = await self.get()
        self.assertTrue(all(item["current"]["price"] is None and not item["history"] for item in response["references"]))
        self.assertEqual(response["attributions"], [])

    async def test_invalid_payloads_never_publish_a_source_snapshot_or_save_current(self):
        cases = (
            httpx.Response(200, text="not-json", headers={"Content-Type": "application/json"}),
            httpx.Response(200, text=json.dumps(LIVE_PAYLOAD), headers={"Content-Type": "text/html"}),
            httpx.Response(200, json={"date": "1405/07/25", "time": "15:30", "rates": []}),
            httpx.Response(200, content=b'{"v":NaN}', headers={"Content-Type": "application/json"}),
            httpx.Response(200, json={**LIVE_PAYLOAD, "time": "15:35"}),
        )
        for bad in cases:
            with self.subTest(payload=bad.status_code):
                response = await self.get(lambda request: bad if request.url.path.endswith("live.json") else httpx.Response(200, json=HISTORY_PAYLOAD))
                self.assertTrue(all(item["current"]["price"] is None for item in response["references"]))
                self.assertIsNone(await self.redis.get(self.service.source_snapshots.cache_key(LIVE)))
        self.repository.save_snapshot.assert_not_awaited()

    async def test_live_byte_limit_applies_to_stream_without_content_length(self):
        response = await self.get(lambda request: httpx.Response(200, stream=_Chunks(), headers={"Content-Type": "application/json"})
                                  if request.url.path.endswith("live.json") else httpx.Response(200, json=HISTORY_PAYLOAD))
        self.assertTrue(all(item["current"]["price"] is None for item in response["references"]))
        self.assertIn({"stage": "current", "code": "payload_too_large"}, response["errors"])
        self.assertIsNone(await self.redis.get(self.service.source_snapshots.cache_key(LIVE)))

    async def test_history_has_separate_bounded_eight_mib_transport_limit(self):
        large = {**HISTORY_PAYLOAD, "padding": "a" * 1_200_000}
        response = await self.get(lambda request: httpx.Response(200, json=LIVE_PAYLOAD if request.url.path.endswith("live.json") else large))
        self.assertTrue(all(item["history"] for item in response["references"]))
        self.repository.save_history.assert_awaited_once()

    async def test_rate_limit_records_retry_after_for_each_shared_source_url_without_retry(self):
        response = await self.get(lambda _request: httpx.Response(429, headers={"Retry-After": "120"}))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.budgets.record_rate_limit.await_count, 2)
        self.assertEqual({call.kwargs["source_url"] for call in self.budgets.record_rate_limit.await_args_list}, {LIVE, DAILY})
        self.assertTrue(all(call.kwargs["retry_after_seconds"] == 120 for call in self.budgets.record_rate_limit.await_args_list))
        self.assertTrue(all(item["current"]["storage_fallback"] for item in response["references"]))

    async def test_budget_denial_never_calls_http_and_keeps_allowed_stored_history(self):
        self.budgets.consume.return_value = BudgetDecision(False, "budget_limit_1", 0)
        response = await self.get(lambda _request: self.fail("Budget must stop transport"))
        self.assertEqual(self.requests, [])
        self.assertTrue(all(item["current"]["storage_fallback"] and item["history"] for item in response["references"]))
        self.repository.load.assert_awaited_once()

    async def test_disallowed_host_never_reads_upstream_even_when_stored_output_is_allowed(self):
        with patch.object(settings, "pricing_provider_allowed_hosts", "other.invalid"):
            response = await self.get(lambda _request: self.fail("Host must remain blocked"))
        self.assertEqual(self.requests, [])
        self.assertTrue(all(item["current"]["storage_fallback"] for item in response["references"]))

    async def test_persistence_failure_keeps_new_reference_explicitly_unpersisted(self):
        self.repository.save_snapshot.side_effect = OSError("Owned test repository unavailable")
        response = await self.get()
        self.assertTrue(all(item["current"]["price"] is not None and item["current"]["persistence_status"] == "unpersisted"
                            for item in response["references"]))
        self.assertIn({"stage": "persistence_current", "code": "reference_persistence_unavailable"}, response["errors"])

    async def test_waiting_for_persistence_cannot_extend_reference_freshness(self):
        async def delayed_save(*_args, **_kwargs):
            self.now += timedelta(seconds=45)
            return 3
        self.repository.save_snapshot.side_effect = delayed_save
        response = await self.get()
        bitcoin = self.by_id(response)[REFERENCE_IDS[1]]["current"]
        self.assertEqual(bitcoin["status"], "delayed_reference")
        self.assertEqual(bitcoin["age_seconds"], 45)
        self.assertEqual(bitcoin["received_at"], NOW.isoformat())
        self.assertEqual(response["checked_at"], (NOW + timedelta(seconds=45)).isoformat())
        self.assertNotIn("storage_fallback", bitcoin)

    async def test_published_history_merges_stored_dates_and_new_values_win_same_date(self):
        old_payload = deepcopy(HISTORY_PAYLOAD)
        for series in old_payload["series"]:
            series["days"] = [["1405/07/22", series["days"][0][1]], ["1405/07/23", series["days"][0][1]]]
        self.saved_history = build_reference_history(old_payload, range_start=NOW - timedelta(days=30), range_end=NOW)
        new_payload = deepcopy(HISTORY_PAYLOAD)
        next(series for series in new_payload["series"] if series["key"] == "bitcoin")["days"][0][1] = 23760000000
        response = await self.get(lambda request: httpx.Response(200, json=LIVE_PAYLOAD if request.url.path.endswith("live.json") else new_payload))
        bitcoin = self.by_id(response)[REFERENCE_IDS[1]]
        self.assertEqual([point["source_date"] for point in bitcoin["history"]], ["1405/07/22", "1405/07/23", "1405/07/24"])
        self.assertEqual(bitcoin["history"][1]["price"], 90000)
        self.assertEqual(bitcoin["history_status"], "partial")
        self.repository.load.assert_awaited_once()

    async def test_stored_native_or_wrong_method_metadata_is_not_relabelled_as_reference(self):
        self.saved_snapshot = [{**item, "market": "global_exchange"} for item in self.saved_snapshot]
        response = await self.get(lambda _request: httpx.Response(503))
        self.assertTrue(all(item["current"]["price"] is None for item in response["references"]))
        self.assertTrue(all(item["history"] for item in response["references"]))

    async def test_unrecognized_timeframe_is_rejected_before_any_io(self):
        with self.assertRaises(ValueError):
            await self.get(timeframe="100y")
        self.assertEqual(self.requests, [])
        self.repository.load.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
