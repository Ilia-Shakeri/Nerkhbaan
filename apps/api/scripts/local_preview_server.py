"""Entry point for isolated local review. Never imported by production startup."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

if os.environ.get("NERKHBAAN_LOCAL_PREVIEW") != "1":
    raise RuntimeError("Use scripts/local_preview.py; preview requires explicit isolated configuration")
if (Path.cwd() / "../../.env").resolve().exists():
    raise RuntimeError("Preview refuses an inherited dotenv file")

from browser_fixture_database import prepare

schema, engine, async_engine = prepare(os.environ["NERKHBAAN_BROWSER_SCHEMA"])

from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db, request_engine
from app.deps import get_current_user
from app.main import app
from app.models import User, UserNotification
from app.schemas import PricesResponse, PriceHistoryResponse, ReferenceRatesResponse
from local_preview_data import REVISION, prices, history, references

web_origin = os.environ["LOCAL_PREVIEW_WEB_ORIGIN"]
assert settings.public_frontend_origin == web_origin
assert settings.admin_frontend_origin == web_origin

allowed = ("/api/auth", "/api/alerts", "/api/notifications", "/api/support", "/api/prices", "/api/local-preview")


@app.middleware("http")
async def preview_guard(request: Request, call_next):
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        return JSONResponse({"detail": "Local preview only"}, status_code=403)
    if request.url.path != "/__preview__/health" and not request.url.path.startswith(allowed):
        return JSONResponse({"detail": "این بخش در مرور محلی به خدمت بیرونی وصل نمی‌شود."}, status_code=503)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("origin") != web_origin:
            return JSONResponse({"detail": "Local preview origin required"}, status_code=403)
        if request.url.path.startswith("/api/auth") and request.url.path.rsplit("/", 1)[-1] not in {
            "signup", "signin", "signout", "refresh", "change-password"} and not (
                request.method == "DELETE" and request.url.path.startswith("/api/auth/sessions/")):
            return JSONResponse({"detail": "ارسال پیام و بازیابی ایمیلی در مرور محلی خاموش است."}, status_code=503)
        if request.url.path.startswith("/api/notifications/") and request.url.path not in {
            "/api/notifications/preferences/push_app", "/api/notifications/preferences/silent_mode",
            "/api/notifications/preferences/aggressive_alerts", "/api/notifications/read-all"} and not request.url.path.endswith("/read"):
            return JSONResponse({"detail": "ارسال بیرونی در مرور محلی خاموش است."}, status_code=503)
    response = await call_next(request)
    response.headers["X-Nerkhbaan-Local-Preview"] = "synthetic-no-external-delivery"
    response.headers["Cache-Control"] = "no-store"
    return response


@asynccontextmanager
async def local_lifespan(_app):
    yield
    await async_engine.dispose()
    engine.dispose()
    if request_engine is not engine:
        request_engine.dispose()


app.router.lifespan_context = local_lifespan
app.router.routes = [r for r in app.router.routes if not getattr(r, "path", "").startswith(("/api/prices", "/api/ws/prices"))]


@app.get("/__preview__/health")
def preview_health():
    return {"mode": "local-preview", "ready": True, "prices": "synthetic", "external_delivery": False,
            "migration_acceptance": False, "schema": schema}


@app.get("/api/prices", response_model=PricesResponse)
def preview_prices():
    return prices()


@app.get("/api/prices/references", response_model=ReferenceRatesResponse)
def preview_references(timeframe: str = "30d"):
    try:
        return references(timeframe)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/prices/{asset}/history", response_model=PriceHistoryResponse)
def preview_history(asset: str, timeframe: str = "30d"):
    try:
        return history(asset, timeframe)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/local-preview/notice", status_code=201)
def preview_notice(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = UserNotification(user_id=user.id, title="اعلان نمونهٔ محلی",
                            message="این پیام فقط در نسخهٔ محلی ثبت شد؛ اعلان بیرونی ارسال نشده است.",
                            severity="info", resource_type="system")
    db.add(note)
    db.commit()
    return {"created": True, "external_delivery": False}


@app.websocket("/api/ws/prices")
async def preview_socket(websocket: WebSocket):
    if websocket.headers.get("origin") != web_origin:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json({"event_type": "heartbeat", "rights_revision": REVISION})
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass


# Included production routers may be lazy wrapper routes in newer FastAPI.
# Put this module's explicit review endpoints first without altering those routers.
preview_routes = [route for route in app.router.routes
                  if getattr(getattr(route, "endpoint", None), "__module__", None) == __name__]
app.router.routes[:] = preview_routes + [route for route in app.router.routes if route not in preview_routes]
