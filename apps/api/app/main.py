import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .routers import alerts, auth, insights, notifications, prices, providers, push, support
from .services.background import background_runner
from .db import engine, Base, get_db
from sqlalchemy import text
from sqlalchemy.orm import Session

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

price_fetches_total = Counter('price_fetches_total', 'Total price fetches', ['asset', 'region', 'status'])
cache_staleness_seconds = Gauge('cache_staleness_seconds', 'Cache staleness in seconds', ['asset', 'region'])
price_fetch_duration_seconds = Histogram('price_fetch_duration_seconds', 'Price fetch duration', ['asset'])

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
        
# Seed the administrative account securely
        from .models import User
        from .security import hash_password
        from .db import SessionLocal
        
        db = SessionLocal()
        try:
            admin_password = os.environ.get("ADMIN_INITIAL_PASSWORD")
            if not admin_password:
                logger.warning("Administrative password not configured. Skipping seeding.")
            else:
                admin = db.query(User).filter(User.username == 'admin').first()
                if not admin:
                    admin_user = User(
                        username='admin',
                        full_name='Administrator',
                        email='admin@nerkhbaan.local',
                        password_hash=hash_password(admin_password)
                    )
                    db.add(admin_user)
                    db.commit()
                    logger.info("Administrative account successfully provisioned.")
                else:
                    logger.info("Administrative account already exists in the registry.")
            insights.purge_expired_chat_history(db)
        except Exception as seed_exception:
            # Trigger a rollback to release locks and prevent database hanging on failure
            db.rollback()
            logger.critical(f"Database seeding execution failed: {seed_exception}")
            raise
        finally:
            # Guarantee the session is terminated and returned to the pool
            db.close()
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        raise e

    # Launch the price-evaluation loop and DLQ worker that deliver alerts.
    await background_runner.start()
    yield
    logger.info("Shutting down API...")
    await background_runner.stop()

app = FastAPI(
    title="Nerkhbaan API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc"
)

# Extract and format the allowed origins from the environment configuration
origins = [origin.strip() for origin in settings.allowed_origins.split(',') if origin.strip()]

# Dynamically route the CORS middleware based on the presence of a wildcard
if "*" in origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], 
        # Credentials must be strictly disabled when utilizing wildcard origins
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins, 
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    if request.url.path not in {"/api/docs", "/api/redoc", "/api/openapi.json"}:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith(("/api/auth", "/api/insights")):
        response.headers["Cache-Control"] = "no-store"
    forwarded_scheme = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    if request.url.scheme == "https" or forwarded_scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Include routers without prefix since they define their own in the router files
app.include_router(auth.router, tags=["Authentication"])
app.include_router(prices.router, tags=["Prices"])
app.include_router(providers.router, tags=["Providers"])
app.include_router(support.router, tags=["Support"])
app.include_router(alerts.router, tags=["Alerts"])
app.include_router(push.router, tags=["Push"])
app.include_router(insights.router, tags=["Insights"])
app.include_router(notifications.router, tags=["Notifications"])

@app.get("/api/health", tags=["System"])
@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """Health validation endpoint mapping database connectivity."""
    try:
        # Synchronous execution is now safely isolated from the core event loop
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Health check execution failure: {e}")
        db_status = "disconnected"
        
    return {
        "status": "operational" if db_status == "connected" else "degraded",
        "database": db_status,
        "version": "1.0.0"
    }

@app.get("/metrics", tags=["System"])
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global catch-all to prevent silent failures and ensure CORS headers are maintained."""
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code, 
            content={"detail": exc.detail}
        )
        
    logger.error(f"Unhandled system error on {request.url.path}: {exc}", exc_info=True)
    # Avoid leaking internal exception details to clients in production. The full
    # traceback is logged above; debug mode surfaces it for local development.
    detail = str(exc) if settings.debug else "An internal error occurred."
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "detail": detail}
    )
