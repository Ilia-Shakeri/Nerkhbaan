from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass

# Upgraded connection pooling for high concurrency and zero hanging queries
engine = create_engine(
    settings.database_url, 
    future=True, 
    pool_pre_ping=True,    # Verifies connection health before usage
    pool_size=20,          # Maintain up to 20 connections in the pool
    max_overflow=10,       # Allow up to 10 additional temporary connections during traffic spikes
    pool_timeout=30,       # Timeout if no connection is available after 30 seconds
    pool_recycle=1800      # Recycle connections every 30 minutes to prevent database disconnects
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()