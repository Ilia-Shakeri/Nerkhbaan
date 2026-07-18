from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .history import TIMEFRAMES
from .instruments import LEGACY_ASSET_MAPPING
from .models import CanonicalQuote, CanonicalStatus
from .service import InstrumentPricingService, instrument_pricing_service

_LABELS = {
    "gold": {"fa": "\u0637\u0644\u0627", "en": "Gold"},
    "silver": {"fa": "\u0646\u0642\u0631\u0647", "en": "Silver"},
    "usdt": {"fa": "\u062a\u062a\u0631", "en": "Tether"},
    "btc": {"fa": "\u0628\u06cc\u062a \u06a9\u0648\u06cc\u0646", "en": "Bitcoin"},
}

_CHART_ERROR = {
    "fa": "\u062f\u0627\u062f\u0647 \u0628\u0627\u0632\u0627\u0631 \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0646\u06cc\u0633\u062a",
    "en": "Unable to fetch market data",
}


class LegacyPricingAdapter:
    def __init__(self, service: InstrumentPricingService = instrument_pricing_service) -> None:
        self.service = service

    async def get_prices(self) -> dict[str, Any]:
        snapshots = await self.service.get_all_canonical()
        assets = [
            await self._asset_payload(asset, snapshots)
            for asset in ("gold", "silver", "usdt", "btc")
        ]
        refresh_times = [
            quote.canonical_at for quote in snapshots.values() if quote is not None
        ]
        refreshed_at = max(refresh_times).isoformat() if refresh_times else datetime.now(UTC).isoformat()
        return {
            "refreshed_at": refreshed_at,
            "source": {"usd": "canonical", "toman": "canonical"},
            "assets": assets,
        }

    async def get_history(self, asset: str, timeframe: str = "30d") -> dict[str, Any]:
        normalized = asset.lower()
        if normalized not in _LABELS:
            raise ValueError("Unknown asset")
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported timeframe")
        usd_id = LEGACY_ASSET_MAPPING[(normalized, "usd")]
        toman_id = LEGACY_ASSET_MAPPING[(normalized, "toman")]
        usd, toman = await self._paired_history(usd_id, toman_id, timeframe)
        merged = self._merge_history(usd.points, toman.points)
        return {
            "asset": normalized,
            "timeframe": timeframe,
            "status": "partial" if "partial" in {usd.status, toman.status} else "complete",
            "points": merged,
        }

    async def health(self) -> dict[str, Any]:
        snapshots = await self.service.get_all_canonical()
        chains: dict[str, Any] = {}
        for asset in _LABELS:
            toman = snapshots.get(LEGACY_ASSET_MAPPING[(asset, "toman")])
            usd = snapshots.get(LEGACY_ASSET_MAPPING[(asset, "usd")])
            chains[asset] = {
                "iran": self._chain_health(toman),
                "international": self._chain_health(usd),
            }
        times = [quote.canonical_at for quote in snapshots.values()]
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "last_refresh_at": max(times).isoformat() if times else None,
            "startup": {
                "checked_at": datetime.now(UTC).isoformat(),
                "required_env_keys": [],
                "missing_env_keys": [],
                "optional_env_keys": [],
                "missing_optional_env_keys": [],
                "strict_mode": False,
                "ok": True,
            },
            "chains": chains,
        }

    async def _asset_payload(
        self,
        asset: str,
        snapshots: dict[str, CanonicalQuote],
    ) -> dict[str, Any]:
        usd_id = LEGACY_ASSET_MAPPING[(asset, "usd")]
        toman_id = LEGACY_ASSET_MAPPING[(asset, "toman")]
        usd = snapshots.get(usd_id)
        toman = snapshots.get(toman_id)
        change = toman.change_24h if toman else (usd.change_24h if usd else None)
        ages = [
            int((datetime.now(UTC) - quote.observed_at).total_seconds() // 60)
            for quote in (usd, toman)
            if quote is not None
        ]
        history = await self._short_history(usd_id, toman_id)
        return {
            "asset": asset,
            "label_fa": _LABELS[asset]["fa"],
            "label_en": _LABELS[asset]["en"],
            "price_usd": float(usd.price) if usd else None,
            "price_toman": float(toman.price) if toman else None,
            "change_percent": float(change) if change is not None else None,
            "trend": "neutral" if change is None else ("up" if change >= 0 else "down"),
            "history": history,
            "source_usd": self._public_source(usd),
            "source_toman": self._public_source(toman),
            "usd_status": usd.effective_status().value if usd else "unavailable",
            "toman_status": toman.effective_status().value if toman else "unavailable",
            "stale_minutes": max(ages) if ages else None,
            "chart_error": usd is None and toman is None,
            "chart_error_message": _CHART_ERROR,
        }

    async def _paired_history(self, usd_id: str, toman_id: str, timeframe: str):
        import asyncio

        return await asyncio.gather(
            self.service.canonical_history(usd_id, timeframe),
            self.service.canonical_history(toman_id, timeframe),
        )

    async def _short_history(
        self, usd_id: str, toman_id: str
    ) -> list[dict[str, Any]]:
        import asyncio

        try:
            usd_quotes, toman_quotes = await asyncio.gather(
                self.service.store.recent_canonical(usd_id, limit=48),
                self.service.store.recent_canonical(toman_id, limit=48),
            )
        except Exception:
            return []
        buckets: dict[str, dict[str, Any]] = {}
        for field, quotes in (("value_usd", usd_quotes), ("value_toman", toman_quotes)):
            for quote in reversed(quotes):
                timestamp = quote.canonical_at.replace(second=0, microsecond=0).isoformat()
                buckets.setdefault(timestamp, {"timestamp": timestamp})[field] = float(
                    quote.price
                )
        return [
            {
                "timestamp": timestamp,
                "value_usd": row.get("value_usd"),
                "value_toman": row.get("value_toman"),
                "open": None,
                "close": None,
                "high": None,
                "low": None,
                "volume": None,
            }
            for timestamp, row in sorted(buckets.items())[-48:]
        ]

    @staticmethod
    def _merge_history(
        usd_points: list[dict[str, Any]],
        toman_points: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        combined: dict[str, dict[str, Any]] = {}
        for point in usd_points:
            combined.setdefault(point["timestamp"], {"timestamp": point["timestamp"]})[
                "value_usd"
            ] = point["value"]
        for point in toman_points:
            row = combined.setdefault(point["timestamp"], {"timestamp": point["timestamp"]})
            row["value_toman"] = point["value"]
            for key in ("open", "close", "high", "low"):
                row[key] = point.get(key)
        return [
            {
                "timestamp": timestamp,
                "value_usd": row.get("value_usd"),
                "value_toman": row.get("value_toman"),
                "open": row.get("open"),
                "close": row.get("close"),
                "high": row.get("high"),
                "low": row.get("low"),
                "volume": None,
            }
            for timestamp, row in sorted(combined.items())
        ]

    @staticmethod
    def _public_source(quote: CanonicalQuote | None) -> str:
        if quote is None:
            return "unavailable"
        return "derived" if quote.status is CanonicalStatus.DERIVED_FALLBACK else "canonical"

    @classmethod
    def _chain_health(cls, quote: CanonicalQuote | None) -> dict[str, Any]:
        return {
            "status": quote.effective_status().value if quote else "unavailable",
            "source": cls._public_source(quote),
            "updated_at": quote.canonical_at.isoformat() if quote else None,
            "error": None if quote else "No canonical snapshot",
            "providers": [],
        }


legacy_pricing_adapter = LegacyPricingAdapter()
