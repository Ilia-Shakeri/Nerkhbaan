from __future__ import annotations

from ...config import settings


def _setting(name: str, default: str) -> str:
    value = getattr(settings, name.lower(), None)
    return str(value) if value is not None else default

from .base import ExplicitParser, ParserContext, ParserError, ParsedProviderValue
from .bitpin import BitpinPricesParser
from .wallgold import WallgoldMarketParser
from .local_reference import (
    ArzbinMarketParser,
    CoinbaseTickerParser,
    CoinGeckoSimplePriceParser,
    NavasanLatestParser,
    NerkhIoLiteParser,
    PersianToolboxMarketParser,
    ServixAssetsParser,
    TalaRatesParser,
    TicaroPricesParser,
    WallexMarketParser,
)
from .metals import GoldApiFreeBtcParser, GoldApiFreeParser, GoldApiParser, MetalsDevParser, XausSilverParser
from .nobitex import NobitexOrderBookParser, NobitexStatsParser
from .tickers import AlanchandGold18Parser, CoinCapParser, TetherlandParser
from .nerkhsanj_markets import NerkhsanjSnapshotParser
from .gta_silver import GtaSilver925Parser
from .wallgold_quotes import WallgoldPublicQuoteParser


class HistoricalOnlyParser:
    parser_version = "historical-only/1.0.0"

    def parse(self, payload: object, context: ParserContext) -> ParsedProviderValue:
        raise ParserError("history_only", "Daily archives cannot provide current quotes")


