from __future__ import annotations

import asyncio
import os
import re
import unittest
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "reference-test-key-not-for-runtime-0000000000000")

from sqlalchemy import MetaData, create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.pricing import rights
from app.pricing.db_models import ReferenceRateRecord
from app.pricing.reference_rates import (
    HISTORY_PROVIDER_ID, REFERENCE_IDS, SNAPSHOT_PROVIDER_ID,
    build_reference_history, build_reference_snapshot,
)
from app.pricing.reference_repository import ReferenceRateRepository

if __package__:
    from .test_pricing_rights_postgres import _OwnedPostgresFixture
else:
    from test_pricing_rights_postgres import _OwnedPostgresFixture


TEST_URL = os.getenv("TEST_DATABASE_URL")
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
GOLD, BTC, USDT = REFERENCE_IDS


def _owned_test_url(value):
    url = make_url(value)
    markers = set(re.split(r"[_-]+", (url.database or "").lower()))
    if (url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or markers.isdisjoint({"test", "ci"})
            or {key.lower() for key in url.query} & {"host", "hostaddr", "port", "dbname", "database", "service", "servicefile", "options"}):
        raise ValueError("Only an explicit loopback named test/CI PostgreSQL fixture is permitted")
    return url


class ReferenceFixtureBoundaryTests(unittest.TestCase):
    def test_connection_guard_refuses_remote_or_production_database_names(self):
        for value in ("postgresql://user:unused@remote.invalid/nerkhbaan_ci",
                      "postgresql://user:unused@127.0.0.1/production",
                      "postgresql://user:unused@127.0.0.1/testimonial",
                      "postgresql://user:unused@127.0.0.1/reference_ci?host=remote.invalid",
                      "postgresql://user:unused@127.0.0.1/reference_ci?dbname=production",
                      "postgresql:///nerkhbaan_ci", "sqlite:///:memory:"):
            with self.subTest(kind=value.split(":", 1)[0]), self.assertRaises(ValueError):
                _owned_test_url(value)
        self.assertEqual(_owned_test_url("postgresql://user:unused@127.0.0.1/reference_ci").host, "127.0.0.1")


