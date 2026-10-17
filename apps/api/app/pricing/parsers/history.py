from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ..models import InstrumentDefinition, ensure_utc, utc_now
from .base import ParserError, exact_path, require_list, require_object, strict_decimal


@dataclass(frozen=True, slots=True)
class HistoricalPricePoint:
    observed_at: datetime
    price: Decimal
    volume: Decimal | None


@dataclass(frozen=True, slots=True)
class WallexUdfHistoryParser:
    symbol: str
    instrument_id: str
    parser_version: str = "wallex-udf-history/1.0.0"

    def parse(self, payload: object, instrument: InstrumentDefinition,
              range_start: datetime, range_end: datetime) -> list[HistoricalPricePoint]:
        if instrument.instrument_id != self.instrument_id or instrument.quote_currency.value != "TOMAN":
            raise ParserError("currency_mismatch", "Wallex market does not match instrument")
        root = require_object(payload, "Wallex history response")
        if root.get("s") == "no_data":
            return []
        if root.get("s") != "ok":
            raise ParserError("history_status", "Wallex history status is not ok")
        arrays = {key: require_list(root.get(key), "history." + key) for key in ("t", "o", "h", "l", "c", "v")}
        count = len(arrays["t"])
        if count > 20_000 or any(len(values) != count for values in arrays.values()):
            raise ParserError("history_shape", "Wallex candle arrays have invalid lengths")
        closed_before = min(ensure_utc(range_end), utc_now())
        points: list[HistoricalPricePoint] = []
        previous: datetime | None = None
        for index, raw_time in enumerate(arrays["t"]):
            if isinstance(raw_time, bool) or not isinstance(raw_time, (int, str)) or not str(raw_time).isdigit():
                raise ParserError("invalid_timestamp", "Wallex candle time must be Unix seconds")
            try:
                observed_at = datetime.fromtimestamp(int(raw_time), UTC)
            except (OSError, OverflowError, ValueError) as exc:
                raise ParserError("invalid_timestamp", "Wallex candle time is invalid") from exc
            if previous is not None and observed_at <= previous:
                raise ParserError("history_order", "Wallex candle times are not strictly ordered")
            previous = observed_at
            prices = {key: strict_decimal(arrays[key][index], "history " + key) for key in ("o", "h", "l", "c")}
            if not all(instrument.accepts(value) for value in prices.values()):
                raise ParserError("outside_sanity_bounds", "Wallex history price is outside instrument bounds")
            if not (prices["l"] <= min(prices["o"], prices["c"]) <= max(prices["o"], prices["c"]) <= prices["h"]):
                raise ParserError("history_ohlc", "Wallex candle bounds are inconsistent")
            volume = strict_decimal(arrays["v"][index], "history volume", allow_zero=True)
            # A closing observation is final only after its hour has ended.
            if observed_at < range_start or observed_at + timedelta(hours=1) > closed_before:
                continue
            points.append(HistoricalPricePoint(observed_at, prices["c"], volume))
        return points


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
        if root.get("s") == "no_data":
            # TradingView UDF explicitly distinguishes an empty range from an error.
            return []
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
    parser_version: str = "servix-history/1.1.0"

    def parse(
        self,
        payload: object,
        instrument: InstrumentDefinition,
        range_start: datetime,
        range_end: datetime,
    ) -> list[HistoricalPricePoint]:
        expected = {
            "USD_RLS": "USD_TOMAN", "BTC_USD": "BTC_USD", "USDT_USD": "USDT_USD",
            "GOLD_OUNCE_USD": "XAU_USD_OZ", "SILVER_OUNCE_USD": "XAG_USD_OZ",
            "GOLD_18_RLS": "GOLD_18K_TOMAN_GRAM", "GOLD_24_RLS": "GOLD_24K_TOMAN_GRAM",
        }
        if expected.get(self.symbol) != instrument.instrument_id:
            raise ParserError("unsupported_symbol", "Servix history code does not match instrument")
        expected_currency = "TOMAN" if self.quote_unit == "RLS" else self.quote_unit
        if instrument.quote_currency.value != expected_currency:
            raise ParserError("currency_mismatch", "Servix history currency does not match instrument")
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
            source_time = exact_path(row, "businessTime")
            if not isinstance(source_time, str) or not source_time.strip():
                raise ParserError("invalid_timestamp", "Servix history source time is required")
            try:
                observed_at = datetime.fromisoformat(source_time.strip().replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise ParserError("invalid_timestamp", "History timestamp is invalid") from exc
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ParserError("invalid_timestamp", "Servix history source timezone is required")
            observed_at = ensure_utc(observed_at)
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
) -> NobitexUdfHistoryParser | WallexUdfHistoryParser | CoinGeckoHistoryParser | ServixHistoryParser:
    parsers = {
        "nobitex_udf_usdtirt_v1": NobitexUdfHistoryParser("USDTIRT"),
        "nobitex_udf_btcirt_v1": NobitexUdfHistoryParser("BTCIRT"),
        "wallex_udf_usdt_toman_v1": WallexUdfHistoryParser("USDTTMN", "USDT_TOMAN"),
        "wallex_udf_btc_toman_v1": WallexUdfHistoryParser("BTCTMN", "BTC_TOMAN"),
        "coingecko_bitcoin_usd_history_v1": CoinGeckoHistoryParser("bitcoin"),
        "coingecko_tether_usd_history_v1": CoinGeckoHistoryParser("tether"),
        "servix_btc_usd_history_v1": ServixHistoryParser("BTC_USD", "USD"),
        "servix_usdt_usd_history_v1": ServixHistoryParser("USDT_USD", "USD"),
        "servix_usd_rls_history_v1": ServixHistoryParser(
            "USD_RLS", "RLS", Decimal("0.1")
        ),
        "servix_xau_usd_history_v1": ServixHistoryParser("GOLD_OUNCE_USD", "USD"),
        "servix_xag_usd_history_v1": ServixHistoryParser("SILVER_OUNCE_USD", "USD"),
        "servix_gold18_toman_history_v1": ServixHistoryParser("GOLD_18_RLS", "RLS", Decimal("0.1")),
        "servix_gold24_toman_history_v1": ServixHistoryParser("GOLD_24_RLS", "RLS", Decimal("0.1")),
    }
    try:
        return parsers[parser_id]
    except KeyError as exc:
        raise ParserError("unknown_history_parser", "History parser is not registered") from exc
