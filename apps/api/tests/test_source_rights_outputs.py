from __future__ import annotations

import asyncio
import copy
import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, WebSocketDisconnect
from sqlalchemy import MetaData, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET_KEY", "source-rights-test-secret-not-for-runtime-000000000")

from app.models import Alert, AlertDeliveryJob, AlertTriggerEvent, User, UserNotification
from app.pricing import rights
from app.pricing.models import CanonicalQuote, CanonicalStatus
from app.pricing.websocket import PriceWebSocketHub
from app.routers import notifications
from app.services.alert_engine import Alert as DeliveryAlert, AlertEngine, PermanentDeliveryError
from app.services.dlq_worker import DLQWorker
from app.services.insights import InsightUnavailableError, MarketInsightEngine


APPROVED = "gold_api_free_xau"
DENIED = "unreviewed_market_source"


def _summary(provider=APPROVED):
    return {"primary_provider_id": provider, "provider_ids": [provider], "derived": False}


def _asset(provider=APPROVED):
    return {
        "asset": "gold", "price_usd": 2080, "usd_status": "live",
        "usd_source_semantic": "reference_rate", "usd_source_summary": {"source_semantic": "reference_rate"},
        "_usd_rights_source_summary": _summary(provider),
        "usd_is_persisted": True, "usd_persistence_status": "persisted",
        "usd_live_eligible": True, "usd_is_suspicious": False, "usd_expired": False,
        "usd_derivation_depth": 0,
    }


def _grant(*extra):
    now = datetime.now(UTC)
    return {"permissions": ["collect", "store", "display", "history", "derive", *extra],
            "checked_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "evidence_ref": "https://rights.fixture.invalid/terms",
            "attribution": {"label": "Fixture market", "url": "https://rights.fixture.invalid/"}}


class SourceRightsOutputTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(patch.object(rights.settings, "pricing_rights_enforced", True))
        self.grants = {APPROVED: _grant()}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.engine = create_engine("sqlite://", poolclass=StaticPool,
                                    connect_args={"check_same_thread": False})
        metadata = MetaData()
        for model in (User, Alert, AlertTriggerEvent, AlertDeliveryJob, UserNotification):
            model.__table__.to_metadata(metadata)
        metadata.create_all(self.engine)

        class LocalSession(Session):
            pass

        counters = {AlertTriggerEvent: 0, AlertDeliveryJob: 0, UserNotification: 0}

        @event.listens_for(LocalSession, "before_flush")
        def assign_local_ids(db, _context, _instances):
            # SQLite does not auto-increment the PostgreSQL BIGINT primary keys.
            for row in db.new:
                kind = type(row)
                if kind in counters and row.id is None:
                    counters[kind] += 1
                    row.id = counters[kind]

        self.session = sessionmaker(bind=self.engine, class_=LocalSession, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        with self.session() as db:
            db.add(User(id=1, username="rights_owner", full_name="Fixture owner",
                        email="rights@example.invalid", password_hash="fixture"))
            db.add(Alert(id=1, user_id=1, asset="gold", target_price=1900, currency_mode="usd",
                         price_source_mode="reference", condition="above", mode="recurring",
                         notify_app=True, notify_webhook=True, webhook_url="https://hook.fixture.invalid/",
                         notify_email=False, notify_telegram=False, notifications_today=0))
            db.commit()

    def queue(self, assets=None, *, formula=None):
        with self.session() as db:
            row = db.get(Alert, 1)
            if formula:
                row.alert_type, row.formula = "formula", formula
            AlertEngine()._queue_trigger(
                db, row, {"assets": [_asset()] if assets is None else assets}, datetime.now(UTC),
                preferences=SimpleNamespace(push_app=True), push_available=False,
            )
            db.commit()
            occurrence = db.scalar(select(AlertTriggerEvent).order_by(AlertTriggerEvent.id.desc()))
            return occurrence.id if occurrence else None

    def deliver(self, occurrence_id):
        with self.session() as db:
            job = db.scalar(select(AlertDeliveryJob).where(AlertDeliveryJob.trigger_event_id == occurrence_id))
            job.status, job.attempt_count = "processing", 1
            db.commit()
            job_id = job.id
        sender = AlertEngine()
        sender._send_webhook = AsyncMock()
        return sender, job_id

    def test_unapproved_quote_cannot_trigger_or_create_market_notification(self):
        asset = _asset(DENIED)
        self.assertFalse(AlertEngine()._asset_is_operational(asset, "usd", "reference"))
        self.assertIsNone(self.queue([asset]))
        with self.session() as db:
            self.assertEqual(list(db.scalars(select(UserNotification))), [])

    def test_missing_provenance_cannot_enter_delivery_queue(self):
        asset = _asset()
        asset["_usd_rights_source_summary"] = {"source_family": "legacy"}
        self.assertIsNone(self.queue([asset]))

    def test_public_summary_is_never_accepted_as_internal_source_proof(self):
        asset = _asset()
        asset.pop("_usd_rights_source_summary")
        asset["usd_source_summary"] = _summary()
        self.assertIsNone(self.queue([asset]))

    def test_queue_keeps_full_source_proof_and_links_notification_to_occurrence(self):
        assets = [_asset()]
        event_id = self.queue(assets)
        assets[0]["_usd_rights_source_summary"]["provider_ids"].append(DENIED)
        with self.session() as db:
            occurrence = db.get(AlertTriggerEvent, event_id)
            self.assertEqual(occurrence.condition_snapshot["assets"][0]["_usd_rights_source_summary"], _summary())
            notice = db.scalar(select(UserNotification))
            self.assertEqual((notice.resource_type, notice.resource_id), ("alert_trigger", str(event_id)))

    def test_revoked_queued_source_is_dead_before_any_transport_without_deleting_occurrence(self):
        event_id = self.queue()
        sender, job_id = self.deliver(event_id)
        self.grants.clear()
        with patch("app.services.alert_engine.SessionLocal", self.session), \
                patch("app.services.dlq_worker.SessionLocal", self.session):
            asyncio.run(DLQWorker(sender)._process_job(job_id, 1))
        sender._send_webhook.assert_not_awaited()
        with self.session() as db:
            self.assertEqual(db.get(AlertDeliveryJob, job_id).status, "dead")
            self.assertEqual(db.get(AlertTriggerEvent, event_id).price, 2080)

    def test_approved_queued_source_still_sends_original_price(self):
        event_id = self.queue()
        sender, job_id = self.deliver(event_id)
        with patch("app.services.alert_engine.SessionLocal", self.session):
            result = asyncio.run(sender.deliver_job(job_id, expected_attempt=1))
        self.assertEqual(result, {"channel": "webhook", "accepted": True})
        sender._send_webhook.assert_awaited_once()
        self.assertEqual(sender._send_webhook.await_args.args[1]["assets"][0]["price_usd"], 2080)

    def test_notification_body_and_external_context_carry_safe_source_credit_without_private_ids(self):
        event_id = self.queue()
        with self.session() as db:
            notice = db.scalar(select(UserNotification))
            snapshot = db.get(AlertTriggerEvent, event_id).condition_snapshot
            self.assertIn("Fixture market", notice.message)
            self.assertIn("https://rights.fixture.invalid/", notice.message)
            context = AlertEngine()._selected_price_context(DeliveryAlert(**snapshot["delivery_alert"]), snapshot)
            self.assertEqual(context["attribution"], [{"label": "Fixture market", "url": "https://rights.fixture.invalid/"}])
            self.assertNotIn(APPROVED, json.dumps(context))

    def test_legacy_queue_without_source_proof_never_sends_in_strict_mode(self):
        event_id = self.queue()
        with self.session() as db:
            occurrence = db.get(AlertTriggerEvent, event_id)
            snapshot = copy.deepcopy(occurrence.condition_snapshot)
            snapshot["assets"][0].pop("_usd_rights_source_summary")
            snapshot.pop("selected_price_context", None)
            occurrence.condition_snapshot = snapshot
            db.commit()
        sender, job_id = self.deliver(event_id)
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(sender.deliver_job(job_id, expected_attempt=1))
        sender._send_webhook.assert_not_awaited()

    def test_formula_rechecks_all_contributors_when_one_permission_is_withdrawn(self):
        self.grants[DENIED] = _grant()
        btc = dict(_asset(DENIED), asset="btc", price_usd=60000)
        event_id = self.queue([_asset(), btc], formula="gold + btc > x")
        sender, job_id = self.deliver(event_id)
        del self.grants[DENIED]
        with patch("app.services.alert_engine.SessionLocal", self.session), self.assertRaises(PermanentDeliveryError):
            asyncio.run(sender.deliver_job(job_id, expected_attempt=1))
        sender._send_webhook.assert_not_awaited()

    def test_formula_dollar_alias_keeps_the_usd_source_proof(self):
        usd = dict(_asset(), asset="usd", price_usd=1)
        self.assertIsNotNone(self.queue([usd], formula="dollar > x"))

    def test_notification_list_hides_legacy_unknown_and_revoked_market_data_but_keeps_security(self):
        event_id = self.queue()
        with self.session() as db:
            db.add_all([
                UserNotification(user_id=1, title="Old market price", message="2080", resource_type="alert", resource_id="1"),
                UserNotification(user_id=1, title="Unknown old notice", message="2080"),
                UserNotification(user_id=1, title="Password changed", message="Account secured", resource_type="security"),
            ])
            db.commit()
            visible = notifications.list_notifications(limit=100, offset=0, current_user=SimpleNamespace(id=1), db=db)
            self.assertEqual({row.resource_type for row in visible}, {"security", "alert_trigger"})
            self.grants.clear()
            visible = notifications.list_notifications(limit=100, offset=0, current_user=SimpleNamespace(id=1), db=db)
            self.assertEqual([row.title for row in visible], ["Password changed"])
            self.assertEqual(db.get(AlertTriggerEvent, event_id).price, 2080)

    def test_mark_read_does_not_return_price_after_permission_revocation(self):
        self.queue()
        with self.session() as db:
            notice_id = db.scalar(select(UserNotification.id))
            self.grants.clear()
            with self.assertRaises(HTTPException) as raised:
                notifications.mark_notification_read(notice_id, current_user=SimpleNamespace(id=1), db=db)
            self.assertEqual(raised.exception.status_code, 404)
            self.assertIsNone(db.get(UserNotification, notice_id).read_at)

    def test_hidden_rows_do_not_consume_notification_page_limit_or_offset(self):
        event_id = self.queue()
        self.grants.clear()
        with self.session() as db:
            db.add(UserNotification(user_id=1, title="Password changed", message="Account secured",
                                    resource_type="security", created_at=datetime(2000, 1, 1, tzinfo=UTC)))
            for _ in range(205):
                db.add(UserNotification(user_id=1, title="Old price", message="2080",
                                        resource_type="alert_trigger", resource_id=str(event_id)))
            db.commit()
            visible = notifications.list_notifications(limit=1, offset=0, current_user=SimpleNamespace(id=1), db=db)
            self.assertEqual([row.title for row in visible], ["Password changed"])
            self.assertEqual(notifications.list_notifications(limit=1, offset=1,
                             current_user=SimpleNamespace(id=1), db=db), [])

    def test_notice_cannot_borrow_another_owners_approved_occurrence(self):
        event_id = self.queue()
        with self.session() as db:
            db.add(User(id=2, username="other_owner", full_name="Other owner",
                        email="other@example.invalid", password_hash="fixture"))
            db.add(UserNotification(user_id=2, title="Borrowed price", message="2080",
                                    resource_type="alert_trigger", resource_id=str(event_id)))
            db.commit()
            self.assertEqual(notifications.list_notifications(limit=100, offset=0,
                             current_user=SimpleNamespace(id=2), db=db), [])

    def test_email_rechecks_permission_inside_the_sending_thread(self):
        event_id = self.queue()
        with self.session() as db:
            snapshot = db.get(AlertTriggerEvent, event_id).condition_snapshot
        alert = DeliveryAlert(**snapshot["delivery_alert"])
        fake_db = Mock()
        fake_db.scalar.return_value = SimpleNamespace(email_enabled=True, email_verified=True,
                                                      email_address="fixture@example.invalid")
        mail = Mock()

        async def run_thread(function, *args, **kwargs):
            self.grants.clear()
            return function(*args, **kwargs)

        with patch("app.services.alert_engine.SessionLocal", return_value=fake_db), \
                patch("app.services.alert_engine.settings", SimpleNamespace(smtp_host="fixture.invalid", smtp_from="fixture@example.invalid")), \
                patch("app.services.alert_engine.send_smtp_message", mail), \
                patch("app.services.alert_engine.asyncio.to_thread", side_effect=run_thread):
            with self.assertRaises(PermanentDeliveryError):
                asyncio.run(AlertEngine()._send_email(alert, snapshot))
        mail.assert_not_called()

    def test_telegram_rechecks_permission_after_client_entry_before_post(self):
        event_id = self.queue()
        with self.session() as db:
            snapshot = db.get(AlertTriggerEvent, event_id).condition_snapshot
        alert = DeliveryAlert(**snapshot["delivery_alert"])
        fake_db = Mock()
        fake_db.scalar.return_value = SimpleNamespace(telegram_enabled=True, telegram_verified=True,
                                                      telegram_id="123456789", silent_mode=True)
        post = AsyncMock(return_value=SimpleNamespace(status_code=200, raise_for_status=Mock()))
        grants = self.grants

        class FakeClient:
            async def __aenter__(self):
                grants.clear()
                return SimpleNamespace(post=post)

            async def __aexit__(self, *_args):
                pass

        configured = SimpleNamespace(telegram_alert_delivery_enabled=True, telegram_bot_token="fixture-token")
        with patch("app.services.alert_engine.SessionLocal", return_value=fake_db), \
                patch("app.services.alert_engine.settings", configured), \
                patch("app.services.alert_engine.httpx.AsyncClient", return_value=FakeClient()):
            with self.assertRaises(PermanentDeliveryError):
                asyncio.run(AlertEngine()._send_telegram(alert, snapshot))
        post.assert_not_awaited()


class SourceRightsStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(rights.settings, "pricing_rights_enforced", True))
        self.grants = {APPROVED: _grant()}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))

    def quote(self, provider=APPROVED):
        now = datetime.now(UTC)
        return CanonicalQuote.create(
            instrument_id="XAU_USD_OZ", price=2080, status=CanonicalStatus.LIVE, primary_quote_id=None,
            verification_quote_ids=[], source_summary=_summary(provider), observed_at=now,
            canonical_at=now, valid_until=now + timedelta(seconds=60),
            stale_at=now + timedelta(seconds=120), expires_at=now + timedelta(seconds=240),
            is_persisted=True, decision_reason="fixture", sequence_number=1,
        )

    async def test_explicit_snapshot_cannot_bypass_current_source_permission(self):
        quote = self.quote(DENIED)
        store = SimpleNamespace(ping=AsyncMock(return_value=True), get_all_canonical=AsyncMock(return_value={}))
        hub = PriceWebSocketHub(store=store)
        hub._dispatch_forever, hub._event_loop = AsyncMock(), AsyncMock()
        socket = SimpleNamespace(accept=AsyncMock(), close=AsyncMock(), send_json=AsyncMock())
        await hub.serve(socket, {quote.instrument_id: quote})
        self.assertEqual(socket.send_json.await_args.args[0]["prices"], [])

    async def test_legacy_candidate_outside_summary_cannot_bypass_snapshot_permission(self):
        quote = self.quote()
        quote.candidate_price, quote.candidate_provider_id = 9999, DENIED
        hub = PriceWebSocketHub(store=AsyncMock())
        hub._dispatch_forever, hub._event_loop = AsyncMock(), AsyncMock()
        socket = SimpleNamespace(accept=AsyncMock(), close=AsyncMock(), send_json=AsyncMock())
        await hub.serve(socket, {quote.instrument_id: quote})
        self.assertEqual(socket.send_json.await_args.args[0]["prices"], [])

    async def test_old_stream_percentages_without_baseline_proof_are_not_published(self):
        quote = self.quote()
        quote.change_1h, quote.change_24h, quote.change_7d, quote.change_30d = 1, 2, 3, 4
        payload = PriceWebSocketHub._public_event(quote)
        for field in ("change_1h", "change_24h", "change_7d", "change_30d"):
            self.assertIsNone(payload[field])
        self.assertEqual(quote.change_24h, 2)

    async def test_old_pubsub_payload_never_reaches_socket_without_permission(self):
        quotes = [self.quote(DENIED), self.quote()]
        messages = asyncio.Queue()
        for quote in quotes:
            messages.put_nowait({"type": "message", "data": json.dumps(quote.to_dict())})
        blocked = asyncio.Event()

        async def receive(**_kwargs):
            if messages.empty():
                blocked.set()
            return await messages.get()

        pubsub = SimpleNamespace(get_message=receive, unsubscribe=AsyncMock(), aclose=AsyncMock())
        store = SimpleNamespace(subscribe=AsyncMock(return_value=pubsub), events_channel="fixture")
        hub = PriceWebSocketHub(store=store, snapshot_reader=AsyncMock(return_value={}))
        queue = asyncio.Queue()
        hub._clients["fixture"] = queue
        task = asyncio.create_task(hub._dispatch_forever())
        await asyncio.wait_for(blocked.wait(), 1)
        async def receive_text():
            await asyncio.Event().wait()

        socket = SimpleNamespace(receive_text=receive_text)
        sent = []

        async def send(payload):
            sent.append(payload)
            if any(item.get("price") == 2080 for item in sent):
                raise WebSocketDisconnect()

        socket.send_json = send
        try:
            with self.assertRaises(WebSocketDisconnect):
                await asyncio.wait_for(hub._event_loop(socket, queue, {"XAU_USD_OZ"}), 1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        prices = [item for item in sent if item.get("price") is not None]
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0].get("attribution"), [{"label": "Fixture market", "url": "https://rights.fixture.invalid/"}])
        self.assertNotIn("primary_provider_id", json.dumps(sent))

    async def test_permission_withdrawn_after_queueing_clears_socket_instead_of_sending_price(self):
        quote = self.quote()
        hub = PriceWebSocketHub(store=AsyncMock(), snapshot_reader=AsyncMock(return_value={quote.instrument_id: quote}))
        queue = asyncio.Queue()
        queue.put_nowait({"event_type": "canonical_quote", "quote": quote})
        self.grants.clear()
        sent = []

        async def receive_text():
            await asyncio.Event().wait()

        async def send(payload):
            sent.append(payload)
            raise WebSocketDisconnect()

        socket = SimpleNamespace(receive_text=receive_text, send_json=send)
        with self.assertRaises(WebSocketDisconnect):
            await asyncio.wait_for(hub._event_loop(socket, queue, {quote.instrument_id}), 1)
        self.assertEqual(sent, [{"event_type": "snapshot", "type": "snapshot",
                                "reason": "source_permission_changed", "rights_revision": rights.revision(), "prices": []}])

    async def test_external_analysis_without_specific_right_never_calls_provider_or_quota(self):
        engine = MarketInsightEngine()
        engine._complete, engine._check_quota = AsyncMock(return_value="not sent"), unittest.mock.Mock()
        with self.assertRaisesRegex(InsightUnavailableError, "permission"):
            await engine.analyze_chart("gold", _asset(), "en", "1")
        engine._complete.assert_not_awaited()
        engine._check_quota.assert_not_called()

    async def test_external_analysis_rejects_history_without_provenance_even_with_current_quote_permission(self):
        self.grants[APPROVED] = _grant("external_processing")
        engine = MarketInsightEngine()
        engine._complete, engine._check_quota = AsyncMock(return_value="not sent"), unittest.mock.Mock()
        snapshot = dict(_asset(), history=[{"timestamp": datetime.now(UTC).isoformat(), "value_usd": 2070}])
        with self.assertRaisesRegex(InsightUnavailableError, "permission"):
            await engine.analyze_chart("gold", snapshot, "en", "1")
        engine._complete.assert_not_awaited()

    async def test_user_chat_without_market_snapshot_stays_available(self):
        engine = MarketInsightEngine()
        engine._complete, engine._check_quota = AsyncMock(return_value="General explanation"), unittest.mock.Mock()
        reply = await engine.chat([{"role": "user", "content": "What is a gram?"}], "en", "1")
        self.assertIn("General explanation", reply)
        engine._complete.assert_awaited_once()

    async def test_explicit_processing_permission_allows_only_a_proved_price_without_unproved_history(self):
        self.grants[APPROVED] = _grant("external_processing")
        engine = MarketInsightEngine()
        engine._complete, engine._check_quota = AsyncMock(return_value="Approved analysis"), Mock()
        result = await engine.analyze_chart("gold", _asset(), "en", "1")
        self.assertEqual(result, "Approved analysis")
        engine._complete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
