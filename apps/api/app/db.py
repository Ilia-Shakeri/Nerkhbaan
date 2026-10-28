from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass

def sync_pool_plan(size: int, overflow: int) -> tuple[int, int, int]:
    """Reserve request capacity inside the configured synchronous budget."""
    if size < 1 or overflow < 0:
        raise ValueError("Database pools require a positive size and bounded overflow")
    budget = size + overflow
    reserved = min(2, budget - 1)
    background_size = min(size, budget - reserved)
    return background_size, budget - reserved - background_size, reserved


# Price workers and history reads must not occupy the last request connections.
# The two synchronous pools together keep the existing configured peak budget;
# the asynchronous pool keeps its independent configured budget.
_background_size, _background_overflow, _request_size = sync_pool_plan(
    settings.database_pool_size, settings.database_max_overflow,
)
engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    pool_size=_background_size,
    max_overflow=_background_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    pool_recycle=1800,
    connect_args={"connect_timeout": 5} if settings.database_url.startswith("postgresql") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
request_engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    pool_size=_request_size,
    max_overflow=0,
    pool_timeout=settings.database_pool_timeout_seconds,
    pool_recycle=1800,
    connect_args={"connect_timeout": 5} if settings.database_url.startswith("postgresql") else {},
) if _request_size else engine
RequestSessionLocal = sessionmaker(bind=request_engine, autoflush=False, autocommit=False, class_=Session)


def _async_database_url(url: str) -> str:
    parsed = make_url(url)
    if parsed.get_backend_name() == "postgresql":
        return parsed.set(drivername="postgresql+asyncpg", query={}).render_as_string(hide_password=False)
    return url


def _async_connect_args(url: str) -> dict:
    if make_url(url).get_backend_name() != "postgresql":
        return {}
    # Let asyncpg parse PostgreSQL DSN options; they are not connect keywords.
    dsn = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    return {"dsn": dsn, "timeout": 5, "command_timeout": 15}


async_engine = create_async_engine(
    _async_database_url(settings.database_url),
    pool_pre_ping=True,
    pool_size=settings.database_async_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    pool_recycle=1800,
    connect_args=_async_connect_args(settings.database_url),
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


def get_db() -> Generator[Session, None, None]:
    db = RequestSessionLocal()
    try:
        yield db
    except Exception:
        # Close alone returns a connection with an open transaction to the
        # pool; rolling back first makes the failure explicit and keeps a
        # half-applied unit of work from being reused.
        db.rollback()
        raise
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()
