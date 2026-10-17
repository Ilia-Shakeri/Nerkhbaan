from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..models import Currency, WeightUnit
from .base import (
    ParsedProviderValue,
    ParserContext,
    ParserError,
    exact_path,
    optional_timestamp,
    require_list,
    require_object,
    strict_decimal,
    validate_parsed_value,
)

_TOMAN_UNITS = {"TOMAN", "TMN", "IRT", "تومان"}
_RIAL_UNITS = {"RIAL", "IRR", "RLS", "ریال"}
_USD_UNITS = {"USD"}
_USDT_UNITS = {"USDT"}
_SOURCE_VENUES = {
    "nobitex": "nobitex",
    "wallex": "wallex",
    "bitpin": "bitpin",
    "ramzinex": "ramzinex",
}


def _unit_factor(unit: object) -> tuple[str, Decimal]:
    normalized = str(unit or "").strip().upper()
    if str(unit).strip() in _TOMAN_UNITS or normalized in _TOMAN_UNITS:
        return "TOMAN", Decimal("1")
    if str(unit).strip() in _RIAL_UNITS or normalized in _RIAL_UNITS:
        return "RIAL", Decimal("0.1")
    if normalized in _USD_UNITS:
        return "USD", Decimal("1")
    if normalized in _USDT_UNITS:
        return "USDT", Decimal("1")
    raise ParserError("unknown_unit", "Provider unit is not allowlisted")


def _node_by_key(rows: object, key_field: str, expected: str) -> dict[str, Any]:
    if isinstance(rows, dict):
        candidate = rows.get(expected)
        if isinstance(candidate, dict):
            return candidate
        for value in rows.values():
            if isinstance(value, dict) and str(value.get(key_field, "")).upper() == expected.upper():
                return value
    for row in require_list(rows, "rows"):
        item = require_object(row, "row")
        if str(item.get(key_field, "")).upper() == expected.upper():
            return item
    raise ParserError("unsupported_symbol", "Provider symbol is not present")


def _parsed(
    price: Decimal,
    context: ParserContext,
    observed_at: object | None,
    metadata: dict[str, Any],
) -> ParsedProviderValue:
    source_currency, _factor = _unit_factor(metadata.get("source_currency"))
    currency_code = "TOMAN" if source_currency == "RIAL" else source_currency
    if currency_code != context.instrument.quote_currency.value:
        raise ParserError("currency_mismatch", "Provider currency does not match instrument")
    parsed = ParsedProviderValue(
        price=price,
        currency=Currency(currency_code),
        weight_unit=context.instrument.weight_unit,
        purity=context.instrument.purity,
        observed_at=optional_timestamp(observed_at, context, "quote timestamp"),
        metadata=metadata,
    )
    return validate_parsed_value(parsed, context)


@dataclass(frozen=True, slots=True)
class CoinbaseTickerParser:
    product_id: str
    parser_version: str = "coinbase-ticker/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Coinbase ticker response")
        price = strict_decimal(exact_path(root, "price"), "price")
        return _parsed(
            price,
            context,
            root.get("time") or root.get("trade_time"),
            {
                "product_id": self.product_id,
                "source_currency": "USD",
                "original_value": str(price),
                "conversion_factor": "1",
            },
        )


@dataclass(frozen=True, slots=True)
class CoinGeckoSimplePriceParser:
    asset_id: str
    parser_version: str = "coingecko-simple-price/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        node = require_object(exact_path(payload, self.asset_id), self.asset_id)
        price = strict_decimal(exact_path(node, "usd"), f"{self.asset_id}.usd")
        return _parsed(
            price,
            context,
            node.get("last_updated_at"),
            {
                "asset_id": self.asset_id,
                "source_currency": "USD",
                "original_value": str(price),
                "conversion_factor": "1",
            },
        )


