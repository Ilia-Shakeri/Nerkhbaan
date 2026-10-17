from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import prices


class HistoryTimeContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(prices.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_http_current_prices_keep_publication_metadata_and_time_on_the_correct_leg(self):
        summary = {"source_timestamp_scope": "publication_snapshot", "source_timestamp_precision": "minute",
                   "source_timezone": "Asia/Tehran", "source_trade_time_known": False}
        payload = {"refreshed_at": "2026-10-17T11:31:30Z", "source": {}, "assets": [{
            "asset": "silver", "label_fa": "نقره", "label_en": "Silver", "price_usd": 55,
            "price_toman": 500000, "change_percent": None, "trend": "neutral", "history": [],
            "source_usd": "canonical", "source_toman": "canonical", "usd_status": "live", "toman_status": "live",
            "chart_error": False, "chart_error_message": {}, "usd_source_summary": {},
            "toman_source_summary": summary, "usd_observed_at": "2026-10-17T11:31:21Z",
            "toman_observed_at": "2026-10-17T11:30:00Z", "_toman_rights_source_summary": {"private": "fixture"},
        }]}
        with patch.object(prices.legacy_pricing_adapter, "get_prices", AsyncMock(return_value=payload)):
            response = self.client.get("/api/prices")
        self.assertEqual(response.status_code, 200)
        asset, = response.json()["assets"]
        self.assertEqual(asset["toman_source_summary"], summary)
        self.assertEqual(asset["usd_source_summary"], {})
        self.assertEqual(asset["toman_observed_at"], "2026-10-17T11:30:00Z")
        self.assertEqual(asset["usd_observed_at"], "2026-10-17T11:31:21Z")
        self.assertNotIn("_toman_rights_source_summary", asset)

    def test_http_history_keeps_utc_gregorian_day_metadata_in_paired_response(self):
        utc = {"timestamp_precision": "day", "timestamp_role": "day_bucket_start",
               "source_observation_time_known": False, "source_timezone": "UTC",
               "source_calendar": "gregorian", "source_date": "2026-10-14"}
        payload = {"asset": "silver", "status": "partial", "points": [{
            "timestamp": "2026-10-14T00:00:00Z", "value_usd": 55, "value_toman": 467000,
            **utc, "time_info_usd": {"timestamp_precision": "instant"}, "time_info_toman": utc,
        }]}
        with patch.object(prices.legacy_pricing_adapter, "get_history", AsyncMock(return_value=payload)):
            response = self.client.get("/api/prices/silver/history?timeframe=1y")
        self.assertEqual(response.status_code, 200)
        point, = response.json()["points"]
        self.assertEqual(point["source_calendar"], "gregorian")
        self.assertEqual(point["time_info_toman"]["source_timezone"], "UTC")
        self.assertEqual(point["time_info_toman"]["source_date"], "2026-10-14")
        self.assertEqual(point["time_info_usd"]["timestamp_precision"], "instant")


if __name__ == "__main__":
    unittest.main()
