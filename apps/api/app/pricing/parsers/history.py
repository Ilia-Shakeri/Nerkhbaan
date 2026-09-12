from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..models import InstrumentDefinition, ensure_utc, parse_datetime
from .base import ParserError, exact_path, require_list, require_object, strict_decimal


@dataclass(frozen=True, slots=True)
class HistoricalPricePoint:
    observed_at: datetime
    price: Decimal
    volume: Decimal | None


@dataclass(frozen=True, slots=True)
class NobitexUdfHistoryParser:
    symbol: str
    parser_version: str = "nobitex-udf-history/1.0.0"

    def parse(
        self,
        payload: object,
        instrument: InstrumentDefinition,
        range_start: datetime,
        range_end: datetime,
    ) -> list[HistoricalPricePoint]:
        root = require_object(payload, "Nobitex history response")
        if root.get("s") != "ok":
            raise ParserError("history_status", "Nobitex history status is not ok")
        timestamps = require_list(root.get("t"), "history.t")
        closes = require_list(root.get("c"), "history.c")
        volumes = require_list(root.get("v"), "history.v")
        if not (len(timestamps) == len(closes) == len(volumes)):
            raise ParserError("history_shape", "History arrays have different lengths")
        if len(timestamps) > 20_000:
            raise ParserError("history_too_large", "History response has too many points")
        points: list[HistoricalPricePoint] = []
        last_timestamp: datetime | None = None
        for index, raw_timestamp in enumerate(timestamps):
            try:
                timestamp_value = int(raw_timestamp)
                observed_at = datetime.fromtimestamp(timestamp_value, UTC)
            except (OSError, OverflowError, TypeError, ValueError) as exc:
                raise ParserError("invalid_timestamp", "History timestamp is invalid") from exc
            if observed_at < range_start or observed_at > range_end:
                continue
            if last_timestamp is not None and observed_at <= last_timestamp:
                raise ParserError("history_order", "History timestamps are not strictly ordered")
            price = strict_decimal(closes[index], "history close")
            if not instrument.accepts(price):
                raise ParserError(
                    "outside_sanity_bounds", "History price is outside instrument bounds"
                )
            raw_volume = volumes[index]
            volume = None
            if raw_volume not in (None, ""):
                volume = strict_decimal(raw_volume, "history volume", allow_zero=True)
            points.append(
                HistoricalPricePoint(
                    observed_at=observed_at,
                    price=price,
                    volume=volume,
                )
            )
            last_timestamp = observed_at
        return points


@dataclass(frozen=True, slots=True)
class CoinGeckoHistoryParser:
    asset_id: str
    parser_version: str = "coingecko-market-chart/1.0.0"

    def parse(
        self,
        payload: object,
        instrument: InstrumentDefinition,
        range_start: datetime,
        range_end: datetime,
    ) -> list[HistoricalPricePoint]:
        root = require_object(payload, "CoinGecko history response")
        prices = require_list(root.get("prices"), "history.prices")
        volumes = {row[0]: row[1] for row in require_list(root.get("total_volumes", []), "history.total_volumes") if isinstance(row, list) and len(row) == 2}
        points: list[HistoricalPricePoint] = []
        last_timestamp: datetime | None = None
        for row in prices:
            if not isinstance(row, list) or len(row) != 2:
                raise ParserError("history_shape", "CoinGecko history point is invalid")
            try:
                observed_at = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
            except (OSError, OverflowError, TypeError, ValueError) as exc:
                raise ParserError("invalid_timestamp", "History timestamp is invalid") from exc
            if observed_at < range_start or observed_at > range_end:
                continue
            if last_timestamp is not None and observed_at <= last_timestamp:
                raise ParserError("history_order", "History timestamps are not strictly ordered")
            price = strict_decimal(row[1], "history price")
            if not instrument.accepts(price):
                raise ParserError("outside_sanity_bounds", "History price is outside instrument bounds")
            raw_volume = volumes.get(row[0])
            volume = strict_decimal(raw_volume, "history volume", allow_zero=True) if raw_volume not in (None, "") else None
            points.append(HistoricalPricePoint(observed_at=observed_at, price=price, volume=volume))
            last_timestamp = observed_at
        return points


@dataclass(frozen=True, slots=True)
class ServixHistoryParser:
    symbol: str
    quote_unit: str
    conversion_factor: Decimal = Decimal("1")
    parser_version: str = "servix-history/1.0.0"

    def parse(
        self,
        payload: object,
        instrument: InstrumentDefinition,
        range_start: datetime,
        range_end: datetime,
    ) -> list[HistoricalPricePoint]:
        rows = require_list(payload, "Servix history response")
        if len(rows) > 20_000:
            raise ParserError("history_too_large", "History response has too many points")
        points: list[HistoricalPricePoint] = []
        for raw_row in rows:
            row = require_object(raw_row, "Servix history row")
            if row.get("code") != self.symbol:
                raise ParserError("unsupported_symbol", "Servix history symbol does not match")
            if row.get("quoteUnit") != self.quote_unit:
                raise ParserError("unknown_unit", "Servix history quote unit does not match")
            try:
                observed_at = ensure_utc(parse_datetime(exact_path(row, "businessTime")))
            except (TypeError, ValueError) as exc:
                raise ParserError("invalid_timestamp", "History timestamp is invalid") from exc
            if observed_at < range_start or observed_at > range_end:
                continue
            price = strict_decimal(exact_path(row, "value"), "history value")
            price *= self.conversion_factor
            if not instrument.accepts(price):
                raise ParserError(
                    "outside_sanity_bounds", "History price is outside instrument bounds"
                )
            points.append(
                HistoricalPricePoint(observed_at=observed_at, price=price, volume=None)
            )
        points.sort(key=lambda point: point.observed_at)
        if any(
            current.observed_at <= previous.observed_at
            for previous, current in zip(points, points[1:])
        ):
            raise ParserError("history_order", "History timestamps are not unique")
        return points


def build_history_parser(
    parser_id: str,
) -> NobitexUdfHistoryParser | CoinGeckoHistoryParser | ServixHistoryParser:
    parsers = {
        "nobitex_udf_usdtirt_v1": NobitexUdfHistoryParser("USDTIRT"),
        "nobitex_udf_btcirt_v1": NobitexUdfHistoryParser("BTCIRT"),
        "coingecko_bitcoin_usd_history_v1": CoinGeckoHistoryParser("bitcoin"),
        "coingecko_tether_usd_history_v1": CoinGeckoHistoryParser("tether"),
        "servix_btc_usd_history_v1": ServixHistoryParser("BTC_USD", "USD"),
        "servix_usdt_usd_history_v1": ServixHistoryParser("USDT_USD", "USD"),
        "servix_usd_rls_history_v1": ServixHistoryParser(
            "USD_RLS", "RLS", Decimal("0.1")
        ),
    }
    try:
        return parsers[parser_id]
    except KeyError as exc:
        raise ParserError("unknown_history_parser", "History parser is not registered") from exc
