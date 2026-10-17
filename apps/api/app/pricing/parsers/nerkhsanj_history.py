from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..models import Currency, InstrumentDefinition, WeightUnit, utc_now
from .base import ParserError, require_list, require_object, strict_decimal

if TYPE_CHECKING:
    from .history import HistoricalPricePoint


_SOURCE_DATE = re.compile(r"([0-9]{4})/([0-9]{2})/([0-9]{2})\Z")
_TEHRAN = ZoneInfo("Asia/Tehran")
_JALALI_BREAKS = (
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181,
    1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178,
)


def _jalali_year_start(year: int) -> date:
    # Borkowski's Jalali break-year method: Gregorian March day of Farvardin 1.
    # Only the documented 1300..1500 input window is exposed below. This avoids
    # extrapolating a fixed 2820-year cycle across disputed leap-year boundaries.
    gregorian_year = year + 621
    jalali_leaps = -14
    previous_break = _JALALI_BREAKS[0]
    for next_break in _JALALI_BREAKS[1:]:
        jump = next_break - previous_break
        if year < next_break:
            break
        jalali_leaps += (jump // 33) * 8 + (jump % 33) // 4
        previous_break = next_break
    years_since_break = year - previous_break
    jalali_leaps += (years_since_break // 33) * 8 + ((years_since_break % 33) + 3) // 4
    if jump % 33 == 4 and jump - years_since_break == 4:
        jalali_leaps += 1
    gregorian_leaps = (
        gregorian_year // 4 - ((gregorian_year // 100 + 1) * 3) // 4 - 150
    )
    return date(gregorian_year, 3, 20 + jalali_leaps - gregorian_leaps)


def _source_day(value: object) -> date:
    match = _SOURCE_DATE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ParserError("invalid_source_date", "Daily source date must use YYYY/MM/DD")
    year, month, day = (int(part) for part in match.groups())
    if not (1300 <= year <= 1500 and 1 <= month <= 12):
        raise ParserError("invalid_source_date", "Daily source date is outside supported calendar bounds")
    year_start = _jalali_year_start(year)
    leap_year = (_jalali_year_start(year + 1) - year_start).days == 366
    month_length = 31 if month <= 6 else (30 if month <= 11 or leap_year else 29)
    if not 1 <= day <= month_length:
        raise ParserError("invalid_source_date", "Daily source date is not a valid Jalali day")
    offset = (month - 1) * 31 if month <= 6 else 186 + (month - 7) * 30
    return year_start + timedelta(days=offset + day - 1)


def _history_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if any(
        not isinstance(value, datetime)
        or value.tzinfo is None or value.utcoffset() is None
        for value in (start, end)
    ):
        raise ParserError("invalid_history_range", "History range needs explicit timezones")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end < start or end - start > timedelta(days=366):
        raise ParserError("invalid_history_range", "Daily history range must be within 366 days")
    return start, end


def _price(value: object) -> Decimal:
    if (isinstance(value, str) and len(value) > 128) or (
        isinstance(value, int) and value.bit_length() > 256
    ):
        raise ParserError("invalid_number", "Daily close number is too long")
    try:
        return strict_decimal(value, "daily close")
    except InvalidOperation as exc:
        raise ParserError("invalid_number", "Daily close must be finite and positive") from exc


@dataclass(frozen=True, slots=True)
class NerkhsanjDailyHistoryParser:
    symbol: str = "silver"
    parser_version: str = "nerkhsanj-daily-history/1.0.0"

    def parse(
        self,
        payload: object,
        instrument: InstrumentDefinition,
        range_start: datetime,
        range_end: datetime,
    ) -> list[HistoricalPricePoint]:
        # Lazy import keeps the history parser registry free of an import cycle.
        from .history import HistoricalPricePoint

        if self.symbol != "silver" or instrument.instrument_id != "SILVER_999_TOMAN_GRAM":
            raise ParserError("unsupported_symbol", "Daily archive supports only silver 999")
        if instrument.quote_currency is not Currency.TOMAN:
            raise ParserError("currency_mismatch", "Daily silver archive is quoted in Toman")
        if instrument.weight_unit is not WeightUnit.GRAM:
            raise ParserError("unit_mismatch", "Daily silver archive is quoted per gram")
        if instrument.purity != Decimal("0.999") or instrument.base_asset != "XAG":
            raise ParserError("purity_mismatch", "Daily silver archive requires silver 999")
        range_start, range_end = _history_range(range_start, range_end)
        root = require_object(payload, "Nerkhsanj daily history response")
        series = require_list(root.get("series"), "history.series")
        if len(series) > 64:
            raise ParserError("history_too_large", "Daily archive has too many series")
        selected: list | None = None
        for raw_series in series:
            item = require_object(raw_series, "daily history series")
            key, name = item.get("key"), item.get("name")
            if not isinstance(key, str) or not 1 <= len(key) <= 64:
                raise ParserError("history_shape", "Daily series needs a bounded source key")
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise ParserError("history_shape", "Daily series needs a bounded source name")
            days = require_list(item.get("days"), "daily history days")
            if key == self.symbol:
                if selected is not None:
                    raise ParserError("duplicate_series", "Daily archive repeats the silver series")
                selected = days
        if selected is None:
            raise ParserError("missing_series", "Daily archive has no silver series")
        if len(selected) > 20_000:
            raise ParserError("history_too_large", "Daily silver archive has too many rows")
        today = utc_now().astimezone(_TEHRAN).date()
        points: list[HistoricalPricePoint] = []
        seen: set[date] = set()
        for row in selected:
            if not isinstance(row, list) or len(row) != 2:
                raise ParserError("history_shape", "Daily point must contain source date and close")
            source_date = row[0]
            source_day = _source_day(source_date)
            if source_day in seen:
                raise ParserError("duplicate_date", "Daily archive repeats a silver date")
            seen.add(source_day)
            price = _price(row[1])
            # Midnight is a chart bucket label. No observation/closing hour exists
            # in this source; current/future calendar days are not final closes.
            bucket_start = datetime.combine(source_day, datetime.min.time(), _TEHRAN).astimezone(UTC)
            if source_day >= today or not range_start <= bucket_start <= range_end:
                continue
            # Current instrument limits govern returned history, not unrelated
            # old archive values that are neither returned nor persisted.
            if not instrument.accepts(price):
                raise ParserError("outside_sanity_bounds", "Daily close is outside instrument bounds")
            points.append(HistoricalPricePoint(
                observed_at=bucket_start,
                price=price,
                volume=None,
                metadata={
                    "source_calendar": "jalali",
                    "source_date": source_date,
                    "source_timezone": "Asia/Tehran",
                    "timestamp_precision": "day",
                    "timestamp_role": "day_bucket_start",
                    "source_observation_time_known": False,
                    "history_point_kind": "source_reported_daily_close",
                },
            ))
        return sorted(points, key=lambda point: point.observed_at)
