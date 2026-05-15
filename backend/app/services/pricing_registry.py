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
                    "id": "tgju_gold",
                    "priority": 1,
                    "url": "https://api.tgju.org/v1/data/sana/json",
                    "method": "GET",
                    "response_path": "gold",
                    "unit": "gram",
                },
                {
                    "id": "bonbast_gold",
                    "priority": 2,
                    "url": "https://www.bonbast.com/json",
                    "method": "GET",
                    "auth": {"type": "header_simulation"},
                    "response_path": "gold",
                    "unit": "gram",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "metals_dev_gold",
                    "priority": 1,
                    "url": "https://api.metals.dev/v1/latest",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "query_params": {"currency": "USD", "unit": "toz"},
                    "response_path": "metals.gold",
                    "unit": "troy_ounce",
                },
                {
                    "id": "goldapi_gold",
                    "priority": 2,
                    "url": "https://www.goldapi.io/api/XAU/USD",
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
                    "response_path": "silver",
                    "unit": "gram",
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
                    "url": "https://api.nobitex.ir/market/stats",
                    "method": "POST",
                    "body": {"srcCurrency": "usdt", "dstCurrency": "rls"},
                    "response_path": "stats.usdt-rls.latest",
                    "unit": "rial",
                    "convert_to_toman": True,
                },
                {
                    "id": "tetherland_usdt",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "usdt",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "coingecko_usdt",
                    "priority": 1,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "tether.usd",
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
                    "url": "https://api.nobitex.ir/market/stats",
                    "method": "POST",
                    "body": {"srcCurrency": "btc", "dstCurrency": "rls"},
                    "response_path": "stats.btc-rls.latest",
                    "unit": "rial",
                    "convert_to_toman": True,
                },
                {
                    "id": "tetherland_btc",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "btc",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "coingecko_btc",
                    "priority": 1,
                    "url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                    "method": "GET",
                    "response_path": "bitcoin.usd",
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
