# Pricing API Sources

Nerkhbaan backend uses per-asset provider chains with regional separation.

- Iran chains populate `price_toman`.
- International chains populate `price_usd`.
- Each chain uses priority fallback.
- If all providers in a chain fail, backend serves the chain's last known value from Redis or the file cache.
- If cache is missing too, the value is returned as `null` and the frontend renders `--`.

## Assets and chains

- `gold` Iran: TGJU -> Alanchand -> Bonbast -> Tetherland
- `gold` international: GoldAPI -> Gold API free fallback -> Metals.dev
- `silver` Iran: TGJU -> Tetherland -> Bonbast
- `silver` international: GoldAPI -> Gold API free fallback -> Metals.dev
- `usdt` Iran: Nobitex -> Tetherland -> Bonbast -> TGJU
- `usdt` international: CoinGecko -> CoinCap -> ExchangeRate-API -> Frankfurter
- `btc` Iran: Nobitex -> Tetherland
- `btc` international: CoinGecko -> CoinCap

## Error behavior

- Price cards remain visible during provider outages.
- Chain-level failures mark the asset as `cached` or `unavailable` without blocking the other region.
- Chart error text is returned in both languages:
  - `fa`: `داده بازار در دسترس نیست`
  - `en`: `Unable to fetch market data`

## Registry metadata

`GET /api/providers` exposes catalog metadata from `apps/api/app/services/api_registry.py`.

`GET /api/prices/health` exposes:

- per-asset regional status (`live`, `cached`, `unavailable`)
- provider source used for each chain
- cache age metadata and startup environment key checks
- per-provider rows with `provider_name`, `status`, `last_success_time`, and `has_api_key`
