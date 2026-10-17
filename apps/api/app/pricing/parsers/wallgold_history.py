from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from ..models import Currency, InstrumentDefinition, WeightUnit, utc_now
from .base import ParserError, require_list, require_object
from .history import HistoricalPricePoint
from .nerkhsanj_history import _history_range, _price


def _candle_start(value: object, period: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ParserError("invalid_timestamp", "Candle date needs an explicit UTC timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
            raise ValueError
        stamp = stamp.astimezone(UTC)
    except ValueError as exc:
        raise ParserError("invalid_timestamp", "Candle date needs an explicit UTC timestamp") from exc
    if stamp.minute or stamp.second or stamp.microsecond or (period == "day" and stamp.hour):
        raise ParserError("invalid_timestamp", "Candle must start at its published UTC period boundary")
    return stamp


@dataclass(frozen=True, slots=True)
class WallgoldSilver925HistoryParser:
    # The caller binds this parser to the fixed, allowlisted SLV_925TMN URL.
    # The public chart body does not echo the requested market or currency.
    period: Literal["hour", "day"] = "day"
    parser_version: str = "wallgold-ohlc-history/1.0.0"

    def parse(self, payload: object, instrument: InstrumentDefinition,
              range_start: datetime, range_end: datetime) -> list[HistoricalPricePoint]:
        if self.period not in {"hour", "day"}:
            raise ParserError("unsupported_period", "Wallgold history period must be hour or day")
        if instrument.instrument_id != "SILVER_925_TOMAN_GRAM":
            raise ParserError("unsupported_symbol", "Chart route supports only the published SLV_925TMN market")
        if instrument.quote_currency is not Currency.TOMAN:
            raise ParserError("currency_mismatch", "SLV_925TMN candles are denominated in Toman")
        if instrument.weight_unit is not WeightUnit.GRAM:
            raise ParserError("unit_mismatch", "SLV_925TMN candles quote each gram")
        if instrument.purity != Decimal("0.925") or instrument.base_asset != "XAG":
            raise ParserError("purity_mismatch", "SLV_925TMN candles require physical silver 925")
        range_start, range_end = _history_range(range_start, range_end)
        root = require_object(payload, "Wallgold history response")
        if root.get("success") is not True:
            raise ParserError("provider_error", "Wallgold history request failed")
        result = require_object(root.get("result"), "history.result")
        chart = require_object(result.get("chart"), "history.result.chart")
        rows = require_list(chart.get("data"), "history.result.chart.data")
        # MONTHLY exposes at most 31 days of hourly bars; YEARLY exposes at
        # most one year of daily bars. Missing sessions are never filled here.
        maximum_rows = 744 if self.period == "hour" else 366
        if len(rows) > maximum_rows:
            raise ParserError("history_too_large", "Chart exceeds its published period capacity")
        interval = timedelta(hours=1) if self.period == "hour" else timedelta(days=1)
        now = utc_now().astimezone(UTC)
        points, seen = [], set()
        for raw in rows:
            row = require_object(raw, "OHLC candle")
            stamp = _candle_start(row.get("date"), self.period)
            if stamp in seen:
                raise ParserError("duplicate_timestamp", "Chart repeats a candle boundary")
            seen.add(stamp)
            prices = {key: _price(row.get(key)) for key in ("open", "low", "high", "close")}
            if not (prices["low"] <= prices["open"] <= prices["high"]
                    and prices["low"] <= prices["close"] <= prices["high"]):
                raise ParserError("invalid_ohlc", "Candle prices contradict their low and high")
            # A bar labels its start. Its close is final only when that complete
            # UTC period has ended, regardless of when this response arrived.
            if stamp + interval > now or not range_start <= stamp <= range_end:
                continue
            if any(not instrument.accepts(price) for price in prices.values()):
                raise ParserError("outside_sanity_bounds", "Candle is outside instrument price bounds")
            metadata = {
                "source_key": "SLV_925TMN",
                "source_currency": "TOMAN", "source_weight_unit": "gram",
                "source_calendar": "gregorian", "source_timezone": "UTC",
                "source_date": stamp.date().isoformat(),
                "source_observation_time_known": False,
                "source_trade_time_known": False,
                "source_candle_time_role": "period_start",
                "source_candle_interval_seconds": int(interval.total_seconds()),
                "history_point_kind": f"source_reported_{'daily' if self.period == 'day' else 'hourly'}_close",
                "source_ohlc": {key: str(price) for key, price in prices.items()},
            }
            if self.period == "day":
                metadata.update({"timestamp_precision": "day", "timestamp_role": "day_bucket_start"})
            points.append(HistoricalPricePoint(stamp, prices["close"], None, metadata))
        return sorted(points, key=lambda point: point.observed_at)