@dataclass(frozen=True, slots=True)
class PersianToolboxMarketParser:
    asset: str
    parser_version: str = "persian-toolbox-market/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "PersianToolbox response")
        if root.get("ok") is not True:
            raise ParserError("provider_error", "PersianToolbox response is not successful")
        data = require_object(exact_path(root, "data"), "PersianToolbox data")
        freshness = str(data.get("freshness") or "").strip().lower()
        if freshness not in {"live", "cached"}:
            raise ParserError("stale_payload", "PersianToolbox data is not fresh")
        units = require_object(exact_path(data, "units"), "PersianToolbox units")
        sources = require_list(exact_path(data, "sources"), "PersianToolbox sources")
        if not sources or any(not isinstance(source, str) or not source.strip() for source in sources):
            raise ParserError("invalid_source", "PersianToolbox sources are invalid")

        if self.asset == "BTC_USD":
            if units.get("cryptoPrice") != "USD":
                raise ParserError("unknown_unit", "PersianToolbox crypto unit must be USD")
            crypto = require_object(exact_path(data, "crypto"), "PersianToolbox crypto")
            node = require_object(exact_path(crypto, "BTC"), "PersianToolbox BTC")
            if node.get("symbol") != "BTC":
                raise ParserError("unsupported_symbol", "PersianToolbox BTC symbol does not match")
            raw = strict_decimal(exact_path(node, "priceUSD"), "BTC priceUSD")
            factor = Decimal("1")
            source_currency = "USD"
        elif self.asset == "GOLD_24K_TOMAN_GRAM":
            if units.get("goldPricePerGram") != "IRR":
                raise ParserError(
                    "unknown_unit",
                    "PersianToolbox gold unit must be IRR per gram",
                )
            raise ParserError("ambiguous_purity", "Gold feed does not identify a direct 24K quote")
        elif self.asset == "USD_TOMAN":
            if units.get("currencyBase") != "USD" or units.get("iranCurrency") != "IRR":
                raise ParserError("unknown_unit", "PersianToolbox currency units must be USD and IRR")
            currencies = require_object(exact_path(data, "currencies"), "PersianToolbox currencies")
            usd = require_object(exact_path(currencies, "USD"), "PersianToolbox USD")
            irr = require_object(exact_path(currencies, "IRR"), "PersianToolbox IRR")
            if usd.get("code") != "USD" or irr.get("code") != "IRR":
                raise ParserError("unsupported_symbol", "PersianToolbox currency symbols do not match")
            if strict_decimal(exact_path(usd, "rate"), "USD rate") != Decimal("1"):
                raise ParserError("invalid_base_rate", "PersianToolbox USD base rate must equal one")
            raw = strict_decimal(exact_path(irr, "rate"), "IRR rate")
            factor = Decimal("0.1")
            source_currency = "RIAL"
        else:
            raise ParserError("unsupported_symbol", "PersianToolbox asset is not supported")

        return _parsed(
            raw * factor,
            context,
            exact_path(data, "timestamp"),
            {
                "asset": self.asset,
                "freshness": freshness,
                "upstream_sources": [source.strip() for source in sources],
                "source_currency": source_currency,
                "original_value": str(raw),
                "conversion_factor": str(factor),
                "normalization": "rial_to_toman" if factor == Decimal("0.1") else "none",
            },
        )


@dataclass(frozen=True, slots=True)
class WallexMarketParser:
    symbol: str
    parser_version: str = "wallex-market/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Wallex response")
        rows = root.get("result", {}).get("symbols") if isinstance(root.get("result"), dict) else root.get("symbols")
        node = _node_by_key(rows or root.get("data") or root, "symbol", self.symbol)
        price = strict_decimal(node.get("lastPrice") or node.get("last_price") or node.get("stats", {}).get("lastPrice"), "last price")
        return _parsed(
            price,
            context,
            node.get("updatedAt") or node.get("updated_at") or node.get("timestamp"),
            {
                "market_symbol": self.symbol,
                "source_currency": "TOMAN",
                "original_value": str(price),
                "conversion_factor": "1",
            },
        )


