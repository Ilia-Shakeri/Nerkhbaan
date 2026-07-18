from __future__ import annotations

from fastapi import APIRouter, WebSocket

from ..pricing.instruments import get_instrument
from ..pricing.service import instrument_pricing_service
from ..pricing.websocket import price_websocket_hub

router = APIRouter(tags=["prices-websocket"])


@router.websocket("/api/ws/prices")
async def price_updates(websocket: WebSocket) -> None:
    raw = websocket.query_params.get("instruments", "")
    requested: set[str] | None = None
    if raw:
        requested = set()
        for value in raw.split(",")[:100]:
            try:
                requested.add(get_instrument(value).instrument_id)
            except KeyError:
                continue
        if not requested:
            requested = None
    initial = await instrument_pricing_service.get_all_canonical()
    await price_websocket_hub.serve(websocket, initial, requested)
