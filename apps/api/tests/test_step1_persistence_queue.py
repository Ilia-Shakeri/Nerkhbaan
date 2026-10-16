from __future__ import annotations

import asyncio
import base64
import os
import re
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, patch

from sqlalchemy import MetaData, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "unit-test-key-not-for-runtime-0000000000000000")

from app.pricing.cache import PricingRedisStore, PricingRedisUnavailable
from app.pricing.db_models import PricingPersistenceEventRecord, ProviderQuoteRecord
from app.pricing.models import PersistenceStatus, ProviderQuote
from app.pricing.persistence import PricingPersistence


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")


class PricingQueueResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_enqueue_does_not_claim_quote_is_queued(self) -> None:
        quote = ProviderQuote.from_dict(PersistenceQueueIntegrationTests._quote_payload())
        store = PricingRedisStore("redis://127.0.0.1:1/0")
        persistence = PricingPersistence(store)
        with patch.object(persistence, "_persist_provider_quote", side_effect=OSError("test database offline")), patch.object(store, "append_persistence_event", new=AsyncMock(side_effect=PricingRedisUnavailable("test queue full"))):
            result = await persistence.persist_provider_quote(quote)
        self.assertFalse(result.persisted)
        self.assertFalse(result.queued)
        self.assertEqual(quote.persistence_status, PersistenceStatus.UNPERSISTED)

    async def test_accepted_enqueue_keeps_quote_queued(self) -> None:
        quote = ProviderQuote.from_dict(PersistenceQueueIntegrationTests._quote_payload())
        store = PricingRedisStore("redis://127.0.0.1:1/0")
        persistence = PricingPersistence(store)
        with patch.object(persistence, "_persist_provider_quote", side_effect=OSError("test database offline")), patch.object(store, "append_persistence_event", new=AsyncMock(return_value="1-0")):
            result = await persistence.persist_provider_quote(quote)
        self.assertTrue(result.queued)
        self.assertEqual(quote.persistence_status, PersistenceStatus.QUEUED)


