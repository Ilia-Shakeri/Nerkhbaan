from __future__ import annotations

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-source-window-secret-long-enough")

import httpx

from sqlalchemy import Integer, MetaData, create_engine, create_mock_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.pricing import rights
from app.pricing.backfill import PricingBackfillQueue, _servix_history_windows
from app.pricing.budgets import BudgetDecision
from app.pricing.db_models import InstrumentRecord, PricingBackfillJobRecord
from app.pricing.instruments import get_instrument
from app.pricing.persistence import PersistenceResult
from app.pricing.registry import RETIRED_PROVIDERS


NOW = datetime(2026, 10, 17, 12, 30, tzinfo=UTC)
_SERVIX_FIXTURE_TABLES = ("instruments", "pricing_backfill_jobs")
_SERVIX_SCHEMA = re.compile(r"servix_windows_test_[0-9a-f]{32}\Z")


class _FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


def _servix_fixture_metadata(schema=None):
    metadata = MetaData()
    for table in (InstrumentRecord.__table__, PricingBackfillJobRecord.__table__):
        table.to_metadata(metadata, schema=schema)
    return metadata


def _assert_servix_fixture_boundary(connection, schema):
    if not isinstance(schema, str) or not _SERVIX_SCHEMA.fullmatch(schema):
        raise AssertionError("Refusing a fixture outside its owned schema")
    rows = connection.execute(text("""
        SELECT current_schema() AS active_schema, target.name AS table_name,
               namespace.nspname AS resolved_schema
        FROM unnest(CAST(:table_names AS TEXT[])) AS target(name)
        LEFT JOIN pg_class AS relation ON relation.oid = to_regclass(target.name)
        LEFT JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    """), {"table_names": list(_SERVIX_FIXTURE_TABLES)}).mappings().all()
    if (len(rows) != len(_SERVIX_FIXTURE_TABLES)
            or {row["table_name"] for row in rows} != set(_SERVIX_FIXTURE_TABLES)
            or any(row["active_schema"] != schema or row["resolved_schema"] != schema for row in rows)):
        raise AssertionError("Fixture tables must resolve only inside their owned schema")


def _assert_servix_fixture_write_target(statement, schema):
    if not re.match(r"\s*(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|COPY)\b", statement, re.I):
        if re.match(r"\s*WITH\b", statement, re.I) and re.search(
            r"\b(INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\S+\s+SET|MERGE\s+INTO|TRUNCATE|COPY)\b",
            statement, re.I,
        ):
            raise AssertionError("Fixture does not permit an unverified CTE write target")
        return
    target = re.match(
        r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE(?:\s+TABLE)?)\s+'
        r'((?:"[^"]+"|[A-Za-z_][A-Za-z_0-9]*)(?:\.(?:"[^"]+"|[A-Za-z_][A-Za-z_0-9]*))?)',
        statement, re.I,
    )
    parts = target.group(1).split(".") if target else []
    if (not parts or parts[-1].strip('"') not in _SERVIX_FIXTURE_TABLES
            or len(parts) == 2 and parts[0].strip('"') != schema):
        raise AssertionError("Fixture write target is outside its owned tables")


def _servix_public_fingerprint(connection):
    result = {}
    for name in _SERVIX_FIXTURE_TABLES:
        exists = connection.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": "public."+name})
        if not exists:
            result[name] = None
            continue
        row = connection.execute(text(f"""
            SELECT count(*) AS row_count,
                   md5(COALESCE(string_agg(to_jsonb(target)::text, chr(10)
                       ORDER BY to_jsonb(target)::text), '')) AS row_fingerprint
            FROM public.{name} AS target
        """)).mappings().one()
        result[name] = dict(row)
    return result


class _Locks:
    @asynccontextmanager
    async def backfill_lock(self, _instrument_id):
        yield object()


