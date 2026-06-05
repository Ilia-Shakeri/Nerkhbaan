import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .routers import auth, prices, providers
from .db import engine, Base, get_db
from sqlalchemy import text
from sqlalchemy.orm import Session

# Import models to ensure SQLAlchemy registers the tables before create_all executes
from . import models  

# Initialize logger for debugging and monitoring
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

# Safely parse allowed origins to prevent CORS crashes
origins = [origin.strip() for origin in settings.allowed_origins.split(',') if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers without prefix since they define their own in the router files
app.include_router(auth.router, tags=["Authentication"])
app.include_router(prices.router, tags=["Prices"])
app.include_router(providers.router, tags=["Providers"])

@app.get("/api/health", tags=["System"])
@app.get("/health", tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint that verifies database connectivity."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Health check database failure: {e}")
        db_status = "disconnected"
        
    return {
        "status": "operational" if db_status == "connected" else "degraded",
        "database": db_status,
        "version": "1.0.0"
    }

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global catch-all to prevent silent failures and ensure CORS headers are maintained."""
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code, 
            content={"detail": exc.detail}
        )
        
    logger.error(f"Unhandled system error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": str(exc), "path": request.url.path}
    )