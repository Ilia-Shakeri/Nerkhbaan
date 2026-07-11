from __future__ import annotations

from typing import Any

REQUEST_TIMEOUT_SECONDS = 5
RETRY_ATTEMPTS = 0

CHART_ERROR_MESSAGE = {
    "fa": "داده بازار در دسترس نیست",
    "en": "Unable to fetch market data",
}

ASSET_LABELS: dict[str, dict[str, str]] = {
    "gold": {"fa": "طلا", "en": "Gold"},
    "silver": {"fa": "نقره", "en": "Silver"},
    "usdt": {"fa": "تتر", "en": "Tether"},
    "btc": {"fa": "بیت کوین", "en": "Bitcoin"},
}

NOBITEX_HEADERS = {"User-Agent": "TraderBot/Nerkhbaan_Worker"}
LIMITED_INTERVAL_SECONDS = 60 * 60
SLOW_INTERVAL_SECONDS = 2 * 60 * 60

PRICE_REGISTRY: dict[str, dict[str, dict[str, Any]]] = {
    "gold": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "tgju_gold",
                    "priority": 1,
                    "url": "https://api.tgju.org/v1/market/indicator/summary-table-data/global-price",
                    "method": "GET",
                    "response_path": "data.gold.p",
                    "unit": "toman",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
                {
                    "id": "alanchand_gold",
                    "priority": 2,
                    "url": "https://api.alanchand.com/v1/markets/gold",
                    "method": "GET",
                    "auth": {"type": "header_api_key", "key_source": "alanchand_api_token", "header_name": "Authorization"},
                    "response_path": "data.gold_18k.price",
                    "unit": "toman",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
                    "optional_auth": True,
                },
                {
                    "id": "bonbast_gold",
                    "priority": 3,
                    "url": "https://www.bonbast.com/json",
                    "method": "GET",
                    "auth": {"type": "header_simulation"},
                    "response_path": "gold",
                    "unit": "toman",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
                {
                    "id": "tetherland_gold",
                    "priority": 4,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.GOLD.price",
                    "unit": "toman",
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "goldapi_xau",
                    "priority": 1,
                    "url": "https://www.goldapi.io/api/XAU/USD",
                    "method": "GET",
                    "auth": {"type": "header_api_key", "key_source": "goldapi_api_key", "header_name": "x-access-token"},
                    "response_path": "price",
                    "unit": "troy_ounce",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
                },
                {
                    "id": "gold_api_xau_free",
                    "priority": 2,
                    "url": "https://api.gold-api.com/price/XAU",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "troy_ounce",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
                {
                    "id": "metals_dev_gold",
                    "priority": 3,
                    "url": "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "response_path": "metals.gold",
                    "unit": "troy_ounce",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
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
                    "url": "https://api.tgju.org/v1/market/indicator/summary-table-data/silver",
                    "method": "GET",
                    "response_path": "data.silver.p",
                    "unit": "toman",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
                {
                    "id": "tetherland_silver",
                    "priority": 2,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.SILVER.price",
                    "unit": "toman",
                },
                {
                    "id": "bonbast_silver",
                    "priority": 3,
                    "url": "https://www.bonbast.com/json",
                    "method": "GET",
                    "auth": {"type": "header_simulation"},
                    "response_path": "silver",
                    "unit": "toman",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "goldapi_xag",
                    "priority": 1,
                    "url": "https://www.goldapi.io/api/XAG/USD",
                    "method": "GET",
                    "auth": {"type": "header_api_key", "key_source": "goldapi_api_key", "header_name": "x-access-token"},
                    "response_path": "price",
                    "unit": "troy_ounce",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
                },
                {
                    "id": "gold_api_xag_free",
                    "priority": 2,
                    "url": "https://api.gold-api.com/price/XAG",
                    "method": "GET",
                    "response_path": "price",
                    "unit": "troy_ounce",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
                {
                    "id": "metals_dev_silver",
                    "priority": 3,
                    "url": "https://api.metals.dev/v1/latest?currency=USD&unit=toz",
                    "method": "GET",
                    "auth": {"type": "api_key", "key_source": "metals_dev_api_key", "key_param": "api_key"},
                    "response_path": "metals.silver",
                    "unit": "troy_ounce",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
                },
            ],
        },
    },
    "usdt": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "nobitex_stats_usdt",
                    "priority": 1,
                    "url": "https://apiv2.nobitex.ir/market/stats",
                    "method": "GET",
                    "headers": NOBITEX_HEADERS,
                    "response_path": "stats.usdt-rls.latest",
                    "unit": "rial",
                    "convert_to_toman": True,
                },
                {
                    "id": "nobitex_usdt",
                    "priority": 2,
                    "url": "https://apiv2.nobitex.ir/v3/orderbook/all",
                    "method": "GET",
                    "headers": NOBITEX_HEADERS,
                    "orderbook_symbol": "USDTIRT",
                    "orderbook_side": "mid",
                    "unit": "toman",
                },
                {
                    "id": "tetherland_usdt",
                    "priority": 3,
                    "url": "https://api.tetherland.com/currencies",
                    "method": "GET",
                    "response_path": "data.currencies.USDT.price",
                    "unit": "toman",
                },
                {
                    "id": "bonbast_usd",
                    "priority": 4,
                    "url": "https://www.bonbast.com/json",
                    "method": "GET",
                    "auth": {"type": "header_simulation"},
                    "response_path": "usd1",
                    "unit": "toman",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
            ],
        },
        "international": {
            "currency": "USD",
            "providers": [
                {
                    "id": "nobitex_usdt_usd_reference",
                    "priority": 1,
                    "url": "https://apiv2.nobitex.ir/market/stats",
                    "method": "GET",
                    "fixed_value": 1,
                    "unit": "usd",
                },
                {
                    "id": "coincap_usdt",
                    "priority": 2,
                    "url": "https://api.coincap.io/v2/assets/tether",
                    "method": "GET",
                    "response_path": "data.priceUsd",
                    "unit": "usd",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
                {
                    "id": "exchangerate_usd",
                    "priority": 3,
                    "url": "https://v6.exchangerate-api.com/v6/latest/USD",
                    "method": "GET",
                    "auth": {"type": "path_api_key", "key_source": "exchangerate_api_key", "path_token": "latest"},
                    "response_path": "conversion_rates.USD",
                    "unit": "usd",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
                },
                {
                    "id": "frankfurter_usd",
                    "priority": 4,
                    "url": "https://api.frankfurter.app/latest?from=USD&to=EUR",
                    "method": "GET",
                    "fixed_value": 1,
                    "unit": "usd",
                    "min_interval_seconds": SLOW_INTERVAL_SECONDS,
                },
            ],
        },
    },
    "btc": {
        "iran": {
            "currency": "IRR",
            "providers": [
                {
                    "id": "nobitex_stats_btc",
                    "priority": 1,
                    "url": "https://apiv2.nobitex.ir/market/stats",
                    "method": "GET",
                    "headers": NOBITEX_HEADERS,
                    "response_path": "stats.btc-rls.latest",
                    "unit": "rial",
                    "convert_to_toman": True,
                },
                {
                    "id": "nobitex_btc",
                    "priority": 2,
                    "url": "https://apiv2.nobitex.ir/v3/orderbook/all",
                    "method": "GET",
                    "headers": NOBITEX_HEADERS,
                    "orderbook_symbol": "BTCIRT",
                    "orderbook_side": "mid",
                    "unit": "toman",
                },
                {
                    "id": "tetherland_btc",
                    "priority": 3,
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
                    "id": "nobitex_stats_btc_usdt",
                    "priority": 1,
                    "url": "https://apiv2.nobitex.ir/market/stats",
                    "method": "GET",
                    "headers": NOBITEX_HEADERS,
                    "response_path": "stats.btc-usdt.latest",
                    "unit": "usd",
                },
                {
                    "id": "coincap_btc",
                    "priority": 2,
                    "url": "https://api.coincap.io/v2/assets/bitcoin",
                    "method": "GET",
                    "response_path": "data.priceUsd",
                    "unit": "usd",
                    "min_interval_seconds": LIMITED_INTERVAL_SECONDS,
                },
            ],
        },
    },
}
