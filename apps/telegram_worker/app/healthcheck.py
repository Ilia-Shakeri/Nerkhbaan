"""Fresh reconciliation receipts, never an assertion of device delivery."""
from datetime import UTC, datetime
import json
import os
from pathlib import Path


def healthy(path: str, *, now: datetime | None = None) -> bool:
    try:
        selected = Path(path)
        if selected.stat().st_size > 1_048_576:
            return False
        value = json.loads(selected.read_text(encoding="utf8"))
        sources = value["sources"]
        if value.get("schema_version") != 1 or not isinstance(sources, dict) or not sources:
            return False
        current = now or datetime.now(UTC)
        for row in sources.values():
            age = (current - datetime.fromisoformat(row["checked_at"])).total_seconds()
            if row["result"] != "reconciled" or not 0 <= age <= 180:
                return False
        return True
    except (OSError, KeyError, ValueError, TypeError, OverflowError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy(os.environ.get("TELEGRAM_STATE_PATH", "")) else 1)