@unittest.skipUnless(TEST_URL, "Requires an explicitly owned loopback test PostgreSQL database")
class ReferenceRepositoryPostgresTests(_OwnedPostgresFixture, unittest.TestCase):
    owned_table_names = ("pricing_reference_records",)

    @classmethod
    def setUpClass(cls):
        url = _owned_test_url(TEST_URL)
        cls.schema = "reference_repository_test_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, hide_parameters=True)
        cls.public_fingerprint = cls._public_fingerprint()
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            cls.timescale_available = connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')")).scalar_one()
            if connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                                  {"schema": cls.schema}).scalar_one():
                raise AssertionError("Refusing an existing fixture namespace")
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        try:
            cls.engine = create_engine(url, hide_parameters=True,
                connect_args={"options": f"-csearch_path={cls.schema},public"})
            cls.sessions = sessionmaker(bind=cls.engine)
            with cls.engine.connect() as connection:
                if connection.execute(text("SELECT current_schema()")).scalar_one() != cls.schema:
                    raise AssertionError("Refusing DDL outside the owned namespace")
            metadata = MetaData(schema=cls.schema)
            ReferenceRateRecord.__table__.to_metadata(metadata, schema=cls.schema)
            metadata.create_all(cls.engine)
            cls._install_ownership_guard()
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        if cls._public_fingerprint() != cls.public_fingerprint:
            raise AssertionError("Existing public reference data changed during isolated tests")
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        try:
            if not re.fullmatch(r"reference_repository_test_[0-9a-f]{32}", cls.schema):
                raise AssertionError("Refusing cleanup outside the owned UUID namespace")
            with cls.admin_engine.begin() as connection:
                owner = connection.execute(text("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=:schema"),
                                           {"schema": cls.schema}).scalar_one()
                if owner != connection.execute(text("SELECT current_user")).scalar_one():
                    raise AssertionError("Refusing cleanup of another namespace owner")
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
                cls.owned_schema_removed = not connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"),
                    {"schema": cls.schema}).scalar_one()
            cls.public_unchanged = cls._public_fingerprint() == cls.public_fingerprint
            if not cls.owned_schema_removed or not cls.public_unchanged:
                raise AssertionError("Owned cleanup or public preservation failed")
        finally:
            cls.admin_engine.dispose()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        self.addCleanup(self._assert_public_unchanged)
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        self.enterContext(patch.object(settings, "pricing_rights_manifest_path", None))
        now = datetime.now(UTC)
        grant = {"permissions": ["collect", "store", "display", "history", "derive"],
                 "checked_at": (now - timedelta(hours=1)).isoformat(),
                 "expires_at": (now + timedelta(days=1)).isoformat(),
                 "evidence_ref": "https://fixture.example.invalid/reference-permission",
                 "hosts": ["nerkh.jahankhahan.shop"]}
        self.grants = {key: deepcopy(grant) for key in (SNAPSHOT_PROVIDER_ID, HISTORY_PROVIDER_ID)}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.repo = ReferenceRateRepository(self.sessions)
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM pricing_reference_records"))

    def snapshots(self, *, clock="15:28", gold=35_000_000, received=NOW):
        return build_reference_snapshot({"date": "1405/07/25", "time": clock, "rates": {
            "gold24": gold, "bitcoin": 20_000_000_000, "tether": 275_000, "dollar": 250_000,
        }}, received_at=received, now=received)

    def gold(self, **kwargs):
        return next(item for item in self.snapshots(**kwargs) if item["instrument_id"] == GOLD)

    def histories(self, *, many=False):
        days = ([f"1405/{month:02}/{day:02}" for month, length in ((5, 31), (6, 31), (7, 18))
                 for day in range(1, length + 1)] if many else ["1405/07/23", "1405/07/24"])
        payload = {"updated": "1405/07/24", "series": [
            {"key": key, "name": key, "days": [[day, price] for day in days]}
            for key, price in (("gold24", 35_000_000), ("bitcoin", 20_000_000_000),
                               ("tether", 275_000), ("dollar", 250_000))]}
        with patch("app.pricing.reference_rates.utc_now", return_value=NOW):
            return build_reference_history(payload, range_start=NOW - timedelta(days=180), range_end=NOW)

    def count(self):
        with self.sessions() as db:
            return db.scalar(text("SELECT count(*) FROM pricing_reference_records"))

    def stored(self, reference_id=GOLD, kind="snapshot", slot="current"):
        with self.sessions() as db:
            return db.scalar(select(ReferenceRateRecord).where(
                ReferenceRateRecord.reference_id == reference_id,
                ReferenceRateRecord.record_kind == kind, ReferenceRateRecord.slot == slot))

    def load(self, start=NOW - timedelta(days=180), end=NOW):
        return asyncio.run(self.repo.load(start, end))

    def test_owned_tables_shadow_public_and_dml_guard_blocks_fallthrough(self):
        with self.engine.begin() as connection:
            self._assert_owned_tables(connection)
            with self.assertRaisesRegex(AssertionError, "explicitly public mutation"):
                connection.exec_driver_sql("DELETE FROM public.pricing_reference_records")
            connection.exec_driver_sql("SET LOCAL search_path = public")
            with self.assertRaisesRegex(AssertionError, "explicitly owned test schema"):
                connection.exec_driver_sql("DELETE FROM pricing_reference_records")
        self._assert_public_unchanged()

    def test_current_replay_ignores_display_age_status_and_receipt_without_freshening(self):
        original = self.gold()
        self.assertEqual(asyncio.run(self.repo.save_snapshot([original], NOW)), 1)
        stored = self.stored()
        replay = deepcopy(original)
        replay.update(age_seconds=9999, status="delayed_reference", received_at=(NOW + timedelta(minutes=2)).isoformat(),
                      checked_at=(NOW + timedelta(minutes=2)).isoformat(), persistence_status="persisted")
        self.assertEqual(asyncio.run(self.repo.save_snapshot([replay], NOW + timedelta(minutes=2))), 0)
        after = self.stored()
        self.assertEqual(after.payload_hash, stored.payload_hash)
        self.assertEqual(after.received_at, NOW)
        self.assertEqual(after.payload, original)
        self.assertEqual(self.count(), 1)

    def test_older_source_or_older_http_receipt_cannot_replace_current_observation(self):
        original = self.gold(clock="15:28")
        asyncio.run(self.repo.save_snapshot([original], NOW))
        old_source = self.gold(clock="15:27", gold=36_000_000, received=NOW + timedelta(minutes=1))
        self.assertEqual(asyncio.run(self.repo.save_snapshot([old_source], NOW + timedelta(minutes=1))), 0)
        old_receipt = self.gold(clock="15:29", gold=36_000_000, received=NOW - timedelta(seconds=30))
        self.assertEqual(asyncio.run(self.repo.save_snapshot([old_receipt], NOW - timedelta(seconds=30))), 0)
        self.assertEqual(self.stored().payload, original)

    def test_newer_source_and_receipt_replace_current_without_duplicate_slots(self):
        asyncio.run(self.repo.save_snapshot([self.gold()], NOW))
        newer = self.gold(clock="15:29", gold=36_000_000, received=NOW + timedelta(minutes=1))
        self.assertEqual(asyncio.run(self.repo.save_snapshot([newer], NOW + timedelta(minutes=1))), 1)
        self.assertEqual(self.stored().payload, newer)
        self.assertEqual(self.count(), 1)

    def test_daily_correction_keeps_exact_day_slot_and_range_does_not_include_next_day(self):
        histories = self.histories()
        self.assertEqual(asyncio.run(self.repo.save_history(histories, NOW)), 6)
        correction = deepcopy(histories[GOLD][-1])
        correction.update(price=35_000_001.0, price_decimal="35000001")
        correction["inputs"][0].update(price=35_000_001.0, price_decimal="35000001")
        self.assertEqual(asyncio.run(self.repo.save_history({GOLD: [correction]}, NOW + timedelta(minutes=1))), 1)
        self.assertEqual(self.count(), 6)
        point = self.stored(GOLD, "history", "1405/07/24")
        self.assertEqual(point.payload["source_date"], "1405/07/24")
        self.assertEqual(point.payload["price_decimal"], "35000001")
        boundary = datetime.fromisoformat(correction["timestamp"])
        selected = self.load(boundary, boundary + timedelta(days=1))["histories"][GOLD]
        self.assertEqual(selected, [correction])
        earlier = self.load(boundary - timedelta(days=1), boundary)["histories"][GOLD]
        self.assertEqual([row["source_date"] for row in earlier], ["1405/07/23"])

    def test_unknown_physical_and_global_ids_never_enter_reference_store(self):
        for identifier in ("GOLD_24K_TOMAN_GRAM", "BTC_USD", "USDT_USD", "OTHER_REFERENCE"):
            row = {**self.gold(), "instrument_id": identifier}
            self.assertEqual(asyncio.run(self.repo.save_snapshot([row], NOW)), 0)
            self.assertEqual(asyncio.run(self.repo.save_history({identifier: self.histories()[GOLD]}, NOW)), 0)
        with self.assertRaises(ValueError):
            asyncio.run(self.repo.save_history({BTC: self.histories()[GOLD]}, NOW))
        self.assertEqual(self.count(), 0)

    def test_both_record_kinds_reject_physical_or_global_contract_metadata(self):
        for change in ({"market": "global_exchange"}, {"region": "global"},
                       {"physical_purity_confirmed": True}, {"purity": "0.9999"}):
            for kind in ("snapshot", "history"):
                with self.subTest(kind=kind, change=change):
                    row = {**(self.gold() if kind == "snapshot" else self.histories()[GOLD][0]), **change}
                    with self.assertRaises(ValueError):
                        asyncio.run(self.repo.save_snapshot([row], NOW) if kind == "snapshot"
                                    else self.repo.save_history({GOLD: [row]}, NOW))
        self.assertEqual(self.count(), 0)

    def test_derive_revocation_hides_only_usd_references_without_deleting_rows(self):
        asyncio.run(self.repo.save_snapshot(self.snapshots(), NOW))
        asyncio.run(self.repo.save_history(self.histories(), NOW))
        for grant in self.grants.values():
            grant["permissions"].remove("derive")
        result = self.load()
        self.assertEqual([row["instrument_id"] for row in result["snapshots"]], [GOLD])
        self.assertEqual(set(result["histories"]), {GOLD})
        self.assertEqual(len(result["histories"][GOLD]), 2)
        self.assertEqual(self.count(), 9)

    def test_collect_revocation_keeps_permitted_existing_history_visible(self):
        asyncio.run(self.repo.save_history(self.histories(), NOW))
        self.grants[HISTORY_PROVIDER_ID]["permissions"].remove("collect")
        self.assertEqual(asyncio.run(self.repo.save_history(self.histories(), NOW)), 0)
        self.assertTrue(all(len(rows) == 2 for rows in self.load()["histories"].values()))
        self.assertEqual(self.count(), 6)

    def test_display_revocation_hides_existing_data_without_erasing_it(self):
        asyncio.run(self.repo.save_snapshot(self.snapshots(), NOW))
        asyncio.run(self.repo.save_history(self.histories(), NOW))
        for grant in self.grants.values():
            grant["permissions"].remove("display")
        result = self.load()
        self.assertEqual(result["snapshots"], [])
        self.assertTrue(all(not rows for rows in result["histories"].values()))
        self.assertEqual(self.count(), 9)

    def test_revocation_after_first_bulk_sql_rolls_back_all_uncommitted_rows(self):
        asyncio.run(self.repo.save_snapshot([self.gold()], NOW))
        sql_batches = []

        def revoke(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("INSERT INTO PRICING_REFERENCE_RECORDS"):
                sql_batches.append(statement)
                self.grants[HISTORY_PROVIDER_ID]["permissions"].remove("store")

        event.listen(self.engine, "after_cursor_execute", revoke)
        self.addCleanup(event.remove, self.engine, "after_cursor_execute", revoke)
        histories = self.histories(many=True)
        self.assertEqual(sum(map(len, histories.values())), 240)
        with self.assertRaises(PermissionError):
            asyncio.run(self.repo.save_history(histories, NOW))
        self.assertEqual(len(sql_batches), 1)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.stored().payload["instrument_id"], GOLD)

    def test_source_clock_future_or_naive_and_future_receipt_cannot_write(self):
        for value in ((NOW + timedelta(seconds=31)).isoformat(), NOW.replace(tzinfo=None).isoformat(), "bad-clock"):
            row = {**self.gold(), "observed_at": value}
            with self.subTest(value=value), self.assertRaises(ValueError):
                asyncio.run(self.repo.save_snapshot([row], NOW))
        tomorrow = datetime.now(UTC) + timedelta(days=1)
        row = {**self.gold(), "observed_at": tomorrow.isoformat()}
        with self.assertRaises(ValueError):
            asyncio.run(self.repo.save_snapshot([row], tomorrow))
        with self.assertRaises(ValueError):
            asyncio.run(self.repo.save_snapshot([self.gold()], NOW.replace(tzinfo=None)))
        self.assertEqual(self.count(), 0)

    def test_history_rejects_wrong_day_bucket_calendar_precision_and_open_day(self):
        original = self.histories()[GOLD][0]
        for change in ({"timestamp": NOW.isoformat()}, {"source_date": "1405/07/24"},
                       {"source_date": "1405/99/99"}, {"source_timezone": "UTC"},
                       {"source_calendar": "gregorian"}, {"timestamp_precision": "instant"},
                       {"timestamp_role": "trade"}, {"source_observation_time_known": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                asyncio.run(self.repo.save_history({GOLD: [{**original, **change}]}, NOW))
        self.assertEqual(self.count(), 0)

    def test_conflicting_duplicate_points_abort_the_entire_import(self):
        original = self.histories()[GOLD][0]
        changed = {**original, "price": 35_000_001.0, "price_decimal": "35000001"}
        with self.assertRaises(ValueError):
            asyncio.run(self.repo.save_history({GOLD: [original, changed]}, NOW))
        self.assertEqual(self.count(), 0)

    def test_exact_366_day_read_bound_is_enforced_before_database_access(self):
        for start, end in ((NOW, NOW), (NOW, NOW - timedelta(seconds=1)),
                           (NOW - timedelta(days=366, seconds=1), NOW),
                           (NOW.replace(tzinfo=None), NOW)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.load(start, end)

    def test_database_constraints_block_native_ids_kinds_slots_and_nonobject_payload(self):
        base = dict(reference_id=GOLD, record_kind="snapshot", slot="current", recorded_at=NOW,
                    received_at=NOW, payload_hash="a" * 64, payload=self.gold())
        for change in ({"reference_id": "GOLD_24K_TOMAN_GRAM"}, {"record_kind": "physical"},
                       {"slot": "other"}, {"payload": []}):
            with self.subTest(change=change), self.assertRaises(IntegrityError), self.engine.begin() as connection:
                connection.execute(ReferenceRateRecord.__table__.insert(), {**base, **change})
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
