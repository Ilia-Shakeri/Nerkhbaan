from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from threading import Lock
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.pricing.models import ProviderRole
from app.pricing.operational import OperationalPricingSettings
from app.pricing.registry import PROVIDERS_BY_INSTRUMENT


class ProviderPolicyBulkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nerkhbaan-provider-bulk-")
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name) / "policies.sqlite"
        self.engine = create_engine(f"sqlite:///{path.as_posix()}", poolclass=QueuePool,
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(bind=self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("""CREATE TABLE operational_settings (
                key TEXT, scope_id TEXT, value TEXT, PRIMARY KEY (key, scope_id))"""))
            connection.execute(text("""CREATE TABLE pricing_providers (
                provider_id TEXT PRIMARY KEY, role TEXT, priority INTEGER, trust_score TEXT,
                enabled BOOLEAN, requests_per_minute INTEGER, requests_per_hour INTEGER,
                requests_per_day INTEGER, reserved_anomaly_requests INTEGER,
                reserved_fallback_requests INTEGER, minimum_interval_seconds INTEGER,
                cooldown_after_429_seconds INTEGER, estimated_request_cost TEXT)"""))
            connection.execute(text("""CREATE TABLE instrument_provider_configs (
                instrument_id TEXT, provider_id TEXT, role TEXT, priority INTEGER,
                trust_score TEXT, enabled BOOLEAN, operational_ttl_seconds INTEGER)"""))
            for instrument_id in ("BTC_USD", "BTC_TOMAN"):
                for provider in PROVIDERS_BY_INSTRUMENT[instrument_id]:
                    values = {"id": provider.provider_id, "role": provider.role.value,
                              "priority": provider.priority, "trust": str(provider.trust_score)}
                    values.update({name: getattr(provider.budget, name) for name in (
                        "requests_per_minute", "requests_per_hour", "requests_per_day",
                        "reserved_anomaly_requests", "reserved_fallback_requests",
                        "minimum_interval_seconds", "cooldown_after_429_seconds")})
                    values["cost"] = str(provider.budget.estimated_request_cost)
                    connection.execute(text("""INSERT INTO pricing_providers VALUES (
                        :id, :role, :priority, :trust, 1, :requests_per_minute,
                        :requests_per_hour, :requests_per_day, :reserved_anomaly_requests,
                        :reserved_fallback_requests, :minimum_interval_seconds,
                        :cooldown_after_429_seconds, :cost)"""), values)
                    connection.execute(text("""INSERT INTO instrument_provider_configs VALUES
                        (:instrument, :id, :role, :priority, :trust, 1, :ttl)"""),
                        {**values, "instrument": instrument_id, "ttl": provider.operational_ttl_seconds})
        self.calls, self.guard = Counter(), Lock()
        @event.listens_for(self.engine, "before_cursor_execute")
        def count(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                table = "settings" if "FROM operational_settings" in statement else "providers"
                with self.guard:
                    self.calls[table] += 1
        patcher = patch("app.pricing.operational.SessionLocal", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.operational = OperationalPricingSettings()

    def setting(self, key, scope, value, *, raw=False):
        with self.engine.begin() as connection:
            connection.execute(text("INSERT OR REPLACE INTO operational_settings VALUES (:key, :scope, :value)"),
                               {"key": key, "scope": scope, "value": value if raw else json.dumps(value)})

    async def read(self, instrument="BTC_USD", *roles):
        self.calls.clear()
        values = await self.operational.providers_for(instrument, *roles)
        self.assertEqual(self.calls, Counter(providers=1, settings=1))
        return {provider.provider_id: provider for provider in values}

    async def test_global_scoped_provider_and_budget_policy_use_two_actual_queries(self):
        self.setting("provider.config", "global", {"priority": 8, "requests_per_hour": 22})
        self.setting("provider.config", "coingecko_btc", {
            "priority": 2, "role": "fallback", "operational_ttl_seconds": 30,
            "requests_per_hour": 15})
        self.setting("provider_budget_requests_per_hour", "global", 19)
        self.setting("provider_budget_requests_per_hour", "coingecko_btc", 3)
        values = await self.read()
        self.assertEqual(values["coingecko_btc"].priority, 2)
        self.assertEqual(values["coingecko_btc"].role, ProviderRole.FALLBACK)
        self.assertEqual(values["coingecko_btc"].operational_ttl_seconds, 30)
        self.assertEqual(values["coingecko_btc"].budget.requests_per_hour, 3)
        self.assertEqual(values["coinbase_btc_usd"].priority, 8)
        self.assertEqual(values["coinbase_btc_usd"].budget.requests_per_hour, 19)
        scoped = await self.read("BTC_USD", ProviderRole.FALLBACK)
        self.assertTrue(all(value.role == ProviderRole.FALLBACK for value in scoped.values()))

    async def test_scoped_null_and_malformed_values_shadow_globals(self):
        self.setting("provider.config", "global", {"enabled": False})
        self.setting("provider.config", "coingecko_btc", "bad-json", raw=True)
        self.setting("provider_budget_requests_per_hour", "global", 0)
        self.setting("provider_budget_requests_per_hour", "coingecko_btc", None)
        values = await self.read()
        self.assertTrue(values["coingecko_btc"].enabled)
        original = next(item for item in PROVIDERS_BY_INSTRUMENT["BTC_USD"] if item.provider_id == "coingecko_btc")
        self.assertEqual(values["coingecko_btc"].budget.requests_per_hour, original.budget.requests_per_hour)
        self.assertFalse(values["coinbase_btc_usd"].enabled)
        self.assertEqual(values["coinbase_btc_usd"].budget.requests_per_hour, 0)

    async def test_invalid_policy_disables_only_one_source_and_quarantine_is_ceiling(self):
        self.setting("provider.config", "coingecko_btc", {"trust_score": "NaN"})
        values = await self.read()
        self.assertFalse(values["coingecko_btc"].enabled)
        self.assertTrue(values["coinbase_btc_usd"].enabled)
        self.setting("provider.config", "tetherland_btc", {"enabled": True})
        toman = await self.read("BTC_TOMAN")
        self.assertFalse(toman["tetherland_btc"].enabled)

    async def test_policy_failure_uses_defaults_but_keeps_database_disable(self):
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE pricing_providers SET enabled = 0 WHERE provider_id = 'coingecko_btc'"))
        with patch.object(self.operational, "_provider_override_rows", side_effect=OSError("test unavailable")):
            values = await self.operational.providers_for("BTC_USD")
        by_id = {item.provider_id: item for item in values}
        self.assertFalse(by_id["coingecko_btc"].enabled)
        self.assertTrue(by_id["coinbase_btc_usd"].enabled)


if __name__ == "__main__":
    unittest.main()