@dataclass(frozen=True, slots=True)
class ServixAssetsParser:
    code: str
    parser_version: str = "servix-assets/1.2.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        expected = {
            "USD_RLS": "USD_TOMAN", "BTC_USD": "BTC_USD", "USDT_USD": "USDT_USD",
            "BTC_RLS": "BTC_TOMAN", "USDT_RLS": "USDT_TOMAN",
            "GOLD_OUNCE_USD": "XAU_USD_OZ", "SILVER_OUNCE_USD": "XAG_USD_OZ",
            "GOLD_18_RLS": "GOLD_18K_TOMAN_GRAM", "GOLD_24_RLS": "GOLD_24K_TOMAN_GRAM",
        }
        if expected.get(self.code) != context.instrument.instrument_id:
            raise ParserError("unsupported_symbol", "Servix code does not match instrument")
        rows = payload
        if isinstance(payload, dict):
            for field in ("data", "assets", "result"):
                if field in payload:
                    rows = payload[field]
                    break
            if isinstance(rows, dict) and "code" in rows:
                rows = [rows]
        records = list(rows.values()) if isinstance(rows, dict) else require_list(rows, "Servix quotes")
        matches = []
        for record in records:
            item = require_object(record, "Servix quote")
            if str(item.get("code", "")).upper() == self.code.upper():
                matches.append(item)
        if not matches:
            raise ParserError("unsupported_symbol", "Servix quote code does not match")
        if len(matches) != 1:
            raise ParserError("ambiguous_symbol", "Servix quote code is duplicated")
        node = matches[0]
        raw = strict_decimal(exact_path(node, "value"), "value")
        quote_unit = exact_path(node, "quoteUnit")
        if not isinstance(quote_unit, str):
            raise ParserError("unknown_unit", "Servix quoteUnit must be explicit text")
        if self.code in {"BTC_RLS", "USDT_RLS"}:
            if quote_unit != "RLS":
                raise ParserError("unknown_unit", "Servix local crypto quoteUnit must be RLS")
            if context.instrument.weight_unit is not WeightUnit.UNIT or context.instrument.purity is not None:
                raise ParserError("unit_mismatch", "Servix crypto quote must be per asset unit")
        source_unit, factor = _unit_factor(quote_unit)
        source_time = exact_path(node, "businessTime")
        if not isinstance(source_time, str) or not source_time.strip():
            raise ParserError("invalid_timestamp", "Servix businessTime is required")
        try:
            parsed_time = datetime.fromisoformat(source_time.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ParserError("invalid_timestamp", "Servix businessTime is invalid") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ParserError("invalid_timestamp", "Servix businessTime timezone is required")
        return _parsed(
            raw * factor,
            context,
            source_time.strip(),
            {
                "source_code": self.code,
                "source_currency": source_unit,
                "original_value": str(raw),
                "conversion_factor": str(factor),
                "normalization": "rial_to_toman" if factor == Decimal("0.1") else "none",
            },
        )


@dataclass(frozen=True, slots=True)
class TalaRatesParser:
    key: str
    parser_version: str = "tala-rates/1.1.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "TALA response")
        if "success" in root and root["success"] is not True:
            raise ParserError("provider_disabled", "TALA response did not succeed")
        rows = root
        for field in ("rates", "data", "result"):
            if field in root:
                rows = root[field]
                break
        if isinstance(rows, dict):
            records = [(None, rows)] if "key" in rows else list(rows.items())
        else:
            records = [(None, row) for row in require_list(rows, "TALA rates")]
        matches = []
        for dictionary_key, record in records:
            item = require_object(record, "TALA rate")
            if str(item.get("key", "")).upper() == self.key.upper():
                matches.append((dictionary_key, item))
        if not matches:
            raise ParserError("unsupported_symbol", "TALA rate key is not present")
        if len(matches) != 1:
            raise ParserError("ambiguous_symbol", "TALA rate key is duplicated")
        dictionary_key, node = matches[0]
        if dictionary_key is not None and str(dictionary_key).upper() != self.key.upper():
            raise ParserError("unsupported_symbol", "TALA dictionary key does not match rate key")
        if str(node.get("status", "")).strip().lower() not in {"active", "ok", "live"}:
            raise ParserError("provider_disabled", "TALA key is not active")
        source_unit, factor = _unit_factor(node.get("unit"))
        raw = strict_decimal(exact_path(node, "value"), "value")
        source_time = node.get("updated_at")
        if not isinstance(source_time, str) or not source_time.strip():
            raise ParserError("invalid_timestamp", "TALA updated_at is required")
        try:
            parsed_time = datetime.fromisoformat(source_time.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ParserError("invalid_timestamp", "TALA updated_at is invalid") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ParserError("invalid_timestamp", "TALA updated_at timezone is required")
        return _parsed(
            raw * factor,
            context,
            source_time.strip(),
            {
                "source_key": self.key,
                "source_currency": source_unit,
                "original_value": str(raw),
                "conversion_factor": str(factor),
                "normalization": "rial_to_toman" if factor == Decimal("0.1") else "none",
            },
        )


@dataclass(frozen=True, slots=True)
class TicaroPricesParser:
    pair: str
    parser_version: str = "ticaro-prices/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Ticaro response")
        rows = root.get("data") or root.get("prices") or root.get("result") or payload
        node = _node_by_key(rows, "pair", self.pair)
        source_unit, factor = _unit_factor(node.get("quote_currency"))
        raw = strict_decimal(exact_path(node, "price"), "price")
        source = str(node.get("source") or "").strip().lower()
        venue = _SOURCE_VENUES.get(source, "opaque_aggregator")
        return _parsed(
            raw * factor,
            context,
            node.get("fetched_at"),
            {
                "pair": self.pair,
                "source_currency": source_unit,
                "original_value": str(raw),
                "conversion_factor": str(factor),
                "upstream_source": source or None,
                "independence_venue": venue,
            },
        )


@dataclass(frozen=True, slots=True)
class ArzbinMarketParser:
    code: str
    semantic: str
    unit: str
    parser_version: str = "arzbin-market/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        if self.semantic not in {"buy", "sell", "midpoint"}:
            raise ParserError("invalid_price_semantic", "Arzbin semantic is invalid")
        root = require_object(payload, "Arzbin response")
        rows = root.get("data") or root.get("rates") or root.get("result") or payload
        node = _node_by_key(rows, "code", self.code)
        source_unit, factor = _unit_factor(self.unit)
        buy = strict_decimal(node.get("buy"), "buy") if node.get("buy") is not None else None
        sell = strict_decimal(node.get("sell"), "sell") if node.get("sell") is not None else None
        if self.semantic == "buy" and buy is not None:
            raw = buy
        elif self.semantic == "sell" and sell is not None:
            raw = sell
        elif self.semantic == "midpoint" and buy is not None and sell is not None:
            raw = (buy + sell) / Decimal("2")
        else:
            raise ParserError("missing_price", "Configured Arzbin price is missing")
        return _parsed(
            raw * factor,
            context,
            node.get("updatedAt") or node.get("updated_at"),
            {
                "source_code": self.code,
                "selected_price_semantic": self.semantic,
                "source_currency": source_unit,
                "original_value": str(raw),
                "conversion_factor": str(factor),
            },
        )


@dataclass(frozen=True, slots=True)
class NavasanLatestParser:
    item: str
    source_unit: str = ""
    parser_version: str = "navasan-latest/1.1.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        if self.source_unit not in {"RIAL", "TOMAN"}:
            raise ParserError("missing_unit_configuration", "Navasan local currency unit must be confirmed")
        root = require_object(payload, "Navasan response")
        node = require_object(root.get(self.item), self.item)
        source_unit, factor = _unit_factor(self.source_unit)
        if "unit" in node and _unit_factor(node["unit"])[0] != source_unit:
            raise ParserError("currency_mismatch", "Navasan response unit differs from configured contract")
        timestamp = exact_path(node, "timestamp")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, str)) or not str(timestamp).isdigit():
            raise ParserError("invalid_timestamp", "Navasan source Unix timestamp is required")
        raw = strict_decimal(exact_path(node, "value"), "value")
        return _parsed(
            raw * factor,
            context,
            timestamp,
            {
                "item": self.item,
                "source_currency": source_unit,
                "original_value": str(raw),
                "conversion_factor": str(factor),
                "normalization": "rial_to_toman" if source_unit == "RIAL" else "none",
            },
        )


@dataclass(frozen=True, slots=True)
class NerkhIoLiteParser:
    symbol: str
    source_unit: str
    parser_version: str = "nerkh-io-lite/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        if not self.source_unit:
            raise ParserError("missing_unit_configuration", "Nerkh.io category unit is required")
        root = require_object(payload, "Nerkh.io response")
        rows = root.get("data") or root.get("prices") or root.get("result") or payload
        node = _node_by_key(rows, "symbol", self.symbol)
        source_unit, factor = _unit_factor(self.source_unit)
        raw = strict_decimal(node.get("price") or node.get("value"), "price")
        return _parsed(
            raw * factor,
            context,
            node.get("timestamp") or root.get("timestamp"),
            {
                "symbol": self.symbol,
                "source_currency": source_unit,
                "original_value": str(raw),
                "conversion_factor": str(factor),
                "normalization": "rial_to_toman" if factor == Decimal("0.1") else "none",
            },
        )
