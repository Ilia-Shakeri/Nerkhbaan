from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings
from .cache import PricingRedisStore, pricing_redis
from .instruments import INSTRUMENTS, get_instrument, legacy_asset_for_instrument
from .models import CanonicalQuote

logger = logging.getLogger(__name__)

#: Bound on queued events per connection. A client that cannot keep up is
#: disconnected rather than allowed to grow the worker's memory.
_CLIENT_QUEUE_SIZE = 64

#: Client frames accepted per connection per minute.
_CLIENT_MESSAGE_LIMIT = 30


class PriceWebSocketHub:
    """Fan out canonical price updates to connected clients.

    One Redis subscription is shared by every connection. Subscribing per
    connection meant a worker at its configured connection ceiling also held
    that many Redis connections, which exhausts Redis long before the worker
    itself is saturated.
    """

    def __init__(self, store: PricingRedisStore = pricing_redis) -> None:
        self.store = store
        self.heartbeat_seconds = settings.websocket_heartbeat_seconds
        self.maximum_connections = settings.websocket_max_connections_per_worker
        # A client that has sent nothing and acknowledged nothing for this long
        # is treated as gone, so dead sockets do not hold a slot forever.
        self.client_timeout_seconds = settings.websocket_client_timeout_seconds
        self.poll_fallback_seconds = settings.websocket_poll_fallback_seconds
        self._clients: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._guard = asyncio.Lock()
        self._dispatcher: asyncio.Task | None = None

    @property
    def connection_count(self) -> int:
        return len(self._clients)

    async def _register(self, connection_id: str) -> asyncio.Queue | None:
        async with self._guard:
            if len(self._clients) >= self.maximum_connections:
                return None
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
                maxsize=_CLIENT_QUEUE_SIZE
            )
            self._clients[connection_id] = queue
            if self._dispatcher is None or self._dispatcher.done():
                self._dispatcher = asyncio.create_task(self._dispatch_forever())
            return queue

    async def _unregister(self, connection_id: str) -> None:
        async with self._guard:
            self._clients.pop(connection_id, None)
            if not self._clients and self._dispatcher is not None:
                self._dispatcher.cancel()
                self._dispatcher = None

    async def _dispatch_forever(self) -> None:
        """Read the shared channel and hand each event to every client queue."""
        while True:
            pubsub = None
            try:
                pubsub = await self.store.subscribe()
                while True:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True, timeout=5.0
                    )
                    if not message or message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                        quote = CanonicalQuote.from_dict(payload)
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        continue
                    event = self._public_event(quote)
                    async with self._guard:
                        targets = list(self._clients.values())
                    for queue in targets:
                        try:
                            queue.put_nowait(event)
                        except asyncio.QueueFull:
                            # A stalled reader must not slow the whole fan-out.
                            continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Price fan-out subscription dropped; retrying")
                await asyncio.sleep(2.0)
            finally:
                if pubsub is not None:
                    with contextlib.suppress(Exception):
                        await pubsub.unsubscribe(self.store.events_channel)
                        await pubsub.aclose()

    async def serve(
        self,
        websocket: WebSocket,
        initial_quotes: dict[str, CanonicalQuote],
        requested_instruments: set[str] | None = None,
    ) -> None:
        connection_id = uuid.uuid4().hex
        subscriptions = requested_instruments or set(INSTRUMENTS)
        await websocket.accept()

        queue = await self._register(connection_id)
        if queue is None:
            await websocket.close(code=1013, reason="Price stream is at capacity")
            return
        try:
            if not await self.store.ping():
                await websocket.send_json(
                    {
                        "event_type": "degraded",
                        "reason": "redis_unavailable",
                        "polling_required": True,
                        "poll_fallback_seconds": self.poll_fallback_seconds,
                    }
                )
                await websocket.close(code=1013, reason="Price fan-out is unavailable")
                return
            await websocket.send_json(
                {
                    "event_type": "snapshot",
                    "type": "snapshot",
                    "connection_id": connection_id,
                    "heartbeat_seconds": self.heartbeat_seconds,
                    # Tells the client how often to poll if it loses the socket.
                    "poll_fallback_seconds": self.poll_fallback_seconds,
                    "prices": [
                        self._public_event(quote)
                        for instrument_id, quote in initial_quotes.items()
                        if instrument_id in subscriptions
                    ],
                }
            )
            await self._event_loop(websocket, queue, subscriptions)
        except WebSocketDisconnect:
            return
        finally:
            await self._unregister(connection_id)

    async def _event_loop(
        self,
        websocket: WebSocket,
        queue: asyncio.Queue[dict[str, Any]],
        subscriptions: set[str],
    ) -> None:
        message_window_started = time.monotonic()
        messages_in_window = 0
        receive_task: asyncio.Task | None = None
        queue_task: asyncio.Task | None = None
        try:
            while True:
                if receive_task is None:
                    receive_task = asyncio.create_task(websocket.receive_text())
                if queue_task is None:
                    queue_task = asyncio.create_task(queue.get())
                done, _pending = await asyncio.wait(
                    {receive_task, queue_task},
                    timeout=self.heartbeat_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    await websocket.send_json(self._heartbeat())
                    continue

                if receive_task in done:
                    # Cancelling and recreating a pending receive can drop a
                    # frame, so the task is kept across iterations and only
                    # replaced once it has actually produced a result.
                    message = receive_task.result()
                    receive_task = None
                    now = time.monotonic()
                    if now - message_window_started >= 60:
                        message_window_started = now
                        messages_in_window = 0
                    messages_in_window += 1
                    if messages_in_window > _CLIENT_MESSAGE_LIMIT:
                        await websocket.close(code=1008, reason="Too many client frames")
                        return
                    self._handle_client_message(message, subscriptions)

                if queue_task in done:
                    event = queue_task.result()
                    queue_task = None
                    if event.get("instrument_id") in subscriptions:
                        await websocket.send_json(event)
        finally:
            for task in (receive_task, queue_task):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

    @staticmethod
    def _heartbeat() -> dict[str, Any]:
        return {
            "event_type": "heartbeat",
            "type": "heartbeat",
            "event_id": int(time.time() * 1000),
            "server_time": time.time(),
        }

    @staticmethod
    def _handle_client_message(message: str, subscriptions: set[str]) -> None:
        if len(message) > 4096:
            return
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict) or payload.get("event_type") != "subscribe":
            return
        requested = payload.get("instruments")
        if not isinstance(requested, list):
            return
        normalized: set[str] = set()
        for value in requested[:100]:
            try:
                normalized.add(get_instrument(str(value)).instrument_id)
            except KeyError:
                continue
        if normalized:
            subscriptions.clear()
            subscriptions.update(normalized)

    @staticmethod
    def _public_event(quote: CanonicalQuote) -> dict[str, Any]:
        instrument = get_instrument(quote.instrument_id)
        payload = quote.to_dict(authenticated=False)
        payload.update(
            {
                "event_type": "canonical_update",
                "type": "canonical_update",
                "compatibility_asset_id": legacy_asset_for_instrument(quote.instrument_id),
                "compatibility_asset": legacy_asset_for_instrument(quote.instrument_id),
                "sequence": quote.sequence_number,
                "currency": instrument.quote_currency.value,
                "unit": instrument.weight_unit.value,
                "purity": float(instrument.purity) if instrument.purity is not None else None,
                "persistence_status": "persisted" if quote.is_persisted else "unpersisted",
            }
        )
        return payload


price_websocket_hub = PriceWebSocketHub()
