from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Lock
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.pricing.instruments import INSTRUMENTS, get_instrument
from app.pricing.models import CanonicalQuote, CanonicalStatus
from app.pricing.operational import OperationalPricingSettings
from app.pricing.service import InstrumentPricingService


def current_quotes():
    now = datetime.now(UTC)
    return {
        key: CanonicalQuote.create(
            instrument_id=key, price=(item.minimum_price+item.maximum_price)/Decimal(2),
            status=CanonicalStatus.LIVE, primary_quote_id=1, verification_quote_ids=[],
            source_summary={"derived": False, "primary_provider_id": "bulk-read-fixture"},
            observed_at=now, canonical_at=now,
            valid_until=now+timedelta(seconds=item.operational_ttl_seconds),
            stale_at=now+timedelta(seconds=item.stale_after_seconds),
            expires_at=now+timedelta(seconds=item.expire_after_seconds),
            is_persisted=True, decision_reason="bulk-read-test",
        ) for key, item in INSTRUMENTS.items()
    }


class BulkOperationalReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_coalesced_request_keeps_fresh_policy_with_five_actual_queries(self):
        from types import SimpleNamespace
        from app.pricing.backfill import BackfillEnqueueResult, PricingBackfillQueue
        from tests.test_automatic_backfill_guard import _Redis, NOW

        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE feature_flags (key TEXT PRIMARY KEY, enabled BOOLEAN)"))
        redis = _Redis()
        operational = OperationalPricingSettings()
        queue = PricingBackfillQueue(store=SimpleNamespace(client=lambda: redis), operational=operational)
        options = {"instrument_id": "BTC_USD", "range_start": NOW-timedelta(days=1),
                   "range_end": NOW, "bucket_seconds": 900}
        with patch("app.pricing.operational.SessionLocal", self.session), \
             patch.object(queue, "enqueue", new=AsyncMock(return_value=BackfillEnqueueResult("queued", "test", 1, None))) as enqueue, \
             patch.object(operational, "_provider_rows", side_effect=AssertionError("coalesced request must not load providers")):
            await queue.enqueue_automatic(**options)
            self.calls.clear()
            result = await queue.enqueue_automatic(**options)
            self.assertEqual(result.status, "coalesced")
            # One instrument, one batched instrument override, two feature overrides and one flag.
            self.assertEqual(self.calls, Counter(instruments=1, operational_settings=4))
            self.assertEqual(enqueue.await_count, 1)
            self.setting("backfill_enabled", "BTC_USD", False)
            self.calls.clear()
            self.assertEqual((await queue.enqueue_automatic(**options)).status, "disabled")
            self.assertEqual(self.calls, Counter(instruments=1, operational_settings=2))
            self.assertEqual(enqueue.await_count, 1)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nerkhbaan-bulk-test-")
        database = Path(self.directory.name) / "bulk.sqlite"
        self.engine = create_engine(f"sqlite:///{database.as_posix()}", poolclass=QueuePool,
                                    connect_args={"check_same_thread": False})
        self.session = sessionmaker(bind=self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("""CREATE TABLE instruments (
                instrument_id TEXT PRIMARY KEY, operational_ttl_seconds INTEGER,
                stale_after_seconds INTEGER, expire_after_seconds INTEGER,
                base_anomaly_threshold_percent TEXT, maximum_dynamic_threshold_percent TEXT,
                minimum_sanity_price TEXT, maximum_sanity_price TEXT,
                importance INTEGER, enabled BOOLEAN, allow_derived_fallback BOOLEAN)"""))
            connection.execute(text("""CREATE TABLE operational_settings (
                key TEXT, scope_id TEXT, value TEXT, PRIMARY KEY (key, scope_id))"""))
            for key, item in INSTRUMENTS.items():
                connection.execute(text("""INSERT INTO instruments VALUES
                    (:id, :ttl, :stale, :expire, :base, :maximum, :low, :high,
                     :importance, :enabled, :derived)"""), {
                    "id": key, "ttl": item.operational_ttl_seconds,
                    "stale": item.stale_after_seconds, "expire": item.expire_after_seconds,
                    "base": str(item.base_anomaly_threshold_percent),
                    "maximum": str(item.maximum_dynamic_threshold_percent),
                    "low": str(item.minimum_price), "high": str(item.maximum_price),
                    "importance": item.importance, "enabled": item.enabled,
                    "derived": item.allow_derived_fallback,
                })
        self.calls, self.guard = Counter(), Lock()

        @event.listens_for(self.engine, "before_cursor_execute")
        def count(_connection, _cursor, statement, _parameters, _context, _many):
            sql = statement.upper()
            if sql.lstrip().startswith("SELECT"):
                table = "instruments" if "FROM INSTRUMENTS" in sql else "operational_settings"
                with self.guard:
                    self.calls[table] += 1

    def tearDown(self):
        self.engine.dispose()
        self.directory.cleanup()

    def setting(self, key, scope, value, *, raw=False):
        with self.engine.begin() as connection:
            connection.execute(text("INSERT OR REPLACE INTO operational_settings VALUES (:key, :scope, :value)"),
                               {"key": key, "scope": scope, "value": value if raw else json.dumps(value)})

    def update(self, sql):
        with self.engine.begin() as connection:
            connection.execute(text(sql))

    async def compare_reads(self):
        operational = OperationalPricingSettings()
        with patch("app.pricing.operational.SessionLocal", self.session):
            expected = {key: await operational.instrument(key) for key in INSTRUMENTS}
            self.calls.clear()
            actual = await operational.instruments(INSTRUMENTS)
        self.assertEqual(actual, expected)
        self.assertEqual(self.calls, Counter(instruments=1, operational_settings=1))
        return actual

    async def test_bulk_matches_individual_defaults_and_two_actual_sql_queries(self):
        await self.compare_reads()
        with patch("app.pricing.operational.SessionLocal", self.session):
            self.calls.clear()
            result = await OperationalPricingSettings().instruments(["btc_usd", " BTC_USD "])
            self.assertEqual(list(result), ["BTC_USD"])
            self.assertEqual(self.calls, Counter(instruments=1, operational_settings=1))
            self.calls.clear()
            self.assertEqual(await OperationalPricingSettings().instruments([]), {})
            self.assertEqual(self.calls, {})

    async def test_scoped_global_null_malformed_and_invalid_overrides_match(self):
        self.setting("canonical_expiry_seconds", "global", 60)
        self.setting("anomaly_threshold_percent", "global", 4)
        self.setting("canonical_expiry_seconds", "BTC_USD", 30)
        self.setting("anomaly_threshold_percent", "BTC_USD", 2)
        self.setting("canonical_expiry_seconds", "USDT_USD", None)
        self.setting("anomaly_threshold_percent", "USDT_USD", "broken-json", raw=True)
        self.setting("canonical_expiry_seconds", "XAU_USD_OZ", 0)
        self.setting("anomaly_threshold_percent", "XAG_USD_OZ", "NaN")
        actual = await self.compare_reads()
        self.assertEqual(actual["BTC_USD"].expire_after_seconds, 30)
        self.assertEqual(actual["BTC_USD"].operational_ttl_seconds, 30)
        self.assertEqual(actual["BTC_USD"].base_anomaly_threshold_percent, Decimal(2))
        self.assertEqual(actual["USDT_USD"], get_instrument("USDT_USD"))
        self.assertEqual(actual["XAU_USD_OZ"], get_instrument("XAU_USD_OZ"))
        self.assertEqual(actual["XAG_USD_OZ"], get_instrument("XAG_USD_OZ"))

    async def test_invalid_row_missing_row_disabled_and_safety_ceiling_match(self):
        self.setting("canonical_expiry_seconds", "global", 20)
        self.update("UPDATE instruments SET enabled=0 WHERE instrument_id='BTC_USD'")
        self.update("UPDATE instruments SET operational_ttl_seconds=0 WHERE instrument_id='USDT_USD'")
        self.update("UPDATE instruments SET allow_derived_fallback=1 WHERE instrument_id='GOLD_24K_TOMAN_GRAM'")
        self.update("DELETE FROM instruments WHERE instrument_id='XAU_USD_OZ'")
        actual = await self.compare_reads()
        self.assertFalse(actual["BTC_USD"].enabled)
        self.assertEqual(actual["USDT_USD"], get_instrument("USDT_USD"))
        self.assertFalse(actual["GOLD_24K_TOMAN_GRAM"].allow_derived_fallback)
        self.assertEqual(actual["XAU_USD_OZ"].expire_after_seconds, 20)

    async def test_read_failure_uses_same_defaults_without_hiding_bulk_adapter_errors(self):
        operational = OperationalPricingSettings()
        with patch.object(operational, "_instrument_row", side_effect=RuntimeError("read_failed")), \
             patch.object(operational, "_instrument_rows", side_effect=RuntimeError("read_failed")), \
             patch.object(operational, "_instrument_override_rows", return_value=[
                 {"key": "canonical_expiry_seconds", "scope_id": "global", "value": 10}]):
            self.assertEqual(await operational.instruments(["BTC_USD"]),
                             {"BTC_USD": await operational.instrument("BTC_USD")})
        with patch("app.pricing.operational.SessionLocal", self.session), \
             patch.object(operational, "_setting_row", side_effect=RuntimeError("settings_failed")), \
             patch.object(operational, "_instrument_override_rows", side_effect=RuntimeError("settings_failed")):
            self.assertEqual(await operational.instruments(["BTC_USD"]),
                             {"BTC_USD": await operational.instrument("BTC_USD")})

    async def test_aggregate_and_list_each_use_only_one_policy_batch_and_immediate_updates(self):
        store, history = AsyncMock(), AsyncMock()
        store.get_all_canonical.return_value = {}
        history.latest_all.side_effect = lambda: current_quotes()
        service = InstrumentPricingService(store=store, history=history, operational=OperationalPricingSettings())
        with patch("app.pricing.operational.SessionLocal", self.session):
            self.calls.clear()
            self.assertEqual(len(await service.get_all_canonical()), len(INSTRUMENTS))
            self.assertEqual(self.calls, Counter(instruments=1, operational_settings=1))
            self.calls.clear()
            self.assertEqual(len(await service.list_instruments()), len(INSTRUMENTS))
            self.assertEqual(self.calls, Counter(instruments=1, operational_settings=1))
            self.setting("canonical_expiry_seconds", "BTC_USD", 20)
            self.update("UPDATE instruments SET enabled=0 WHERE instrument_id='USDT_USD'")
            self.calls.clear()
            snapshot = await service.get_all_canonical()
            self.assertNotIn("USDT_USD", snapshot)
            btc = snapshot["BTC_USD"]
            self.assertEqual(btc.valid_until, btc.observed_at+timedelta(seconds=20))
            self.assertEqual(self.calls, Counter(instruments=1, operational_settings=1))
        self.assertEqual(history.latest_all.await_count, 3)

    async def test_unknown_snapshot_identity_does_not_hide_known_quotes(self):
        quotes = current_quotes()
        quotes["UNKNOWN"] = quotes["BTC_USD"]
        quotes["btc_usd"] = quotes["BTC_USD"]
        store, history = AsyncMock(), AsyncMock()
        store.get_all_canonical.return_value = quotes
        history.latest_all.return_value = {}
        service = InstrumentPricingService(store=store, history=history, operational=OperationalPricingSettings())
        with patch("app.pricing.operational.SessionLocal", self.session):
            snapshot = await service.get_all_canonical()
        self.assertNotIn("UNKNOWN", snapshot)
        self.assertIn("BTC_USD", snapshot)
        self.assertIn("btc_usd", snapshot)

    async def test_legacy_adapter_supported_but_explicit_bulk_errors_surface(self):
        store, history, operational = AsyncMock(), AsyncMock(), AsyncMock()
        store.get_all_canonical.return_value = current_quotes()
        history.latest_all.return_value = {}
        operational.instrument.side_effect = get_instrument
        service = InstrumentPricingService(store=store, history=history, operational=operational)
        self.assertEqual(len(await service.get_all_canonical()), len(INSTRUMENTS))
        self.assertEqual(operational.instrument.await_count, len(INSTRUMENTS))

        class BrokenBulk:
            async def instruments(self, _ids):
                raise RuntimeError("bulk_contract_failed")
            async def instrument(self, _key):
                raise AssertionError("Must not mask the bulk failure")

        service.operational = BrokenBulk()
        with self.assertRaisesRegex(RuntimeError, "bulk_contract_failed"):
            await service.get_all_canonical()

        class InvalidBulk(BrokenBulk):
            async def instruments(self, _ids):
                return []

        service.operational = InvalidBulk()
        with self.assertRaisesRegex(TypeError, "mapping"):
            await service.get_all_canonical()


if __name__ == "__main__":
    unittest.main()
