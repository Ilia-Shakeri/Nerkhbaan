# Pricing API Sources

Nerkhban backend aggregates market prices from two external sources:

1. **International USD source:** Gold-API (`https://api.gold-api.com`)
   - Endpoints used:
     - `GET /price/XAU` (Gold spot price in USD)
     - `GET /price/XAG` (Silver spot price in USD)

2. **Persian Toman source:** Alanchand API (`https://api.alanchand.com`)
   - Endpoint used:
     - `GET /?type=gold` with `Authorization: Bearer <token>`
   - Backend attempts to extract both gold and silver Toman quotes from the response payload.

## Fallback strategy

If Alanchand is unavailable or the token is not configured, backend falls back to:
- USD prices from Gold-API +
- USD/IRR exchange rate from `https://open.er-api.com/v6/latest/USD`

Then it derives Toman as:

`Toman = (USD * IRR) / 10`

This keeps the UI live even when the Persian provider is temporarily unavailable.
