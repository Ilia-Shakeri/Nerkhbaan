from __future__ import annotations

from .base import ExplicitParser, ParserContext, ParserError, ParsedProviderValue
from .metals import GoldApiFreeParser, GoldApiParser, MetalsDevParser
from .nobitex import NobitexOrderBookParser, NobitexStatsParser
from .tickers import AlanchandGold18Parser, CoinCapParser, TetherlandParser


def build_parser(parser_id: str) -> ExplicitParser:
    factories = {
        "nobitex_stats_usdt_rls_v1": lambda: NobitexStatsParser(
            pair="usdt-rls", convert_rial_to_toman=True
        ),
        "nobitex_stats_btc_rls_v1": lambda: NobitexStatsParser(
            pair="btc-rls", convert_rial_to_toman=True
        ),
        "nobitex_orderbook_usdtirt_v1": lambda: NobitexOrderBookParser(
            symbol="USDTIRT"
        ),
        "nobitex_orderbook_btcirt_v1": lambda: NobitexOrderBookParser(
            symbol="BTCIRT"
        ),
        "goldapi_xau_v1": lambda: GoldApiParser(symbol="XAU"),
        "goldapi_xag_v1": lambda: GoldApiParser(symbol="XAG"),
        "gold_api_free_xau_v1": lambda: GoldApiFreeParser(symbol="XAU"),
        "gold_api_free_xag_v1": lambda: GoldApiFreeParser(symbol="XAG"),
        "metals_dev_gold_v1": lambda: MetalsDevParser(metal="gold"),
        "metals_dev_silver_v1": lambda: MetalsDevParser(metal="silver"),
        "coincap_tether_v1": lambda: CoinCapParser(asset_id="tether", symbol="USDT"),
        "coincap_bitcoin_v1": lambda: CoinCapParser(asset_id="bitcoin", symbol="BTC"),
        "alanchand_gold18_v1": AlanchandGold18Parser,
        "tetherland_usdt_v1": lambda: TetherlandParser(symbol="USDT"),
        "tetherland_btc_v1": lambda: TetherlandParser(symbol="BTC"),
    }
    try:
        return factories[parser_id]()
    except KeyError as exc:
        raise ParserError("unknown_parser", f"Parser is not registered: {parser_id}") from exc


__all__ = [
    "ExplicitParser",
    "ParsedProviderValue",
    "ParserContext",
    "ParserError",
    "build_parser",
]
