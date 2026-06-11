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
                    "response_path": "gold",
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
                    "id": "coingecko_gold_fallback",
                    "priority": 2,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "pax-gold.usd",
                    "unit": "troy_ounce",
                },
                {
                    "id": "binance_paxg_gold_backup",
                    "priority": 3,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT",
                    "method": "GET",
                    "response_path": "price",
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
                    "response_path": "silver",
                    "unit": "toman",
                }
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "metals_dev_silver",
                    "priority": 1,
                    "url": "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "response_path": "metals.silver",
                    "unit": "troy_ounce",
                },
                {
                    "id": "coingecko_paxg_silver_fallback",
                    "priority": 2,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=silver-tokenized-stock-defichain&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "silver-tokenized-stock-defichain.usd",
                    "unit": "troy_ounce",
                },
                {
                    "id": "metals_dev_silver_original",
                    "priority": 3,
                    "url": "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "response_path": "metals.silver",
                    "unit": "troy_ounce",
                }
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
                    "id": "nobitex_usdt_backup",
                    "priority": 3,
                    "url": "https://api.nobitex.ir/v2/orderbook/USDTIRT",
                    "method": "GET",
                    "response_path": "lastTradePrice",
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
                    "id": "binance_usdt_backup",
                    "priority": 3,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=USDCUSDT",
                    "method": "GET",
                    "response_path": "price",
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
                    "id": "nobitex_btc_backup",
                    "priority": 3,
                    "url": "https://api.nobitex.ir/v2/orderbook/BTCIRT",
                    "method": "GET",
                    "response_path": "lastTradePrice",
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
                    "id": "binance_btc_backup",
                    "priority": 3,
                    "url": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "usd",
                }
            ],
        },
    },
}
