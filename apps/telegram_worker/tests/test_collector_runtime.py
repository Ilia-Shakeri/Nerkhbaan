"""Collector failure boundaries with owned fake transport; never logs in."""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
import json
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.telegram_worker.app import runtime
from apps.telegram_worker.app.state import CollectorState
from apps.telegram_worker.app.healthcheck import healthy
from telethon.tl.types import PeerChannel, PeerChat


def message(identity=10, *, age=0, peer=None, text="USDT 100000 تومان"):
    return SimpleNamespace(id=identity, date=datetime.now(UTC)-timedelta(seconds=age), edit_date=None,
                           message=text, peer_id=peer or PeerChannel(123))


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/"state.json"
        self.source = {"id": 1, "channel_id": "-1000000000123", "source_type": "channel",
                       "username": "fixture_channel", "maximum_message_age_seconds": 300}
        self.storage = SimpleNamespace(_eligible_sources=Mock(return_value=[self.source]),
                                       store_message=Mock(return_value="accepted"),
                                       delete_messages=Mock(), reconcile_ids=Mock(return_value=[]))
        self.client = Mock()
        self.client.get_messages = AsyncMock(return_value=[])
        self.client.get_entity = AsyncMock(return_value=PeerChannel(123))
        self.collector = runtime.Collector(self.client, self.storage)
        self.collector.state = CollectorState(str(self.path), 9001)
        self.addCleanup(self.collector.state.close)
        self.collector.ready = True
        self.permissions = patch.object(runtime.source_rights, "source_allowed", return_value=True)
        self.permissions.start()
        self.addCleanup(self.permissions.stop)
        await self.collector.refresh_sources()
        self.items = []
        async def iterator(*args, **kwargs):
            for item in self.items:
                yield item
        self.client.iter_messages = iterator

    async def test_unlisted_peer_and_private_message_never_touch_text(self):
        event = Mock(chat_id=123, is_channel=False, is_group=False)
        await self.collector.message(event)
        self.storage.store_message.assert_not_called()
        self.client.get_entity.assert_not_called()

    async def test_event_waits_for_session_and_account_binding(self):
        self.collector.ready = False
        await self.collector.message(SimpleNamespace(chat_id=-1000000000123, is_channel=True))
        self.storage.store_message.assert_not_called()

    async def test_basic_group_keeps_its_peer_identity(self):
        self.source.update(channel_id="-12345", source_type="group", username=None)
        await self.collector.refresh_sources()
        await self.collector.message(SimpleNamespace(chat_id=-12345, is_channel=False, is_group=True,
                                                      message=message(peer=PeerChat(12345))))
        self.assertEqual(self.storage.store_message.call_args.kwargs['channel_id'], "-12345")
        self.assertEqual(self.storage.store_message.call_args.kwargs['source_type'], "group")

    async def test_new_and_edited_event_share_storage_version_checks(self):
        event = SimpleNamespace(chat_id=-1000000000123, is_channel=True, message=message())
        await self.collector.message(event)
        event.message.edit_date = datetime.now(UTC)
        await self.collector.message(event)
        self.assertEqual(self.storage.store_message.call_count, 2)
        self.assertIsNotNone(self.storage.store_message.call_args.kwargs['edited_at'])

    async def test_forwarded_price_keeps_original_clock_and_origin(self):
        item=message()
        original=datetime.now(UTC)-timedelta(seconds=600)
        item.fwd_from=SimpleNamespace(date=original,from_id=PeerChannel(456))
        await self.collector.store(self.source,item)
        values=self.storage.store_message.call_args.kwargs
        self.assertEqual(values['message_date'],original)
        first=values['origin_identity']
        other=dict(self.source,id=2,channel_id='-1000000000789')
        self.storage._eligible_sources.return_value=[self.source,other]
        await self.collector.refresh_sources()
        await self.collector.store(other,item)
        self.assertEqual(self.storage.store_message.call_args.kwargs['origin_identity'],first)

    async def test_anonymous_forward_cannot_claim_a_fresh_independent_rate(self):
        item=message()
        item.fwd_from=SimpleNamespace(date=datetime.now(UTC),from_id=None)
        self.assertEqual(await self.collector.store(self.source,item),'rejected_forward_identity')
        self.storage.store_message.assert_not_called()

    async def test_peerless_deletion_does_not_guess_basic_group(self):
        await self.collector.deleted(SimpleNamespace(chat_id=None, deleted_ids=[10]))
        self.storage.delete_messages.assert_not_called()

    async def test_known_peer_deletion_is_scoped(self):
        await self.collector.deleted(SimpleNamespace(chat_id=-1000000000123, deleted_ids=[10]))
        self.storage.delete_messages.assert_called_once_with("-1000000000123", [10])

    async def test_missing_from_limited_history_does_not_mean_deleted(self):
        self.items = [message(11)]
        self.storage.reconcile_ids.return_value = [10]
        self.client.get_messages.return_value = [message(10)]
        await self.collector.recover(self.source)
        self.storage.delete_messages.assert_not_called()
        self.assertTrue(healthy(str(self.path)))

    async def test_explicit_absence_retracts_known_message(self):
        self.storage.reconcile_ids.return_value = [10]
        self.client.get_messages.return_value = [None]
        await self.collector.recover(self.source)
        self.storage.delete_messages.assert_called_once_with("-1000000000123", [10])

    async def test_foreign_reconciliation_peer_never_gets_stored(self):
        self.storage.reconcile_ids.return_value = [10]
        self.client.get_messages.return_value = [message(10, peer=PeerChat(12))]
        with self.assertRaisesRegex(ValueError, "identity"):
            await self.collector.recover(self.source)
        self.storage.store_message.assert_not_called()
        self.storage.delete_messages.assert_not_called()

    async def test_history_permission_is_checked_before_network(self):
        with patch.object(runtime.source_rights, "source_allowed", return_value=False):
            await self.collector.recover(self.source)
        self.client.get_entity.assert_not_called()

    async def test_changed_username_never_fetches_messages(self):
        self.client.get_entity.return_value = PeerChannel(999)
        await self.collector.cycle()
        self.storage.store_message.assert_not_called()
        self.assertFalse(healthy(str(self.path)))

    async def test_history_limit_marks_gap_and_does_not_claim_health(self):
        self.collector.limit = 2
        self.items = [message(13), message(12), message(11)]
        await self.collector.recover(self.source)
        self.assertEqual(self.storage.store_message.call_count, 2)
        self.assertFalse(healthy(str(self.path)))
        self.assertEqual(self.collector.state.data['sources']['1']['result'], "recovery_limit_reached")

    async def test_old_history_is_not_replayed_as_current(self):
        self.items = [message(11), message(10, age=500)]
        await self.collector.recover(self.source)
        self.assertEqual(self.storage.store_message.call_count, 1)

    async def test_recovery_repeats_overlap_after_restart(self):
        self.items = [message(11)]
        await self.collector.recover(self.source)
        self.collector.state.close()
        self.collector.state = CollectorState(str(self.path), 9001)
        self.addCleanup(self.collector.state.close)
        await self.collector.recover(self.source)
        self.assertEqual(self.storage.store_message.call_count, 2)

    async def test_flood_wait_has_per_source_cooldown(self):
        error = RuntimeError("private provider text must not be logged")
        error.seconds = 900
        self.client.get_entity.side_effect = error
        with self.assertLogs("telegram_worker", level="WARNING") as captured:
            await self.collector.cycle()
            await self.collector.cycle()
        self.assertNotIn("private provider text", str(captured.output))
        self.assertEqual(self.client.get_entity.await_count, 1)
        self.assertFalse(healthy(str(self.path)))

    async def test_disabled_sources_removed_without_restart(self):
        self.storage._eligible_sources.return_value = []
        await self.collector.cycle()
        self.assertEqual(self.collector.sources, {})
        self.assertFalse(healthy(str(self.path)))

    async def test_event_queue_is_bounded_and_overflow_is_not_healthy(self):
        self.collector.queue = asyncio.Queue(maxsize=1)
        event = SimpleNamespace(chat_id=-1000000000123)
        self.collector.enqueue('message',event)
        self.collector.enqueue('message',event)
        self.assertEqual(self.collector.queue.qsize(),1)
        self.assertFalse(healthy(str(self.path)))

    async def test_one_slow_source_does_not_hold_a_fast_source(self):
        other = dict(self.source,id=2,channel_id='-1000000000456')
        self.storage._eligible_sources.return_value = [self.source,other]
        fast = asyncio.Event()
        slow = asyncio.Event()
        async def recover(source):
            if source['id'] == 1:
                await slow.wait()
            else:
                fast.set()
        self.collector.recover = AsyncMock(side_effect=recover)
        self.client.is_connected.return_value = True
        task = asyncio.create_task(self.collector.poll())
        try:
            await asyncio.wait_for(fast.wait(),timeout=1)
            self.assertFalse(self.collector.jobs[self.source['channel_id']].done())
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def test_invalid_session_never_attempts_interactive_login(self):
        self.client.connect = AsyncMock()
        self.client.disconnect = AsyncMock()
        self.client.is_user_authorized = AsyncMock(return_value=False)
        self.collector.event_types = SimpleNamespace(NewMessage=Mock(),MessageEdited=Mock(),MessageDeleted=Mock())
        with self.assertRaisesRegex(RuntimeError,'authorized'):
            await self.collector.run()
        self.client.start.assert_not_called()
        self.client.get_me.assert_not_called()

    async def test_lost_basic_group_binding_is_not_silently_recreated(self):
        self.source.update(channel_id='-12345',source_type='group',username=None)
        self.collector.state.close()
        self.collector.state = None
        self.path.unlink()
        self.storage.has_group_history = Mock(return_value=True)
        self.client.connect = AsyncMock()
        self.client.disconnect = AsyncMock()
        self.client.is_user_authorized = AsyncMock(return_value=True)
        self.client.get_me = AsyncMock(return_value=SimpleNamespace(id=9001,bot=False))
        self.collector.event_types = SimpleNamespace(NewMessage=Mock(),MessageEdited=Mock(),MessageDeleted=Mock())
        with patch.dict(runtime.os.environ,{'TELEGRAM_STATE_PATH':str(self.path)}):
            with self.assertRaisesRegex(RuntimeError,'binding'):
                await self.collector.run()
        self.assertFalse(self.path.exists())


