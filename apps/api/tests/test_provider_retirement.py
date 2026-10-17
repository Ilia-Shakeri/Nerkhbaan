from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.admin.routers import providers as admin_providers
from app.pricing import rights
from app.pricing.compatibility import LegacyPricingAdapter
from app.pricing.contracts import provider_contract_inventory
from app.pricing.health import pricing_health_service
from app.pricing.operational import OperationalPricingSettings
from app.pricing.registry import (
    PROVIDERS,
    PROVIDERS_BY_INSTRUMENT,
    RETIRED_PROVIDERS,
    _provider,
)


class ProviderRetirementTests(unittest.TestCase):
    def test_retired_definitions_stay_available_only_for_legacy_provenance(self):
        self.assertEqual(len(RETIRED_PROVIDERS), 9)
        self.assertTrue(all(provider.source_family == "servix" and not provider.enabled
                            for provider in RETIRED_PROVIDERS.values()))
        self.assertTrue(set(PROVIDERS).isdisjoint(RETIRED_PROVIDERS))
        self.assertTrue(all(provider.provider_id not in RETIRED_PROVIDERS
                            for providers in PROVIDERS_BY_INSTRUMENT.values() for provider in providers))

    def test_environment_enable_flag_cannot_revive_a_retired_family(self):
        retired = RETIRED_PROVIDERS["servix_btc_usd"]
        with patch.dict(os.environ, {"PRICING_PROVIDER_SERVIX_BTC_USD_ENABLED": "true"}):
            candidate = _provider(
                retired.provider_id, retired.display_name, retired.instrument_id, retired.role,
                retired.priority, str(retired.trust_score), retired.url, retired.parser_id,
                retired.parser_version, retired.operational_ttl_seconds,
                source_family=retired.source_family, enabled_default=True,
            )
        self.assertFalse(candidate.enabled)

    def test_startup_requirements_do_not_ask_for_retired_credentials(self):
        result = LegacyPricingAdapter.startup_checks()
        all_keys = result["required_env_keys"] + result["optional_env_keys"]
        self.assertNotIn("servix_api_key", all_keys)

    def test_live_canaries_and_contract_inventory_omit_retired_routes(self):
        self.assertTrue(all(row["provider_id"] not in RETIRED_PROVIDERS
                            for row in pricing_health_service.provider_canaries()))
        self.assertTrue(set(provider_contract_inventory()["providers"]).isdisjoint(RETIRED_PROVIDERS))

    def test_old_admin_database_rows_are_omitted_without_database_mutations(self):
        retired_row = {"provider_id": "servix_btc_usd", "enabled": True,
                       "required_key_name": "servix_api_key"}
        active_row = {"provider_id": "coingecko_btc", "enabled": True}
        with patch.object(admin_providers, "safe_rows", side_effect=([
                retired_row, active_row], [])):
            rows = admin_providers._db_providers(object())
        self.assertEqual([row["provider_id"] for row in rows], ["coingecko_btc"])
        self.assertTrue(retired_row["enabled"])
        self.assertEqual(retired_row["required_key_name"], "servix_api_key")

    def test_retirement_does_not_revoke_permitted_old_history(self):
        provider_id = "servix_btc_usd"
        now = datetime.now(UTC)
        grant = {provider_id: {
            "permissions": ["display", "history"],
            "checked_at": (now-timedelta(hours=1)).isoformat(),
            "expires_at": (now+timedelta(days=1)).isoformat(),
            "evidence_ref": "https://fixture.example.invalid/archive-permission",
            "hosts": ["servix.cc"],
        }}
        with patch.object(rights, "grants", return_value=grant), patch.object(rights, "enforced", return_value=True):
            self.assertTrue(rights.provider_allowed(provider_id, "history"))
            self.assertTrue(rights.canonical_allowed({
                "provider_ids": [provider_id], "primary_provider_id": provider_id,
            }, "history"))


class ProviderRetirementOperationalTests(unittest.IsolatedAsyncioTestCase):
    async def test_stored_enable_overrides_cannot_return_retired_candidates(self):
        operational = OperationalPricingSettings()
        old_rows = [{"provider_id": "servix_btc_usd", "provider_enabled": True, "config_enabled": True}]
        old_overrides = [{"key": "provider.config", "scope_id": "servix_btc_usd",
                          "value": {"enabled": True}}]
        with patch.object(operational, "_provider_rows", return_value=old_rows):
            with patch.object(operational, "_provider_override_rows", return_value=old_overrides) as overrides:
                providers = await operational.providers_for("BTC_USD")
        self.assertTrue(providers)
        self.assertTrue(all(provider.provider_id not in RETIRED_PROVIDERS for provider in providers))
        self.assertTrue(set(overrides.call_args.args[0]).isdisjoint(RETIRED_PROVIDERS))


if __name__ == "__main__":
    unittest.main()
