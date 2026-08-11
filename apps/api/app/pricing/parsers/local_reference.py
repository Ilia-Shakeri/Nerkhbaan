from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

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
    parsed = ParsedProviderValue(
        price=price,
        currency=context.instrument.quote_currency,
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
    parser_version: str = "servix-assets/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Servix response")
        rows = root.get("data") or root.get("assets") or root.get("result") or payload
        node = _node_by_key(rows, "code", self.code)
        raw = strict_decimal(exact_path(node, "value"), "value")
        source_unit = "RIAL" if self.code.upper().endswith("_RLS") else context.instrument.quote_currency.value
        factor = Decimal("0.1") if source_unit == "RIAL" else Decimal("1")
        return _parsed(
            raw * factor,
            context,
            node.get("businessTime") or node.get("updated_at"),
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
    parser_version: str = "tala-rates/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "TALA response")
        rows = root.get("data") or root.get("rates") or root.get("result") or payload
        node = _node_by_key(rows, "key", self.key)
        if str(node.get("status", "active")).lower() not in {"active", "ok", "live"}:
            raise ParserError("provider_disabled", "TALA key is not active")
        source_unit, factor = _unit_factor(node.get("unit"))
        raw = strict_decimal(exact_path(node, "value"), "value")
        return _parsed(
            raw * factor,
            context,
            node.get("updated_at"),
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
    parser_version: str = "navasan-latest/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Navasan response")
        node = require_object(root.get(self.item), self.item)
        raw = strict_decimal(exact_path(node, "value"), "value")
        return _parsed(
            raw * Decimal("0.1"),
            context,
            node.get("timestamp"),
            {
                "item": self.item,
                "source_currency": "RIAL",
                "original_value": str(raw),
                "conversion_factor": "0.1",
                "normalization": "rial_to_toman",
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
