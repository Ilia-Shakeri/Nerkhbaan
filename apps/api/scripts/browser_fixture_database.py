"""Isolated PostgreSQL ORM fixtures. Never a production migration substitute."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import event, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url

API_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATTERN = re.compile(r"^browser_fixture_[0-9a-f]{32}$")


def validate_local_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or not parsed.port or not 1 <= parsed.port <= 65535):
        raise ValueError("Browser fixtures require an explicit loopback HTTP origin")
    return value


def validate_database_url(value: str) -> str:
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Browser fixtures require an explicit loopback PostgreSQL test URL")
    if not url.database or not re.search(r"(?:^|_)(?:test|e2e|audit|browser|fixture|ci)(?:_|$)", url.database, re.IGNORECASE):
        raise ValueError("Browser fixture database name must contain a test marker")
    if url.database in {"postgres", "template0", "template1"}:
        raise ValueError("System databases cannot hold browser fixtures")
    return value


def configure(schema: str | None = None):
    value = os.environ.get("TEST_DATABASE_URL", "")
    if not value:
        raise ValueError("TEST_DATABASE_URL is required; runtime DATABASE_URL is never inferred")
    schema = schema or os.environ.get("NERKHBAAN_BROWSER_SCHEMA") or f"browser_fixture_{uuid.uuid4().hex}"
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("Fixture schema must have the generated browser_fixture UUID shape")
    os.environ["DATABASE_URL"] = validate_database_url(value)
    os.environ["PRICING_REQUIRE_PROVIDER_KEYS"] = "false"
    os.environ["BACKGROUND_TASKS_ENABLED"] = "false"
    os.environ["REDIS_URL"] = ""
    os.environ["JWT_SECRET_KEY"] = os.environ.get("BROWSER_TEST_JWT_SECRET", "browser-fixture-key-not-for-runtime-000000000000")
    os.environ["AUTH_COOKIE_SECURE"] = "false"
    os.environ["ADMIN_COOKIE_SECURE"] = "false"
    public = validate_local_origin(os.environ.get("BROWSER_TEST_PUBLIC_ORIGIN", "http://127.0.0.1:4173"))
    admin = validate_local_origin(os.environ.get("BROWSER_TEST_ADMIN_ORIGIN", "http://127.0.0.1:4174"))
    os.environ["PUBLIC_FRONTEND_ORIGIN"] = public
    os.environ["ALLOWED_ORIGINS"] = f"{public},{admin}"
    os.environ["ADMIN_FRONTEND_ORIGIN"] = admin
    os.environ["TRUSTED_HOSTS"] = "127.0.0.1,localhost,testserver"
    os.environ["NERKHBAAN_BROWSER_SCHEMA"] = schema
    sys.path.insert(0, str(API_ROOT))
    from app.db import Base, async_engine, engine, request_engine
    from app import models as _user_models  # noqa: F401
    from app.admin import models as _admin_models  # noqa: F401
    from app.pricing import db_models as _pricing_models  # noqa: F401
    del _user_models, _admin_models, _pricing_models
    if engine.url != make_url(value) or request_engine.url != make_url(value):
        raise ValueError("Database engines were already loaded for another URL; use a fresh fixture process")

    def set_search_path(dbapi_connection, _connection_record):
        previous = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f'SET search_path TO "{schema}"')
            finally:
                cursor.close()
        finally:
            dbapi_connection.autocommit = previous

    event.listen(engine, "connect", set_search_path)
    if request_engine is not engine:
        event.listen(request_engine, "connect", set_search_path)
    event.listen(async_engine.sync_engine, "connect", set_search_path)
    return schema, Base, engine, async_engine


def prepare(schema: str | None = None):
    schema, base, engine, async_engine = configure(schema)
    with engine.begin() as connection:
        exists = connection.execute(text("SELECT to_regnamespace(:schema)"), {"schema": schema}).scalar_one()
        if exists:
            owner = connection.execute(text(f'SELECT run_id FROM "{schema}"._browser_fixture_marker')).scalar_one()
            if owner != schema.removeprefix("browser_fixture_"):
                raise ValueError("Existing schema is not owned by this fixture run")
        else:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'CREATE TABLE "{schema}"._browser_fixture_marker (run_id TEXT PRIMARY KEY)'))
            connection.execute(text(f'INSERT INTO "{schema}"._browser_fixture_marker VALUES (:run_id)'), {"run_id": schema.removeprefix("browser_fixture_")})
    base.metadata.create_all(engine)
    return schema, engine, async_engine


def cleanup(schema: str) -> None:
    schema, _base, engine, _async_engine = configure(schema)
    try:
        with engine.begin() as connection:
            if connection.execute(text("SELECT to_regnamespace(:schema)"), {"schema": schema}).scalar_one() is None:
                return
            owner = connection.execute(text(f'SELECT run_id FROM "{schema}"._browser_fixture_marker')).scalar_one()
            if owner != schema.removeprefix("browser_fixture_"):
                raise ValueError("Refusing cleanup of an unowned schema")
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def align_owned_json_types(schema: str, engine) -> int:
    """Align only this fixture's old JSON columns after the PostgreSQL ORM type fix."""
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("Refusing type alignment outside a generated fixture schema")
    from app.db import Base
    changes = 0
    with engine.begin() as connection:
        owner = connection.execute(text(f'SELECT run_id FROM "{schema}"._browser_fixture_marker')).scalar_one()
        if owner != schema.removeprefix("browser_fixture_"):
            raise ValueError("Refusing type alignment of an unowned schema")
        quote = engine.dialect.identifier_preparer.quote_identifier
        inspector = inspect(connection)
        for table in Base.metadata.sorted_tables:
            actual = {column["name"]: column["type"] for column in inspector.get_columns(table.name, schema=schema)}
            for column in table.columns:
                if isinstance(column.type.dialect_impl(engine.dialect), JSONB) and not isinstance(actual.get(column.name), JSONB):
                    connection.exec_driver_sql(f'ALTER TABLE {quote(schema)}.{quote(table.name)} ALTER COLUMN {quote(column.name)} TYPE JSONB USING {quote(column.name)}::jsonb')
                    changes += 1
    return changes