class StateTests(unittest.TestCase):
    def test_private_login_saves_session_without_printing_it(self):
        from apps.telegram_worker import login
        class Client:
            session=SimpleNamespace(save=lambda:'owned-fixture-session-not-real')
            async def __aenter__(self):
                return self
            async def __aexit__(self,*args):
                return False
            async def get_me(self):
                return SimpleNamespace(bot=False)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'private.env'
            path.write_text('TELEGRAM_API_ID=9001\nTELEGRAM_API_HASH='+'a'*32+'\n')
            captured=io.StringIO()
            with patch.object(sys,'argv',['login','--env-file',str(path)]), patch.object(login,'TelegramClient',return_value=Client()), redirect_stdout(captured):
                asyncio.run(login.main())
            self.assertNotIn('owned-fixture-session-not-real',captured.getvalue())
            self.assertEqual(login.read_environment(path)['TELEGRAM_SESSION_STRING'],'owned-fixture-session-not-real')

    def test_account_change_fails_and_original_state_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"state.json"
            first = CollectorState(str(path), 9001)
            first.receipt(1, result="reconciled", checked_at=datetime.now(UTC).isoformat())
            first.close()
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "identity"):
                CollectorState(str(path), 9002)
            self.assertEqual(path.read_bytes(), before)
            again = CollectorState(str(path), 9001)
            again.close()

    def test_health_rejects_expired_future_empty_and_bad_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"state.json"
            state = CollectorState(str(path), 9001)
            self.addCleanup(state.close)
            self.assertFalse(healthy(str(path)))
            for age in (181, -1):
                state.receipt(1, result="reconciled", checked_at=(datetime.now(UTC)-timedelta(seconds=age)).isoformat())
                self.assertFalse(healthy(str(path)))
            path.write_text(json.dumps([]))
            self.assertFalse(healthy(str(path)))
