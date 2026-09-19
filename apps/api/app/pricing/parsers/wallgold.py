from __future__ import annotations

from dataclasses import dataclass

from .base import ParserContext, ParserError, ParsedProviderValue, exact_path, require_list, require_object, strict_decimal
from .local_reference import _parsed


@dataclass(frozen=True, slots=True)
class WallgoldMarketParser:
    symbol: str
    parser_version: str = "wallgold-market/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        instruments = {"GLD_18C_750TMN": "GOLD_18K_TOMAN_GRAM", "SLV_925TMN": "SILVER_925_TOMAN_GRAM"}
        if instruments.get(self.symbol) != context.instrument.instrument_id:
            raise ParserError("unsupported_symbol", "Wallgold purity does not match instrument")
        root = require_object(payload, "Wallgold response")
        if root.get("success") is not True:
            raise ParserError("provider_error", "Wallgold request failed")
        matches = [row for row in require_list(exact_path(root, "result"), "markets")
                   if require_object(row, "market").get("symbol") == self.symbol]
        if len(matches) != 1:
            raise ParserError("unsupported_symbol", "Expected one unique Wallgold market")
        market = matches[0]
        if market.get("quoteAsset") != "TMN" or market.get("baseAsset") != self.symbol[:-3]:
            raise ParserError("unknown_unit", "Wallgold asset or currency differs from contract")
        if (market.get("IsEnableBuySide") is not True or market.get("IsEnableSellSide") is not True
                or market.get("buyStatus") != "enable" or market.get("sellStatus") != "enable"):
            raise ParserError("market_closed", "Wallgold market is not tradable")
        stats = require_object(exact_path(market, "marketCap"), "marketCap")
        if stats.get("symbol") != self.symbol:
            raise ParserError("unsupported_symbol", "Wallgold price belongs to another market")
        price = strict_decimal(exact_path(stats, "lastPrice"), "lastPrice")
        return _parsed(price, context, None, {
            "symbol": self.symbol, "source_currency": "TOMAN", "source_weight_unit": "gram",
            "original_value": str(price), "conversion_factor": "1",
            "timestamp_basis": "received_at", "provider_timestamp_available": False,
            "selected_price_field": "marketCap.lastPrice",
        })
