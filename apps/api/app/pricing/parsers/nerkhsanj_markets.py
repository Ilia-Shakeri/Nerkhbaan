from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from types import MappingProxyType

from ..models import Currency, InstrumentDefinition, WeightUnit, utc_now
from .base import (
    ParsedProviderValue, ParserContext, ParserError, optional_timestamp,
    require_list, require_object, validate_parsed_value,
)
from .history import HistoricalPricePoint
from .nerkhsanj_history import _TEHRAN, _history_range, _price, _source_day


@dataclass(frozen=True, slots=True)
class _Market:
    instrument_id: str
    currency: Currency
    unit: WeightUnit
    purity: Decimal | None
    base_asset: str


# Source keys and units come from the publisher's developers page. A 24K
# label alone does not certify the distinct 9999 instrument contract.
NERKHSANJ_MARKETS = MappingProxyType({
    "dollar": _Market("USD_TOMAN", Currency.TOMAN, WeightUnit.UNIT, None, "USD"),
    "gold": _Market("GOLD_18K_TOMAN_GRAM", Currency.TOMAN, WeightUnit.GRAM, Decimal("0.750"), "XAU_18K"),
    "silver": _Market("SILVER_999_TOMAN_GRAM", Currency.TOMAN, WeightUnit.GRAM, Decimal("0.999"), "XAG"),
    "tether": _Market("USDT_TOMAN", Currency.TOMAN, WeightUnit.UNIT, None, "USDT"),
    "bitcoin": _Market("BTC_TOMAN", Currency.TOMAN, WeightUnit.UNIT, None, "BTC"),
    "ounce": _Market("XAU_USD_OZ", Currency.USD, WeightUnit.TROY_OUNCE, Decimal("0.9999"), "XAU"),
    "silver-ounce": _Market("XAG_USD_OZ", Currency.USD, WeightUnit.TROY_OUNCE, Decimal("0.9999"), "XAG"),
})
_CLOCK = re.compile(r"([0-9]{2}):([0-9]{2})\Z")


def _market(symbol: str, instrument: InstrumentDefinition) -> _Market:
    market = NERKHSANJ_MARKETS.get(symbol)
    if market is None or market.instrument_id != instrument.instrument_id:
        raise ParserError("unsupported_symbol", "Published source key does not match the instrument")
    if instrument.quote_currency is not market.currency:
        raise ParserError("currency_mismatch", "Published source currency differs from instrument")
    if instrument.weight_unit is not market.unit:
        raise ParserError("unit_mismatch", "Published source weight unit differs from instrument")
    if instrument.purity != market.purity or instrument.base_asset != market.base_asset:
        raise ParserError("purity_mismatch", "Published source asset or purity differs from instrument")
    return market


def _source_instant(source_date: object, clock: object) -> datetime:
    day = _source_day(source_date)
    match = _CLOCK.fullmatch(clock) if isinstance(clock, str) else None
    if match is None:
        # The publisher leaves time blank outside market hours. Reception time
        # must never turn that previous close into a fresh quote.
        raise ParserError("missing_timestamp", "Publication needs an explicit Tehran clock")
    hour, minute = map(int, match.groups())
    try:
        return datetime.combine(day, time(hour, minute), _TEHRAN).astimezone(UTC)
    except ValueError as exc:
        raise ParserError("invalid_timestamp", "Publication clock is not a valid time") from exc


def parse_source_timestamp(payload: object) -> datetime:
    """Return the published snapshot clock; never substitute fetch time."""
    root = require_object(payload, "Nerkhsanj publication")
    return _source_instant(root.get("date"), root.get("time"))


def _publication_metadata(symbol: str, source_date: str, clock: str) -> dict:
    return {
        "source_key": symbol,
        "source_calendar": "jalali",
        "source_date": source_date,
        "source_time": clock,
        "source_timezone": "Asia/Tehran",
        "source_timestamp_precision": "minute",
        "source_timestamp_scope": "publication_snapshot",
        "source_observation_time_known": False,
        "source_trade_time_known": False,
        "source_currency": NERKHSANJ_MARKETS[symbol].currency.value,
        "conversion_factor": "1",
    }


@dataclass(frozen=True, slots=True)
class NerkhsanjSnapshotParser:
    symbol: str
    parser_version: str = "nerkhsanj-snapshot/1.1.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        market = _market(self.symbol, context.instrument)
        root = require_object(payload, "Nerkhsanj publication")
        source_date, clock = root.get("date"), root.get("time")
        instant = parse_source_timestamp(root)
        observed_at = optional_timestamp(instant.isoformat(), context, "publication timestamp")
        section = "usd" if market.currency is Currency.USD else "rates"
        values = require_object(root.get(section), f"publication.{section}")
        if self.symbol not in values:
            raise ParserError("missing_field", "Publication has no requested source key")
        price = _price(values[self.symbol])
        return validate_parsed_value(ParsedProviderValue(
            price=price, currency=market.currency, weight_unit=market.unit,
            purity=market.purity, observed_at=observed_at,
            metadata={**_publication_metadata(self.symbol, source_date, clock),
                      "source_timestamp_scope": "source_rates_last_change",
                      "original_value": str(price)},
        ), context)


