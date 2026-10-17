from __future__ import annotations

import asyncio
import os
import re
import unittest
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "rights-test-key-not-for-runtime-000000000000000")

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.admin.routers import pricing as admin_pricing
from app.config import settings
from app.pricing import rights
from app.pricing.db_models import CanonicalQuoteRecord, ProviderQuoteRecord, InstrumentRecord
from app.pricing.history import InternalPriceHistory
from app.pricing.instruments import get_instrument


TEST_URL = os.getenv("TEST_DATABASE_URL")
START = datetime(2026, 10, 17, tzinfo=UTC)
END = START + timedelta(hours=1)


def _summary(provider="approved"):
    return {"provider_ids": [provider], "primary_provider_id": provider, "derived": False}


class _OwnedPostgresFixture:
    """Guard every test connection against falling through to public tables."""

    @classmethod
    def _public_fingerprint(cls):
        result = {}
        with cls.admin_engine.connect() as connection:
            for name in cls.owned_table_names:
                qualified = "public." + name
                if connection.execute(text("SELECT to_regclass(:name)"), {"name": qualified}).scalar_one() is None:
                    result[name] = None
                    continue
                # Identifiers come only from a fixed test-table allowlist. Read
                # existing public rows without copying their values into output.
                quoted = cls.admin_engine.dialect.identifier_preparer.quote(name)
                rows = tuple(connection.execute(text(f"""SELECT COUNT(*),
                    md5(COALESCE(string_agg(md5(to_jsonb(row_value)::text), ''
                        ORDER BY md5(to_jsonb(row_value)::text)), ''))
                    FROM public.{quoted} AS row_value""")).one())
                columns = connection.execute(text("""SELECT attribute.attname,
                    format_type(attribute.atttypid, attribute.atttypmod), attribute.attnotnull,
                    attribute.attidentity, pg_get_expr(default_value.adbin, default_value.adrelid)
                    FROM pg_attribute attribute
                    LEFT JOIN pg_attrdef default_value ON default_value.adrelid = attribute.attrelid
                        AND default_value.adnum = attribute.attnum
                    WHERE attribute.attrelid = to_regclass(:name)
                      AND attribute.attnum > 0 AND NOT attribute.attisdropped
                    ORDER BY attribute.attnum"""), {"name": qualified}).all()
                sequence_last_value = None
                if any(column[0] == "id" for column in columns):
                    sequence_last_value = connection.execute(text("""SELECT
                        pg_sequence_last_value(pg_get_serial_sequence(:name, 'id')::regclass)"""),
                        {"name": qualified}).scalar_one()
                result[name] = (rows, tuple(tuple(column) for column in columns), sequence_last_value)
        return result

    @classmethod
    def _assert_owned_tables(cls, connection):
        # A direct, separate DBAPI cursor avoids recursing through the SQL event
        # guard and does not replace the statement's own result cursor.
        cursor = connection.connection.cursor()
        try:
            cursor.execute("""SELECT current_schema(), table_name, namespace.nspname
                FROM unnest(%s::text[]) AS expected(table_name)
                LEFT JOIN pg_class relation ON relation.oid = to_regclass(table_name)
                LEFT JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace""",
                           (list(cls.owned_table_names),))
            rows = cursor.fetchall()
        finally:
            cursor.close()
        if (len(rows) != len(cls.owned_table_names)
                or {row[1] for row in rows} != set(cls.owned_table_names)
                or any(row[0] != cls.schema or row[2] != cls.schema for row in rows)):
            raise AssertionError("Refusing SQL outside the explicitly owned test schema")

    @classmethod
    def _install_ownership_guard(cls):
        with cls.engine.connect() as connection:
            cls._assert_owned_tables(connection)

        def guard(connection, cursor, statement, parameters, context, executemany):
            cls._assert_owned_tables(connection)
            if re.search(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+(?:ONLY\s+)?"?public"?\.', statement, re.IGNORECASE):
                raise AssertionError("Refusing explicitly public mutation in an owned test")

        cls.ownership_guard = guard
        event.listen(cls.engine, "before_cursor_execute", guard)

    def _assert_public_unchanged(self):
        self.assertEqual(self._public_fingerprint(), self.public_fingerprint,
                         "Existing public data changed during an isolated test")

    def test_owned_tables_shadow_public_and_dml_guard_blocks_fallthrough(self):
        with self.engine.begin() as connection:
            self._assert_owned_tables(connection)
            with self.assertRaisesRegex(AssertionError, "explicitly public mutation"):
                connection.exec_driver_sql("DELETE FROM public.canonical_quotes")
            # The SET itself is checked while the connection is still owned.
            # The next mutation must be rejected before PostgreSQL sees it.
            connection.exec_driver_sql("SET LOCAL search_path = public")
            with self.assertRaisesRegex(AssertionError, "explicitly owned test schema"):
                connection.exec_driver_sql("DELETE FROM canonical_quotes")
        self.assertEqual(self._public_fingerprint(), self.public_fingerprint)


@unittest.skipUnless(TEST_URL, "Requires an explicitly owned test PostgreSQL database")
class RightsPostgresTests(_OwnedPostgresFixture, unittest.TestCase):
    owned_table_names = ("instruments", "canonical_quotes", "provider_quotes", "pricing_anomalies", "pricing_verifications")

    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("Only a named test/CI PostgreSQL database is permitted")
        cls.schema = "pricing_rights_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, hide_parameters=True)
        cls.public_fingerprint = cls._public_fingerprint()
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        try:
            cls.engine = create_engine(url, hide_parameters=True, connect_args={"options": f"-csearch_path={cls.schema},public"})
            cls.sessions = sessionmaker(bind=cls.engine)
            metadata = MetaData(schema=cls.schema)
            for model in (InstrumentRecord, CanonicalQuoteRecord, ProviderQuoteRecord):
                model.__table__.to_metadata(metadata, schema=cls.schema)
            metadata.create_all(cls.engine)
            with cls.engine.begin() as connection:
                if connection.execute(text("SELECT current_schema()" )).scalar_one() != cls.schema:
                    raise AssertionError("Refusing DDL outside the owned test schema")
                connection.execute(text(f"""CREATE TABLE {cls.quoted_schema}.pricing_anomalies (
                    id BIGINT PRIMARY KEY, instrument_id TEXT, candidate_quote_id BIGINT,
                    previous_canonical_quote_id BIGINT, deviation_percent NUMERIC,
                    dynamic_threshold_percent NUMERIC, severity TEXT, status TEXT,
                    reason TEXT, reviewed_at TIMESTAMPTZ, review_note TEXT,
                    reviewed_by_admin_id INTEGER, created_at TIMESTAMPTZ)"""))
                connection.execute(text(f"""CREATE TABLE {cls.quoted_schema}.pricing_verifications (
                    id BIGINT PRIMARY KEY, instrument_id TEXT, anomaly_id BIGINT,
                    candidate_quote_id BIGINT, verifier_quote_ids JSONB,
                    decision TEXT, tolerance_percent NUMERIC, decision_reason TEXT,
                    created_at TIMESTAMPTZ)"""))
            cls._install_ownership_guard()
        except Exception:
            cls._cleanup()
            raise

    @classmethod
    def _cleanup(cls):
        if hasattr(cls, "public_fingerprint"):
            if cls._public_fingerprint() != cls.public_fingerprint:
                raise AssertionError("Existing public data changed during the isolated fixture")
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        try:
            if not re.fullmatch(r"pricing_rights_[0-9a-f]{32}", cls.schema):
                raise AssertionError("Refusing cleanup outside the owned schema")
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
        finally:
            cls.admin_engine.dispose()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup()

    def setUp(self):
        self.addCleanup(self._assert_public_unchanged)
        self.enterContext(patch.object(settings, "pricing_rights_enforced", True))
        now = datetime.now(UTC)
        grant = {"permissions": ["collect", "store", "display", "history", "derive"], "checked_at": (now-timedelta(days=1)).isoformat(), "expires_at": (now+timedelta(days=1)).isoformat(), "evidence_ref": "https://fixture.example.invalid/terms"}
        self.grants = {name: deepcopy(grant) for name in ("approved", "approved_fx")}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.enterContext(patch("app.pricing.history.SessionLocal", self.sessions))
        with self.engine.begin() as connection:
            for table in ("pricing_verifications", "pricing_anomalies", "canonical_quotes", "provider_quotes", "instruments"):
                connection.execute(text(f"DELETE FROM {table}"))
            instrument = get_instrument("BTC_USD")
            connection.execute(InstrumentRecord.__table__.insert(), {
                "instrument_id": instrument.instrument_id, "base_asset": instrument.base_asset,
                "quote_currency": instrument.quote_currency.value, "market": instrument.market.value,
                "region": instrument.region.value, "weight_unit": instrument.weight_unit.value,
                "purity": str(instrument.purity) if instrument.purity is not None else None,
                "display_decimals": instrument.display_decimals,
                "operational_ttl_seconds": instrument.operational_ttl_seconds,
                "stale_after_seconds": instrument.stale_after_seconds,
                "expire_after_seconds": instrument.expire_after_seconds,
                "base_anomaly_threshold_percent": instrument.base_anomaly_threshold_percent,
                "maximum_dynamic_threshold_percent": instrument.maximum_dynamic_threshold_percent,
                "minimum_sanity_price": instrument.minimum_price,
                "maximum_sanity_price": instrument.maximum_price,
                "importance": instrument.importance, "enabled": instrument.enabled,
                "allow_derived_fallback": instrument.allow_derived_fallback,
            })

    def canonical(self, identifier, price, minute, *, summary=None, candidate=None, status="live"):
        stamp = START + timedelta(minutes=minute)
        values = dict(id=identifier, instrument_id="BTC_USD", price=price, status=status, primary_quote_id=10, verification_quote_ids=[], source_summary=_summary() if summary is None else summary, candidate_provider_id=candidate, canonical_at=stamp, observed_at=stamp, valid_until=END, stale_at=END, expires_at=END+timedelta(hours=1), is_persisted=True, decision_reason="owned_fixture", verification_status="not_required", idempotency_key=f"owned-canonical-{identifier}")
        with self.engine.begin() as connection:
            connection.execute(CanonicalQuoteRecord.__table__.insert(), values)

    def provider(self, identifier, provider="approved", minute=0):
        stamp = START+timedelta(minutes=minute)
        with self.engine.begin() as connection:
            connection.execute(ProviderQuoteRecord.__table__.insert(), dict(id=identifier, instrument_id="BTC_USD", provider_id=provider, price=100+identifier, observed_at=stamp, received_at=stamp, source_type="http", currency="USD", parser_version="owned/1", validation_status="accepted", confidence_score=1, persistence_status="persisted", idempotency_key=f"owned-provider-{identifier}"))

    def test_aggregate_and_revocation_filter_before_ohlc_without_erasing_rows(self):
        self.canonical(1, 100, 1)
        self.canonical(2, 9999, 2, summary=_summary("restricted"))
        self.canonical(3, 1, 3, summary={})
        self.canonical(4, 120, 4)
        rows = InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["open"], rows[0]["close"], rows[0]["high"], rows[0]["low"], rows[0]["sample_count"]), (100, 120, 120, 100, 2))
        self.grants.clear()
        self.assertEqual(InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour"), [])
        with self.sessions() as db:
            self.assertEqual(db.scalar(text("SELECT count(*) FROM canonical_quotes")), 4)

    def test_legacy_derived_status_cannot_claim_direct_lineage_for_chart_or_admin(self):
        self.canonical(1, 100, 1, status="derived_fallback")
        self.assertEqual(InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour"), [])
        with self.sessions() as db:
            rows = admin_pricing._rows_for(db, "canonical_quotes", admin_pricing._CANONICAL_COLUMNS, identity_fields=("instrument_id",), identity="BTC_USD")
        self.assertEqual(rows, [])

    def test_latest_baseline_recent_and_admin_rank_skip_restricted_newest(self):
        self.canonical(1, 100, 1)
        self.canonical(2, 999, 2, summary=_summary("restricted"))
        self.canonical(3, 777, 3, candidate="restricted")
        self.assertEqual(InternalPriceHistory._query_latest_canonical("BTC_USD").id, 1)
        # Baseline and recent prices include only rows whose whole lineage is allowed.
        self.assertEqual(InternalPriceHistory._query_baseline("BTC_USD", END, START), 100)
        self.assertEqual(InternalPriceHistory._query_recent_prices("BTC_USD", 3), [100])
        with self.sessions() as db:
            response = admin_pricing.list_instruments(principal=None, db=db)
            btc = next(row for row in response["items"] if row["instrument_id"] == "BTC_USD")
            self.assertEqual(btc["latest_canonical"]["id"], 1)
            limited = admin_pricing._rows_for(db, "canonical_quotes", admin_pricing._CANONICAL_COLUMNS, identity_fields=("instrument_id",), identity="BTC_USD", limit=1)
            self.assertEqual([row["id"] for row in limited], [1])

    def test_provider_history_action_is_separate_from_display(self):
        self.provider(10)
        self.provider(11, "restricted", 1)
        self.assertEqual([row["provider_id"] for row in InternalPriceHistory._query_latest_sources("BTC_USD")], ["approved"])
        self.assertEqual(len(InternalPriceHistory._query_provider_history("BTC_USD", None, START, END)), 1)
        self.grants["approved"]["permissions"].remove("history")
        self.assertEqual(InternalPriceHistory._query_provider_history("BTC_USD", None, START, END), [])
        self.assertEqual(len(InternalPriceHistory._query_latest_sources("BTC_USD")), 1)

    def test_history_attribution_comes_from_every_included_bucket_source(self):
        self.grants["approved"]["attribution"] = {"label": "Source one", "url": "https://one.example.invalid/"}
        self.grants["approved_fx"]["attribution"] = {"label": "Source two", "url": "https://two.example.invalid/"}
        self.canonical(1, 100, 1)
        self.canonical(2, 110, 2, summary=_summary("approved_fx"))
        self.canonical(3, 999, 3, summary=_summary("restricted"))
        rows = InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour")
        self.assertEqual(rows[0].get("attributions"), [self.grants["approved"]["attribution"], self.grants["approved_fx"]["attribution"]])
        result = asyncio.run(InternalPriceHistory().canonical_history("BTC_USD", "1h", end=END))
        self.assertEqual(result.attributions, rows[0]["attributions"])
        self.assertEqual(result.to_dict()["attributions"], result.attributions)
        self.grants.pop("approved_fx")
        rows = InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour")
        self.assertEqual(rows[0]["attributions"], [self.grants["approved"]["attribution"]])

    def test_derived_history_attribution_uses_real_parent_tree_not_a_flat_stamp(self):
        self.grants["approved"]["attribution"] = {"label": "Real parent", "url": "https://real.example.invalid/"}
        self.grants["approved_fx"]["attribution"] = {"label": "Unrelated", "url": "https://unrelated.example.invalid/"}
        derived = {"provider_ids": ["derived:owned"], "primary_provider_id": "derived:owned", "derived": True, "inputs": [{"source_summary": _summary()}], "rights_provenance_version": 1, "rights_provider_ids": ["approved_fx"]}
        self.canonical(1, 100, 1, summary=derived)
        rows = InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour")
        self.assertEqual(rows[0]["attributions"], [self.grants["approved"]["attribution"]])

    def test_derived_recursive_permission_and_malformed_sql_parity(self):
        derived = rights.stamp_summary({"provider_ids": ["derived:owned"], "primary_provider_id": "derived:owned", "derived": True, "inputs": [{"source_summary": _summary()}]})
        malformed = []
        for replacement in ({}, {"provider_ids": "approved"}, {"provider_ids": ["approved"], "primary_provider_id": "restricted"}, {"provider_ids": ["approved"], "derived": "false"}, {"provider_ids": ["derived:missing"], "primary_provider_id": "derived:missing", "derived": True}, {**_summary(), "candidate_provider_id": "restricted"}, {**_summary(), "previous_provider_id": "restricted"}):
            value = deepcopy(derived)
            value["inputs"] = [{"source_summary": replacement}]
            malformed.append(value)
        mismatched_primary = deepcopy(derived)
        mismatched_primary["provider_ids"] = ["derived:other"]
        unmarked_formula = deepcopy(derived)
        unmarked_formula["inputs"] = [{"source_summary": {"provider_ids": ["derived:unknown"]}}]
        too_wide = deepcopy(derived)
        too_wide["inputs"] *= 17
        too_deep = deepcopy(derived)
        for _ in range(8):
            too_deep = {**deepcopy(derived), "inputs": [{"source_summary": too_deep}]}
        malformed.extend((mismatched_primary, unmarked_formula, too_wide, too_deep))
        summaries = [derived, _summary(), _summary("restricted"), {}, {"provider_ids": ["approved"], "primary_provider_id": "approved_fx"}, *malformed]
        for identifier, summary in enumerate(summaries, 1):
            self.canonical(identifier, 100+identifier, identifier, summary=summary)
        clause, parameters = rights.sql_filter("history")
        with self.sessions() as db:
            identifiers = set(db.execute(text(f"SELECT id FROM canonical_quotes WHERE {clause}"), parameters).scalars())
        expected = {index for index, summary in enumerate(summaries, 1) if rights.canonical_allowed(summary, "history")}
        self.assertEqual(identifiers, expected)
        self.grants["approved"]["permissions"].remove("derive")
        rows = InternalPriceHistory._query_canonical_history("BTC_USD", START, END, "1 hour")
        self.assertEqual(rows[0]["sample_count"], 1)

    def test_verification_resolves_candidate_previous_and_every_verifier(self):
        self.provider(10)
        self.provider(11, "approved_fx")
        self.canonical(1, 100, 0)
        with self.engine.begin() as connection:
            connection.execute(text("""INSERT INTO pricing_anomalies VALUES (20,'BTC_USD',10,1,25,5,'high','open','owned fixture',NULL,NULL,NULL,:stamp)"""), {"stamp": START})
            connection.execute(text("""INSERT INTO pricing_verifications VALUES (30,'BTC_USD',20,10,'[11]'::jsonb,'confirmed',5,'owned fixture',:stamp)"""), {"stamp": START})
        self.assertEqual(InternalPriceHistory._query_verification_details("BTC_USD", True)["status"], "confirmed")
        for provider in ("approved_fx", "approved"):
            saved = self.grants.pop(provider)
            self.assertEqual(InternalPriceHistory._query_verification_details("BTC_USD", True), {"instrument_id": "BTC_USD", "status": "unavailable"})
            with self.sessions() as db:
                rows = admin_pricing.list_anomalies(anomaly_status="", limit=10, offset=0, principal=None, db=db)["items"]
                self.assertEqual(rows[0]["id"], 20)
                if provider == "approved":
                    self.assertTrue(rows[0]["rights_restricted"])
                    self.assertNotIn("deviation_percent", rows[0])
                verifications = admin_pricing._rows_for(db, "pricing_verifications", admin_pricing._VERIFICATION_COLUMNS, identity_fields=("instrument_id",), identity="BTC_USD")
                self.assertNotIn("decision", verifications[0])
            self.grants[provider] = saved

    def test_verification_does_not_trust_a_different_candidate_or_missing_previous(self):
        self.provider(10)
        self.provider(11, "approved_fx")
        self.provider(12, "restricted")
        self.canonical(1, 100, 0)
        with self.engine.begin() as connection:
            connection.execute(text("""INSERT INTO pricing_anomalies VALUES (20,'BTC_USD',10,1,25,5,'high','open','owned fixture',NULL,NULL,NULL,:stamp)"""), {"stamp": START})
            connection.execute(text("""INSERT INTO pricing_verifications VALUES (30,'BTC_USD',20,12,'[11]'::jsonb,'confirmed',5,'owned fixture',:stamp)"""), {"stamp": START})
        self.assertEqual(InternalPriceHistory._query_verification_details("BTC_USD", True), {"instrument_id": "BTC_USD", "status": "unavailable"})
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE pricing_verifications SET candidate_quote_id=10"))
            connection.execute(text("UPDATE pricing_anomalies SET previous_canonical_quote_id=NULL"))
        self.assertEqual(InternalPriceHistory._query_verification_details("BTC_USD", True), {"instrument_id": "BTC_USD", "status": "unavailable"})
