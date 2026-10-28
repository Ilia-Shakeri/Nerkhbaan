"""Rights boundaries with fake transport and transactional SQL; no external services."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch


APP = Path(__file__).resolve().parents[1] / "app"
PACKAGE = "telegram_rights_test_app"
spec = importlib.util.spec_from_file_location(
    PACKAGE, APP / "__init__.py", submodule_search_locations=[str(APP)]
)
package = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = package
spec.loader.exec_module(package)

fake_psycopg = types.ModuleType("psycopg")
fake_psycopg.connect = Mock()
fake_rows = types.ModuleType("psycopg.rows")
fake_rows.dict_row = object()
fake_telethon = types.ModuleType("telethon")
fake_telethon.TelegramClient = Mock()


class EventFilter:
    def __init__(self, **kwargs):
        self.chats = kwargs.get("chats")


fake_telethon.events = types.SimpleNamespace(NewMessage=EventFilter, MessageEdited=EventFilter, MessageDeleted=EventFilter)
fake_sessions = types.ModuleType("telethon.sessions")
fake_sessions.StringSession = lambda value: value
with patch.dict(sys.modules, {"psycopg": fake_psycopg, "psycopg.rows": fake_rows,
                             "telethon": fake_telethon, "telethon.sessions": fake_sessions}):
    worker = importlib.import_module(f"{PACKAGE}.worker")


def policy():
    return importlib.import_module(f"{PACKAGE}.source_rights")


def grant(**changes):
    now = datetime.now(UTC)
    result = {"permissions": ["collect", "store"],
              "checked_at": (now-timedelta(hours=1)).isoformat(),
              "expires_at": (now+timedelta(days=1)).isoformat(),
              "evidence_ref": "https://rights.example.test/channel-terms"}
    result.update(changes)
    return result


def source(source_id=1):
    return {"id": source_id, "channel_id": "-100123", "username": "fixture_channel",
            "enabled": True, "maximum_message_age_seconds": 300,
            "allowed_instruments": ["USDT_TOMAN"], "parser_type": "strict_explicit", "parser_version": "strict-text-4",
            "minimum_confidence": "0.8", "role": "verifier", "trust_score": "0.8",
            "requires_multiple_sources": False}


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.response = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters=()):
        sql = " ".join(sql.split())
        self.database.statements.append((sql, parameters))
        if sql.startswith(("INSERT", "UPDATE", "DELETE")):
            self.database.pending.append(sql)
        if sql.startswith("SELECT") and "FROM telegram_sources" in sql:
            if "ANY" in sql:
                self.response = [row for row in self.database.sources if row["id"] in parameters[0]]
            else:
                self.response = next((row for row in self.database.sources
                                      if row["channel_id"] == parameters[0]), None)
        elif sql.startswith("SELECT id, message_hash"):
            self.response = self.database.existing
        elif sql.startswith("INSERT INTO provider_quotes"):
            self.response = {"id": 70}
        elif "RETURNING id" in sql:
            self.response = {"id": 40}
        else:
            self.response = None
        if self.database.on_execute:
            self.database.on_execute(sql)

    def fetchone(self):
        return self.response

    def fetchall(self):
        return self.response or []


class FakeDatabase:
    def __init__(self):
        self.sources = [source()]
        self.existing = None
        self.statements = []
        self.pending = []
        self.committed = []
        self.rollbacks = 0
        self.connections = 0
        self.on_execute = None

    def connect(self, *args, **kwargs):
        self.connections += 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, exception_type, *args):
        if exception_type:
            self.rollbacks += 1
        else:
            self.committed.extend(self.pending)
        self.pending.clear()
        return False

    def cursor(self):
        return FakeCursor(self)


class FakeEvent:
    is_channel = True

    def __init__(self, channel_id=-100123):
        self.chat_id = channel_id
        self._message = types.SimpleNamespace(id=8, date=datetime.now(UTC), edit_date=None, message="USDT 100000 تومان")
        self.raw_reads = 0
        self.metadata_requests = 0

    @property
    def message(self):
        self.raw_reads += 1
        return self._message

    @property
    def raw_text(self):
        self.raw_reads += 1
        return "USDT 100000 تومان"

    async def get_chat(self):
        self.metadata_requests += 1
        return types.SimpleNamespace(username="fixture_channel")


class FakeClient:
    def __init__(self, event=None, on_start=None):
        self.event = event
        self.on_start = on_start
        self.filters = []
        self.handlers = []
        self.starts = 0
        self.disconnects = 0

    def on(self, event_filter):
        self.filters.append(event_filter)

        def decorate(callback):
            self.handlers.append(callback)
            return callback
        return decorate

    async def connect(self):
        self.starts += 1
        if self.on_start:
            self.on_start()

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return types.SimpleNamespace(id=9001, bot=False)

    def is_connected(self):
        return self.disconnects == 0

    @property
    def disconnected(self):
        future = asyncio.get_running_loop().create_future()
        async def complete():
            if self.event:
                await self.handlers[0](self.event)
            future.set_result(None)
        asyncio.create_task(complete())
        return future

    async def disconnect(self):
        self.disconnects += 1


class ManifestFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manifest = Path(self.directory.name) / "permissions.json"
        self.environment = patch.dict(os.environ, {"PRICING_RIGHTS_MANIFEST_PATH": str(self.manifest),
            "DATABASE_URL": "postgresql://fixture/db", "TELEGRAM_API_ID": "9001",
            "TELEGRAM_STATE_PATH": str(Path(self.directory.name) / "collector.json"),
            "TELEGRAM_API_HASH": "fixture-hash", "TELEGRAM_SESSION_STRING": "fixture-session"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.write({})

    def write(self, entries, **changes):
        document = {"schema_version": 1, "environment": "production", "providers": entries}
        document.update(changes)
        self.manifest.write_text(json.dumps(document), encoding="utf-8")


class SourceRightsPolicyTests(ManifestFixture):
    def test_no_default_grant_or_disable_switch(self):
        del os.environ["PRICING_RIGHTS_MANIFEST_PATH"]
        os.environ["PRICING_RIGHTS_ENFORCED"] = "false"
        self.assertFalse(policy().source_allowed(1))
        self.assertEqual(policy().allowed_source_ids(), ())

    def test_collect_and_store_are_both_required(self):
        for permissions in (["collect"], ["store"], ["display"], ["history"], []):
            with self.subTest(permissions=permissions):
                self.write({"telegram:1": grant(permissions=permissions)})
                self.assertFalse(policy().source_allowed(1))

    def test_minimal_proved_grant_does_not_imply_display_or_history(self):
        self.write({"telegram:1": grant()})
        self.assertTrue(policy().source_allowed(1))
        self.assertFalse(policy().source_allowed(1, "display"))
        self.assertFalse(policy().source_allowed(1, "history"))

    def test_history_requires_display_like_core(self):
        self.write({"telegram:1": grant(permissions=["history"])})
        self.assertFalse(policy().source_allowed(1, "history"))
        self.write({"telegram:1": grant(permissions=["history", "display"])})
        self.assertTrue(policy().source_allowed(1, "history"))

    def test_manifest_schema_and_environment_fail_closed(self):
        for changes in ({"schema_version": 2}, {"schema_version": True},
                        {"environment": "staging"}, {"providers": []}):
            with self.subTest(changes=changes):
                self.write({"telegram:1": grant()}, **changes)
                self.assertFalse(policy().source_allowed(1))

    def test_unknown_actions_and_unproved_evidence_fail_closed(self):
        for changes in ({"permissions": ["collect", "store", "unknown"]},
                        {"permissions": "collect,store"},
                        {"evidence_ref": "http://rights.example.test"},
                        {"evidence_ref": "https://user:pass@rights.example.test"},
                        {"evidence_ref": None}):
            with self.subTest(changes=changes):
                self.write({"telegram:1": grant(**changes)})
                self.assertFalse(policy().source_allowed(1))

    def test_missing_naive_expired_future_and_overlong_times_fail_closed(self):
        now = datetime.now(UTC)
        cases = [{"checked_at": None}, {"expires_at": None},
                 {"checked_at": now.replace(tzinfo=None).isoformat()},
                 {"expires_at": now.replace(tzinfo=None).isoformat()},
                 {"expires_at": (now-timedelta(seconds=1)).isoformat()},
                 {"checked_at": (now+timedelta(hours=1)).isoformat()},
                 {"checked_at": (now-timedelta(days=1)).isoformat(),
                  "expires_at": (now+timedelta(days=366)).isoformat()}]
        for changes in cases:
            with self.subTest(changes=changes):
                self.write({"telegram:1": grant(**changes)})
                self.assertFalse(policy().source_allowed(1))

    def test_missing_relative_malformed_and_oversize_files_fail_closed(self):
        self.manifest.unlink()
        self.assertFalse(policy().source_allowed(1))
        os.environ["PRICING_RIGHTS_MANIFEST_PATH"] = "relative.json"
        self.assertFalse(policy().source_allowed(1))
        os.environ["PRICING_RIGHTS_MANIFEST_PATH"] = str(self.manifest)
        for contents in ("broken", "[]", "x"*262145):
            self.manifest.write_text(contents, encoding="utf-8")
            self.assertFalse(policy().source_allowed(1))

    def test_revoke_replace_and_unlink_take_effect_without_restart(self):
        self.write({"telegram:1": grant()})
        self.assertTrue(policy().source_allowed(1))
        self.write({})
        self.assertFalse(policy().source_allowed(1))
        self.write({"telegram:1": grant()})
        self.assertTrue(policy().source_allowed(1))
        self.manifest.unlink()
        self.assertFalse(policy().source_allowed(1))

    def test_only_canonical_source_ids_are_granted(self):
        self.write({name: grant() for name in ("telegram:1", "telegram:2", "telegram:01",
                                              "telegram:0", "telegram:unknown", "other:3")})
        self.assertEqual(policy().allowed_source_ids(), (1, 2))
        for source_id in (True, 0, -1, "01", "unknown", "telegram:1", 3):
            self.assertFalse(policy().source_allowed(source_id))

    def test_huge_source_ids_and_nontext_actions_cannot_crash_the_worker(self):
        self.write({"telegram:"+"9"*5000: grant(), "telegram:9223372036854775808": grant(),
                    "telegram:1": grant()})
        self.assertEqual(policy().allowed_source_ids(), (1,))
        self.assertFalse(policy().source_allowed("9"*5000))
        self.assertFalse(policy().source_allowed(1, []))


class WorkerRightsBoundaryTests(ManifestFixture):
    def setUp(self):
        super().setUp()
        self.database = FakeDatabase()
        self.connection = patch.object(worker.psycopg, "connect", side_effect=self.database.connect)
        self.connection.start()
        self.addCleanup(self.connection.stop)
        self.client = FakeClient()
        self.factory = patch.object(worker, "TelegramClient", return_value=self.client)
        self.factory_mock = self.factory.start()
        self.addCleanup(self.factory.stop)

    def store(self):
        return worker.store_message(channel_id="-100123", username="fixture_channel", chat_id="-100123",
            telegram_message_id="8", message_date=datetime.now(UTC), edited_at=None,
            text="USDT 100000 تومان")

    def test_no_rights_stops_before_credentials_database_and_client(self):
        for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING", "DATABASE_URL"):
            del os.environ[name]
        asyncio.run(worker.main())
        self.factory_mock.assert_not_called()
        self.assertEqual(self.database.connections, 0)

    def test_direct_message_denied_before_hash_parse_or_database(self):
        with patch.object(worker, "message_hash") as hashed, patch.object(worker, "parse_message") as parsed:
            self.assertEqual(self.store(), "rejected_rights")
        hashed.assert_not_called()
        parsed.assert_not_called()
        self.assertEqual(self.database.connections, 0)

    def test_other_granted_source_does_not_authorize_this_source(self):
        self.write({"telegram:2": grant()})
        with patch.object(worker, "parse_message") as parsed:
            self.assertEqual(self.store(), "rejected_rights")
        parsed.assert_not_called()
        self.assertEqual(self.database.committed, [])

    def test_unknown_channel_never_writes_runtime_event_or_message(self):
        self.write({"telegram:1": grant()})
        self.database.sources = []
        self.assertEqual(self.store(), "rejected_source")
        self.assertEqual(self.database.committed, [])

    def test_one_permission_does_not_open_message_collection(self):
        for permissions in (["collect"], ["store"]):
            self.write({"telegram:1": grant(permissions=permissions)})
            self.assertEqual(self.store(), "rejected_rights")
        self.assertEqual(self.database.connections, 0)

    def test_valid_grant_preserves_message_parse_and_quote_transaction(self):
        self.write({"telegram:1": grant()})
        self.assertEqual(self.store(), "accepted")
        for table in ("telegram_messages", "telegram_parse_results", "provider_quotes"):
            self.assertTrue(any(f"INSERT INTO {table}" in sql for sql in self.database.committed))

    def test_revocation_after_source_lookup_prevents_hash_and_writes(self):
        self.write({"telegram:1": grant()})
        self.database.on_execute = lambda sql: self.write({}) if "FROM telegram_sources" in sql else None
        with patch.object(worker, "message_hash") as hashed:
            self.assertEqual(self.store(), "rejected_rights")
        hashed.assert_not_called()
        self.assertEqual(self.database.committed, [])

    def test_revocation_after_raw_insert_rolls_back_before_parser(self):
        self.write({"telegram:1": grant()})
        self.database.on_execute = lambda sql: self.write({}) if sql.startswith("INSERT INTO telegram_messages") else None
        with patch.object(worker, "parse_message") as parsed:
            self.assertEqual(self.store(), "rejected_rights")
        parsed.assert_not_called()
        self.assertEqual(self.database.committed, [])
        self.assertEqual(self.database.rollbacks, 1)

    def test_revocation_after_quote_insert_rolls_back_all_staged_rows(self):
        self.write({"telegram:1": grant()})
        self.database.on_execute = lambda sql: self.write({}) if sql.startswith("INSERT INTO provider_quotes") else None
        self.assertEqual(self.store(), "rejected_rights")
        self.assertEqual(self.database.committed, [])
        self.assertEqual(self.database.rollbacks, 1)

    def test_parse_result_entry_point_denies_before_sql(self):
        quote = worker.ParsedTelegramQuote(None, None, None, None, None, 0, "rejected", "fixture")
        with self.assertRaises(worker.SourceRightsRevoked):
            worker._store_parse_result(FakeCursor(self.database), source(), 40, quote, "fixture")
        self.assertEqual(self.database.statements, [])

    def test_unlicensed_edit_never_supersedes_existing_quote(self):
        self.write({"telegram:2": grant()})
        self.database.existing = {"id": 40, "message_hash": "old"}
        self.assertEqual(self.store(), "rejected_rights")
        self.assertEqual(self.database.committed, [])

    def test_no_enabled_licensed_source_prevents_client_construction(self):
        self.write({"telegram:1": grant()})
        self.database.sources = []
        asyncio.run(worker.main())
        self.factory_mock.assert_not_called()

    def test_unknown_event_dropped_before_raw_text_or_network_metadata(self):
        self.write({"telegram:1": grant()})
        event = FakeEvent(-100999)
        self.client.event = event
        asyncio.run(worker.main())
        self.assertEqual(self.client.starts, 1)
        self.assertEqual(event.raw_reads, 0)
        self.assertEqual(event.metadata_requests, 0)
        self.assertEqual(len(self.client.filters), 3)
        self.assertEqual(self.database.committed, [])

    def test_granted_event_persists_without_network_metadata_request(self):
        self.write({"telegram:1": grant()})
        event = FakeEvent()
        self.client.event = event
        asyncio.run(worker.main())
        self.assertEqual(event.raw_reads, 1)
        self.assertEqual(event.metadata_requests, 0)
        self.assertTrue(any("INSERT INTO provider_quotes" in sql for sql in self.database.committed))

    def test_revoked_event_dropped_before_raw_text_or_network_metadata(self):
        self.write({"telegram:1": grant()})
        event = FakeEvent()
        self.client.event = event
        self.client.on_start = lambda: self.write({})
        asyncio.run(worker.main())
        self.assertEqual(event.raw_reads, 0)
        self.assertEqual(event.metadata_requests, 0)
        self.assertEqual(self.database.committed, [])

    def test_permission_rechecked_immediately_before_connect(self):
        self.write({"telegram:1": grant()})
        with patch.object(worker, "StringSession", side_effect=lambda value: (self.write({}), value)[1]):
            asyncio.run(worker.main())
        self.assertEqual(self.client.starts, 0)

    def test_watchdog_disconnects_when_all_sources_revoked(self):
        asyncio.run(worker._watch_source_rights(self.client, [source()]))
        self.assertEqual(self.client.disconnects, 1)


if __name__ == "__main__":
    unittest.main()
