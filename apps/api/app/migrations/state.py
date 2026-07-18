from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy import Engine, text


def expected_migrations() -> dict[str, str]:
    root = Path(os.getenv("MIGRATIONS_DIR", "/app/db/migrations"))
    if not root.is_dir():
        local_root = Path(__file__).resolve().parents[2] / "db" / "migrations"
        root = local_root
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.glob("*.sql"))
    }


def migration_state(engine: Engine) -> dict:
    expected = expected_migrations()
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT version, checksum, applied_at FROM public.schema_migrations ORDER BY version")
        ).mappings().all()
    applied = {row["version"]: row["checksum"] for row in rows}
    missing = sorted(set(expected) - set(applied))
    changed = sorted(name for name, checksum in expected.items() if applied.get(name) not in (None, checksum))
    return {
        "current": not missing and not changed,
        "version": rows[-1]["version"] if rows else None,
        "applied_count": len(rows),
        "expected_count": len(expected),
        "missing": missing,
        "changed": changed,
    }


def assert_migrations_current(engine: Engine) -> None:
    state = migration_state(engine)
    if not state["current"]:
        raise RuntimeError(
            "Database migrations are not current; run the dedicated migration service before the backend"
        )
