from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worker = load("rights_worker", "infra/price-worker/worker.py")
builder = load("rights_feed_builder", "scripts/build-price-feed.py")


def payload(symbol, *, now=None, **overrides):
    return {"symbol": symbol, "currency": "USD", "price": {"XAU": 4000, "XAG": 50, "BTC": 90000}[symbol], "updatedAt": (now or datetime.now(UTC)).isoformat(), **overrides}


class RightsProducerTests(unittest.TestCase):
    def test_live_worker_fetches_only_three_approved_routes_with_source_times(self):
        source_time = datetime.now(UTC)-timedelta(seconds=25)
        seen = []
        def get(url):
            seen.append(url)
            self.assertTrue(url.startswith("https://api.gold-api.com/price/"))
            return payload(url.rsplit("/", 1)[1], now=source_time)
        with patch.object(worker, "get_json", side_effect=get), patch.object(worker, "send") as send:
            worker.live()
        self.assertEqual(set(seen), {f"https://api.gold-api.com/price/{symbol}" for symbol in ("XAU", "XAG", "BTC")})
        quotes = send.call_args.args[0]
        self.assertEqual({row["instrument_id"] for row in quotes}, {"XAU_USD_OZ", "XAG_USD_OZ", "BTC_USD"})
        self.assertTrue(all(row["observed_at"] == source_time.isoformat() for row in quotes))

    def test_unsupported_history_preserves_old_progress_and_never_fetches(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)/"progress.json"
            state.write_text('{"old":{"complete":false,"last_timestamp":123}}')
            before = state.read_bytes()
            with patch.object(worker, "STATE_FILE", state), patch.object(worker, "get_json") as get, patch.object(worker, "send") as send:
                self.assertEqual(worker.backfill()["status"], "unavailable")
            get.assert_not_called()
            send.assert_not_called()
            self.assertEqual(state.read_bytes(), before)

    def test_public_publisher_default_denies_before_network_or_output_change(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"prices.json"
            target.write_text("previous owned fixture")
            with patch.dict(os.environ, {"PRICING_RIGHTS_MANIFEST_PATH": ""}), patch.object(builder, "_get_json") as get:
                with self.assertRaisesRegex(RuntimeError, "permission"):
                    builder.main(target)
            get.assert_not_called()
            self.assertEqual(target.read_text(), "previous owned fixture")

    def test_version_three_btc_uses_real_btc_payload_and_credit(self):
        now = datetime.now(UTC)
        result = builder.build_partial_feed(None, payload("BTC", now=now), now)
        self.assertEqual(result["feed_version"], 3)
        self.assertEqual([row["provider_id"] for row in result["quotes"]], ["gold_api_free_btc"])
        quote = result["quotes"][0]
        self.assertEqual((quote["currency"], quote["weight_unit"]), ("USD", "unit"))
        self.assertEqual(quote["attributions"], [{"label": "Gold API", "url": "https://gold-api.com/"}])
        self.assertEqual(result["attributions"], quote["attributions"])

    def test_legacy_crypto_and_silver_routes_never_enter_new_feed(self):
        now = datetime.now(UTC)
        old_crypto = {"bitcoin": {"usd": 90000, "last_updated_at": now.timestamp()}, "tether": {"usd": 1, "last_updated_at": now.timestamp()}}
        with self.assertRaises(ValueError):
            builder.build_partial_feed(None, old_crypto, now)
        with self.assertRaises(ValueError):
            builder.build_partial_feed({"silver_usd_oz": 50, "data_state": {"status": "fresh", "as_of": now.isoformat()}}, old_crypto, now, silver_provider="xaus_xag")

    def test_worker_rejects_unknown_destination_before_network(self):
        with patch.object(worker, "build_opener") as request:
            with self.assertRaisesRegex(RuntimeError, "permission|route"):
                worker.get_json("https://api.coingecko.com/api/v3/simple/price")
        request.assert_not_called()

    def test_custom_permissions_expiry_revocation_and_host_types_fail_closed(self):
        now = datetime.now(UTC)
        grant = {"permissions": ["collect", "store", "display", "history", "own_app_transport"], "checked_at": (now-timedelta(hours=1)).isoformat(), "expires_at": (now+timedelta(hours=1)).isoformat(), "evidence_ref": "https://gold-api.com/terms", "hosts": ["api.gold-api.com"]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"rights.json"
            manifest = {"schema_version": 1, "environment": "production", "providers": {"gold_api_free_btc": grant}}
            with patch.dict(os.environ, {"PRICING_RIGHTS_MANIFEST_PATH": str(path)}):
                path.write_text(json.dumps(manifest))
                self.assertTrue(worker.source_allowed("gold_api_free_btc", "collect"))
                self.assertTrue(worker.source_allowed("gold_api_free_btc", "history"))
                manifest["schema_version"] = True
                path.write_text(json.dumps(manifest))
                self.assertFalse(worker.source_allowed("gold_api_free_btc", "collect"))
                manifest["schema_version"] = 1
                for field, value in (("hosts", "not-api.gold-api.com.example"), ("permissions", []), ("permissions", ["history"]), ("expires_at", (now-timedelta(minutes=1)).isoformat())):
                    prior = grant[field]
                    grant[field] = value
                    path.write_text(json.dumps(manifest))
                    self.assertFalse(worker.source_allowed("gold_api_free_btc", "history"))
                    grant[field] = prior
                grant["permissions"].remove("own_app_transport")
                path.write_text(json.dumps(manifest))
                with patch.object(worker, "build_opener") as request, self.assertRaises(RuntimeError):
                    worker.get_json("https://api.gold-api.com/price/BTC")
                request.assert_not_called()
                path.write_text("{")
                self.assertFalse(worker.source_allowed("gold_api_free_btc", "collect"))
