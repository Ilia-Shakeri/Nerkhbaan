from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..models import WeightUnit
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


@dataclass(frozen=True, slots=True)
class NobitexStatsParser:
    pair: str
    convert_rial_to_toman: bool
    parser_version: str = "nobitex-stats/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        pair_payload = require_object(
            exact_path(payload, "stats", self.pair), f"stats.{self.pair}"
        )
        if "latest" not in pair_payload:
            raise ParserError("missing_field", f"Missing stats.{self.pair}.latest")
        price = strict_decimal(pair_payload["latest"], "latest")
        if self.convert_rial_to_toman:
            price /= Decimal(10)
        timestamp = optional_timestamp(
            pair_payload.get("updated_at") or pair_payload.get("timestamp"),
            context,
            "stats timestamp",
        )
        parsed = ParsedProviderValue(
            price=price,
            currency=context.instrument.quote_currency,
            weight_unit=context.instrument.weight_unit,
            purity=context.instrument.purity,
            observed_at=timestamp,
            metadata={
                "market_pair": self.pair,
                "source_currency": "RIAL" if self.convert_rial_to_toman else "USDT",
                "normalization": "rial_to_toman" if self.convert_rial_to_toman else "none",
            },
        )
        return validate_parsed_value(parsed, context)


@dataclass(frozen=True, slots=True)
class NobitexOrderBookParser:
    symbol: str
    parser_version: str = "nobitex-orderbook/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        root = require_object(payload, "orderbook response")
        book = require_object(root.get(self.symbol), self.symbol)
        stated_symbol = book.get("symbol")
        if stated_symbol is not None and str(stated_symbol).upper() != self.symbol:
            raise ParserError("instrument_mismatch", "Order book symbol does not match")
        bids = require_list(book.get("bids"), f"{self.symbol}.bids")
        asks = require_list(book.get("asks"), f"{self.symbol}.asks")
        bid = self._level_price(bids, "bid")
        ask = self._level_price(asks, "ask")
        if bid > ask:
            raise ParserError("crossed_orderbook", "Best bid exceeds best ask")
        midpoint = (bid + ask) / Decimal(2)
        timestamp = optional_timestamp(
            book.get("lastUpdate") or book.get("updated_at") or root.get("lastUpdate"),
            context,
            "order book timestamp",
        )
        parsed = ParsedProviderValue(
            price=midpoint,
            currency=context.instrument.quote_currency,
            weight_unit=WeightUnit.UNIT,
            purity=None,
            observed_at=timestamp,
            bid=bid,
            ask=ask,
            metadata={"market_symbol": self.symbol, "selection": "best_bid_ask_midpoint"},
        )
        return validate_parsed_value(parsed, context)

    @staticmethod
    def _level_price(levels: list[Any], side: str) -> Decimal:
        if not levels:
            raise ParserError("empty_orderbook", f"Order book has no {side} levels")
        first = levels[0]
        if isinstance(first, list) and len(first) >= 1:
            node = first[0]
        elif isinstance(first, dict) and "price" in first:
            node = first["price"]
        else:
            raise ParserError("invalid_shape", f"First {side} level has invalid shape")
        return strict_decimal(node, f"best {side}")