@unittest.skipUnless(TEST_DATABASE_URL and TEST_REDIS_URL, "Owned PostgreSQL and Redis test endpoints are required")
class PersistenceQueueIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        url = make_url(TEST_DATABASE_URL)
        name_parts = set(re.split(r"[_-]+", (url.database or "").lower()))
        if url.get_backend_name() != "postgresql" or name_parts.isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("A PostgreSQL test or CI database is required")
        if urlsplit(TEST_REDIS_URL).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise unittest.SkipTest("The Redis test endpoint must be loopback")
        cls.schema = "persistence_queue_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url)
        cls.quoted_schema = cls.admin_engine.dialect.identifier_preparer.quote(cls.schema)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.quoted_schema}"))
        metadata = MetaData()
        for table in (ProviderQuoteRecord.__table__, PricingPersistenceEventRecord.__table__):
            table.to_metadata(metadata, schema=cls.schema)
        metadata.create_all(cls.admin_engine)
        cls.engine = create_engine(url, connect_args={"options": f"-csearch_path={cls.schema},public"})
        cls.session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        try:
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {cls.quoted_schema} CASCADE"))
        finally:
            cls.admin_engine.dispose()

    async def asyncSetUp(self) -> None:
        self.store = PricingRedisStore(TEST_REDIS_URL)
        self.store.persistence_stream = "pricing:test:" + uuid.uuid4().hex + ":persistence-stream"
        self.persistence = PricingPersistence(self.store)
        self.client = self.store.client()
        self.assertTrue(await self.client.ping())
        with self.engine.begin() as connection:
            connection.execute(PricingPersistenceEventRecord.__table__.delete())
            connection.execute(ProviderQuoteRecord.__table__.delete())
        self.session_patch = patch("app.pricing.persistence.SessionLocal", self.session)
        self.session_patch.start()

    async def asyncTearDown(self) -> None:
        self.session_patch.stop()
        await self.client.delete(self.store.persistence_stream)
        await self.store.close()

    @staticmethod
    def _quote_payload() -> dict:
        now = datetime.now(UTC).isoformat()
        return ProviderQuote.from_dict(dict(instrument_id="BTC_USD", provider_id="test_provider", source_type="http", price="100", currency="USD", weight_unit="unit", observed_at=now, received_at=now, parser_version="test1", validation_status="accepted")).to_dict(authenticated=True)

    async def test_full_queue_rejects_new_records_without_trimming_old_records(self) -> None:
        async with self.client.pipeline(transaction=True) as pipe:
            for index in range(999):
                pipe.xadd(self.store.persistence_stream, {"event_type": "provider_quote", "idempotency_key": f"old-{index}", "payload": "{}"})
            original = await pipe.execute()
        original.append(await self.store.append_persistence_event("provider_quote", "old-999", {}, 1000))
        results = await asyncio.gather(*[
            self.store.append_persistence_event("provider_quote", f"new-{index}", {"index": index}, 1000)
            for index in range(100)
        ], return_exceptions=True)
        self.assertTrue(all(isinstance(result, PricingRedisUnavailable) for result in results))
        self.assertEqual([row[0] for row in await self.client.xrange(self.store.persistence_stream)], original)

    async def test_parallel_append_at_capacity_accepts_one_and_preserves_existing_rows(self) -> None:
        async with self.client.pipeline(transaction=True) as pipe:
            for index in range(999):
                pipe.xadd(self.store.persistence_stream, {"event_type": "provider_quote", "idempotency_key": f"old-{index}", "payload": "{}"})
            original = await pipe.execute()
        results = await asyncio.gather(*[
            self.store.append_persistence_event("provider_quote", f"new-{index}", {}, 1000)
            for index in range(30)
        ], return_exceptions=True)
        self.assertEqual(sum(isinstance(result, str) for result in results), 1)
        self.assertEqual(sum(isinstance(result, PricingRedisUnavailable) for result in results), 29)
        rows = await self.client.xrange(self.store.persistence_stream)
        self.assertEqual(len(rows), 1000)
        self.assertEqual([row[0] for row in rows[:999]], original)

    async def test_poison_is_durable_and_good_quote_behind_it_reaches_database(self) -> None:
        fields = {"event_type": "provider_quote", "idempotency_key": "poison-key", "payload": "broken-json\x00keep-full" + "z" * 10000}
        poison_id = await self.client.xadd(self.store.persistence_stream, fields)
        payload = self._quote_payload()
        await self.store.append_persistence_event("provider_quote", payload["idempotency_key"], payload, 1000)
        result = await self.persistence.flush_stream()
        self.assertEqual(result, {"processed": 1, "failed": 0, "quarantined": 1})
        with self.session() as db:
            record = db.scalar(select(PricingPersistenceEventRecord).where(PricingPersistenceEventRecord.stream_event_id == poison_id))
            self.assertIsNotNone(record)
            self.assertEqual(record.status, "quarantined")
            restored = {base64.b64decode(key).decode("utf-8"): base64.b64decode(value).decode("utf-8") for key, value in record.payload["fields_base64"]}
            self.assertEqual(restored, fields)
            self.assertEqual(db.scalar(select(func.count(ProviderQuoteRecord.id))), 1)
        self.assertEqual(await self.client.xlen(self.store.persistence_stream), 0)
        self.assertEqual((await self.client.xpending(self.store.persistence_stream, self.persistence.consumer_group))["pending"], 0)

    async def test_unknown_event_and_invalid_quote_do_not_block_later_valid_records(self) -> None:
        bad_ids = [await self.client.xadd(self.store.persistence_stream, fields) for fields in (
            {"event_type": "future_unknown", "idempotency_key": "bad-type", "payload": "{}"},
            {"event_type": "provider_quote", "idempotency_key": "bad-quote", "payload": "{}"},
        )]
        payload = self._quote_payload()
        await self.store.append_persistence_event("provider_quote", payload["idempotency_key"], payload, 1000)
        result = await self.persistence.flush_stream()
        self.assertEqual(result, {"processed": 1, "failed": 0, "quarantined": 2})
        with self.session() as db:
            self.assertEqual(set(db.scalars(select(PricingPersistenceEventRecord.stream_event_id).where(PricingPersistenceEventRecord.status == "quarantined"))), set(bad_ids))
            self.assertEqual(db.scalar(select(func.count(ProviderQuoteRecord.id))), 1)

    async def test_transient_database_failure_keeps_original_pending_for_retry(self) -> None:
        payload = self._quote_payload()
        stream_id = await self.store.append_persistence_event("provider_quote", payload["idempotency_key"], payload, 1000)
        with patch.object(self.persistence, "_replay_event", side_effect=OSError("test database offline")):
            result = await self.persistence.flush_stream()
        self.assertEqual(result, {"processed": 0, "failed": 1, "quarantined": 0})
        self.assertEqual([row[0] for row in await self.client.xrange(self.store.persistence_stream)], [stream_id])
        with self.session() as db:
            self.assertEqual(db.scalar(select(func.count(PricingPersistenceEventRecord.id))), 0)

    async def test_quarantine_database_failure_preserves_poison_and_healthy_pending(self) -> None:
        poison_id = await self.client.xadd(self.store.persistence_stream, {"event_type": "bad", "idempotency_key": "bad", "payload": "{}"})
        payload = self._quote_payload()
        good_id = await self.store.append_persistence_event("provider_quote", payload["idempotency_key"], payload, 1000)
        with patch("app.pricing.persistence.SessionLocal", side_effect=OSError("test database offline")):
            result = await self.persistence.flush_stream()
        self.assertEqual(result, {"processed": 0, "failed": 1, "quarantined": 0})
        self.assertEqual([row[0] for row in await self.client.xrange(self.store.persistence_stream)], [poison_id, good_id])

    async def test_queue_failure_is_explicit_in_persistence_result(self) -> None:
        with patch.object(self.store, "append_persistence_event", side_effect=PricingRedisUnavailable("test queue full")):
            result = await self.persistence._queue("provider_quote", "test", {}, OSError("test database offline"))
        self.assertFalse(result.persisted)
        self.assertFalse(result.queued)
        self.assertIsNone(result.stream_event_id)

    async def test_database_data_error_is_quarantined_without_blocking_good_quote(self) -> None:
        payload = self._quote_payload()
        payload["provider_id"] = "x" * 65
        bad_id = await self.store.append_persistence_event("provider_quote", "oversized-provider", payload, 1000)
        good = self._quote_payload()
        await self.store.append_persistence_event("provider_quote", good["idempotency_key"], good, 1000)
        self.assertEqual(await self.persistence.flush_stream(), {"processed": 1, "failed": 0, "quarantined": 1})
        with self.session() as db:
            self.assertEqual(db.scalar(select(func.count(ProviderQuoteRecord.id))), 1)
            self.assertEqual(db.scalar(select(PricingPersistenceEventRecord).where(PricingPersistenceEventRecord.stream_event_id == bad_id)).status, "quarantined")

    async def test_quarantine_commit_before_ack_failure_replays_idempotently(self) -> None:
        bad_id = await self.client.xadd(self.store.persistence_stream, {"event_type": "unknown", "idempotency_key": "bad", "payload": "{}"})
        good = self._quote_payload()
        good_id = await self.store.append_persistence_event("provider_quote", good["idempotency_key"], good, 1000)
        with patch.object(self.persistence, "_acknowledge_stream_event", side_effect=OSError("test ack lost")):
            self.assertEqual(await self.persistence.flush_stream(), {"processed": 0, "failed": 1, "quarantined": 1})
        self.assertEqual(await self.client.xlen(self.store.persistence_stream), 2)
        await self.client.xclaim(self.store.persistence_stream, self.persistence.consumer_group, self.persistence.consumer_name, min_idle_time=0, message_ids=[bad_id, good_id], idle=60001)
        self.assertEqual(await self.persistence.flush_stream(), {"processed": 1, "failed": 0, "quarantined": 1})
        with self.session() as db:
            self.assertEqual(db.scalar(select(func.count(PricingPersistenceEventRecord.id)).where(PricingPersistenceEventRecord.status == "quarantined")), 1)
            self.assertEqual(db.scalar(select(func.count(ProviderQuoteRecord.id))), 1)

    async def test_ack_delete_failure_cannot_leave_an_unclaimable_backlog_record(self) -> None:
        payload = self._quote_payload()
        await self.store.append_persistence_event("provider_quote", payload["idempotency_key"], payload, 1000)
        with patch.object(self.client, "xdel", side_effect=OSError("test delete connection lost")):
            await self.persistence.flush_stream()
        backlog = await self.client.xlen(self.store.persistence_stream)
        pending = (await self.client.xpending(self.store.persistence_stream, self.persistence.consumer_group))["pending"]
        self.assertTrue(backlog == 0 or pending > 0, "Acknowledged records must not remain forever outside the pending list")

    async def test_invalid_utf8_is_quarantined_losslessly_and_does_not_block_good_quote(self) -> None:
        bad_id = await self.client.xadd(self.store.persistence_stream, {b"event_type": b"provider_quote", b"idempotency_key": b"invalid-utf8", b"payload": b"\xff\x00raw"})
        good = self._quote_payload()
        await self.store.append_persistence_event("provider_quote", good["idempotency_key"], good, 1000)
        self.assertEqual(await self.persistence.flush_stream(), {"processed": 1, "failed": 0, "quarantined": 1})
        with self.session() as db:
            record = db.scalar(select(PricingPersistenceEventRecord).where(PricingPersistenceEventRecord.stream_event_id == bad_id))
            restored = {base64.b64decode(key): base64.b64decode(value) for key, value in record.payload["fields_base64"]}
            self.assertEqual(restored[b"payload"], b"\xff\x00raw")
            self.assertEqual(db.scalar(select(func.count(ProviderQuoteRecord.id))), 1)

    async def test_invalid_canonical_decimal_is_quarantined_before_good_quote(self) -> None:
        now = datetime.now(UTC)
        payload = dict(instrument_id="BTC_USD", price="100", status="live", observed_at=now.isoformat(), canonical_at=now.isoformat(), valid_until=(now + timedelta(seconds=10)).isoformat(), stale_at=(now + timedelta(seconds=20)).isoformat(), expires_at=(now + timedelta(seconds=30)).isoformat(), change_1h="not-a-decimal")
        bad_id = await self.store.append_persistence_event("canonical_quote", "bad-decimal", payload, 1000)
        good = self._quote_payload()
        await self.store.append_persistence_event("provider_quote", good["idempotency_key"], good, 1000)
        self.assertEqual(await self.persistence.flush_stream(), {"processed": 1, "failed": 0, "quarantined": 1})
        with self.session() as db:
            self.assertEqual(db.scalar(select(PricingPersistenceEventRecord).where(PricingPersistenceEventRecord.stream_event_id == bad_id)).status, "quarantined")
            self.assertEqual(db.scalar(select(func.count(ProviderQuoteRecord.id))), 1)
