from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

spec = importlib.util.spec_from_file_location("source_key_plan", Path(__file__).resolve().parents[3] / "scripts/iranian_provider_plan.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IranianKeyPlanTests(unittest.TestCase):
    def test_key_presence_and_contract_gaps_never_include_credential_value(self):
        secret = "private-test-key-never-in-output"
        result = module.plan(SimpleNamespace(nerkh_io_api_key=secret))
        encoded = json.dumps(result)
        self.assertNotIn(secret, encoded)
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["database_or_redis_connections"], 0)
        metals = next(row for row in result["routes"] if row["provider_id"] == "nerkh_io_gold24")
        self.assertTrue(metals["key_present"])
        self.assertFalse(metals["configuration_present"])
        self.assertIn("NERKH_IO_GOLD_UNIT", metals["missing_contract_variables"])

    def test_nerkh_alias_is_reported_without_exposing_it(self):
        result = module.plan(SimpleNamespace(nerkh_io_api_key="alias-test-key", nerkh_io_gold_unit="TOMAN"))
        row = next(row for row in result["routes"] if row["provider_id"] == "nerkh_io_gold24")
        self.assertTrue(row["key_present"])
        self.assertIn("NERKH_IO_API_KEY", row["key_variables"])
        self.assertNotIn("alias-test-key", json.dumps(result))

    def test_registered_physical_archives_remain_separate_from_operational_coverage(self):
        result = module.plan(SimpleNamespace())
        self.assertNotIn("SILVER_925_TOMAN_GRAM", result["instruments_without_iranian_history_route"])
        self.assertNotIn("SILVER_999_TOMAN_GRAM", result["instruments_without_iranian_history_route"])
        self.assertTrue(any(row["provider_id"] == "gta_silver925_toman" for row in result["routes"]))
        self.assertTrue(all(row["scope"] == "catalogue_only_not_a_price_or_rights_proof" for row in result["routes"]))

    def test_catalogue_budget_is_not_presented_as_effective_account_quota(self):
        result = module.plan(SimpleNamespace())
        self.assertEqual(result["budget_scope"], "catalogue_only")
        self.assertEqual(result["effective_runtime_budget"], "unknown_not_read")
        self.assertFalse(result["account_quota_verified"])
        self.assertNotIn("servix_budget", result)
        self.assertFalse(any(row["provider_id"].startswith("servix_") for row in result["routes"]))


if __name__ == "__main__":
    unittest.main()
