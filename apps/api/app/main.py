import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import auth, prices, providers
from app.db import engine, Base

# CRITICAL FIX: We MUST import models here before create_all() 
# so SQLAlchemy knows which tables to build in the database.
import app.models  

# Initialize logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events."""
    logger.info("Starting up API and initializing database...")
    try:
        # Create tables on startup synchronously using SQLAlchemy metadata
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables verified/created successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        raise e
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

# Configure CORS securely (fallback to allow all for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Router Inclusion
# ---------------------------------------------------------
# CRITICAL FIX: Removed the `prefix=` parameter here because the 
# routers in app/routers/*.py already define their own prefixes.
app.include_router(auth.router, tags=["Authentication"])
app.include_router(prices.router, tags=["Prices"])
app.include_router(providers.router, tags=["Providers"])

@app.get("/api/health", tags=["System"])
@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint mapped to both /health and /api/health.
    """
    return {"status": "operational", "version": "1.0.0", "message": "Nerkhbaan API is fully responsive."}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global catch-all to prevent silent failures."""
    logger.error(f"Unhandled system error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": str(exc), "path": request.url.path}
    )