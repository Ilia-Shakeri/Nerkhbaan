from __future__ import annotations
from typing import Any

REQUEST_TIMEOUT_SECONDS = 10
RETRY_ATTEMPTS = 2

CHART_ERROR_MESSAGE = {
    "fa": "امکان دریافت اطلاعات وجود ندارد",
    "en": "Unable to fetch data",
}

ASSET_LABELS: dict[str, dict[str, str]] = {
    "gold": {"fa": "طلا", "en": "Gold"},
    "silver": {"fa": "نقره", "en": "Silver"},
    "usdt": {"fa": "تتر", "en": "Tether"},
    "btc": {"fa": "بیت کوین", "en": "Bitcoin"},
}

PRICE_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "gold": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "tetherland_gold",
                    "priority": 1,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.GOLD.price",
                    "unit": "toman",
                },
                {
                    "id": "tgju_gold_fallback",
                    "priority": 2,
                    "url": "https://api.tgju.org/v1/market/indicator/summary-table-data/global-price",
                    "method": "GET",
                    "response_path": "data.gold.p",
                    "unit": "toman",
                },
                {
                    "id": "brsapi_gold",
                    "priority": 3,
                    "url": "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency.json",
                    "method": "GET",
                    "response_path": "gold.0.price",
                    "unit": "toman",
                }
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "binance_paxg_gold",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
                {
                    # Free spot metal price, no API key required.
                    "id": "goldapi_xau",
                    "priority": 2,
                    "url": "https://api.gold-api.com/price/XAU",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
                {
                    "id": "coingecko_gold_fallback",
                    "priority": 3,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "pax-gold.usd",
                    "unit": "troy_ounce",
                },
                {
                    # Free tier, no API key required.
                    "id": "coinpaprika_paxg",
                    "priority": 4,
                    "url": "https://api.coinpaprika.com/v1/tickers/paxg-pax-gold",
                    "method": "GET",
                    "response_path": "quotes.USD.price",
                    "unit": "troy_ounce",
                },
                {
                    "id": "metals_dev_gold_backup",
                    "priority": 5,
                    "url": "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "response_path": "metals.gold",
                    "unit": "troy_ounce",
                }
            ],
        },
    },
    "silver": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "tetherland_silver",
                    "priority": 1,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.SILVER.price",
                    "unit": "toman",
                },
                {
                    "id": "tgju_silver_fallback",
                    "priority": 2,
                    "url": "https://api.tgju.org/v1/market/indicator/summary-table-data/silver",
                    "method": "GET",
                    "response_path": "data.silver.p",
                    "unit": "toman",
                }
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "binance_silver",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=XAGUSDT",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
                {
                    # Free spot metal price, no API key required. Replaces the old
                    # coingecko "silver" id, which resolved to an unrelated token.
                    "id": "goldapi_xag",
                    "priority": 2,
                    "url": "https://api.gold-api.com/price/XAG",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
                {
                    "id": "metals_dev_silver",
                    "priority": 3,
                    "url": "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "response_path": "metals.silver",
                    "unit": "troy_ounce",
                },
            ],
        },
    },
    "usdt": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "nobitex_usdt",
                    "priority": 1,
                    "url": "https://api.nobitex.ir/v2/orderbook/USDTIRT",
                    "method": "GET",
                    "response_path": "lastTradePrice",
                    "unit": "toman",
                },
                {
                    "id": "tetherland_usdt_fallback",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.USDT.price",
                    "unit": "toman",
                },
                {
                    "id": "wallex_usdt_backup",
                    "priority": 3,
                    "url": "https://api.wallex.ir/v1/markets",
                    "method": "GET",
                    "response_path": "result.symbols.USDTTMN.stats.lastPrice",
                    "unit": "toman",
                }
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "binance_usdt",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "usd",
                },
                {
                    "id": "coingecko_usdt_fallback",
                    "priority": 2,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "tether.usd",
                    "unit": "usd",
                },
                {
                    # Free tier, no API key required.
                    "id": "coinpaprika_usdt",
                    "priority": 3,
                    "url": "https://api.coinpaprika.com/v1/tickers/usdt-tether",
                    "method": "GET",
                    "response_path": "quotes.USD.price",
                    "unit": "usd",
                },
                {
                    "id": "kraken_usdt_backup",
                    "priority": 4,
                    "url": "https://api.kraken.com/0/public/Ticker?pair=USDTUSD",
                    "method": "GET",
                    "response_path": "result.USDTUSD.c.0",
                    "unit": "usd",
                }
            ],
        },
    },
    "btc": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "nobitex_btc",
                    "priority": 1,
                    "url": "https://api.nobitex.ir/v2/orderbook/BTCIRT",
                    "method": "GET",
                    "response_path": "lastTradePrice",
                    "unit": "toman",
                },
                {
                    "id": "tetherland_btc_fallback",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.BTC.price",
                    "unit": "toman",
                },
                {
                    "id": "wallex_btc_backup",
                    "priority": 3,
                    "url": "https://api.wallex.ir/v1/markets",
                    "method": "GET",
                    "response_path": "result.symbols.BTCTMN.stats.lastPrice",
                    "unit": "toman",
                }
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "binance_btc",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "usd",
                },
                {
                    "id": "coingecko_btc_fallback",
                    "priority": 2,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "bitcoin.usd",
                    "unit": "usd",
                },
                {
                    # Free tier, no API key required.
                    "id": "coinpaprika_btc",
                    "priority": 3,
                    "url": "https://api.coinpaprika.com/v1/tickers/btc-bitcoin",
                    "method": "GET",
                    "response_path": "quotes.USD.price",
                    "unit": "usd",
                },
                {
                    # Free, no API key required. Returns a single-element array.
                    "id": "coinlore_btc",
                    "priority": 4,
                    "url": "https://api.coinlore.net/api/ticker/?id=90",
                    "method": "GET",
                    "response_path": "0.price_usd",
                    "unit": "usd",
                },
                {
                    "id": "kraken_btc_backup",
                    "priority": 5,
                    "url": "https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
                    "method": "GET",
                    "response_path": "result.XXBTZUSD.c.0",
                    "unit": "usd",
                }
            ],
        },
    },
}
