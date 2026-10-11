from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.pricing.websocket import PriceWebSocketHub
from app.routers.price_ws import price_updates


class WebSocketAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def make_hub(self, *, available=True, reader=None):
        store = SimpleNamespace(ping=AsyncMock(return_value=available))
        reader = reader if reader is not None else AsyncMock(return_value={})
        hub = PriceWebSocketHub(store=store, snapshot_reader=reader)
        hub._dispatch_forever = AsyncMock()
        hub._event_loop = AsyncMock()
        websocket = SimpleNamespace(
            accept=AsyncMock(), close=AsyncMock(), send_json=AsyncMock()
        )
        return hub, store, reader, websocket

    async def test_capacity_rejection_does_not_ping_or_read_snapshot(self):
        hub, store, reader, websocket = self.make_hub()
        hub.maximum_connections = 0

        await hub.serve(websocket)

        reader.assert_not_awaited()
        store.ping.assert_not_awaited()
        hub._dispatch_forever.assert_not_awaited()
        websocket.close.assert_awaited_once_with(
            code=1013, reason="Price stream is at capacity"
        )
        websocket.send_json.assert_not_awaited()
        self.assertEqual(hub.connection_count, 0)

    async def test_admitted_snapshot_loads_after_registration_and_redis_check(self):
        hub, store, reader, websocket = self.make_hub()
        quotes = {
            instrument: SimpleNamespace(instrument_id=instrument)
            for instrument in ("BTC_USD", "USDT_USD")
        }

        async def load():
            self.assertEqual(hub.connection_count, 1)
            store.ping.assert_awaited_once()
            return quotes

        reader.side_effect = load
        hub._public_event = Mock(
            side_effect=lambda quote: {
                "event_type": "canonical_update",
                "instrument_id": quote.instrument_id,
            }
        )

        await hub.serve(websocket, requested_instruments={"BTC_USD"})

        reader.assert_awaited_once()
        websocket.accept.assert_awaited_once()
        payload = websocket.send_json.call_args.args[0]
        self.assertEqual(payload["event_type"], "snapshot")
        self.assertEqual(payload["type"], "snapshot")
        self.assertTrue(payload["connection_id"])
        self.assertEqual(payload["heartbeat_seconds"], hub.heartbeat_seconds)
        self.assertEqual(payload["poll_fallback_seconds"], hub.poll_fallback_seconds)
        self.assertEqual(
            payload["prices"],
            [{"event_type": "canonical_update", "instrument_id": "BTC_USD"}],
        )
        hub._event_loop.assert_awaited_once()
        self.assertEqual(hub._event_loop.call_args.args[2], {"BTC_USD"})
        self.assertEqual(hub.connection_count, 0)
        self.assertIsNone(hub._dispatcher)

    async def test_snapshot_failure_releases_admitted_slot(self):
        hub, store, reader, websocket = self.make_hub()
        reader.side_effect = RuntimeError("snapshot unavailable")

        with self.assertRaisesRegex(RuntimeError, "snapshot unavailable"):
            await hub.serve(websocket)

        store.ping.assert_awaited_once()
        reader.assert_awaited_once()
        self.assertEqual(hub.connection_count, 0)
        self.assertIsNone(hub._dispatcher)
        hub._event_loop.assert_not_awaited()

    async def test_redis_unavailable_skips_snapshot_and_releases_slot(self):
        hub, store, reader, websocket = self.make_hub(available=False)

        await hub.serve(websocket)

        store.ping.assert_awaited_once()
        reader.assert_not_awaited()
        self.assertEqual(
            websocket.send_json.call_args.args[0],
            {
                "event_type": "degraded",
                "reason": "redis_unavailable",
                "polling_required": True,
                "poll_fallback_seconds": hub.poll_fallback_seconds,
            },
        )
        websocket.close.assert_awaited_once_with(
            code=1013, reason="Price fan-out is unavailable"
        )
        self.assertEqual(hub.connection_count, 0)
        self.assertIsNone(hub._dispatcher)

    async def test_explicit_snapshot_preserves_existing_callers(self):
        hub, _store, reader, websocket = self.make_hub()

        await hub.serve(websocket, {}, {"BTC_USD"})

        reader.assert_not_awaited()
        self.assertEqual(websocket.send_json.call_args.args[0]["prices"], [])
        self.assertEqual(hub._event_loop.call_args.args[2], {"BTC_USD"})

    async def test_router_passes_subscriptions_without_eager_snapshot(self):
        websocket = SimpleNamespace(
            headers={}, query_params={"instruments": "BTC_USD,invalid"}
        )
        serve = AsyncMock()

        with patch("app.routers.price_ws.price_websocket_hub.serve", serve):
            await price_updates(websocket)

        serve.assert_awaited_once_with(
            websocket, requested_instruments={"BTC_USD"}
        )
