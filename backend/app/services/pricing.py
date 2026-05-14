from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from ..config import settings

CACHE_TTL_SECONDS = 20
HISTORY_MAX_POINTS = 48


@dataclass
class LivePrices:
    gold_usd: float
    silver_usd: float
    gold_toman: float
    silver_toman: float
    source_usd: str
    source_toman: str


class PricingService:
    def __init__(self) -> None:
        self._last_refresh: datetime | None = None
        self._history: dict[str, list[dict[str, float | str]]] = {"gold": [], "silver": []}
        self._latest: LivePrices | None = None

    async def get_prices(self) -> dict:
        if self._should_refresh():
            await self._refresh_prices()

        if not self._latest:
            raise RuntimeError("Price cache is not initialized")

        return self._build_payload(self._latest)

    def _should_refresh(self) -> bool:
        if not self._last_refresh:
            return True
        return datetime.now(UTC) - self._last_refresh > timedelta(seconds=CACHE_TTL_SECONDS)

    async def _refresh_prices(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            usd_prices = await self._fetch_usd_prices(client)

            toman_prices: dict[str, float] | None = None
            toman_source = ""
            try:
                toman_prices = await self._fetch_toman_prices(client)
                toman_source = "alanchand"
            except Exception:
                toman_prices = None

            if toman_prices is None:
                toman_prices = await self._build_toman_from_fx(client, usd_prices)
                toman_source = "open.er-api (derived from USD)"

        current = LivePrices(
            gold_usd=usd_prices["gold"],
            silver_usd=usd_prices["silver"],
            gold_toman=toman_prices["gold"],
            silver_toman=toman_prices["silver"],
            source_usd="gold-api",
            source_toman=toman_source,
        )

        self._append_history(current)
        self._latest = current
        self._last_refresh = datetime.now(UTC)

    async def _fetch_usd_prices(self, client: httpx.AsyncClient) -> dict[str, float]:
        gold_response = await client.get(f"{settings.gold_api_base_url}/price/XAU")
        silver_response = await client.get(f"{settings.gold_api_base_url}/price/XAG")
        gold_response.raise_for_status()
        silver_response.raise_for_status()

        gold_payload = gold_response.json()
        silver_payload = silver_response.json()

        gold_price = self._to_float(gold_payload.get("price"))
        silver_price = self._to_float(silver_payload.get("price"))

        if gold_price is None or silver_price is None:
            raise RuntimeError("USD provider did not return valid prices")

        return {"gold": gold_price, "silver": silver_price}

    async def _fetch_toman_prices(self, client: httpx.AsyncClient) -> dict[str, float]:
        if not settings.alanchand_api_token:
            raise RuntimeError("ALANCHAND_API_TOKEN is not set")

        response = await client.get(
            settings.alanchand_api_base_url,
            params={"type": "gold"},
            headers={"Authorization": f"Bearer {settings.alanchand_api_token}"},
        )
        response.raise_for_status()

        payload = response.json()
        records = list(self._iter_dict_records(payload))

        gold_value = self._extract_value_by_keywords(
            records,
            include_keywords=["gold", "xau", "طلا", "18", "عیار"],
        )
        silver_value = self._extract_value_by_keywords(
            records,
            include_keywords=["silver", "xag", "نقره"],
        )

        if gold_value is None or silver_value is None:
            raise RuntimeError("Persian provider did not include gold/silver Toman prices")

        return {"gold": gold_value, "silver": silver_value}

    async def _build_toman_from_fx(
        self, client: httpx.AsyncClient, usd_prices: dict[str, float]
    ) -> dict[str, float]:
        response = await client.get(f"{settings.exchange_rate_api_base_url}/USD")
        response.raise_for_status()
        payload = response.json()

        irr_rate = self._to_float((payload.get("rates") or {}).get("IRR"))
        if irr_rate is None:
            raise RuntimeError("Exchange-rate provider did not include IRR rate")

        # 10 IRR equals 1 Toman.
        usd_to_toman = irr_rate / 10

        return {
            "gold": usd_prices["gold"] * usd_to_toman,
            "silver": usd_prices["silver"] * usd_to_toman,
        }

    def _append_history(self, prices: LivePrices) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()

        self._history["gold"].append(
            {"timestamp": now, "price_usd": prices.gold_usd, "price_toman": prices.gold_toman}
        )
        self._history["silver"].append(
            {"timestamp": now, "price_usd": prices.silver_usd, "price_toman": prices.silver_toman}
        )

        for asset_key in ("gold", "silver"):
            self._history[asset_key] = self._history[asset_key][-HISTORY_MAX_POINTS:]

    def _build_payload(self, prices: LivePrices) -> dict:
        gold_change = self._calc_change_percent("gold", prices.gold_usd)
        silver_change = self._calc_change_percent("silver", prices.silver_usd)

        return {
            "refreshed_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "source": {
                "usd": prices.source_usd,
                "toman": prices.source_toman,
            },
            "assets": [
                {
                    "asset": "gold",
                    "label_fa": "طلا",
                    "label_en": "Gold",
                    "price_usd": prices.gold_usd,
                    "price_toman": prices.gold_toman,
                    "change_percent": gold_change,
                    "trend": "up" if gold_change >= 0 else "down",
                    "history": self._history_points("gold"),
                },
                {
                    "asset": "silver",
                    "label_fa": "نقره",
                    "label_en": "Silver",
                    "price_usd": prices.silver_usd,
                    "price_toman": prices.silver_toman,
                    "change_percent": silver_change,
                    "trend": "up" if silver_change >= 0 else "down",
                    "history": self._history_points("silver"),
                },
            ],
        }

    def _history_points(self, asset_key: str) -> list[dict[str, str | float]]:
        return [
            {
                "timestamp": str(point["timestamp"]),
                "value_usd": float(point["price_usd"]),
                "value_toman": float(point["price_toman"]),
            }
            for point in self._history[asset_key]
        ]

    def _calc_change_percent(self, asset_key: str, latest_usd_price: float) -> float:
        history = self._history[asset_key]
        if len(history) < 2:
            return 0.0

        prev = float(history[-2]["price_usd"])
        if prev == 0:
            return 0.0

        return round(((latest_usd_price - prev) / prev) * 100, 2)

    def _extract_value_by_keywords(
        self,
        records: list[dict],
        include_keywords: list[str],
    ) -> float | None:
        best_value: float | None = None
        for record in records:
            text = " ".join(
                str(record.get(key, ""))
                for key in ("symbol", "name", "title", "label", "slug", "id")
            ).lower()
            if not any(keyword in text for keyword in include_keywords):
                continue

            number = self._extract_numeric_candidate(record)
            if number is None:
                continue

            unit = str(record.get("unit", "")).lower()
            currency = str(record.get("currency", "")).lower()
            if "rial" in unit or "ريال" in unit or "rial" in currency or "ريال" in currency:
                number = number / 10

            if number < 1_000:
                continue

            # Prefer larger values when both gram and ounce exist and Toman quote is usually larger.
            if best_value is None or number > best_value:
                best_value = number

        return best_value

    def _extract_numeric_candidate(self, record: dict) -> float | None:
        for key in ("price", "value", "last", "rate", "buy", "sell", "close"):
            if key in record:
                number = self._to_float(record.get(key))
                if number is not None:
                    return number

        for value in record.values():
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                number = self._to_float(value)
                if number is not None:
                    return number

        return None

    def _iter_dict_records(self, value: object) -> Iterable[dict]:
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from self._iter_dict_records(nested)
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_dict_records(item)

    def _to_float(self, value: object) -> float | None:
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


pricing_service = PricingService()
