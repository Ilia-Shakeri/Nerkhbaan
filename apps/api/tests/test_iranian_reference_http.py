from __future__ import annotations

import os
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.pricing.reference_rates import build_reference_history, build_reference_snapshot, reference_definitions
from app.pricing.reference_service import IranianReferenceService, iranian_reference_service
from app.routers.prices import router


NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def response_payload():
    current = build_reference_snapshot({"date": "1405/07/25", "time": "15:00", "rates": {
        "gold24": 35_000_000, "bitcoin": 20_000_000_000, "tether": 275_000, "dollar": 250_000,
    }}, received_at=NOW, now=NOW)
    history = build_reference_history({"series": [
        {"key": key, "name": key, "days": [["1405/07/24", value]]}
        for key, value in {"gold24": 34_000_000, "bitcoin": 19_000_000_000,
                           "tether": 260_000, "dollar": 250_000}.items()
    ]}, range_start=NOW - timedelta(days=30), range_end=NOW)
    return IranianReferenceService._response(
        reference_definitions(), {item["instrument_id"]: item for item in current}, history,
        revision="reference-http-fixture", checked_at=NOW, timeframe="30d", attributions=[], errors=[])


class IranianReferenceHttpTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = self.enterContext(TestClient(app))

    def test_reference_http_keeps_contracts_source_clocks_and_daily_precision(self):
        with patch.object(iranian_reference_service, "get", AsyncMock(return_value=response_payload())) as fetch:
            result = self.client.get("/api/prices/references?timeframe=30d")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        fetch.assert_awaited_once_with("30d")
        gold, btc, usdt = result.json()["references"]
        self.assertIsNone(gold["purity"])
        self.assertFalse(gold["physical_purity_confirmed"])
        self.assertEqual(gold["current"]["status"], "delayed_reference")
        self.assertEqual(gold["current"]["source_time"], "15:00")
        self.assertEqual(gold["current"]["source_timestamp_scope"], "source_rates_last_change")
        self.assertEqual(btc["current"]["price"], 80000)
        self.assertEqual(usdt["current"]["price"], 1.1)
        for item in (gold, btc, usdt):
            point = item["history"][0]
            self.assertEqual(point["timestamp_precision"], "day")
            self.assertEqual(point["timestamp_role"], "day_bucket_start")
            self.assertFalse(point["source_observation_time_known"])
            self.assertEqual(point["source_provider_id"], "nerkhsanj_reference_history")
            self.assertTrue(point["inputs"])
        self.assertNotIn('"BTC_USD"', result.text)
        self.assertNotIn('"GOLD_24K_TOMAN_GRAM"', result.text)

    def test_invalid_timeframe_does_not_fetch_and_source_failure_is_private(self):
        with patch.object(iranian_reference_service, "get", AsyncMock(side_effect=RuntimeError("private-details"))) as fetch:
            self.assertEqual(self.client.get("/api/prices/references?timeframe=forever").status_code, 422)
            fetch.assert_not_awaited()
            result = self.client.get("/api/prices/references")
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private-details", result.text)

    def test_native_contract_or_nonfinite_injection_fails_closed(self):
        for mutation in ("physical", "native", "nonfinite"):
            payload = deepcopy(response_payload())
            current = payload["references"][0]["current"]
            if mutation == "physical":
                current["physical_purity_confirmed"] = True
            elif mutation == "native":
                current["instrument_id"] = "GOLD_24K_TOMAN_GRAM"
            else:
                current["price"] = float("inf")
            with self.subTest(mutation=mutation), patch.object(
                iranian_reference_service, "get", AsyncMock(return_value=payload)):
                self.assertEqual(self.client.get("/api/prices/references").status_code, 503)


    def test_named_contract_currency_method_and_parent_arithmetic_fail_closed(self):
        for target, field, value in (("current", "currency", "USD"), ("current", "method", "iran_fx_ratio"),
                                      ("current", "price", 1), ("current", "price_decimal", "1"),
                                      ("history", "currency", "USD"), ("history", "method", "iran_fx_ratio"),
                                      ("history", "price", 1), ("history", "price_decimal", "1"),
                                      ("parent", "price", 1), ("parent", "price_decimal", "1"),
                                      ("parent", "instrument_id", "GOLD_24K_TOMAN_GRAM")):
            payload = deepcopy(response_payload())
            item = payload["references"][0]
            row = item["current"] if target == "current" else item["history"][0]
            if target == "parent":
                row = row["inputs"][0]
            row[field] = value
            with self.subTest(target=target, field=field), patch.object(
                iranian_reference_service, "get", AsyncMock(return_value=payload)):
                self.assertEqual(self.client.get("/api/prices/references").status_code, 503)


class StoredReferenceValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrupt_saved_contracts_or_parent_values_are_dropped_without_relabeling(self):
        for field, value in (("currency", "USD"), ("method", "iran_fx_ratio"),
                             ("price", 1), ("price_decimal", "1"),
                             ("source_keys", ["gold"]), ("nominal_karat", None)):
            payload = response_payload()
            current = [deepcopy(item["current"]) for item in payload["references"]]
            history = {item["instrument_id"]: deepcopy(item["history"]) for item in payload["references"]}
            current[0][field] = value
            history[current[0]["instrument_id"]][0][field] = value
            repository = AsyncMock()
            repository.load.return_value = {"snapshots": current, "histories": history}
            service = IranianReferenceService(repository=repository)
            with self.subTest(field=field), patch.object(service, "_require_revision"), patch(
                    "app.pricing.reference_service.reference_allowed", return_value=True):
                recovered_current, recovered_history = await service._recover(
                    reference_definitions(), NOW - timedelta(days=30), NOW, NOW,
                    "reference-http-fixture", snapshots=True, history=True)
                self.assertNotIn(current[0]["instrument_id"], recovered_current)
                self.assertEqual(recovered_history[current[0]["instrument_id"]], [])
                self.assertEqual(len(recovered_current), 2)
                self.assertTrue(all(recovered_history[key] for key in list(history)[1:]))

    async def test_corrupt_saved_parent_math_and_cross_reference_history_are_dropped(self):
        payload = response_payload()
        current = [deepcopy(item["current"]) for item in payload["references"]]
        history = {item["instrument_id"]: deepcopy(item["history"]) for item in payload["references"]}
        current[1]["inputs"][0].update(price=1, price_decimal="1")
        first, second = list(history)[:2]
        history[first] = deepcopy(history[second])
        repository = AsyncMock()
        repository.load.return_value = {"snapshots": current, "histories": history}
        service = IranianReferenceService(repository=repository)
        with patch.object(service, "_require_revision"), patch(
                "app.pricing.reference_service.reference_allowed", return_value=True):
            recovered_current, recovered_history = await service._recover(
                reference_definitions(), NOW - timedelta(days=30), NOW, NOW,
                "reference-http-fixture", snapshots=True, history=True)
        self.assertNotIn(second, recovered_current)
        self.assertEqual(recovered_history[first], [])

