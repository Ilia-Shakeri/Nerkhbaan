from __future__ import annotations

import os
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from .models import Currency, InstrumentDefinition, Market, Region, WeightUnit


class UnknownInstrumentError(KeyError):
    pass


def _instrument(
    instrument_id: str,
    base_asset: str,
    currency: Currency,
    market: Market,
    region: Region,
    unit: WeightUnit,
    purity: str | None,
    decimals: int,
    ttl: int,
    stale: int,
    expire: int,
    anomaly: str,
    max_anomaly: str,
    minimum: str,
    maximum: str,
    importance: int,
    verification_depth: int,
    *,
    derived_fallback: bool = False,
) -> InstrumentDefinition:
    return InstrumentDefinition(
        instrument_id=instrument_id,
        base_asset=base_asset,
        quote_currency=currency,
        market=market,
        region=region,
        weight_unit=unit,
        purity=Decimal(purity) if purity is not None else None,
        display_decimals=decimals,
        operational_ttl_seconds=ttl,
        stale_after_seconds=stale,
        expire_after_seconds=expire,
        base_anomaly_threshold_percent=Decimal(anomaly),
        maximum_dynamic_threshold_percent=Decimal(max_anomaly),
        minimum_price=Decimal(minimum),
        maximum_price=Decimal(maximum),
        importance=importance,
        maximum_verification_depth=verification_depth,
        allow_derived_fallback=derived_fallback,
    )


_DEFAULT_INSTRUMENTS = {
    "GOLD_18K_TOMAN_GRAM": _instrument(
        "GOLD_18K_TOMAN_GRAM", "XAU_18K", Currency.TOMAN,
        Market.IRAN_PHYSICAL, Region.IRAN, WeightUnit.GRAM, "0.750", 0,
        60, 180, 900, "1.5", "5", "100000", "100000000", 10, 3,
        derived_fallback=True,
    ),
    "XAU_USD_OZ": _instrument(
        "XAU_USD_OZ", "XAU", Currency.USD, Market.GLOBAL_SPOT,
        Region.GLOBAL, WeightUnit.TROY_OUNCE, "0.9999", 2,
        300, 900, 3600, "1.25", "5", "500", "10000", 9, 3,
    ),
    "SILVER_999_TOMAN_GRAM": _instrument(
        "SILVER_999_TOMAN_GRAM", "XAG", Currency.TOMAN,
        Market.IRAN_PHYSICAL, Region.IRAN, WeightUnit.GRAM, "0.999", 0,
        120, 360, 1200, "2", "7", "1000", "10000000", 7, 2,
        derived_fallback=True,
    ),
    "SILVER_925_TOMAN_GRAM": _instrument(
        "SILVER_925_TOMAN_GRAM", "XAG", Currency.TOMAN,
        Market.IRAN_PHYSICAL, Region.IRAN, WeightUnit.GRAM, "0.925", 0,
        120, 360, 1200, "2", "7", "1000", "10000000", 6, 2,
        derived_fallback=True,
    ),
    "XAG_USD_OZ": _instrument(
        "XAG_USD_OZ", "XAG", Currency.USD, Market.GLOBAL_SPOT,
        Region.GLOBAL, WeightUnit.TROY_OUNCE, "0.9999", 3,
        300, 900, 3600, "2", "7", "5", "500", 7, 2,
    ),
    "USDT_TOMAN": _instrument(
        "USDT_TOMAN", "USDT", Currency.TOMAN, Market.IRAN_EXCHANGE,
        Region.IRAN, WeightUnit.UNIT, None, 0,
        20, 60, 300, "1", "4", "1000", "1000000", 10, 3,
    ),
    "USDT_USD": _instrument(
        "USDT_USD", "USDT", Currency.USD, Market.GLOBAL_EXCHANGE,
        Region.GLOBAL, WeightUnit.UNIT, None, 4,
        30, 90, 300, "0.5", "2", "0.8", "1.2", 8, 2,
    ),
    "BTC_TOMAN": _instrument(
        "BTC_TOMAN", "BTC", Currency.TOMAN, Market.IRAN_EXCHANGE,
        Region.IRAN, WeightUnit.UNIT, None, 0,
        20, 60, 300, "2", "8", "10000000", "1000000000000", 10, 3,
        derived_fallback=True,
    ),
    "BTC_USD": _instrument(
        "BTC_USD", "BTC", Currency.USD, Market.GLOBAL_EXCHANGE,
        Region.GLOBAL, WeightUnit.UNIT, None, 2,
        20, 60, 300, "2", "8", "1000", "1000000", 10, 3,
    ),
}


def _positive_int_override(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _decimal_override(name: str, default: Decimal) -> Decimal:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return default
    return value if value.is_finite() and value > 0 else default


def _apply_environment(definition: InstrumentDefinition) -> InstrumentDefinition:
    prefix = definition.instrument_id
    ttl = _positive_int_override(
        f"PRICING_TTL_{prefix}", definition.operational_ttl_seconds
    )
    stale = max(
        ttl,
        _positive_int_override(
            f"PRICING_STALE_AFTER_{prefix}", definition.stale_after_seconds
        ),
    )
    expire = max(
        stale,
        _positive_int_override(
            f"PRICING_EXPIRE_AFTER_{prefix}", definition.expire_after_seconds
        ),
    )
    base = _decimal_override(
        f"PRICING_ANOMALY_THRESHOLD_{prefix}",
        definition.base_anomaly_threshold_percent,
    )
    maximum = max(
        base,
        _decimal_override(
            f"PRICING_MAX_ANOMALY_THRESHOLD_{prefix}",
            definition.maximum_dynamic_threshold_percent,
        ),
    )
    return replace(
        definition,
        operational_ttl_seconds=ttl,
        stale_after_seconds=stale,
        expire_after_seconds=expire,
        base_anomaly_threshold_percent=base,
        maximum_dynamic_threshold_percent=maximum,
    )


INSTRUMENTS = MappingProxyType(
    {key: _apply_environment(value) for key, value in _DEFAULT_INSTRUMENTS.items()}
)


LEGACY_ASSET_MAPPING = MappingProxyType(
    {
        ("gold", "toman"): "GOLD_18K_TOMAN_GRAM",
        ("gold", "usd"): "XAU_USD_OZ",
        ("silver", "toman"): "SILVER_999_TOMAN_GRAM",
        ("silver", "usd"): "XAG_USD_OZ",
        ("usdt", "toman"): "USDT_TOMAN",
        ("usdt", "usd"): "USDT_USD",
        ("btc", "toman"): "BTC_TOMAN",
        ("btc", "usd"): "BTC_USD",
    }
)

_INSTRUMENT_TO_LEGACY = {
    instrument_id: asset for (asset, _currency), instrument_id in LEGACY_ASSET_MAPPING.items()
}


def get_instrument(instrument_id: str) -> InstrumentDefinition:
    normalized = instrument_id.strip().upper()
    try:
        return INSTRUMENTS[normalized]
    except KeyError as exc:
        raise UnknownInstrumentError(normalized) from exc


def instrument_for_legacy_asset(asset: str, currency: str) -> InstrumentDefinition:
    key = (asset.strip().lower(), currency.strip().lower())
    try:
        return INSTRUMENTS[LEGACY_ASSET_MAPPING[key]]
    except KeyError as exc:
        raise UnknownInstrumentError(f"{key[0]}:{key[1]}") from exc


def legacy_asset_for_instrument(instrument_id: str) -> str | None:
    return _INSTRUMENT_TO_LEGACY.get(instrument_id.upper())
