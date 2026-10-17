from __future__ import annotations

from dataclasses import dataclass
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
    parser_version: str = "nobitex-orderbook/1.1.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        instrument = context.instrument
        expected = {"BTCIRT": ("BTC_TOMAN", "BTC"), "USDTIRT": ("USDT_TOMAN", "USDT")}.get(self.symbol)
        if expected is None:
            raise ParserError("unsupported_symbol", "Unsupported Nobitex book unit")
        if instrument.instrument_id != expected[0] or instrument.base_asset != expected[1]:
            raise ParserError("instrument_mismatch", "Nobitex book does not match the instrument")
        if instrument.quote_currency is not Currency.TOMAN:
            raise ParserError("currency_mismatch", "Nobitex IRT books normalize to Toman")
        if instrument.weight_unit is not WeightUnit.UNIT or instrument.purity is not None:
            raise ParserError("unit_mismatch", "Nobitex crypto books require a plain asset unit")
        root = require_object(payload, "orderbook response")
        if root.get("status", "ok") != "ok":
            raise ParserError("provider_error", "Nobitex book status is not ok")
        if "bids" in root or "asks" in root:
            if self.symbol in root:
                raise ParserError("ambiguous_quote", "Nobitex book mixes single and multiple market shapes")
            book = root
        else:
            book = require_object(root.get(self.symbol), self.symbol)
        stated_symbol = book.get("symbol")
        if stated_symbol is not None and (not isinstance(stated_symbol, str) or stated_symbol.upper() != self.symbol):
            raise ParserError("instrument_mismatch", "Order book symbol does not match")
        bids = require_list(book.get("bids"), f"{self.symbol}.bids")
        asks = require_list(book.get("asks"), f"{self.symbol}.asks")
        bid = self._level_price(bids, "bid")
        ask = self._level_price(asks, "ask")
        # Nobitex's IRT book symbols still contain Rial-valued levels.
        bid /= Decimal(10)
        ask /= Decimal(10)
        if not instrument.accepts(bid) or not instrument.accepts(ask):
            raise ParserError("outside_sanity_bounds", "Nobitex book sides exceed instrument bounds")
        if bid > ask:
            raise ParserError("crossed_orderbook", "Best bid exceeds best ask")
        midpoint = (bid + ask) / Decimal(2)
        raw_time = book.get("lastUpdate")
        if raw_time is None:
            raise ParserError("missing_timestamp", "Nobitex book needs lastUpdate from its source")
        if (isinstance(raw_time, bool) or not isinstance(raw_time, (int, str))
                or not str(raw_time).isascii() or not str(raw_time).isdigit()
                or not 12 <= len(str(raw_time)) <= 14):
            raise ParserError("invalid_timestamp", "Nobitex lastUpdate must be Unix milliseconds")
        timestamp = optional_timestamp(raw_time, context, "order book timestamp")
        parsed = ParsedProviderValue(
            price=midpoint,
            currency=context.instrument.quote_currency,
            weight_unit=WeightUnit.UNIT,
            purity=None,
            observed_at=timestamp,
            bid=bid,
            ask=ask,
            metadata={"market_symbol": self.symbol, "selection": "best_bid_ask_midpoint",
                      "source_currency": "RIAL", "normalization": "rial_to_toman",
                      "conversion_factor": "0.1", "timestamp_basis": "lastUpdate",
                      "provider_timestamp_available": True},
        )
        return validate_parsed_value(parsed, context)

    @staticmethod
    def _level_price(levels: list[Any], side: str) -> Decimal:
        if not levels:
            raise ParserError("empty_orderbook", f"Order book has no {side} levels")
        first = levels[0]
        if isinstance(first, list) and len(first) >= 2:
            node = first[0]
            quantity = first[1]
        elif isinstance(first, dict) and "price" in first:
            node = first["price"]
            quantity = first.get("amount", first.get("quantity"))
        else:
            raise ParserError("invalid_shape", f"First {side} level has invalid shape")
        strict_decimal(quantity, f"best {side} quantity")
        return strict_decimal(node, f"best {side}")