def build_parser(parser_id: str) -> ExplicitParser:
    snapshot_symbols = {
        "usd_toman": "dollar", "gold18_toman": "gold", "silver999_toman": "silver",
        "usdt_toman": "tether", "btc_toman": "bitcoin", "xau_usd": "ounce", "xag_usd": "silver-ounce",
    }
    for asset, symbol in snapshot_symbols.items():
        if parser_id == f"nerkhsanj_{asset}_snapshot_v1":
            return NerkhsanjSnapshotParser(symbol)
    factories = {
        "gta_silver925_v1": GtaSilver925Parser,
        "wallgold_gold18_quote_v1": lambda: WallgoldPublicQuoteParser("GLD_18C_750TMN"),
        "wallgold_silver925_quote_v1": lambda: WallgoldPublicQuoteParser("SLV_925TMN"),
        "historical_only_v1": HistoricalOnlyParser,
        "wallgold_gold18_v1": lambda: WallgoldMarketParser(symbol="GLD_18C_750TMN"),
        "wallgold_silver925_v1": lambda: WallgoldMarketParser(symbol="SLV_925TMN"),
        "bitpin_btc_toman_v1": lambda: BitpinPricesParser(symbol="BTC_IRT"),
        "bitpin_usdt_toman_v1": lambda: BitpinPricesParser(symbol="USDT_IRT"),
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
        "gold_api_free_btc_v1": GoldApiFreeBtcParser,
        "xaus_xag_v1": XausSilverParser,
        "metals_dev_gold_v1": lambda: MetalsDevParser(metal="gold"),
        "metals_dev_silver_v1": lambda: MetalsDevParser(metal="silver"),
        "coinbase_btc_usd_v1": lambda: CoinbaseTickerParser(product_id="BTC-USD"),
        "coinbase_usdt_usd_v1": lambda: CoinbaseTickerParser(product_id="USDT-USD"),
        "coingecko_bitcoin_usd_v1": lambda: CoinGeckoSimplePriceParser(asset_id="bitcoin"),
        "coingecko_tether_usd_v1": lambda: CoinGeckoSimplePriceParser(asset_id="tether"),
        "persian_toolbox_btc_usd_v1": lambda: PersianToolboxMarketParser(asset="BTC_USD"),
        "persian_toolbox_gold24_toman_v1": lambda: PersianToolboxMarketParser(
            asset="GOLD_24K_TOMAN_GRAM"
        ),
        "persian_toolbox_usd_toman_v1": lambda: PersianToolboxMarketParser(asset="USD_TOMAN"),
        "wallex_usdt_toman_v1": lambda: WallexMarketParser(symbol="USDTTMN"),
        "wallex_btc_toman_v1": lambda: WallexMarketParser(symbol="BTCTMN"),
        "servix_usd_rls_v1": lambda: ServixAssetsParser(code="USD_RLS"),
        "servix_gold18_rls_v1": lambda: ServixAssetsParser(code="GOLD_18_RLS"),
        "servix_gold18_toman_v1": lambda: ServixAssetsParser(code="GOLD_18_RLS"),
        "servix_gold24_toman_v1": lambda: ServixAssetsParser(code="GOLD_24_RLS"),
        "servix_xau_usd_v1": lambda: ServixAssetsParser(code="GOLD_OUNCE_USD"),
        "servix_xag_usd_v1": lambda: ServixAssetsParser(code="SILVER_OUNCE_USD"),
        "servix_btc_usd_v1": lambda: ServixAssetsParser(code="BTC_USD"),
        "servix_usdt_usd_v1": lambda: ServixAssetsParser(code="USDT_USD"),
        "servix_btc_toman_v1": lambda: ServixAssetsParser(code="BTC_RLS"),
        "servix_usdt_toman_v1": lambda: ServixAssetsParser(code="USDT_RLS"),
        "tala_xau_usd_v1": lambda: TalaRatesParser(key=_setting("TALA_XAU_USD_KEY", "ons")),
        "tala_xag_usd_v1": lambda: TalaRatesParser(key=_setting("TALA_XAG_USD_KEY", "silver")),
        "tala_usdt_toman_v1": lambda: TalaRatesParser(key=_setting("TALA_USDT_TOMAN_KEY", "usdt_irt")),
        "tala_gold18_toman_v1": lambda: TalaRatesParser(key=_setting("TALA_GOLD18_TOMAN_KEY", "geram18k")),
        "tala_gold24_toman_v1": lambda: TalaRatesParser(key=_setting("TALA_GOLD24_TOMAN_KEY", "geram24k")),
        "tala_silver999_toman_v1": lambda: TalaRatesParser(key=_setting("TALA_SILVER999_TOMAN_KEY", "")),
        "ticaro_usdt_toman_v1": lambda: TicaroPricesParser(pair=_setting("TICARO_USDT_TOMAN_PAIR", "USDT/TMN")),
        "ticaro_btc_toman_v1": lambda: TicaroPricesParser(pair=_setting("TICARO_BTC_TOMAN_PAIR", "BTC/TMN")),
        "ticaro_gold18_toman_v1": lambda: TicaroPricesParser(pair=_setting("TICARO_GOLD18_TOMAN_PAIR", "GOLD18/TMN")),
        "arzbin_usd_v1": lambda: ArzbinMarketParser(code="USD", semantic=_setting("ARZBIN_PRICE_SEMANTIC", "sell"), unit=_setting("ARZBIN_LOCAL_UNIT", "TOMAN")),
        "navasan_usd_v1": lambda: NavasanLatestParser(item=_setting("NAVASAN_USD_ITEM", "usd_sell"), source_unit=_setting("NAVASAN_LOCAL_UNIT", "")),
        "navasan_usdt_v1": lambda: NavasanLatestParser(item=_setting("NAVASAN_USDT_ITEM", "usdt"), source_unit=_setting("NAVASAN_LOCAL_UNIT", "")),
        "navasan_btc_v1": lambda: NavasanLatestParser(item=_setting("NAVASAN_BTC_ITEM", "btc"), source_unit=_setting("NAVASAN_LOCAL_UNIT", "")),
        "navasan_gold18_v1": lambda: NavasanLatestParser(item=_setting("NAVASAN_GOLD18_ITEM", "18ayar"), source_unit=_setting("NAVASAN_LOCAL_UNIT", "")),
        "navasan_xau_v1": lambda: NavasanLatestParser(item=_setting("NAVASAN_XAU_ITEM", "usd_xau"), source_unit=_setting("NAVASAN_LOCAL_UNIT", "")),
        "nerkh_io_usd_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_USD_SYMBOL", "USD"), source_unit=_setting("NERKH_IO_CURRENCY_UNIT", "")),
        "nerkh_io_usdt_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_USDT_SYMBOL", "USDT"), source_unit=_setting("NERKH_IO_CRYPTO_UNIT", "")),
        "nerkh_io_btc_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_BTC_SYMBOL", "BTC"), source_unit=_setting("NERKH_IO_CRYPTO_UNIT", "")),
        "nerkh_io_gold18_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_GOLD18_SYMBOL", "GOLD18K"), source_unit=_setting("NERKH_IO_GOLD_UNIT", "")),
        "nerkh_io_gold24_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_GOLD24_SYMBOL", "GOLD24K"), source_unit=_setting("NERKH_IO_GOLD_UNIT", "")),
        "nerkh_io_xau_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_XAU_SYMBOL", "OUNCE"), source_unit=_setting("NERKH_IO_GOLD_UNIT", "")),
        "nerkh_io_xag_v1": lambda: NerkhIoLiteParser(symbol=_setting("NERKH_IO_XAG_SYMBOL", "OUNCE_SILVER"), source_unit=_setting("NERKH_IO_GOLD_UNIT", "")),
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
