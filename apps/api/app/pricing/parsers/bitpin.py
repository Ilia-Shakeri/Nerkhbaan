from __future__ import annotations

from dataclasses import dataclass

from .base import ParserContext, ParserError, ParsedProviderValue, exact_path, require_list, require_object, strict_decimal
from .local_reference import _parsed


@dataclass(frozen=True, slots=True)
class BitpinPricesParser:
    symbol: str
    parser_version: str = "bitpin-prices/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        instruments = {"BTC_IRT": "BTC_TOMAN", "USDT_IRT": "USDT_TOMAN"}
        if instruments.get(self.symbol) != context.instrument.instrument_id:
            raise ParserError("unsupported_symbol", "Bitpin symbol does not match instrument")
        matches = [
            row for row in require_list(payload, "markets")
            if require_object(row, "market").get("code") == self.symbol
        ]
        if len(matches) != 1:
            raise ParserError("unsupported_symbol", "Expected one unique Bitpin market")
        # Read the exchange order-book price, never the synthetic price_info.
        book = require_object(exact_path(matches[0], "order_book_info"), "order_book_info")
        timestamp = exact_path(book, "time")
        if not timestamp:
            raise ParserError("missing_timestamp", "Bitpin exchange timestamp is required")
        price = strict_decimal(exact_path(book, "price"), "order_book_info.price")
        return _parsed(price, context, timestamp, {
            "symbol": self.symbol,
            "source_currency": "TOMAN",
            "original_value": str(price),
            "conversion_factor": "1",
            "selected_price_field": "order_book_info.price",
        })
