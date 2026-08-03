from __future__ import annotations

import asyncio
import logging
import re
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import models
from .admin import models as admin_models
from .admin.worker import admin_operations_worker
from .config import settings
from .db import engine
from .health import health_snapshot
from .migrations.state import assert_migrations_current
from .pricing import db_models as pricing_models
from .pricing.service import instrument_pricing_service
from .request_body_limit import RequestBodyLimitMiddleware
from .routers import (
    admin,
    alerts,
    auth,
    insights,
    instruments,
    notifications,
    price_ws,
    prices,
    providers,
    push,
    support,
)
from .services.background import background_runner

_MODEL_REGISTRATION_MODULES = (models, admin_models, pricing_models)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

price_fetches_total = Counter(
    "price_fetches_total", "Total price fetches", ["instrument", "status"]
)
cache_staleness_seconds = Gauge(
    "cache_staleness_seconds", "Cache staleness in seconds", ["instrument"]
)
price_fetch_duration_seconds = Histogram(
    "price_fetch_duration_seconds", "Price fetch duration", ["instrument"]
)

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_origins() -> list[str]:
    values = {
        origin
        for origin in (
            *(_origin(value) for value in _csv(settings.allowed_origins)),
            _origin(settings.public_frontend_origin),
            _origin(settings.admin_frontend_origin),
        )
        if origin
    }
    if "*" in _csv(settings.allowed_origins):
        if not settings.debug:
            raise RuntimeError("Wildcard CORS is not allowed outside debug mode")
        return ["*"]
    return sorted(values)


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    await asyncio.to_thread(assert_migrations_current, engine)
    await instrument_pricing_service.initialize()
    await background_runner.start()
    await admin_operations_worker.start()
    logger.info("API startup complete")
    try:
        yield
    finally:
        await admin_operations_worker.stop()
        await background_runner.stop()
        logger.info("API shutdown complete")


app = FastAPI(
    title="Nerkhbaan API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.debug else None,
    openapi_url="/api/openapi.json" if settings.debug else None,
    redoc_url="/api/redoc" if settings.debug else None,
)

origins = _allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origins != ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "If-None-Match",
        "X-Client-Type",
        "X-Request-ID",
    ],
    expose_headers=["ETag", "X-Request-ID"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_csv(settings.trusted_hosts),
)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    request_id = request.headers.get(settings.request_id_header, "")
    if not _REQUEST_ID_PATTERN.fullmatch(request_id):
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id

    cookie_names = {
        settings.auth_cookie_name,
        settings.auth_refresh_cookie_name,
        settings.admin_cookie_name,
        settings.admin_refresh_cookie_name,
    }
    cookie_authenticated = any(name in request.cookies for name in cookie_names)
    if request.method in _MUTATING_METHODS and cookie_authenticated:
        request_origin = _origin(request.headers.get("origin", ""))
        if request_origin not in origins:
            return JSONResponse(
                status_code=403,
                content={"detail": "Request origin is not allowed", "request_id": request_id},
                headers={settings.request_id_header: request_id},
            )

    response = await call_next(request)
    response.headers[settings.request_id_header] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    if request.url.path not in {"/api/docs", "/api/redoc", "/api/openapi.json"}:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith(("/api/auth", "/api/admin", "/api/insights")):
        response.headers["Cache-Control"] = "no-store"
    forwarded_scheme = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if request.url.scheme == "https" or forwarded_scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.max_request_body_bytes,
    request_id_header=settings.request_id_header,
)


app.include_router(auth.router)
app.include_router(prices.router)
app.include_router(instruments.router)
app.include_router(price_ws.router)
app.include_router(providers.router)
app.include_router(support.router)
app.include_router(alerts.router)
app.include_router(push.router)
app.include_router(insights.router)
app.include_router(notifications.router)
app.include_router(admin.router)


@app.get("/api/health/live", tags=["system"])
@app.get("/health", tags=["system"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready", tags=["system"])
def readiness() -> JSONResponse:
    snapshot = health_snapshot()
    return JSONResponse(status_code=200 if snapshot["ready"] else 503, content=snapshot)


@app.get("/api/health", tags=["system"])
def detailed_health() -> JSONResponse:
    snapshot = health_snapshot()
    return JSONResponse(status_code=200 if snapshot["ready"] else 503, content=snapshot)


@app.get("/metrics", tags=["system"])
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
            headers={settings.request_id_header: request_id, **(exc.headers or {})},
        )
    logger.error(
        "Unhandled request failure path=%s request_id=%s error_type=%s",
        request.url.path,
        request_id,
        type(exc).__name__,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={settings.request_id_header: request_id},
    )
