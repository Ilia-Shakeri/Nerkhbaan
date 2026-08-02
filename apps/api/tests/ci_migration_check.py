from __future__ import annotations

from sqlalchemy import text

from app.db import engine
from app.migrations.state import expected_migrations


def main() -> None:
    expected = expected_migrations()
    if not expected:
        raise RuntimeError("No migration files were found")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT version, checksum FROM public.schema_migrations ORDER BY version")
        ).mappings()
        applied = {row["version"]: row["checksum"] for row in rows}

    if applied != expected:
        missing = sorted(set(expected) - set(applied))
        unexpected = sorted(set(applied) - set(expected))
        changed = sorted(
            version
            for version in set(expected) & set(applied)
            if expected[version] != applied[version]
        )
        raise RuntimeError(
            "Migration state mismatch: "
            f"missing={missing}, unexpected={unexpected}, changed={changed}"
        )

    print(f"Migration state current: {len(applied)} files")


if __name__ == "__main__":
    main()
