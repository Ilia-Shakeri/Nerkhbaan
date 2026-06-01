import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, prices, providers
from app.db import init_db

# Initialize logger
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events."""
    logger.info("Starting up API and initializing database...")
    await init_db()
    yield
    logger.info("Shutting down API...")

app = FastAPI(
    title="Nerkhbaan API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc"
)

# Configure CORS securely using settings from .env
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount standard routers with the correct /api prefixes
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(prices.router, prefix="/api/prices", tags=["Prices"])
app.include_router(providers.router, prefix="/api/providers", tags=["Providers"])

@app.get("/api/health", tags=["System"])
@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint.
    Mapped to both /health and /api/health to accommodate internal Docker routing
    as well as external Nginx reverse proxies.
    """
    return {"status": "ok", "version": "1.0.0"}