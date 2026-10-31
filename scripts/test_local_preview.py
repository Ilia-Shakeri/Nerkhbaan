"""Safety and data contracts for the keyless, local review launcher."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
os.environ.setdefault("JWT_SECRET_KEY", "local-preview-contract-test-not-a-real-key-000000")

from browser_fixture_database import validate_local_origin
from local_preview import base_environment, database_url, preview_environment
from local_preview_data import ASSETS, REVISION, history, prices, references
from app.schemas import PricesResponse, PriceHistoryResponse, ReferenceRatesResponse


class LocalPreviewTests(unittest.TestCase):
    def test_parent_credentials_are_not_inherited(self):
        with patch.dict(os.environ, {"DATABASE_URL": "production", "SMTP_PASSWORD": "private",
                                     "TELEGRAM_BOT_TOKEN": "private", "VITE_VAPID_PUBLIC_KEY": "private"}):
            env = base_environment()
        for key in ["DATABASE_URL", "SMTP_PASSWORD", "TELEGRAM_BOT_TOKEN", "VITE_VAPID_PUBLIC_KEY"]:
            self.assertNotIn(key, env)

    def test_only_loopback_origins(self):
        self.assertEqual(validate_local_origin("http://127.0.0.1:43188"), "http://127.0.0.1:43188")
        for value in ["http://0.0.0.0:43188", "https://example.com:443", "http://user@localhost:9",
                      "http://localhost:9/path", "http://localhost:9?query=1", "http://localhost:9#x",
                      "http://localhost", "http://127.0.0.1.example.com:9"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_local_origin(value)

    def test_environment_is_explicit_and_keyless(self):
        value = {"password": "local-password", "jwt": "local-jwt", "id": "a"*32}
        env = preview_environment(value)
        self.assertIn("@127.0.0.1:55449/nerkhbaan_browser_preview", database_url(value))
        self.assertEqual(env["BACKGROUND_TASKS_ENABLED"], "false")
        self.assertEqual(env["VITE_VAPID_PUBLIC_KEY"], "")
        self.assertEqual(env["REDIS_URL"], "")
        self.assertNotEqual(env["BROWSER_TEST_ADMIN_ORIGIN"], env["BROWSER_TEST_PUBLIC_ORIGIN"])
        self.assertNotEqual(env["AUTH_COOKIE_NAME"], env["ADMIN_COOKIE_NAME"])
        self.assertEqual(env["VITE_ADMIN_API_URL"], "http://127.0.0.1:43187/api/admin")

    def test_synthetic_prices_and_history_match_real_response_contracts(self):
        payload = PricesResponse.model_validate(prices())
        self.assertEqual(payload.rights_revision, REVISION)
        self.assertEqual(len(payload.assets), 4)
        for asset in payload.assets:
            self.assertEqual(asset.usd_status, "preview")
            self.assertTrue(asset.usd_source_summary["preview"])
            self.assertIsNotNone(asset.unit_usd)
            self.assertIsNotNone(asset.unit_toman)
        for asset in ASSETS:
            for timeframe in ["1h", "24h", "7d", "30d", "1y"]:
                data = PriceHistoryResponse.model_validate(history(asset, timeframe))
                self.assertEqual(len(data.points), 60)
                self.assertEqual(data.points, sorted(data.points, key=lambda p: p.timestamp))
        with self.assertRaises(ValueError):
            history("unknown", "30d")
        with self.assertRaises(ValueError):
            history("gold", "unknown")

    def test_references_are_unavailable_not_fabricated(self):
        response = ReferenceRatesResponse.model_validate(references())
        self.assertEqual(len(response.references), 3)
        for item in response.references:
            self.assertEqual(item.status, "unavailable_reference")
            self.assertIsNone(item.current.price)
            self.assertEqual(item.history, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
