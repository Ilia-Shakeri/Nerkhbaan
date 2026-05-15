from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PricingCacheStore:
    def __init__(self, cache_file: Path) -> None:
        self.cache_file = cache_file
        self._dirty = False
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {"chains": {}, "history": {}}

        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {"chains": {}, "history": {}}

        if not isinstance(payload, dict):
            return {"chains": {}, "history": {}}

        payload.setdefault("chains", {})
        payload.setdefault("history", {})
        return payload

    def persist_if_dirty(self) -> None:
        if not self._dirty:
            return

        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.cache_file.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.cache_file)
        self._dirty = False

    def get_chain(self, asset_id: str, region: str) -> tuple[float, str, datetime] | None:
        chain_payload = self._data.get("chains", {}).get(asset_id, {}).get(region, {})
        if not isinstance(chain_payload, dict):
            return None

        value = self._to_float(chain_payload.get("value"))
        source = chain_payload.get("source")
        updated_raw = chain_payload.get("updated_at")
        if value is None or not isinstance(source, str) or not isinstance(updated_raw, str):
            return None

        try:
            updated_at = datetime.fromisoformat(updated_raw)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
        except ValueError:
            return None

        return (value, source, updated_at.astimezone(UTC))

    def set_chain(
        self,
        asset_id: str,
        region: str,
        value: float,
        source: str,
        updated_at: datetime,
    ) -> None:
        chains = self._data.setdefault("chains", {})
        asset_chains = chains.setdefault(asset_id, {})
        asset_chains[region] = {
            "value": value,
            "source": source,
            "updated_at": updated_at.replace(microsecond=0).isoformat(),
        }
        self._dirty = True

    def get_history(self, asset_id: str) -> list[dict[str, Any]]:
        history = self._data.get("history", {}).get(asset_id, [])
        if not isinstance(history, list):
            return []
        return history

    def set_history(self, asset_id: str, points: list[dict[str, Any]]) -> None:
        history_payload = self._data.setdefault("history", {})
        history_payload[asset_id] = points
        self._dirty = True

    @staticmethod
    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.replace(",", "").replace(" ", "").replace("_", "")
            try:
                return float(normalized)
            except ValueError:
                return None
        return None
