from __future__ import annotations

import hashlib
import os
from pathlib import Path

from sqlalchemy import Engine, text


def migration_checksum(path: Path) -> str:
    """Checksum a migration independently of how the file was checked out.

    The applier and the verifier previously hashed different byte streams -
    one decoded text, one raw bytes - so a CRLF checkout made every applied
    migration look modified and the API refused to start. Normalising line
    endings makes the checksum describe the SQL, not the checkout.
    """
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def migrations_root() -> Path:
    root = Path(os.getenv("MIGRATIONS_DIR", "/app/db/migrations"))
    if not root.is_dir():
        root = Path(__file__).resolve().parents[2] / "db" / "migrations"
    return root


def expected_migrations() -> dict[str, str]:
    return {
        path.name: migration_checksum(path)
        for path in sorted(migrations_root().glob("*.sql"))
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
