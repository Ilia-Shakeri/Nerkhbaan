from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from ..config import settings

logger = logging.getLogger("nerkhbaan.migrations")

MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    checksum VARCHAR(64) NOT NULL,
    execution_ms INTEGER NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _migration_files() -> list[Path]:
    root = Path(os.getenv("MIGRATIONS_DIR", "/app/db/migrations")).resolve()
    if not root.is_dir():
        raise RuntimeError(f"Migration directory does not exist: {root}")
    files = sorted(path for path in root.iterdir() if path.is_file() and path.suffix == ".sql")
    if not files:
        raise RuntimeError(f"No migration files found in {root}")
    return files


def _connect() -> psycopg.Connection:
    url = make_url(settings.database_url)
    if not url.database or not url.username:
        raise RuntimeError("DATABASE_URL must include database and user names")
    return psycopg.connect(
        host=url.host or "localhost",
        port=url.port or 5432,
        dbname=url.database,
        user=url.username,
        password=url.password or "",
        connect_timeout=settings.migration_connect_timeout_seconds,
        application_name="nerkhbaan-migrate",
    )


def _apply_file(connection: psycopg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT checksum FROM public.schema_migrations WHERE version = %s",
            (path.name,),
        )
        existing = cursor.fetchone()
        if existing:
            if existing[0] != checksum:
                raise RuntimeError(f"Applied migration changed on disk: {path.name}")
            logger.info("Migration already applied: %s", path.name)
            return

    started = time.monotonic()
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(settings.migration_statement_timeout_seconds * 1000),),
                )
                cursor.execute(sql)
                elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
                cursor.execute(
                    """
                    INSERT INTO public.schema_migrations (version, checksum, execution_ms)
                    VALUES (%s, %s, %s)
                    """,
                    (path.name, checksum, elapsed_ms),
                )
    except Exception as exc:
        raise RuntimeError(f"Migration failed: {path.name}") from exc
    logger.info("Migration applied: %s", path.name)


def _release_advisory_lock(connection: psycopg.Connection) -> None:
    if connection.closed:
        logger.warning("Migration connection closed before advisory lock release")
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s)",
                (settings.migration_advisory_lock_id,),
            )
    except psycopg.Error:
        logger.exception("Could not release migration advisory lock")


def run() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    files = _migration_files()
    with _connect() as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_lock(%s)",
                (settings.migration_advisory_lock_id,),
            )
        try:
            with connection.cursor() as cursor:
                cursor.execute(MIGRATION_TABLE_SQL)
            for path in files:
                _apply_file(connection, path)
        finally:
            _release_advisory_lock(connection)

    try:
        from ..admin.bootstrap import bootstrap_super_admin

        bootstrap_super_admin()
    except ImportError:
        logger.info("Admin bootstrap module is not installed")


if __name__ == "__main__":
    run()
