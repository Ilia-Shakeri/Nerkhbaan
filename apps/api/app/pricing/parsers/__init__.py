from __future__ import annotations

import os

from .base import ExplicitParser, ParserContext, ParserError, ParsedProviderValue
from .local_reference import (
    ArzbinMarketParser,
    CoinbaseTickerParser,
    CoinGeckoSimplePriceParser,
    NavasanLatestParser,
    NerkhIoLiteParser,
    ServixAssetsParser,
    TalaRatesParser,
    TicaroPricesParser,
    WallexMarketParser,
)
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
        "coinbase_btc_usd_v1": lambda: CoinbaseTickerParser(product_id="BTC-USD"),
        "coinbase_usdt_usd_v1": lambda: CoinbaseTickerParser(product_id="USDT-USD"),
        "coingecko_bitcoin_usd_v1": lambda: CoinGeckoSimplePriceParser(asset_id="bitcoin"),
        "coingecko_tether_usd_v1": lambda: CoinGeckoSimplePriceParser(asset_id="tether"),
        "wallex_usdt_toman_v1": lambda: WallexMarketParser(symbol="USDTTMN"),
        "wallex_btc_toman_v1": lambda: WallexMarketParser(symbol="BTCTMN"),
        "servix_usd_rls_v1": lambda: ServixAssetsParser(code="USD_RLS"),
        "servix_gold18_rls_v1": lambda: ServixAssetsParser(code="GOLD_18_RLS"),
        "servix_btc_usd_v1": lambda: ServixAssetsParser(code="BTC_USD"),
        "tala_xau_usd_v1": lambda: TalaRatesParser(key=os.getenv("TALA_XAU_USD_KEY", "ons")),
        "tala_xag_usd_v1": lambda: TalaRatesParser(key=os.getenv("TALA_XAG_USD_KEY", "silver")),
        "tala_usdt_toman_v1": lambda: TalaRatesParser(key=os.getenv("TALA_USDT_TOMAN_KEY", "usdt_irt")),
        "tala_gold18_toman_v1": lambda: TalaRatesParser(key=os.getenv("TALA_GOLD18_TOMAN_KEY", "geram18k")),
        "tala_gold24_toman_v1": lambda: TalaRatesParser(key=os.getenv("TALA_GOLD24_TOMAN_KEY", "geram24k")),
        "ticaro_usdt_toman_v1": lambda: TicaroPricesParser(pair=os.getenv("TICARO_USDT_TOMAN_PAIR", "USDT/TMN")),
        "ticaro_btc_toman_v1": lambda: TicaroPricesParser(pair=os.getenv("TICARO_BTC_TOMAN_PAIR", "BTC/TMN")),
        "ticaro_gold18_toman_v1": lambda: TicaroPricesParser(pair=os.getenv("TICARO_GOLD18_TOMAN_PAIR", "GOLD18/TMN")),
        "arzbin_usd_v1": lambda: ArzbinMarketParser(code="USD", semantic=os.getenv("ARZBIN_PRICE_SEMANTIC", "sell"), unit=os.getenv("ARZBIN_LOCAL_UNIT", "TOMAN")),
        "navasan_usd_v1": lambda: NavasanLatestParser(item=os.getenv("NAVASAN_USD_ITEM", "usd_sell")),
        "navasan_usdt_v1": lambda: NavasanLatestParser(item=os.getenv("NAVASAN_USDT_ITEM", "usdt")),
        "navasan_btc_v1": lambda: NavasanLatestParser(item=os.getenv("NAVASAN_BTC_ITEM", "btc")),
        "navasan_gold18_v1": lambda: NavasanLatestParser(item=os.getenv("NAVASAN_GOLD18_ITEM", "18ayar")),
        "navasan_xau_v1": lambda: NavasanLatestParser(item=os.getenv("NAVASAN_XAU_ITEM", "usd_xau")),
        "nerkh_io_usd_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_USD_SYMBOL", "USD"), source_unit=os.getenv("NERKH_IO_CURRENCY_UNIT", "")),
        "nerkh_io_usdt_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_USDT_SYMBOL", "USDT"), source_unit=os.getenv("NERKH_IO_CRYPTO_UNIT", "")),
        "nerkh_io_btc_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_BTC_SYMBOL", "BTC"), source_unit=os.getenv("NERKH_IO_CRYPTO_UNIT", "")),
        "nerkh_io_gold18_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_GOLD18_SYMBOL", "GOLD18K"), source_unit=os.getenv("NERKH_IO_GOLD_UNIT", "")),
        "nerkh_io_gold24_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_GOLD24_SYMBOL", "GOLD24K"), source_unit=os.getenv("NERKH_IO_GOLD_UNIT", "")),
        "nerkh_io_xau_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_XAU_SYMBOL", "OUNCE"), source_unit=os.getenv("NERKH_IO_GOLD_UNIT", "")),
        "nerkh_io_xag_v1": lambda: NerkhIoLiteParser(symbol=os.getenv("NERKH_IO_XAG_SYMBOL", "OUNCE_SILVER"), source_unit=os.getenv("NERKH_IO_GOLD_UNIT", "")),
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
