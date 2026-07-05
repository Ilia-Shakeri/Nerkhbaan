# Nerkhbaan Market API Documentation

This document lists the external market APIs used by the pricing worker and the polling intervals configured in `apps/api/app/services/pricing_registry.py`.

## TimescaleDB rollout

New databases run `apps/api/db/init/001_timescale_market_prices.sql` automatically through Docker entrypoint mounting. Existing databases must run `apps/api/db/migrations/20260705_timescale_market_prices.sql` once with `psql` after the Postgres image is replaced by TimescaleDB.

| Provider | Base URL | API key | Endpoint used | Internal polling frequency |
| --- | --- | --- | --- | --- |
| Nobitex | `https://apiv2.nobitex.ir` | No key. Public order book endpoint. | `GET /v3/orderbook/all` with `User-Agent: TraderBot/Nerkhbaan_Worker`; reads `USDTIRT` and `BTCIRT` top bid/ask. | Normal cache cadence, about every 20 seconds when requested. |
| GoldAPI | `https://www.goldapi.io` | Required for `www.goldapi.io`. Register at `https://www.goldapi.io`; set `GOLDAPI_API_KEY`. | `GET /api/XAU/USD`, `GET /api/XAG/USD` with `x-access-token`. | Once every 2 hours per asset/region chain. |
| Gold API free fallback | `https://api.gold-api.com` | No key. | `GET /price/XAU`, `GET /price/XAG`. | Once every 1 hour per asset/region chain. |
| Alanchand | `https://api.alanchand.com` | Optional key. Register with Alanchand and set `ALANCHAND_API_TOKEN`. | `GET /v1/markets/gold` with bearer token. | Once every 2 hours per asset/region chain. |
| Metals.dev | `https://api.metals.dev/v1` | Required. Register at `https://metals.dev`; set `METALS_DEV_API_KEY`. | `GET /latest?currency=USD&unit=toz&api_key=...`; reads `metals.gold` and `metals.silver`. | Once every 2 hours per asset/region chain. |
| ExchangeRate-API | `https://v6.exchangerate-api.com/v6` | Required. Register at `https://www.exchangerate-api.com`; set `EXCHANGERATE_API_KEY`. | `GET /{EXCHANGERATE_API_KEY}/latest/USD`; reads `conversion_rates.USD`. | Once every 2 hours per asset/region chain. |
| TGJU | `https://api.tgju.org/v1` | No key in current registry. | `GET /market/indicator/summary-table-data/global-price`, `/silver`, and `/currency`. | Once every 1 hour per asset/region chain. |
| Tetherland | `https://api.tetherland.com` | No key in current registry. | `GET /currencies`; reads `USDT`, `BTC`, `GOLD`, and `SILVER` prices. | Normal cache cadence, about every 20 seconds when requested. |
| Bonbast | `https://www.bonbast.com` | No key. Uses browser-like headers. | `GET /json`; reads USD, gold, and silver fallback fields. | Once every 1 hour per asset/region chain. |
| CoinGecko | `https://api.coingecko.com/api/v3` | No key for free public endpoint. Paid plans can add their own gateway later. | `GET /simple/price?ids=bitcoin,tether&vs_currencies=usd` split by asset in registry. | Once every 1 hour per asset/region chain. On `429`, worker retries then falls through to CoinCap. |
| CoinCap | `https://api.coincap.io/v2` | No key in current registry. | `GET /assets/bitcoin`, `GET /assets/tether`; reads `data.priceUsd`. | Once every 1 hour per asset/region chain. |
| Frankfurter | `https://api.frankfurter.app` | No key. | `GET /latest?from=USD&to=EUR`; used only as a stable USD sanity fallback. | Once every 2 hours per asset/region chain. |

## Rate limiting and fallback behavior

The worker stores the last successful provider value in Redis or the file cache. Providers with `min_interval_seconds` reuse that cached value until the interval expires. This prevents free-tier APIs from being called every dashboard refresh.

Fallback order is controlled by provider `priority`. For crypto USD pricing, CoinGecko is first and CoinCap is second, so rate-limit responses or upstream failures fall through to CoinCap automatically. For Iranian prices, Nobitex public order book is primary for USDT and BTC, followed by Tetherland or domestic market fallbacks.
