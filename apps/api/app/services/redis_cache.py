from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisPricingCache:
    def __init__(self, redis_url: str | None = None) -> None:
        self.redis_client = None
        self._fallback_mode = False
        
        if not REDIS_AVAILABLE or not redis_url:
            self._fallback_mode = True
            self._memory_cache: dict[str, Any] = {"chains": {}, "history": {}}
            return
        
        try:
            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2
            )
            self.redis_client.ping()
        except Exception:
            self._fallback_mode = True
            self._memory_cache = {"chains": {}, "history": {}}

    def get_chain(self, asset_id: str, region: str) -> tuple[float, str, datetime] | None:
        key = f"chain:{asset_id}:{region}"
        
        if self._fallback_mode:
            chain_payload = self._memory_cache.get("chains", {}).get(asset_id, {}).get(region, {})
        else:
            try:
                data = self.redis_client.get(key)
                if not data:
                    return None
                chain_payload = json.loads(data)
            except Exception:
                return None
        
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
        key = f"chain:{asset_id}:{region}"
        payload = {
            "value": value,
            "source": source,
            "updated_at": updated_at.replace(microsecond=0).isoformat(),
        }
        
        if self._fallback_mode:
            chains = self._memory_cache.setdefault("chains", {})
            asset_chains = chains.setdefault(asset_id, {})
            asset_chains[region] = payload
        else:
            try:
                self.redis_client.setex(
                    key,
                    300,
                    json.dumps(payload, ensure_ascii=False)
                )
            except Exception:
                pass

    def get_history(self, asset_id: str) -> list[dict[str, Any]]:
        key = f"history:{asset_id}"
        
        if self._fallback_mode:
            history = self._memory_cache.get("history", {}).get(asset_id, [])
        else:
            try:
                data = self.redis_client.get(key)
                if not data:
                    return []
                history = json.loads(data)
            except Exception:
                return []
        
        if not isinstance(history, list):
            return []
        return history

    def set_history(self, asset_id: str, points: list[dict[str, Any]]) -> None:
        key = f"history:{asset_id}"
        
        if self._fallback_mode:
            history_payload = self._memory_cache.setdefault("history", {})
            history_payload[asset_id] = points
        else:
            try:
                self.redis_client.setex(
                    key,
                    86400,
                    json.dumps(points, ensure_ascii=False)
                )
            except Exception:
                pass

    def persist_if_dirty(self) -> None:
        pass

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
