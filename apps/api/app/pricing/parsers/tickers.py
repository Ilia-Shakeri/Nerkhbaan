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
class CoinCapParser:
    asset_id: str
    symbol: str
    parser_version: str = "coincap/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "CoinCap response")
        data = require_object(root.get("data"), "data")
        if str(data.get("id", "")).lower() != self.asset_id:
            raise ParserError("instrument_mismatch", "CoinCap asset ID does not match")
        if str(data.get("symbol", "")).upper() != self.symbol:
            raise ParserError("instrument_mismatch", "CoinCap symbol does not match")
        parsed = ParsedProviderValue(
            price=strict_decimal(exact_path(data, "priceUsd"), "data.priceUsd"),
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=optional_timestamp(root.get("timestamp"), context, "timestamp"),
            metadata={"asset_id": self.asset_id, "symbol": self.symbol},
        )
        return validate_parsed_value(parsed, context)


@dataclass(frozen=True, slots=True)
class AlanchandGold18Parser:
    parser_version: str = "alanchand-gold18/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        node = require_object(exact_path(payload, "data", "gold_18k"), "data.gold_18k")
        parsed = ParsedProviderValue(
            price=strict_decimal(exact_path(node, "price"), "data.gold_18k.price"),
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=optional_timestamp(
                node.get("updated_at") or node.get("timestamp"), context, "gold timestamp"
            ),
            metadata={"contract": "gold_18k_toman_per_gram"},
        )
        return validate_parsed_value(parsed, context)


@dataclass(frozen=True, slots=True)
class TetherlandParser:
    symbol: str
    parser_version: str = "tetherland-currency/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        node = require_object(
            exact_path(payload, "data", "currencies", self.symbol),
            f"data.currencies.{self.symbol}",
        )
        stated_symbol = node.get("symbol") or node.get("code")
        if stated_symbol is not None and str(stated_symbol).upper() != self.symbol:
            raise ParserError("instrument_mismatch", "Tetherland symbol does not match")
        parsed = ParsedProviderValue(
            price=strict_decimal(exact_path(node, "price"), "price"),
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=optional_timestamp(
                node.get("updated_at") or node.get("timestamp"), context, "quote timestamp"
            ),
            metadata={"symbol": self.symbol, "contract": "toman_per_unit"},
        )
        return validate_parsed_value(parsed, context)