class ServixDurableBackfillTests(unittest.IsolatedAsyncioTestCase):
    def database_engine(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nerkhbaan-servix-window-test-")
        self.addCleanup(self.directory.cleanup)
        database = Path(self.directory.name) / "owned.sqlite"
        return create_engine(f"sqlite:///{database.as_posix()}",
                             connect_args={"check_same_thread": False})

    def setUp(self):
        self.engine = self.database_engine()
        self.addCleanup(self.engine.dispose)
        metadata = _servix_fixture_metadata(getattr(self, "fixture_schema", None))
        if self.engine.dialect.name == "sqlite":
            metadata.tables["pricing_backfill_jobs"].c.id.type = Integer()
        metadata.create_all(self.engine)
        if self.engine.dialect.name == "postgresql":
            with self.engine.connect() as connection:
                _assert_servix_fixture_boundary(connection, self.fixture_schema)

            def guard(connection, _cursor, statement, _parameters, _context, _executemany):
                if connection.info.get("servix_fixture_boundary_check"):
                    return
                connection.info["servix_fixture_boundary_check"] = True
                try:
                    _assert_servix_fixture_boundary(connection, self.fixture_schema)
                    _assert_servix_fixture_write_target(statement, self.fixture_schema)
                finally:
                    connection.info.pop("servix_fixture_boundary_check", None)

            event.listen(self.engine, "before_cursor_execute", guard)
            self.addCleanup(event.remove, self.engine, "before_cursor_execute", guard)
        self.sessions = sessionmaker(bind=self.engine)
        definition = get_instrument("BTC_USD")
        with self.sessions() as db:
            db.add(InstrumentRecord(
                instrument_id=definition.instrument_id, base_asset=definition.base_asset,
                quote_currency=definition.quote_currency.value, market=definition.market.value,
                region=definition.region.value, weight_unit=definition.weight_unit.value,
                display_decimals=definition.display_decimals,
                operational_ttl_seconds=definition.operational_ttl_seconds,
                stale_after_seconds=definition.stale_after_seconds,
                expire_after_seconds=definition.expire_after_seconds,
                base_anomaly_threshold_percent=definition.base_anomaly_threshold_percent,
                maximum_dynamic_threshold_percent=definition.maximum_dynamic_threshold_percent,
                minimum_sanity_price=definition.minimum_price, maximum_sanity_price=definition.maximum_price,
                importance=definition.importance, enabled=True, allow_derived_fallback=False,
            ))
            db.commit()
        self.provider = replace(RETIRED_PROVIDERS["servix_btc_usd"], enabled=True,
                                api_key_setting=None)
        self.store = AsyncMock()
        self.store.ping.return_value = True
        self.store.get_canonical.return_value = None
        self.budgets = AsyncMock()
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        self.operational = AsyncMock()
        self.operational.instrument.return_value = get_instrument("BTC_USD")
        self.operational.feature_enabled.return_value = True
        self.operational.providers_for.return_value = (self.provider,)
        self.queue = PricingBackfillQueue(store=self.store, budgets=self.budgets,
                                          operational=self.operational, locks=_Locks())
        self.queue._drain_redis_jobs = AsyncMock()
        self.queue._execute_history_job = AsyncMock(return_value=1)
        self.grants = {self.provider.provider_id: {
            "permissions": ["collect", "store", "display", "history"],
            "checked_at": "2026-10-16T00:00:00Z", "expires_at": "2026-10-19T00:00:00Z",
            "evidence_ref": "https://fixture.example.invalid/terms",
            "hosts": ["servix.cc"],
        }}
        for target, value in (
            ("app.pricing.backfill.SessionLocal", self.sessions),
            ("app.pricing.backfill.utc_now", lambda: NOW),
            ("app.pricing.backfill.PROVIDERS_BY_INSTRUMENT", {"BTC_USD": (self.provider,)}),
        ):
            self.enterContext(patch(target, value))
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.enterContext(patch.object(rights, "datetime", _FixtureClock))

    def job(self, days=365, **overrides):
        start = NOW - timedelta(days=days)
        key = hashlib.sha256(f"BTC_USD|{start.isoformat()}|{NOW.isoformat()}".encode()).hexdigest()
        values = dict(instrument_id="BTC_USD", range_start=start, range_end=NOW,
                      priority=200, status="pending", attempt_count=0,
                      idempotency_key=key, created_at=NOW-timedelta(days=1),
                      updated_at=NOW-timedelta(days=1))
        values.update(overrides)
        with self.sessions() as db:
            record = PricingBackfillJobRecord(**values)
            db.add(record)
            db.commit()
            return record.id

    def rows(self):
        with self.sessions() as db:
            return db.scalars(select(PricingBackfillJobRecord).order_by(
                PricingBackfillJobRecord.range_start, PricingBackfillJobRecord.id)).all()

    def due_parent(self, identifier):
        with self.sessions() as db:
            row = db.get(PricingBackfillJobRecord, identifier)
            row.next_attempt_at = NOW-timedelta(seconds=1)
            db.commit()

    async def test_year_schedules_bounded_durable_children_without_http_budget_or_sleep(self):
        identifier = self.job()
        with patch("app.pricing.backfill.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await self.queue.process_jobs(maximum_jobs=1)
        self.assertEqual(result, {"completed": 0, "deferred": 1, "failed": 0})
        self.queue._execute_history_job.assert_not_awaited()
        self.budgets.consume.assert_not_awaited()
        sleep.assert_not_awaited()
        rows = self.rows()
        parent = next(row for row in rows if row.id == identifier)
        children = sorted((row for row in rows if row.id != identifier), key=lambda row: row.range_start)
        self.assertGreater(len(children), 1)
        self.assertLessEqual(len(children), 13)
        self.assertEqual(parent.status, "deferred")
        self.assertEqual(parent.attempt_count, 0)
        self.assertIsNone(parent.completed_at)
        self.assertEqual(parent.next_attempt_at.replace(tzinfo=UTC), NOW+timedelta(minutes=5))
        self.assertEqual(children[0].range_start, parent.range_start)
        self.assertEqual(children[-1].range_end, parent.range_end)
        for child in children:
            self.assertLess(child.range_start, child.range_end)
            self.assertLessEqual((child.range_end.date()-child.range_start.date()).days, 30)
            self.assertEqual(child.status, "pending")
        self.assertTrue(all(left.range_end == right.range_start
                            for left, right in zip(children, children[1:])))

    async def test_source_permissions_share_the_fixed_backfill_clock(self):
        self.assertEqual(rights.datetime.now(UTC), NOW)
        self.assertTrue(rights.provider_allowed(self.provider.provider_id, "history"))
        identifier = self.job()
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["deferred"], 1)
        self.assertEqual(next(row.status for row in self.rows() if row.id == identifier), "deferred")

    async def test_expired_or_future_source_permissions_still_block_history(self):
        for name, values in (
            ("expired", {"expires_at": NOW.isoformat()}),
            ("future", {"checked_at": (NOW+timedelta(seconds=1)).isoformat()}),
        ):
            with self.subTest(permission=name):
                self.grants[self.provider.provider_id].update({
                    "checked_at": "2026-10-16T00:00:00Z",
                    "expires_at": "2026-10-19T00:00:00Z", **values,
                })
                before = len(self.rows())
                self.job(idempotency_key="owned-source-clock-"+name)
                self.assertFalse(rights.provider_allowed(self.provider.provider_id, "history"))
                self.assertEqual(await self.queue.process_jobs(maximum_jobs=1),
                                 {"completed": 0, "deferred": 0, "failed": 0})
                self.assertEqual(len(self.rows()), before+1)
                self.assertTrue(all(row.status == "pending" for row in self.rows()))
        self.queue._execute_history_job.assert_not_awaited()
        self.budgets.consume.assert_not_awaited()

    async def test_reclaim_parent_reuses_children_and_does_not_claim_full_completion(self):
        identifier = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        before = {row.id for row in self.rows()}
        self.due_parent(identifier)
        await self.queue.process_jobs(maximum_jobs=1)
        self.assertEqual({row.id for row in self.rows()}, before)
        parent = next(row for row in self.rows() if row.id == identifier)
        self.assertEqual((parent.status, parent.attempt_count), ("deferred", 0))
        self.queue._execute_history_job.assert_not_awaited()

    async def test_next_claim_processes_one_child_without_parent_starvation(self):
        identifier = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        result = await self.queue.process_jobs(maximum_jobs=1)
        self.assertEqual(result["completed"], 1)
        child = self.queue._execute_history_job.await_args.args[0]
        self.assertNotEqual(child["id"], identifier)
        self.assertLessEqual((child["range_end"].date()-child["range_start"].date()).days, 30)
        self.budgets.consume.assert_awaited_once()

    async def test_overlapping_parent_ranges_share_exact_calendar_windows(self):
        first = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        before = {row.id for row in self.rows()}
        second = self.job(range_start=NOW-timedelta(days=365)+timedelta(minutes=1),
                          idempotency_key="owned-second-window-parent")
        await self.queue.process_jobs(maximum_jobs=1)
        after = self.rows()
        self.assertEqual(len(after), len(before)+2)
        self.assertTrue(before <= {row.id for row in after})
        added_children = [row for row in after if row.id not in before and row.id != second]
        self.assertEqual(len(added_children), 1)
        self.assertEqual(added_children[0].range_start.replace(tzinfo=UTC),
                         NOW-timedelta(days=365)+timedelta(minutes=1))
        self.assertEqual(next(row.status for row in after if row.id == first), "deferred")
        self.assertEqual(next(row.status for row in after if row.id == second), "deferred")
        self.queue._execute_history_job.assert_not_awaited()

    async def test_initial_quota_denial_defers_without_spending_attempt_or_fetching(self):
        identifier = self.job(days=1)
        self.budgets.consume.return_value = BudgetDecision(False, "budget_limit_1", 0)
        result = await self.queue.process_jobs(maximum_jobs=1)
        self.assertEqual(result, {"completed": 0, "deferred": 1, "failed": 0})
        self.queue._execute_history_job.assert_not_awaited()
        row = self.rows()[0]
        self.assertEqual((row.status, row.attempt_count, row.last_error),
                         ("deferred", 0, "budget_limit_1"))
        self.budgets.consume.return_value = BudgetDecision(True, "allowed", 1)
        self.due_parent(identifier)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 1)

    async def test_revoked_rights_prevent_claiming_existing_parent_or_children(self):
        self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        before = [(row.id, row.status, row.attempt_count) for row in self.rows()]
        self.grants.clear()
        self.assertEqual(await self.queue.process_jobs(maximum_jobs=2),
                         {"completed": 0, "deferred": 0, "failed": 0})
        self.assertEqual([(row.id, row.status, row.attempt_count) for row in self.rows()], before)
        self.budgets.consume.assert_not_awaited()
        self.queue._execute_history_job.assert_not_awaited()

    async def test_parent_finishes_only_after_every_child_finishes_with_receipt_time(self):
        identifier = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        children = [row for row in self.rows() if row.id != identifier]
        with self.sessions() as db:
            for child in children[:-1]:
                row = db.get(PricingBackfillJobRecord, child.id)
                row.status, row.completed_at = "completed", NOW
            db.commit()
        self.due_parent(identifier)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["deferred"], 1)
        with self.sessions() as db:
            row = db.get(PricingBackfillJobRecord, children[-1].id)
            row.status, row.completed_at = "completed", NOW
            db.commit()
        self.due_parent(identifier)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["completed"], 1)
        parent = next(row for row in self.rows() if row.id == identifier)
        self.assertEqual(parent.status, "completed")
        self.assertIn("coverage_requires_observation_check", parent.last_error)
        self.assertIsNotNone(parent.completed_at)
        self.budgets.consume.assert_not_awaited()

    async def test_failed_child_cannot_be_reported_as_parent_success(self):
        identifier = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        child = next(row for row in self.rows() if row.id != identifier)
        with self.sessions() as db:
            db.get(PricingBackfillJobRecord, child.id).status = "failed"
            db.commit()
        self.due_parent(identifier)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["failed"], 1)
        parent = next(row for row in self.rows() if row.id == identifier)
        self.assertEqual(parent.status, "failed")
        self.assertIsNone(parent.completed_at)
        self.budgets.consume.assert_not_awaited()

    async def test_completed_marker_without_receipt_time_fails_closed(self):
        identifier = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        with self.sessions() as db:
            for child in db.scalars(select(PricingBackfillJobRecord).where(
                    PricingBackfillJobRecord.id != identifier)):
                child.status = "completed"
            db.commit()
        self.due_parent(identifier)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["failed"], 1)
        self.assertEqual(next(row.status for row in self.rows() if row.id == identifier), "failed")

    async def test_changed_child_identity_prevents_parent_completion_or_new_rows(self):
        identifier = self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        before = {row.id for row in self.rows()}
        child = next(row for row in self.rows() if row.id != identifier)
        with self.sessions() as db:
            db.get(PricingBackfillJobRecord, child.id).range_end += timedelta(hours=1)
            db.commit()
        self.due_parent(identifier)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["failed"], 1)
        self.assertEqual({row.id for row in self.rows()}, before)
        self.assertEqual(next(row.status for row in self.rows() if row.id == identifier), "retrying")
        self.queue._execute_history_job.assert_not_awaited()

    async def test_stale_parent_attempt_cannot_create_or_update_children(self):
        identifier = self.job()
        claimed = self.queue._claim_job(("BTC_USD",))
        with self.sessions() as db:
            db.get(PricingBackfillJobRecord, identifier).attempt_count += 1
            db.commit()
        with self.assertRaisesRegex(RuntimeError, "no_longer_owned"):
            self.queue._schedule_servix_history_windows(claimed, self.provider)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual((self.rows()[0].status, self.rows()[0].attempt_count), ("processing", 2))

    async def test_child_creation_and_parent_deferral_roll_back_together(self):
        self.job()
        claimed = self.queue._claim_job(("BTC_USD",))

        def reject_flush(_session, _context, _instances):
            raise RuntimeError("owned fixture commit failure")

        event.listen(self.sessions, "before_flush", reject_flush)
        try:
            with self.assertRaisesRegex(RuntimeError, "fixture commit failure"):
                self.queue._schedule_servix_history_windows(claimed, self.provider)
        finally:
            event.remove(self.sessions, "before_flush", reject_flush)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual((self.rows()[0].status, self.rows()[0].attempt_count), ("processing", 1))

    async def test_range_over_one_year_creates_no_children_or_external_requests(self):
        self.job(days=367)
        self.assertEqual((await self.queue.process_jobs(maximum_jobs=1))["failed"], 1)
        self.assertEqual(len(self.rows()), 1)
        self.budgets.consume.assert_not_awaited()
        self.queue._execute_history_job.assert_not_awaited()

    async def execute_real_child(self, response):
        self.job()
        await self.queue.process_jobs(maximum_jobs=1)
        child = self.queue._claim_job(("BTC_USD",))
        self.queue.persistence = AsyncMock()
        self.queue.persistence.persist_provider_quote.return_value = PersistenceResult(True, False, None, None)
        self.queue.persistence.persist_canonical.return_value = PersistenceResult(True, False, None, None)
        self.queue._renew_job = Mock(return_value=True)
        self.client = AsyncMock()
        self.client.get.return_value = response(child)
        with patch("app.pricing.backfill.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = self.client
            return await PricingBackfillQueue._execute_history_job(self.queue, child, self.provider)

    async def test_real_child_keeps_daily_source_time_and_uses_one_bounded_get(self):
        def response(child):
            self.source_time = child["range_start"] + timedelta(days=1, hours=2)
            payload = [{"code": "BTC_USD", "quoteUnit": "USD", "value": "77000",
                        "businessTime": self.source_time.isoformat()}]
            return httpx.Response(200, json=payload, request=httpx.Request("GET", self.provider.history_url))

        self.assertEqual(await self.execute_real_child(response), 1)
        params = self.client.get.await_args.kwargs["params"]
        self.assertLessEqual((datetime.fromisoformat(params["to"])-datetime.fromisoformat(params["from"])).days, 30)
        self.client.get.assert_awaited_once()
        quote = self.queue.persistence.persist_provider_quote.await_args.args[0]
        self.assertEqual(quote.observed_at, self.source_time)
        self.assertEqual(quote.metadata["history_point_kind"], "provider_observation")
        self.budgets.consume.assert_not_awaited()

    async def test_child_http_denial_never_persists_rows(self):
        def response(_child):
            return httpx.Response(403, request=httpx.Request("GET", self.provider.history_url))

        with self.assertRaises(httpx.HTTPStatusError):
            await self.execute_real_child(response)
        self.queue.persistence.persist_provider_quote.assert_not_awaited()
        self.queue.persistence.persist_canonical.assert_not_awaited()


class ServixCalendarWindowTests(unittest.TestCase):
    def test_leap_year_and_midnight_end_have_no_gaps_or_zero_length_windows(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = start+timedelta(days=366)
        windows = _servix_history_windows(start, end)
        self.assertLessEqual(len(windows), 13)
        self.assertEqual((windows[0][0], windows[-1][1]), (start, end))
        self.assertTrue(all(left < right and (right.date()-left.date()).days <= 30
                            for left, right in windows))
        self.assertTrue(all(left[1] == right[0] for left, right in zip(windows, windows[1:])))

    def test_boundary_observation_has_identical_persistence_key_in_adjacent_windows(self):
        from app.pricing.models import Currency, ProviderQuote, SourceType, ValidationStatus, WeightUnit
        from app.pricing.parsers.history import build_history_parser

        windows = _servix_history_windows(NOW-timedelta(days=60), NOW)
        boundary = windows[0][1]
        payload = [{"code": "BTC_USD", "quoteUnit": "USD", "value": "77000",
                    "businessTime": boundary.isoformat()}]
        parser = build_history_parser("servix_btc_usd_history_v1")
        points = [parser.parse(payload, get_instrument("BTC_USD"), *window)[0]
                  for window in windows[:2]]
        self.assertEqual(points[0].observed_at, points[1].observed_at)
        quotes = [ProviderQuote.create(instrument_id="BTC_USD", provider_id="servix_btc_usd",
                                      source_type=SourceType.HTTP, price=point.price, currency=Currency.USD,
                                      weight_unit=WeightUnit.UNIT, purity=None,
                                      validation_status=ValidationStatus.ACCEPTED, observed_at=point.observed_at,
                                      received_at=NOW, parser_version=parser.parser_version)
                  for point in points]
        self.assertEqual(quotes[0].idempotency_key, quotes[1].idempotency_key)


class ServixFixtureBoundaryTests(unittest.TestCase):
    def test_fixture_ddl_names_owned_schema_and_does_not_mutate_orm_tables(self):
        schema = "servix_windows_test_" + "a"*32
        metadata = _servix_fixture_metadata(schema)
        self.assertEqual(set(metadata.tables), {f"{schema}.{name}" for name in _SERVIX_FIXTURE_TABLES})
        statements = []
        engine = create_mock_engine("postgresql://", lambda sql, *_args, **_kwargs:
                                    statements.append(str(sql.compile(dialect=engine.dialect))))
        metadata.create_all(engine, checkfirst=False)
        for name in _SERVIX_FIXTURE_TABLES:
            self.assertTrue(any(f"CREATE TABLE {schema}.{name}" in statement for statement in statements))
        self.assertTrue(any(f"REFERENCES {schema}.instruments" in statement for statement in statements))
        self.assertIsNone(InstrumentRecord.__table__.schema)
        self.assertIsNone(PricingBackfillJobRecord.__table__.schema)

    def test_public_fallback_or_changed_current_schema_fail_before_any_fixture_dml(self):
        schema = "servix_windows_test_" + "b"*32
        for active, resolved in ((schema, "public"), ("public", schema), (schema, None)):
            connection = Mock()
            connection.execute.return_value.mappings.return_value.all.return_value = [
                {"active_schema": active, "table_name": name, "resolved_schema": resolved}
                for name in _SERVIX_FIXTURE_TABLES
            ]
            with self.subTest(active=active, resolved=resolved), self.assertRaisesRegex(AssertionError, "owned schema"):
                _assert_servix_fixture_boundary(connection, schema)
            self.assertTrue(all(str(call.args[0]).lstrip().startswith("SELECT")
                                for call in connection.execute.call_args_list))

    def test_explicit_foreign_qualified_writes_are_rejected(self):
        schema = "servix_windows_test_" + "c"*32
        for statement in (
            "INSERT INTO public.instruments (instrument_id) VALUES ('owned-test')",
            'DELETE FROM "public"."pricing_backfill_jobs"',
            "UPDATE another_schema.instruments SET importance=1",
            "TRUNCATE TABLE public.instruments",
            "WITH removed AS (DELETE FROM public.instruments RETURNING *) SELECT * FROM removed",
        ):
            with self.subTest(statement=statement), self.assertRaises(AssertionError):
                _assert_servix_fixture_write_target(statement, schema)
        _assert_servix_fixture_write_target("UPDATE instruments SET importance=1", schema)
        _assert_servix_fixture_write_target(f"DELETE FROM {schema}.pricing_backfill_jobs", schema)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Requires an explicitly owned test PostgreSQL database")
class ServixDurableBackfillPostgresTests(ServixDurableBackfillTests):
    def database_engine(self):
        url = make_url(os.environ["TEST_DATABASE_URL"])
        parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("Only a named test/CI PostgreSQL database is permitted")
        schema = "servix_windows_test_" + uuid.uuid4().hex
        self.fixture_schema = schema
        admin = create_engine(url, hide_parameters=True)
        self.fixture_admin = admin
        quoted = admin.dialect.identifier_preparer.quote(schema)
        with admin.begin() as connection:
            public_baseline = _servix_public_fingerprint(connection)
            connection.execute(text(f"CREATE SCHEMA {quoted}"))

        def cleanup_schema():
            if not re.fullmatch(r"servix_windows_test_[0-9a-f]{32}", schema):
                raise AssertionError("Refusing cleanup outside the owned schema")
            try:
                try:
                    with admin.connect() as connection:
                        self.assertEqual(_servix_public_fingerprint(connection), public_baseline,
                                         "Foreign public fixture rows changed")
                finally:
                    with admin.begin() as connection:
                        connection.execute(text(f"DROP SCHEMA {quoted} CASCADE"))
            finally:
                admin.dispose()

        self.addCleanup(cleanup_schema)
        return create_engine(url, hide_parameters=True, connect_args={
            "options": f"-csearch_path={schema},public -cstatement_timeout=10000",
        })

    async def test_full_public_tables_remain_unchanged_when_search_path_loses_owned_namespace(self):
        with self.fixture_admin.connect() as connection:
            before = _servix_public_fingerprint(connection)
            for model in (InstrumentRecord, PricingBackfillJobRecord):
                name = model.__table__.name
                if before[name] is None:
                    self.skipTest("Needs existing full public fixture tables; never creates or writes them")
                columns = connection.scalars(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=:name
                """), {"name": name}).all()
                self.assertTrue(set(model.__table__.columns.keys()) <= set(columns),
                                "Public isolation fixture must use full table metadata")
        with self.engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL search_path = public")
            with self.assertRaisesRegex(AssertionError, "owned schema"):
                connection.execute(InstrumentRecord.__table__.insert(),
                                   {"instrument_id": "SERVIX_BOUNDARY_MUST_NOT_BE_WRITTEN"})
        with self.fixture_admin.connect() as connection:
            self.assertEqual(_servix_public_fingerprint(connection), before)

    async def test_simultaneous_parent_schedulers_create_exactly_one_child_set(self):
        identifier = self.job()
        claimed = self.queue._claim_job(("BTC_USD",))
        barrier = threading.Barrier(2)

        def schedule():
            barrier.wait(timeout=5)
            try:
                return self.queue._schedule_servix_history_windows(claimed, self.provider)
            except RuntimeError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(schedule) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertCountEqual(results, ["deferred", "backfill_job_no_longer_owned"])
        rows = self.rows()
        self.assertEqual(len(rows), len(_servix_history_windows(NOW-timedelta(days=365), NOW))+1)
        self.assertEqual(len({row.idempotency_key for row in rows}), len(rows))
        self.assertEqual(next(row.status for row in rows if row.id == identifier), "deferred")

    async def test_skip_locked_claims_do_not_give_same_parent_to_two_workers(self):
        identifier = self.job()
        barrier = threading.Barrier(2)

        def claim():
            barrier.wait(timeout=5)
            return self.queue._claim_job(("BTC_USD",))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        claimed = [result for result in results if result is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual((claimed[0]["id"], claimed[0]["attempt_count"]), (identifier, 1))

    async def test_distinct_parent_race_reuses_one_exact_window_set_after_retry(self):
        identifiers = [self.job(), self.job(idempotency_key="owned-second-parent-same-range")]
        claimed = [self.queue._claim_job(("BTC_USD",)) for _ in identifiers]
        barrier = threading.Barrier(2)

        def schedule(job):
            barrier.wait(timeout=5)
            try:
                return self.queue._schedule_servix_history_windows(job, self.provider)
            except IntegrityError:
                return "unique_window_race_rolled_back"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(schedule, job) for job in claimed]
            results = [future.result(timeout=15) for future in futures]
        self.assertIn("deferred", results)
        self.assertTrue(all(result in {"deferred", "unique_window_race_rolled_back"} for result in results))
        for job in claimed:
            parent = next(row for row in self.rows() if row.id == job["id"])
            if parent.status == "processing":
                self.assertEqual(self.queue._schedule_servix_history_windows(job, self.provider), "deferred")
        rows = self.rows()
        self.assertEqual(len(rows), len(_servix_history_windows(NOW-timedelta(days=365), NOW))+2)
        self.assertEqual(len({row.idempotency_key for row in rows}), len(rows))
        self.assertTrue(all(row.status == "deferred" for row in rows if row.id in identifiers))


if __name__ == "__main__":
    unittest.main()
