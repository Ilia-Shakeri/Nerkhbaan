from __future__ import annotations

from dataclasses import dataclass

from .base import (
    ParsedProviderValue,
    ParserContext,
    ParserError,
    exact_path,
    optional_timestamp,
    require_object,
    strict_decimal,
    validate_parsed_value,
)


@dataclass(frozen=True, slots=True)
class GoldApiParser:
    symbol: str
    parser_version: str = "goldapi/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "GoldAPI response")
        metal = root.get("metal") or root.get("symbol")
        if metal is not None and str(metal).upper() != self.symbol:
            raise ParserError("instrument_mismatch", "Metal symbol does not match")
        currency = root.get("currency")
        if currency is not None and str(currency).upper() != "USD":
            raise ParserError("currency_mismatch", "GoldAPI quote is not USD")
        parsed = ParsedProviderValue(
            price=strict_decimal(exact_path(root, "price"), "price"),
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=optional_timestamp(
                root.get("timestamp") or root.get("updated_at"), context, "quote timestamp"
            ),
            metadata={"metal_symbol": self.symbol},
        )
        return validate_parsed_value(parsed, context)


@dataclass(frozen=True, slots=True)
class GoldApiFreeParser:
    symbol: str
    parser_version: str = "gold-api-free/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Gold API response")
        symbol = root.get("symbol") or root.get("metal")
        if symbol is not None and str(symbol).upper() != self.symbol:
            raise ParserError("instrument_mismatch", "Metal symbol does not match")
        parsed = ParsedProviderValue(
            price=strict_decimal(exact_path(root, "price"), "price"),
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=optional_timestamp(
                root.get("updatedAt") or root.get("timestamp"), context, "quote timestamp"
            ),
            metadata={"metal_symbol": self.symbol},
        )
        return validate_parsed_value(parsed, context)


@dataclass(frozen=True, slots=True)
class MetalsDevParser:
    metal: str
    parser_version: str = "metals-dev/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "Metals.dev response")
        currency = root.get("currency")
        if currency is not None and str(currency).upper() != "USD":
            raise ParserError("currency_mismatch", "Metals.dev quote is not USD")
        unit = root.get("unit")
        if unit is not None and str(unit).lower() not in {"toz", "troy_ounce", "oz"}:
            raise ParserError("unit_mismatch", "Metals.dev quote is not per troy ounce")
        parsed = ParsedProviderValue(
            price=strict_decimal(exact_path(root, "metals", self.metal), self.metal),
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=optional_timestamp(
                root.get("timestamp") or root.get("updated_at"), context, "quote timestamp"
            ),
            metadata={"metal": self.metal},
        )
        return validate_parsed_value(parsed, context)
