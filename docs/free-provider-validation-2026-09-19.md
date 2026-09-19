# Public pricing validation — 2.5.0

Checked from the Iranian production host on 2026-09-19. Successful keyless
access means no payment/authentication was needed for these probes, not a
commercial redistribution licence or an uptime guarantee.

## Accepted routes

| Provider | Route | Instruments | Contract |
| --- | --- | --- | --- |
| Bitpin | `https://api.bitpin.org/v4/mkt/prices/` | BTC/Toman, USDT/Toman | HTTP 200; exact `code`; `order_book_info.price` and `time`, not synthetic `price_info`. 20-second budget; 1 MiB bound. |
| Wallgold | `https://api.wallgold.ir/api/v1/markets` | 18K gold, 925 silver | HTTP 200; exact `GLD_18C_750TMN` / `SLV_925TMN`, active buy/sell, base asset and TMN quote; `marketCap.lastPrice`. 60-second budget. |
| Wallex | `https://api.wallex.ir/v1/markets` | BTC/Toman, USDT/Toman | HTTP 200; existing market parser; enabled by default. |
| Nobitex | `https://apiv2.nobitex.ir/market/stats` and `/v3/orderbook/all` | BTC/Toman, USDT/Toman | HTTP 200; original host failed DNS. Stats and book levels are Rial, divided by 10. UDF history already uses Toman, not divided again. |
| Tetherland | `https://api.tetherland.com/currencies` | USDT/Toman | HTTP 200; existing provider retained. BTC absent, remains disabled. |

Wallgold `createdAt` is market creation, not quote time. Its price payload has
no observation timestamp: receipt time is explicitly labelled and live TTL
limited to 60 seconds. This is not proof of exchange-level freshness. It is a
single venue quote, not independent consensus. Wallgold and Wallex share a
source family and cannot independently corroborate each other.

## Separate gold quotes

18K and 24K are separate instruments. No karat multiplication or ounce/FX
reconstruction is allowed for either. Rial-to-Toman unit normalization is not
a karat calculation. Old calculated/ambiguous gold stays stored for audit but
is excluded from current snapshots, charts and change baselines.

No healthy keyless direct Iranian 24K quote was verified. It remains unavailable
without a suitable configured source. The typed Telegram pipeline remains for
future onboarding; no new channel is connected or certified by this release.

## Rejected / pending candidates

| Candidate | Result |
| --- | --- |
| PersianToolbox gold | HTTP 200 but no karat in `gold.pricePerGram`. Not evidence of direct 24K. Hard disabled; BTC retained. |
| TGJU feeds/API | Connection/read timeouts. |
| Baha24, PriceToDay, XAUS | Timed out from production. |
| GhimatRooz `/api/gold` | `api_key_required`, despite older keyless marketing. |
| TALA `/v1/rates` | HTTP 401; existing keyed integration retained. |
| Servix | Free signup/key required, 50 requests/day, explicit `GOLD_18_RLS` and `GOLD_24_RLS`. Probe timed out. No account created. |
| BRSAPI legacy free URL | Unexpected binary, not JSON. Rejected, never executed. |
| Goldprice.dev carat | Calculated from spot, not direct local gold. |
| Alanchand | Key/trial required; permanent keyless access not established. |
| Bitpin PAXG | Tokenized gold, not physical Iranian gold. Not mapped to gold karats. |

Primary references: [Bitpin](https://docs.bitpin.ir/v1/),
[Wallgold official API](https://developers.wallgold.ir/),
[Wallgold markets](https://wallgold.ir/), [Nobitex](https://apidocs.nobitex.ir/),
[Wallex](https://api-docs.wallex.ir/),
[Servix symbols](https://servix.cc/supported-assets),
[Servix free plan](https://servix.cc/free-api),
[carat methodology](https://goldprice.dev/docs/carat).

## Repeatable read-only check

From `apps/api` with the backend environment:

```sh
python scripts/probe_public_pricing.py
```

It downloads bounded public payloads, uses production parsers, and prints safe
provider IDs, values, times and errors. No keys printed, no prices persisted.
Any failed route causes nonzero exit. Retest after changing host, DNS or API.

## Deployment decision

The operator explicitly authorized a limited release with a backup and health
checks while formal provider-rights, restore and launch evidence stays pending.
The normal gated deploy script is unchanged; no evidence file is fabricated.