@dataclass(frozen=True, slots=True)
class NerkhsanjMarketDailyHistoryParser:
    symbol: str
    parser_version: str = "nerkhsanj-daily-history/2.0.0"

    def parse(self, payload: object, instrument: InstrumentDefinition,
              range_start: datetime, range_end: datetime) -> list[HistoricalPricePoint]:
        market = _market(self.symbol, instrument)
        range_start, range_end = _history_range(range_start, range_end)
        root = require_object(payload, "Nerkhsanj daily archive")
        if market.currency is Currency.USD and root.get("unit") != "usd":
            raise ParserError("currency_mismatch", "Dollar archive needs its explicit usd unit")
        if market.currency is Currency.TOMAN and root.get("unit") not in (None, "toman"):
            raise ParserError("currency_mismatch", "Toman archive cannot use another currency")
        series = require_list(root.get("series"), "daily archive.series")
        if len(series) > 64:
            raise ParserError("history_too_large", "Daily archive has too many series")
        selected = None
        for raw in series:
            item = require_object(raw, "daily series")
            key, name = item.get("key"), item.get("name")
            if not isinstance(key, str) or not 1 <= len(key) <= 64:
                raise ParserError("history_shape", "Daily source key is not bounded")
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise ParserError("history_shape", "Daily source name is not bounded")
            days = require_list(item.get("days"), "daily series.days")
            if key == self.symbol:
                if selected is not None:
                    raise ParserError("duplicate_series", "Daily archive repeats the requested series")
                selected = days
        if selected is None:
            raise ParserError("missing_series", "Daily archive has no requested source key")
        if len(selected) > 20_000:
            raise ParserError("history_too_large", "Daily series has too many observations")
        today = utc_now().astimezone(_TEHRAN).date()
        seen = set()
        result = []
        for row in selected:
            if not isinstance(row, list) or len(row) != 2:
                raise ParserError("history_shape", "Daily observation needs date and close")
            source_day = _source_day(row[0])
            if source_day in seen:
                raise ParserError("duplicate_date", "Daily archive repeats an observation date")
            seen.add(source_day)
            price = _price(row[1])
            bucket = datetime.combine(source_day, time.min, _TEHRAN).astimezone(UTC)
            if source_day >= today or not range_start <= bucket <= range_end:
                continue
            if not instrument.accepts(price):
                raise ParserError("outside_sanity_bounds", "Daily close is outside instrument bounds")
            result.append(HistoricalPricePoint(bucket, price, None, {
                "source_key": self.symbol,
                "source_calendar": "jalali", "source_date": row[0],
                "source_timezone": "Asia/Tehran", "timestamp_precision": "day",
                "timestamp_role": "day_bucket_start", "source_observation_time_known": False,
                "history_point_kind": "source_reported_daily_close",
            }))
        return sorted(result, key=lambda point: point.observed_at)


@dataclass(frozen=True, slots=True)
class NerkhsanjIntradayHistoryParser:
    symbol: str
    parser_version: str = "nerkhsanj-intraday-history/1.0.0"

    def parse(self, payload: object, instrument: InstrumentDefinition,
              range_start: datetime, range_end: datetime) -> list[HistoricalPricePoint]:
        _market(self.symbol, instrument)
        range_start, range_end = _history_range(range_start, range_end)
        root = require_object(payload, "Nerkhsanj intraday archive")
        source_date, clock = root.get("date"), root.get("time")
        source_day = _source_day(source_date)
        now = utc_now()
        clock_known = clock not in (None, "")
        publication = _source_instant(source_date, clock) if clock_known else now
        if source_day > now.astimezone(_TEHRAN).date() or publication > now:
            raise ParserError("invalid_timestamp", "Intraday publication cannot be in the future")
        # This endpoint only publishes the Toman series. A missing USD leg must
        # not be manufactured by dividing two unrelated quote snapshots.
        if NERKHSANJ_MARKETS[self.symbol].currency is not Currency.TOMAN:
            raise ParserError("unsupported_symbol", "Intraday endpoint has no published USD series")
        series = require_object(root.get("series"), "intraday.series")
        if len(series) > 64:
            raise ParserError("history_too_large", "Intraday archive has too many series")
        if self.symbol not in series:
            raise ParserError("missing_series", "Intraday archive has no requested source key")
        item = require_object(series[self.symbol], "intraday source series")
        rows = require_list(item.get("points"), "intraday points")
        if len(rows) > 144:
            raise ParserError("history_too_large", "Intraday series exceeds ten-minute day capacity")
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                raise ParserError("history_shape", "Intraday observation needs clock and price")
            instant = _source_instant(source_date, row[0])
            if instant in seen:
                raise ParserError("duplicate_timestamp", "Intraday archive repeats a publication time")
            seen.add(instant)
            if instant > publication or instant > now:
                raise ParserError("invalid_timestamp", "Intraday point exceeds its publication time")
            price = _price(row[1])
            if not range_start <= instant <= range_end:
                continue
            if not instrument.accepts(price):
                raise ParserError("outside_sanity_bounds", "Intraday rate is outside instrument bounds")
            result.append(HistoricalPricePoint(instant, price, None, {
                **_publication_metadata(self.symbol, source_date, row[0]),
                "timestamp_precision": "instant",
                "history_point_kind": "source_reported_intraday_reference",
                "source_sample_interval_seconds": 600,
                "source_sample_interval_scope": "publisher_declared_nominal_cadence",
                "source_publication_clock_known": clock_known,
            }))
        return sorted(result, key=lambda point: point.observed_at)
