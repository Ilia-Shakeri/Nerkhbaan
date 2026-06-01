"""Catalog of market data providers used by backend services.

This registry is intentionally explicit so backend and frontend can reference
provider metadata from one place.
"""

from __future__ import annotations

API_REGISTRY: dict = {
    "iran_market": {
        "tgju": {
            "description": "Gold, coin, USD, and silver prices in Toman",
            "base_url": "https://api.tgju.org/v1",
            "endpoints": {
                "gold_price": "https://api.tgju.org/v1/data/sana/json",
                "currency": "https://api.tgju.org/v1/data/sana/json",
            },
            "auth": "none",
            "rate_limit": "unknown (unofficial)",
            "note": "Unofficial API, schema may change without notice",
        },
        "nobitex": {
            "description": "Crypto prices in Toman",
            "base_url": "https://api.nobitex.ir",
            "endpoints": {
                "market_stats": "https://api.nobitex.ir/market/stats",
                "orderbook": "https://api.nobitex.ir/v2/orderbook/{symbol}",
                "trades": "https://api.nobitex.ir/v2/trades/{symbol}",
            },
            "auth": "none for public endpoints",
            "rate_limit": "100 requests/minute",
            "docs": "https://apidocs.nobitex.ir",
        },
        "tetherland": {
            "description": "USDT and crypto prices in Toman",
            "base_url": "https://api.tetherland.com",
            "endpoints": {
                "currencies": "https://api.tetherland.com/currencies",
            },
            "auth": "none",
            "rate_limit": "unknown",
        },
        "bonbast": {
            "description": "Open-market forex rates in Toman",
            "base_url": "https://www.bonbast.com",
            "endpoints": {
                "prices": "https://www.bonbast.com/json",
            },
            "auth": "usually requires browser-like headers/cookies",
            "rate_limit": "unknown",
            "note": "May require scraping/browser emulation",
        },
    },
    "international_market": {
        "coingecko": {
            "description": "Crypto prices in USD",
            "base_url": "https://api.coingecko.com/api/v3",
            "endpoints": {
                "bitcoin_price": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                "multi_price": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd,eur",
                "coin_list": "https://api.coingecko.com/api/v3/coins/list",
                "market_data": "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd",
            },
            "auth": "none (free) or API key (paid tiers)",
            "rate_limit": "10-50 requests/minute",
            "docs": "https://www.coingecko.com/en/api/documentation",
        },
        "coincap": {
            "description": "Real-time crypto prices in USD",
            "base_url": "https://api.coincap.io/v2",
            "endpoints": {
                "assets": "https://api.coincap.io/v2/assets",
                "bitcoin": "https://api.coincap.io/v2/assets/bitcoin",
                "rates": "https://api.coincap.io/v2/rates",
            },
            "auth": "none",
            "rate_limit": "200 requests/minute",
            "docs": "https://docs.coincap.io",
        },
        "metals_dev": {
            "description": "Gold and silver prices in USD",
            "base_url": "https://api.metals.dev/v1",
            "endpoints": {
                "latest": "https://api.metals.dev/v1/latest?api_key=YOUR_KEY&currency=USD&unit=toz",
            },
            "auth": "API key",
            "rate_limit": "50 requests/month (free tier)",
            "docs": "https://metals.dev/docs",
        },
        "exchangerate_api": {
            "description": "FX conversion rates",
            "base_url": "https://v6.exchangerate-api.com/v6",
            "endpoints": {
                "latest_usd": "https://v6.exchangerate-api.com/v6/YOUR_KEY/latest/USD",
                "pair": "https://v6.exchangerate-api.com/v6/YOUR_KEY/pair/USD/EUR",
            },
            "auth": "API key",
            "rate_limit": "1500 requests/month",
            "docs": "https://www.exchangerate-api.com/docs",
        },
        "frankfurter": {
            "description": "FX rates (no metals)",
            "base_url": "https://api.frankfurter.app",
            "endpoints": {
                "latest": "https://api.frankfurter.app/latest?from=USD",
                "historical": "https://api.frankfurter.app/2024-01-01?from=USD&to=EUR",
            },
            "auth": "none",
            "rate_limit": "unlimited (reasonable use)",
            "docs": "https://www.frankfurter.app/docs",
        },
    },
}
