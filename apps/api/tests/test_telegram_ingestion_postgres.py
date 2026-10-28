"""Real collector transactions in an exclusively owned PostgreSQL schema."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import psycopg
from psycopg.rows import dict_row, tuple_row
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.pricing.instruments import get_instrument
from app.pricing.telegram import StoredTelegramQuoteRepository
from tests.test_pricing_rights_postgres import _OwnedPostgresFixture

ROOT = Path(__file__).resolve().parents[3]
TEST_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_URL, "Requires an owned PostgreSQL test database")
class TelegramIngestionPostgresTests(_OwnedPostgresFixture, unittest.TestCase):
    owned_table_names = ("telegram_sources", "telegram_messages", "telegram_parse_results",
                         "provider_quotes", "canonical_quotes")

    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_URL)
        if url.get_backend_name() != "postgresql" or set(re.split(r"[_-]+", (url.database or "").lower())).isdisjoint({"test", "ci"}):
            raise unittest.SkipTest("Only a named test/CI database is permitted")
        sys.path.insert(0, str(ROOT))
        from apps.telegram_worker.app import worker
        cls.worker = worker
        cls.schema = "telegram_test_" + uuid.uuid4().hex
        cls.admin_engine = create_engine(url, hide_parameters=True)
        cls.public_fingerprint = cls._public_fingerprint()
        cls.addClassCleanup(cls.cleanup)
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
            migration = (ROOT/'apps/api/db/migrations/20260718_001_core_pricing.sql').read_text(encoding='utf8')
            for name in cls.owned_table_names:
                definition = re.search(r'CREATE TABLE IF NOT EXISTS public\.' + name + r' \([\s\S]*?\n\);', migration)
                if definition is None:
                    raise AssertionError("Test must use the actual immutable table definition")
                connection.exec_driver_sql(definition.group(0).replace('public.', cls.schema+'.'))
        cls.engine = create_engine(url, hide_parameters=True,
                                  connect_args={"options": f"-csearch_path={cls.schema},public"})
        cls.sessions = sessionmaker(bind=cls.engine)
        cls._install_ownership_guard()
        cls.dsn = url.set(drivername='postgresql').render_as_string(hide_password=False)

    @classmethod
    def cleanup(cls):
        if hasattr(cls, 'engine'):
            cls.engine.dispose()
        if cls._public_fingerprint() != cls.public_fingerprint:
            raise AssertionError("Public tables changed during collector tests")
        if not re.fullmatch(r'telegram_test_[0-9a-f]{32}', cls.schema):
            raise AssertionError("Refusing cleanup outside the owned schema")
        with cls.admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{cls.schema}" CASCADE')
        cls.admin_engine.dispose()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.manifest = Path(self.folder.name)/'rights.json'
        now = datetime.now(UTC)
        grant = {'permissions': ['collect', 'store', 'display', 'history'],
                 'checked_at': (now-timedelta(hours=1)).isoformat(),
                 'expires_at': (now+timedelta(days=1)).isoformat(),
                 'evidence_ref': 'https://fixture.example.test/owned-channel-permission'}
        self.manifest.write_text(json.dumps({'schema_version':1,'environment':'production',
                                             'providers':{'telegram:1':grant,'telegram:2':grant}}))
        self.environment = patch.dict(os.environ, {'PRICING_RIGHTS_MANIFEST_PATH':str(self.manifest)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        with self.engine.begin() as connection:
            for table in reversed(self.owned_table_names):
                connection.exec_driver_sql(f'DELETE FROM {table}')
            for identity, peer, kind in ((1,'-1000000000123','channel'),(2,'-12345','group')):
                connection.execute(text("""INSERT INTO telegram_sources
                    (id,channel_id,display_name,source_type,allowed_instruments,role,trust_score,parser_type,parser_version)
                    VALUES (:id,:peer,'Owned fixture',:kind,'["USDT_TOMAN"]'::jsonb,'fallback',0.8,'strict_explicit','strict-explicit-3')"""),
                    {'id':identity,'peer':peer,'kind':kind})
        self.connector = patch.object(self.worker, '_connect', side_effect=self.owned_connection)
        self.connector.start()
        self.addCleanup(self.connector.stop)
        self.hook = None

    def owned_connection(self):
        fixture = self
        class GuardCursor(psycopg.Cursor):
            def execute(self, query, params=None, **kwargs):
                # Inspect through a plain cursor to avoid recursion.
                with psycopg.Cursor(self.connection, row_factory=tuple_row) as check:
                    check.execute("""SELECT current_schema(), n.nspname FROM unnest(%s::text[]) expected(name)
                        LEFT JOIN pg_class c ON c.oid=to_regclass(name)
                        LEFT JOIN pg_namespace n ON n.oid=c.relnamespace""", (list(fixture.owned_table_names),))
                    rows = check.fetchall()
                if len(rows) != len(fixture.owned_table_names) or any(r[0] != fixture.schema or r[1] != fixture.schema for r in rows):
                    raise AssertionError("Collector connection escaped the owned schema")
                if re.search(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE)\s+public\.', str(query), re.I):
                    raise AssertionError("Refusing public mutation")
                result = super().execute(query, params, **kwargs)
                if fixture.hook:
                    fixture.hook(str(query))
                return result
        return psycopg.connect(self.dsn, row_factory=dict_row, cursor_factory=GuardCursor,
                               options=f'-csearch_path={self.schema},public -cstatement_timeout=10000 -clock_timeout=3000')

    def store(self, *, peer='-1000000000123', kind='channel', identity='10', age=0, edited=None, text_value='USDT 100000 تومان', stamp=None):
        return self.worker.store_message(channel_id=peer, username=None, chat_id=peer,
            telegram_message_id=identity, message_date=stamp or datetime.now(UTC)-timedelta(seconds=age),
            edited_at=edited, text=text_value, source_type=kind)

    def rows(self, sql):
        with self.engine.connect() as connection:
            return connection.execute(text(sql)).mappings().all()

    def test_concurrent_duplicate_writers_create_one_quote(self):
        stamp = datetime.now(UTC)
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda _: self.store(stamp=stamp), range(6)))
        self.assertEqual(outcomes.count('accepted'), 1)
        self.assertEqual(outcomes.count('duplicate'), 5)
        self.assertEqual(len(self.rows('SELECT * FROM provider_quotes')), 1)

    def test_basic_group_and_channel_same_message_id_stay_distinct(self):
        self.assertEqual(self.store(), 'accepted')
        self.assertEqual(self.store(peer='-12345',kind='group'), 'accepted')
        self.assertEqual(len(self.rows('SELECT * FROM telegram_messages')), 2)
        self.worker.delete_messages('-12345', [10])
        self.assertEqual(self.store(peer='-12345',kind='group'), 'deleted')
        self.assertEqual(self.store(), 'duplicate')
        self.assertEqual(len(self.rows("SELECT * FROM provider_quotes WHERE validation_status='accepted'")), 1)

    def test_late_edit_does_not_replace_a_newer_revision(self):
        stamp = datetime.now(UTC)-timedelta(seconds=4)
        self.store(stamp=stamp)
        self.assertEqual(self.store(stamp=stamp, edited=stamp+timedelta(seconds=2), text_value='USDT 101000 تومان'), 'accepted')
        self.assertEqual(self.store(stamp=stamp, edited=stamp+timedelta(seconds=1), text_value='USDT 99000 تومان'), 'superseded_event')
        accepted = self.rows("SELECT * FROM provider_quotes WHERE validation_status='accepted'")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(int(accepted[0]['price']), 101000)

    def test_reverting_an_edit_creates_a_valid_new_revision(self):
        stamp = datetime.now(UTC)-timedelta(seconds=5)
        self.store(stamp=stamp)
        self.store(stamp=stamp, edited=stamp+timedelta(seconds=1), text_value='USDT 101000 تومان')
        self.assertEqual(self.store(stamp=stamp, edited=stamp+timedelta(seconds=2)), 'accepted')
        accepted = self.rows("SELECT * FROM provider_quotes WHERE validation_status='accepted'")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(int(accepted[0]['price']), 100000)

    def test_changed_message_date_cannot_renew_a_price(self):
        stamp = datetime.now(UTC)-timedelta(seconds=5)
        self.store(stamp=stamp)
        self.assertEqual(self.store(stamp=stamp+timedelta(seconds=1), edited=stamp+timedelta(seconds=2),
                                    text_value='USDT 101000 تومان'), 'rejected_message_clock')

    def test_parser_policy_change_rechecks_unchanged_text_and_can_be_restored(self):
        stamp=datetime.now(UTC)-timedelta(seconds=5)
        self.store(stamp=stamp)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE telegram_sources SET parser_type='strict_hashtag',updated_at=clock_timestamp() WHERE id=1"))
        self.assertEqual(self.store(stamp=stamp),'rejected')
        self.assertEqual(self.rows("SELECT * FROM provider_quotes WHERE validation_status='accepted'"),[])
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE telegram_sources SET parser_type='strict_explicit',updated_at=clock_timestamp() WHERE id=1"))
        self.assertEqual(self.store(stamp=stamp),'accepted')
        self.assertEqual(len(self.rows("SELECT * FROM provider_quotes WHERE validation_status='accepted'")),1)

    def test_delete_before_message_leaves_a_durable_tombstone(self):
        self.worker.delete_messages('-1000000000123', [10])
        self.assertEqual(self.store(), 'deleted')
        self.assertEqual(self.rows('SELECT * FROM provider_quotes'), [])

    def test_changed_message_invalidates_its_stored_canonical(self):
        self.store()
        quote_id = self.rows('SELECT id FROM provider_quotes')[0]['id']
        with self.engine.begin() as connection:
            connection.execute(text("""INSERT INTO canonical_quotes
                (instrument_id,price,status,primary_quote_id,observed_at,valid_until,stale_at,expires_at,decision_reason,idempotency_key)
                VALUES ('USDT_TOMAN',100000,'live',:id,now(),now()+interval '1 minute',now()+interval '2 minutes',
                    now()+interval '3 minutes','owned fixture','owned-canonical')"""), {'id':quote_id})
        self.worker.delete_messages('-1000000000123', [10])
        self.assertEqual(self.rows('SELECT status FROM canonical_quotes')[0]['status'], 'stale')

    def test_fresh_cache_input_fails_after_delete_or_disabled_source(self):
        self.store()
        from types import SimpleNamespace
        quote_id = self.rows('SELECT id FROM provider_quotes')[0]['id']
        quote = SimpleNamespace(primary_quote_id=quote_id, verification_quote_ids=[],
                                source_summary={'provider_ids':['telegram:1'],'primary_provider_id':'telegram:1','derived':False})
        repository = StoredTelegramQuoteRepository()
        with patch('app.pricing.telegram.SessionLocal', self.sessions), patch('app.pricing.telegram.rights.enforced', return_value=False), patch('app.pricing.telegram.operational_pricing_settings.feature_enabled', AsyncMock(return_value=True)):
            self.assertTrue(asyncio.run(repository.canonical_inputs_valid(quote, get_instrument('USDT_TOMAN'))))
            self.worker.delete_messages('-1000000000123', [10])
            self.assertFalse(asyncio.run(repository.canonical_inputs_valid(quote, get_instrument('USDT_TOMAN'))))

    def test_old_future_and_unknown_source_do_not_create_prices(self):
        self.assertEqual(self.store(age=600), 'rejected')
        self.assertEqual(self.store(identity='11', age=-600), 'rejected_timestamp')
        self.assertEqual(self.store(peer='-1000000000999'), 'rejected_source')
        self.assertEqual(self.rows('SELECT * FROM provider_quotes'), [])

    def test_revocation_during_write_rolls_back_the_whole_transaction(self):
        def revoke(query):
            if 'INSERT INTO provider_quotes' in query:
                self.manifest.write_text('{}')
        self.hook = revoke
        self.assertEqual(self.store(), 'rejected_rights')
        self.assertEqual(self.rows('SELECT * FROM provider_quotes'), [])
        self.assertEqual(self.rows('SELECT * FROM telegram_messages'), [])
