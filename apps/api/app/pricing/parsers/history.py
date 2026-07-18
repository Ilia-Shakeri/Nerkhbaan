from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from ..models import InstrumentDefinition
from .base import ParserError, require_list, require_object, strict_decimal


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


def build_history_parser(parser_id: str) -> NobitexUdfHistoryParser:
    parsers = {
        "nobitex_udf_usdtirt_v1": NobitexUdfHistoryParser("USDTIRT"),
        "nobitex_udf_btcirt_v1": NobitexUdfHistoryParser("BTCIRT"),
    }
    try:
        return parsers[parser_id]
    except KeyError as exc:
        raise ParserError("unknown_history_parser", "History parser is not registered") from exc
