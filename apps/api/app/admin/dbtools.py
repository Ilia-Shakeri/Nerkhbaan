from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.orm import Session

from .redaction import redact


def has_table(db: Session, table_name: str) -> bool:
    return bool(db.bind and inspect(db.bind).has_table(table_name))


def reflected_table(db: Session, table_name: str) -> Table | None:
    if not db.bind or not inspect(db.bind).has_table(table_name):
        return None
    return Table(table_name, MetaData(), autoload_with=db.bind)


def safe_rows(
    db: Session,
    table_name: str,
    allowed_columns: Iterable[str],
    *,
    limit: int = 200,
    order_candidates: tuple[str, ...] = ("created_at", "updated_at", "time"),
) -> list[dict[str, Any]]:
    table = reflected_table(db, table_name)
    if table is None:
        return []
    columns = [table.c[name] for name in allowed_columns if name in table.c]
    if not columns:
        return []
    statement = select(*columns)
    for candidate in order_candidates:
        if candidate in table.c:
            statement = statement.order_by(table.c[candidate].desc())
            break
    records = db.execute(statement.limit(max(1, min(limit, 1000)))).mappings().all()
    return [redact(dict(record)) for record in records]


def safe_count(db: Session, table_name: str, statuses: set[str] | None = None) -> int | None:
    table = reflected_table(db, table_name)
    if table is None:
        return None
    statement = select(func.count()).select_from(table)
    if statuses and "status" in table.c:
        statement = statement.where(table.c.status.in_(statuses))
    return int(db.scalar(statement) or 0)


def serialize_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.isoformat() if isinstance(item, (datetime, date)) else item
        for key, item in value.items()
    }
