from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings
from .cache import PricingRedisStore, pricing_redis
from .instruments import INSTRUMENTS, get_instrument, legacy_asset_for_instrument
from .models import CanonicalQuote


class PriceWebSocketHub:
    def __init__(self, store: PricingRedisStore = pricing_redis) -> None:
        self.store = store
        self.heartbeat_seconds = settings.websocket_heartbeat_seconds
        self.maximum_connections = settings.websocket_max_connections_per_worker
        self._connections: set[str] = set()
        self._guard = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def serve(
        self,
        websocket: WebSocket,
        initial_quotes: dict[str, CanonicalQuote],
        requested_instruments: set[str] | None = None,
    ) -> None:
        connection_id = uuid.uuid4().hex
        subscriptions = requested_instruments or set(INSTRUMENTS)
        await websocket.accept()
        async with self._guard:
            if len(self._connections) >= self.maximum_connections:
                await websocket.close(code=1013, reason="Price stream is at capacity")
                return
            self._connections.add(connection_id)
        if not await self.store.ping():
            await websocket.send_json(
                {
                    "event_type": "degraded",
                    "reason": "redis_unavailable",
                    "polling_required": True,
                }
            )
            await websocket.close(code=1013, reason="Price fan-out is unavailable")
            async with self._guard:
                self._connections.discard(connection_id)
            return
        pubsub: Any | None = None
        try:
            pubsub = await self.store.subscribe()
            await websocket.send_json(
                {
                    "event_type": "snapshot",
                    "type": "snapshot",
                    "connection_id": connection_id,
                    "heartbeat_seconds": self.heartbeat_seconds,
                    "prices": [
                        self._public_event(quote)
                        for instrument_id, quote in initial_quotes.items()
                        if instrument_id in subscriptions
                    ],
                }
            )
            await self._event_loop(websocket, pubsub, subscriptions)
        except WebSocketDisconnect:
            return
        finally:
            async with self._guard:
                self._connections.discard(connection_id)
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(self.store.events_channel)
                    await pubsub.aclose()
                except Exception:
                    pass

    async def _event_loop(
        self,
        websocket: WebSocket,
        pubsub: Any,
        subscriptions: set[str],
    ) -> None:
        while True:
            redis_task = asyncio.create_task(
                pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=self.heartbeat_seconds,
                )
            )
            receive_task = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait(
                {redis_task, receive_task},
                timeout=self.heartbeat_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if not done:
                await websocket.send_json(
                    {
                        "event_type": "heartbeat",
                        "type": "heartbeat",
                        "event_id": int(time.time() * 1000),
                        "server_time": time.time(),
                    }
                )
                continue
            if receive_task in done:
                message = receive_task.result()
                self._handle_client_message(message, subscriptions)
            if redis_task in done:
                message = redis_task.result()
                if not message or message.get("type") != "message":
                    await websocket.send_json(
                        {
                            "event_type": "heartbeat",
                            "type": "heartbeat",
                            "event_id": int(time.time() * 1000),
                            "server_time": time.time(),
                        }
                    )
                    continue
                try:
                    payload = json.loads(message["data"])
                    quote = CanonicalQuote.from_dict(payload)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                if quote.instrument_id in subscriptions:
                    await websocket.send_json(self._public_event(quote))

    @staticmethod
    def _handle_client_message(message: str, subscriptions: set[str]) -> None:
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
