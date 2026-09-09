from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, status

from ..config import settings
from ..pricing.instruments import get_instrument
from ..pricing.service import instrument_pricing_service
from ..pricing.websocket import price_websocket_hub

router = APIRouter(tags=["prices-websocket"])


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_origins() -> set[str]:
    values = {
        _origin(item.strip())
        for item in settings.allowed_origins.split(",")
        if item.strip()
    }
    values.add(_origin(settings.public_frontend_origin))
    values.add(_origin(settings.admin_frontend_origin))
    return {value for value in values if value}


@router.websocket("/api/ws/prices")
async def price_updates(websocket: WebSocket) -> None:
    # The same-origin policy does not cover WebSockets, so the handshake is the
    # only place an unwanted origin can be turned away. Native clients send no
    # Origin at all, which is allowed; a browser always sends one.
    origin_header = websocket.headers.get("origin")
    if origin_header is not None:
        allowed = _allowed_origins()
        if _origin(origin_header) not in allowed:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

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

    # Loading the snapshot only after the hub accepts the connection keeps an
    # unauthenticated connect storm from driving Redis and database reads.
    initial = await instrument_pricing_service.get_all_canonical()
    await price_websocket_hub.serve(websocket, initial, requested)
