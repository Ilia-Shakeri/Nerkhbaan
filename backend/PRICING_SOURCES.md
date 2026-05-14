# Pricing API Sources

Nerkhban backend now uses per-asset provider chains with regional separation:

- **Iran chain** (`price_toman`) and **international chain** (`price_usd`) run independently.
- Each chain uses priority fallback (primary -> backup).
- If both providers in a chain fail, backend serves the chain's **last known value** from `backend/price_cache.json`.
- If cache is missing too, value is returned as `null` and frontend renders `--`.

## Assets and chains

- `gold` (Iran: TGJU -> Bonbast, International: Metals.dev -> GoldAPI)
- `silver` (Iran: TGJU -> Tetherland, International: Metals.dev -> GoldAPI)
- `usdt` (Iran: Nobitex -> Tetherland, International: CoinGecko -> CoinCap)
- `btc` (Iran: Nobitex -> Tetherland, International: CoinGecko -> CoinCap)

## Error behavior

- Price cards remain visible even during provider outages.
- Chain-level failures mark the asset as `cached` or `unavailable` without blocking the other region.
- Chart error text is returned in both languages:
  - `fa`: `امکان دریافت اطلاعات وجود ندارد`
  - `en`: `Unable to fetch data`

## Full provider registry metadata

`GET /api/providers` exposes catalog metadata from:

- `backend/app/services/api_registry.py`

`GET /api/prices/health` exposes chain health details:

- per-asset regional status (`live`, `cached`, `unavailable`)
- provider source used for each chain
- cache age metadata and startup env-key checks
