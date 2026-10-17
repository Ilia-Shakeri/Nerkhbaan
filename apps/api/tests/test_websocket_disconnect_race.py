from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("JWT_SECRET_KEY", "closed-stream-fixture-only-not-for-runtime-00000000")

from starlette.websockets import WebSocketState
from app.pricing.websocket import PriceWebSocketHub

CLOSED_SEND = "Unexpected ASGI message 'websocket.send', after sending 'websocket.close' or response already completed."


class ClosedPriceStreamTests(unittest.IsolatedAsyncioTestCase):
    def hub(self):
        hub = PriceWebSocketHub(store=SimpleNamespace(
            ping=AsyncMock(return_value=True), get_all_canonical=AsyncMock(return_value={})))
        hub._dispatch_forever = AsyncMock()
        return hub

    def socket(self, *, state=WebSocketState.CONNECTED, error=None):
        return SimpleNamespace(accept=AsyncMock(), close=AsyncMock(),
            client_state=state, application_state=WebSocketState.CONNECTED,
            send_json=AsyncMock(side_effect=error), receive_text=AsyncMock())

    async def test_known_closed_transport_during_initial_snapshot_exits_and_unregisters(self):
        hub = self.hub()
        socket = self.socket(error=RuntimeError(CLOSED_SEND))
        await asyncio.wait_for(hub.serve(socket, {}), 1)
        self.assertEqual(hub.connection_count, 0)
        self.assertIsNone(hub._dispatcher)

    async def test_already_disconnected_socket_is_never_sent_a_snapshot(self):
        hub = self.hub()
        socket = self.socket(state=WebSocketState.DISCONNECTED)
        socket.send_json.side_effect = RuntimeError(CLOSED_SEND)
        await asyncio.wait_for(hub.serve(socket, {}), 1)
        socket.send_json.assert_not_awaited()
        self.assertEqual(hub.connection_count, 0)

    async def test_disconnect_during_resync_cleans_receive_and_client_queue(self):
        hub = self.hub()
        socket = self.socket()
        cancelled = asyncio.Event()

        async def receive():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def read():
            socket.client_state = WebSocketState.DISCONNECTED
            return {}

        async def send(_payload):
            if socket.client_state is WebSocketState.DISCONNECTED:
                raise RuntimeError(CLOSED_SEND)

        register = hub._register
        async def register_resync(identifier):
            queue = await register(identifier)
            queue.put_nowait({"event_type": "resync", "reason": "fixture"})
            return queue

        hub._register = register_resync
        hub.snapshot_reader = read
        socket.receive_text.side_effect = receive
        socket.send_json.side_effect = send
        await asyncio.wait_for(hub.serve(socket, {}), 1)
        self.assertEqual(socket.send_json.await_count, 1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(hub.connection_count, 0)

    async def test_unrelated_send_runtime_error_remains_visible_and_unregisters(self):
        hub = self.hub()
        with self.assertRaisesRegex(RuntimeError, "unrelated serialization bug"):
            await asyncio.wait_for(hub.serve(self.socket(error=RuntimeError("unrelated serialization bug")), {}), 1)
        self.assertEqual(hub.connection_count, 0)

    async def test_matching_message_from_snapshot_reader_is_not_swallowed(self):
        hub = self.hub()
        hub.snapshot_reader = AsyncMock(side_effect=RuntimeError(CLOSED_SEND))
        with self.assertRaisesRegex(RuntimeError, "Unexpected ASGI"):
            await asyncio.wait_for(hub.serve(self.socket()), 1)
        self.assertEqual(hub.connection_count, 0)


if __name__ == "__main__":
    unittest.main()
