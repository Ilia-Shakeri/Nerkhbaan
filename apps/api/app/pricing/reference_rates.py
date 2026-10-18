"""Explicit Iranian reference valuations, separate from native market instruments."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, localcontext

from .freshness import DEFAULT_FUTURE_CLOCK_SKEW_SECONDS
from .instruments import get_instrument
from .models import utc_now
from .parsers.base import ParserError, require_list, require_object
from .parsers.nerkhsanj_history import _TEHRAN, _history_range, _price, _source_day
from .parsers.nerkhsanj_markets import parse_source_timestamp


SNAPSHOT_PROVIDER_ID = "nerkhsanj_reference_snapshot"
HISTORY_PROVIDER_ID = "nerkhsanj_reference_history"
_MAXIMUM_REFERENCE_AGE = 86_400
_MINIMUM_PRICE = Decimal("0.000000000001")
_MAXIMUM_PRICE = Decimal("1000000000000000000")


@dataclass(frozen=True, slots=True)
class _Reference:
    instrument_id: str
    label_fa: str
    label_en: str
    currency: str
    parents: tuple[tuple[str, str], ...]

    @property
    def method(self) -> str:
        return "published_reference" if len(self.parents) == 1 else "iran_fx_ratio"

    @property
    def fresh_seconds(self) -> int:
        limits = [get_instrument(instrument).operational_ttl_seconds for _, instrument in self.parents]
        return min(*limits, 60) if len(limits) > 1 else limits[0]


_REFERENCES = (
    _Reference("GOLD_24K_REFERENCE_TOMAN_GRAM", "طلای ۲۴ عیار؛ مرجع ناشر",
               "Published 24K gold reference", "TOMAN", (("gold24", "GOLD_24K_TOMAN_GRAM"),)),
    _Reference("BTC_USD_IRAN_REFERENCE", "بیت‌کوین/دلار؛ مرجع محاسباتی ایران",
               "BTC/USD Iranian reference valuation", "USD",
               (("bitcoin", "BTC_TOMAN"), ("dollar", "USD_TOMAN"))),
    _Reference("USDT_USD_IRAN_REFERENCE", "تتر/دلار؛ مرجع محاسباتی ایران",
               "USDT/USD Iranian reference valuation", "USD",
               (("tether", "USDT_TOMAN"), ("dollar", "USD_TOMAN"))),
)
REFERENCE_IDS = tuple(reference.instrument_id for reference in _REFERENCES)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ParserError("invalid_timestamp", "Reference clocks need explicit timezones")
    return value.astimezone(UTC)


def _money(value: object) -> Decimal:
    result = _price(value)
    if not _MINIMUM_PRICE <= result <= _MAXIMUM_PRICE:
        raise ParserError("outside_sanity_bounds", "Reference value exceeds bounded monetary range")
    return result


def _number(value: Decimal) -> float:
    if not value.is_finite() or not _MINIMUM_PRICE <= value <= _MAXIMUM_PRICE:
        raise ParserError("outside_sanity_bounds", "Reference result exceeds bounded monetary range")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ParserError("invalid_number", "Reference result must be a finite positive number")
    return result


def _value(reference: _Reference, values: list[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return values[0] if reference.method == "published_reference" else values[0] / values[1]


def _base(reference: _Reference, provider_id: str) -> dict:
    return {
        "instrument_id": reference.instrument_id,
        "label_fa": reference.label_fa, "label_en": reference.label_en,
        "currency": reference.currency, "market": "reference", "region": "iran",
        "weight_unit": "gram" if reference.currency == "TOMAN" else "unit",
        "purity": None, "physical_purity_confirmed": False,
        "nominal_karat": 24 if reference.currency == "TOMAN" else None,
        "method": reference.method, "is_derived": reference.method == "iran_fx_ratio",
        "source_provider_id": provider_id,
        "source_keys": [key for key, _ in reference.parents],
        "source_timezone": "Asia/Tehran", "source_calendar": "jalali",
        "source_observation_time_known": False, "source_trade_time_known": False,
        "attribution": {"label": "نرخ‌سنج", "url": "https://nerkh.jahankhahan.shop/developers"},
        "disclaimer_fa": (
            "نرخ مرجع منتشرشدهٔ ۲۴ عیار؛ عیار دقیق و قیمت معاملهٔ شمش ۹۹۹۹ تأیید نشده."
            if reference.method == "published_reference" else
            "نسبت قیمت‌های تومان در ایران؛ قیمت جهانی یا سنجش برابری جهانی تتر و دلار نیست."
        ),
    }


def reference_definitions() -> list[dict]:
    return [{**_base(reference, SNAPSHOT_PROVIDER_ID),
             "freshness_limit_seconds": reference.fresh_seconds,
             "maximum_reference_age_seconds": _MAXIMUM_REFERENCE_AGE}
            for reference in _REFERENCES]


def _record_clock(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ParserError("invalid_timestamp", "Reference record needs a bounded clock")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, OverflowError) as exc:
        raise ParserError("invalid_timestamp", "Reference record needs an aware clock") from exc


def _record_money(row: dict) -> Decimal:
    decimal = row.get("price_decimal")
    if not isinstance(decimal, str):
        raise ParserError("invalid_number", "Reference record needs its decimal string")
    value = _money(decimal)
    number = row.get("price")
    if (isinstance(number, bool) or not isinstance(number, (int, float))
            or number != _number(value)):
        raise ParserError("invalid_number", "Reference number differs from its decimal value")
    return value


def validate_reference_record(row: object, kind: str, *, now: datetime | None = None) -> None:
    """Check named contracts, parent arithmetic, and original source clocks."""
    row = require_object(row, "reference record")
    reference = next((item for item in _REFERENCES if item.instrument_id == row.get("instrument_id")), None)
    if reference is None or not isinstance(kind, str) or kind not in {"snapshot", "history"}:
        raise ParserError("reference_contract", "Reference record has no matching named contract")
    provider = SNAPSHOT_PROVIDER_ID if kind == "snapshot" else HISTORY_PROVIDER_ID
    expected = _base(reference, provider)
    for key in ("currency", "market", "region", "weight_unit", "purity", "physical_purity_confirmed",
                "nominal_karat", "method", "is_derived", "source_provider_id", "source_keys",
                "source_timezone", "source_calendar", "source_observation_time_known"):
        value = row.get(key)
        if (key not in row or value != expected[key]
                or (isinstance(expected[key], bool) and value is not expected[key])):
            raise ParserError("reference_contract", "Reference fields differ from their named contract")
    if row.get("source_trade_time_known", False) is not False:
        raise ParserError("reference_contract", "Reference cannot claim a known trade clock")
    if isinstance(row.get("nominal_karat"), bool):
        raise ParserError("reference_contract", "Reference karat must match its named contract")
    current = _utc(now if now is not None else utc_now())
    skew = timedelta(seconds=DEFAULT_FUTURE_CLOCK_SKEW_SECONDS)
    source_date = row.get("source_date")
    day = _source_day(source_date)
    if kind == "snapshot":
        stamp = _record_clock(row.get("observed_at"))
        received = _record_clock(row.get("received_at"))
        source = parse_source_timestamp({"date": source_date, "time": row.get("source_time")})
        if (stamp != source or row.get("source_timestamp_scope") != "source_rates_last_change"
                or row.get("source_timestamp_precision") != "minute"):
            raise ParserError("invalid_timestamp", "Reference source clock metadata differs from its clock")
        if stamp > min(received, current) + skew or received > current + skew:
            raise ParserError("future_timestamp", "Reference source clock exceeds receipt/current clock")
        if (row.get("status") not in ("fresh_reference", "delayed_reference")
                or row.get("freshness_limit_seconds") != reference.fresh_seconds
                or row.get("maximum_reference_age_seconds") != _MAXIMUM_REFERENCE_AGE):
            raise ParserError("reference_contract", "Priced reference needs its bounded age policy")
        precision, role = "minute", "source_rates_last_change"
    else:
        stamp = _record_clock(row.get("timestamp"))
        bucket = datetime.combine(day, time.min, _TEHRAN).astimezone(UTC)
        closed = datetime.combine(day + timedelta(days=1), time.min, _TEHRAN).astimezone(UTC)
        point_kind = "published_reference_daily_close" if len(reference.parents) == 1 else "same_day_iran_fx_ratio"
        if (stamp != bucket or closed > current or row.get("source_time") is not None
                or row.get("source_timestamp_scope") != "source_reported_daily_close"
                or row.get("timestamp_precision") != "day" or row.get("timestamp_role") != "day_bucket_start"
                or row.get("history_point_kind") != point_kind):
            raise ParserError("invalid_timestamp", "Reference history needs its completed source-day bucket")
        precision, role = "day", "day_bucket_start"
    inputs = require_list(row.get("inputs"), "reference record.inputs")
    if len(inputs) != len(reference.parents):
        raise ParserError("reference_parents", "Reference record needs its exact source parents")
    values = []
    for raw, (key, instrument_id) in zip(inputs, reference.parents, strict=True):
        parent = require_object(raw, "reference parent")
        parent_id = reference.instrument_id if key == "gold24" else instrument_id
        fields = {"source_key": key, "instrument_id": parent_id, "currency": "TOMAN",
                  "source_date": source_date, "source_timezone": "Asia/Tehran", "source_calendar": "jalali",
                  "timestamp_precision": precision, "timestamp_role": role}
        if (any(parent.get(name) != value for name, value in fields.items())
                or parent.get("source_observation_time_known") is not False
                or _record_clock(parent.get("as_of")) != stamp):
            raise ParserError("reference_parents", "Reference parent differs from its source contract or clock")
        values.append(_record_money(parent))
    if _record_money(row) != _value(reference, values):
        raise ParserError("reference_arithmetic", "Reference result differs from its parent arithmetic")


def _parent(key: str, instrument_id: str, price: Decimal | None, as_of: str | None,
            source_date: str, *, daily: bool = False) -> dict:
    # The unproved physical-gold contract is never asserted as an input.
    parent_instrument = REFERENCE_IDS[0] if key == "gold24" else instrument_id
    return {
        "source_key": key, "instrument_id": parent_instrument,
        "price": _number(price) if price is not None else None,
        "price_decimal": str(price) if price is not None else None,
        "currency": "TOMAN", "as_of": as_of, "source_date": source_date,
        "source_timezone": "Asia/Tehran", "source_calendar": "jalali",
        "timestamp_precision": "day" if daily else "minute",
        "timestamp_role": "day_bucket_start" if daily else "source_rates_last_change",
        "source_observation_time_known": False,
    }


def build_reference_snapshot(payload: object, *, received_at: datetime, now: datetime) -> list[dict]:
    """Keep old values as dated references, never relabel them live quotes."""
    received_at, now = _utc(received_at), _utc(now)
    skew = timedelta(seconds=DEFAULT_FUTURE_CLOCK_SKEW_SECONDS)
    if received_at > now + skew:
        raise ParserError("future_timestamp", "HTTP receipt cannot exceed the current clock")
    root = require_object(payload, "reference publication")
    if root.get("unit") not in (None, "toman"):
        raise ParserError("currency_mismatch", "Reference parent prices must be Toman")
    rates = require_object(root.get("rates"), "reference publication.rates")
    if len(rates) > 64:
        raise ParserError("payload_too_large", "Reference publication has too many source keys")
    source_date = root.get("date")
    source_day = _source_day(source_date)
    if source_day > now.astimezone(_TEHRAN).date():
        raise ParserError("future_timestamp", "Source date cannot be in the future")
    clock = root.get("time")
    observed_at = parse_source_timestamp(root) if clock not in (None, "") else None
    if observed_at is not None and (observed_at > received_at + skew or observed_at > now + skew):
        raise ParserError("future_timestamp", "Source clock exceeds receipt/current clock")
    as_of = observed_at.isoformat() if observed_at is not None else None
    age = max(0.0, (now - observed_at).total_seconds()) if observed_at is not None else None
    result = []
    for reference in _REFERENCES:
        item = {
            **_base(reference, SNAPSHOT_PROVIDER_ID),
            "price": None, "price_decimal": None, "status": "unavailable_reference",
            "source_date": source_date, "source_time": clock or None,
            "source_timestamp_scope": "source_rates_last_change",
            "source_timestamp_precision": "minute" if observed_at is not None else None,
            "observed_at": as_of, "received_at": received_at.isoformat(),
            "age_seconds": age, "freshness_limit_seconds": reference.fresh_seconds,
            "maximum_reference_age_seconds": _MAXIMUM_REFERENCE_AGE,
            "inputs": [], "unavailable_reason": None,
        }
        values, invalid = [], None
        for key, instrument_id in reference.parents:
            try:
                price = _money(rates.get(key))
            except ParserError as exc:
                price = None
                invalid = "missing_parent" if key not in rates else exc.code
            if price is not None:
                values.append(price)
            item["inputs"].append(_parent(key, instrument_id, price, as_of, source_date))
        if observed_at is None:
            item["unavailable_reason"] = "source_clock_unavailable"
        elif age > _MAXIMUM_REFERENCE_AGE:
            item["unavailable_reason"] = "source_older_than_24_hours"
        elif invalid:
            item["unavailable_reason"] = invalid
        else:
            try:
                value = _value(reference, values)
                item["price"], item["price_decimal"] = _number(value), str(value)
                item["status"] = "fresh_reference" if age <= reference.fresh_seconds else "delayed_reference"
            except ParserError as exc:
                item["unavailable_reason"] = exc.code
        result.append(item)
    return result


def build_reference_history(payload: object, *, range_start: datetime,
                            range_end: datetime) -> dict[str, list[dict]]:
    """Calculate ratios only on identical, completed published source days."""
    range_start, range_end = _history_range(range_start, range_end)
    root = require_object(payload, "reference daily archive")
    if root.get("unit") not in (None, "toman"):
        raise ParserError("currency_mismatch", "Reference daily parents must be Toman")
    series = require_list(root.get("series"), "reference daily archive.series")
    if len(series) > 64:
        raise ParserError("history_too_large", "Reference archive has too many series")
    now = _utc(utc_now())
    today = now.astimezone(_TEHRAN).date()
    updated = _source_day(root["updated"]) if "updated" in root else None
    if updated is not None and updated > today:
        raise ParserError("future_timestamp", "Archive publication date cannot be in the future")
    wanted = {key for reference in _REFERENCES for key, _ in reference.parents}
    available, seen_series = {}, set()
    for raw in series:
        item = require_object(raw, "reference daily series")
        key, name = item.get("key"), item.get("name")
        if not isinstance(key, str) or not 1 <= len(key) <= 64:
            raise ParserError("history_shape", "Daily source key must be bounded")
        if key in seen_series:
            raise ParserError("duplicate_series", "Daily source series must be unique")
        seen_series.add(key)
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ParserError("history_shape", "Daily source name must be bounded")
        days = require_list(item.get("days"), "reference daily series.days")
        if len(days) > 20_000:
            raise ParserError("history_too_large", "Daily source series has too many observations")
        if key not in wanted:
            continue
        selected, seen_days = {}, set()
        for row in days:
            if not isinstance(row, list) or len(row) != 2:
                raise ParserError("history_shape", "Daily reference needs date and price")
            source_date, value = row
            day = _source_day(source_date)
            if day in seen_days:
                raise ParserError("duplicate_date", "Daily reference cannot repeat a source date")
            seen_days.add(day)
            price = _money(value)
            if day > today or (updated is not None and day > updated):
                raise ParserError("future_timestamp", "Daily reference exceeds the source/current date")
            bucket = datetime.combine(day, time.min, _TEHRAN).astimezone(UTC)
            closed_at = datetime.combine(day + timedelta(days=1), time.min, _TEHRAN).astimezone(UTC)
            if closed_at > min(now, range_end) or not range_start <= bucket <= range_end:
                continue
            selected[source_date] = (bucket, price)
        available[key] = selected
    result = {reference.instrument_id: [] for reference in _REFERENCES}
    for reference in _REFERENCES:
        parents = [available.get(key, {}) for key, _ in reference.parents]
        common = set(parents[0]).intersection(*(set(parent) for parent in parents[1:]))
        for source_date in sorted(common, key=lambda day: parents[0][day][0]):
            bucket = parents[0][source_date][0]
            values = [parent[source_date][1] for parent in parents]
            value = _value(reference, values)
            as_of = bucket.isoformat()
            result[reference.instrument_id].append({
                **_base(reference, HISTORY_PROVIDER_ID),
                "timestamp": as_of, "price": _number(value), "price_decimal": str(value),
                "source_date": source_date, "source_time": None,
                "source_timestamp_scope": "source_reported_daily_close",
                "timestamp_precision": "day", "timestamp_role": "day_bucket_start",
                "history_point_kind": "published_reference_daily_close" if len(parents) == 1 else "same_day_iran_fx_ratio",
                "inputs": [_parent(key, instrument_id, price, as_of, source_date, daily=True)
                           for (key, instrument_id), price in zip(reference.parents, values, strict=True)],
            })
    return result
