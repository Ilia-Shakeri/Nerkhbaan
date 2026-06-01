from __future__ import annotations
from typing import Any

REQUEST_TIMEOUT_SECONDS = 8
RETRY_ATTEMPTS = 1

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
                    "id": "brsapi_gold",
                    "priority": 1,
                    "url": "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency.json",
                    "method": "GET",
                    "response_path": "gold.0.price",
                    "unit": "toman",
                },
                {
                    "id": "tgju_gold",
                    "priority": 2,
                    "url": "https://api.tgju.org/v1/data/sana/json",
                    "method": "GET",
                    "response_path": "gold",
                    "unit": "gram",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    # FREE: Binance PAXG matches 1 Troy Ounce of Gold exactly
                    "id": "binance_paxg_gold",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price",
                    "method": "GET",
                    "query_params": {"symbol": "PAXGUSDT"},
                    "response_path": "price",
                    "unit": "troy_ounce",
                },
                {
                    "id": "metals_dev_gold",
                    "priority": 2,
                    "url": "https://api.metals.dev/v1/latest",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "query_params": {"currency": "USD", "unit": "toz"},
                    "response_path": "metals.gold",
                    "unit": "troy_ounce",
                },
            ],
        },
    },
    "silver": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "tgju_silver",
                    "priority": 1,
                    "url": "https://api.tgju.org/v1/data/sana/json",
                    "method": "GET",
                    "response_path": "silver",
                    "unit": "gram",
                },
                {
                    "id": "tetherland_silver",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.SILVER.price",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "metals_dev_silver",
                    "priority": 1,
                    "url": "https://api.metals.dev/v1/latest",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "query_params": {"currency": "USD", "unit": "toz"},
                    "response_path": "metals.silver",
                    "unit": "troy_ounce",
                },
                {
                    "id": "goldapi_silver",
                    "priority": 2,
                    "url": "https://www.goldapi.io/api/XAG/USD",
                    "method": "GET",
                    "auth": {
                        "type": "header_api_key",
                        "key_source": "goldapi_api_key",
                        "header_name": "x-access-token",
                    },
                    "response_path": "price",
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
                    "id": "tetherland_usdt",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.USDT.price",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "binance_usdt",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price",
                    "method": "GET",
                    "query_params": {"symbol": "USDCUSDT"},
                    "response_path": "price",
                    "unit": "usd",
                },
                {
                    "id": "coincap_usdt",
                    "priority": 2,
                    "url": "https://api.coincap.io/v2/assets/tether",
                    "method": "GET",
                    "response_path": "data.priceUsd",
                    "unit": "usd",
                },
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
                    "id": "tetherland_btc",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.BTC.price",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "binance_btc",
                    "priority": 1,
                    "url": "https://api.binance.com/api/v3/ticker/price",
                    "method": "GET",
                    "query_params": {"symbol": "BTCUSDT"},
                    "response_path": "price",
                    "unit": "usd",
                },
                {
                    "id": "coincap_btc",
                    "priority": 2,
                    "url": "https://api.coincap.io/v2/assets/bitcoin",
                    "method": "GET",
                    "response_path": "data.priceUsd",
                    "unit": "usd",
                },
            ],
        },
    },
}