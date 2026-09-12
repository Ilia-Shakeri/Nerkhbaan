# Pricing Sources and Price Semantics

How a number gets from a third-party API to `/api/prices`, and what it means
when it arrives. Read this before adding a provider or trusting a value.

- Provider onboarding gate — [`../../docs/pricing-operations-runbook.md`](../../docs/pricing-operations-runbook.md)
- API shapes — [`../../API_DOCUMENTATION.md`](../../API_DOCUMENTATION.md)

---

## 1. Instruments, not assets

The unit of pricing is an **instrument**: one asset, one currency, one weight
unit, one purity, one market. "Gold" is not an instrument. These are:

| Instrument | Base | Quote | Unit | Purity | Market | Derived fallback |
| --- | --- | --- | --- | --- | --- | --- |
| `XAU_USD_OZ` | XAU | USD | troy ounce | 0.9999 | global spot | no |
| `XAG_USD_OZ` | XAG | USD | troy ounce | 0.9999 | global spot | no |
| `GOLD_18K_TOMAN_GRAM` | XAU 18K | TOMAN | gram | 0.750 | Iran physical | yes |
| `GOLD_24K_TOMAN_GRAM` | XAU 24K | TOMAN | gram | 0.9999 | Iran physical | yes |
| `SILVER_999_TOMAN_GRAM` | XAG | TOMAN | gram | 0.999 | Iran physical | yes |
| `SILVER_925_TOMAN_GRAM` | XAG | TOMAN | gram | 0.925 | Iran physical | yes |
| `USD_TOMAN` | USD | TOMAN | unit | — | Iran exchange | yes |
| `USDT_TOMAN` | USDT | TOMAN | unit | — | Iran exchange | no |
| `USDT_USD` | USDT | USD | unit | — | global exchange | no |
| `BTC_TOMAN` | BTC | TOMAN | unit | — | Iran exchange | yes |
| `BTC_USD` | BTC | USD | unit | — | global exchange | no |

Definitions live in `app/pricing/instruments.py`. Each carries its own refresh
interval, staleness and expiry windows, sanity bounds, anomaly thresholds and
maximum acceptable spread — all overridable per instrument via
`PRICING_TTL_<ID>`, `PRICING_STALE_AFTER_<ID>`, `PRICING_EXPIRE_AFTER_<ID>`,
`PRICING_ANOMALY_THRESHOLD_<ID>`, `PRICING_MAX_ANOMALY_THRESHOLD_<ID>` and
`PRICING_MAX_SPREAD_BPS_<ID>`.

> The legacy `/api/prices` shape pairs `XAU_USD_OZ` with
> `GOLD_18K_TOMAN_GRAM` under one `gold` row. Those are a **troy ounce at
> 0.9999** and a **gram at 0.750** in two different markets. The row carries
> `unit_usd` and `unit_toman` so a client can label them honestly. Do not treat
> them as one asset in two currencies.

---

## 2. Provider roles

Providers are registered in `app/pricing/registry.py` against a single
instrument, with a role:

| Role | Used for |
| --- | --- |
| `PRIMARY` | First choice on a normal refresh |
| `FALLBACK` | Tried when no primary yields a usable quote |
| `VERIFIER` | Called to corroborate a suspicious candidate |
| `COMPARE` | Displayed for comparison; never canonical on its own |

Selection is not a fixed order. Candidates are ranked each cycle by cache
freshness, whether credentials are configured, circuit state, recent success
rate, trust score, remaining request budget and cost. External calls per refresh
are capped — two for high-importance instruments, one otherwise.

### Current coverage

```
GOLD_18K_TOMAN_GRAM    alanchand_gold18 (primary), tala_gold18_toman (verifier)
GOLD_24K_TOMAN_GRAM    tala_gold24_toman (primary), nerkh_io_gold24 (fallback)
XAU_USD_OZ             goldapi_xau (primary), gold_api_free_xau, metals_dev_gold
SILVER_999_TOMAN_GRAM  tala_silver999_toman (primary, needs key + symbol)
SILVER_925_TOMAN_GRAM  formula only
XAG_USD_OZ             goldapi_xag (primary), gold_api_free_xag, metals_dev_silver
USD_TOMAN              navasan_usd_toman (primary), servix_usd_toman,
                       persian_toolbox_usd_toman (reference, disabled)
USDT_TOMAN             nobitex_stats_usdt (primary), nobitex_orderbook_usdt,
                       tetherland_usdt, wallex_usdt_toman, tala_usdt_toman, navasan_usdt
USDT_USD               coinbase_usdt_usd (primary), coingecko_usdt,
                       servix_usdt_usd, coincap_usdt
BTC_TOMAN              nobitex_stats_btc (primary), nobitex_orderbook_btc,
                       tetherland_btc, wallex_btc_toman
BTC_USD                coinbase_btc_usd (primary), coingecko_btc,
                       persian_toolbox_btc, servix_btc_usd, coincap_btc
```

Several Iranian routes are **key-gated and disabled by default**. With no
optional keys configured, the Toman metal chains fall back to formula output.
`GET /api/prices/health` reports exactly which:

```jsonc
"instruments_without_direct_source": ["SILVER_999_TOMAN_GRAM", "..."]
```

Startup logs the same list. This is checked in CI — a test fails if any
instrument has neither a configured source nor a formula.

`persian_toolbox_btc` is a no-key Iranian fallback. It accepts only `live` or
`cached` payloads and verifies the published timestamp, upstream source list,
BTC symbol, and USD unit. The site's USD/IRR value is a technical reference,
not a promised free-market quote, so `persian_toolbox_usd_toman` stays disabled.

Servix has a permanent keyed free tier of 50 successful requests per day. Its
three routes default to disabled and together are capped at 48 requests per day.
Their history endpoints can backfill charts even when no live canonical quote
exists. Free-tier display requires visible Servix attribution.

---

## 3. What a refresh actually does

```
refresh_instrument(id)
 ├─ acquire distributed lock (renewed while held; a fixed TTL used to expire
 │  mid-refresh and let two workers duplicate the work)
 ├─ reuse a live, persisted cached quote if one exists
 ├─ otherwise rank providers, spend request budget, call up to N of them
 ├─ parse → validate unit, currency, purity, timestamp, sanity bounds
 ├─ assess against previous canonical + recent volatility
 │    └─ suspicious? → publish previous as `verifying`
 │                   → call independent verifiers (different family AND venue)
 │                   → confirm, reach median consensus, or keep previous
 ├─ no usable direct quote? → approved Telegram fallback → formula
 └─ persist, cache, publish
```

A quote must be **durably stored before it can become canonical**. A price that
only exists in Redis is reported as `unpersisted` and is not alert-eligible.

### Independence

A verifier only counts if its `source_family` **and** `venue` both differ from
the candidate's. Two endpoints of the same exchange do not corroborate each
other, and aggregators that resell the same upstream are marked
`venue: opaque_aggregator` so they cannot be double-counted.

---

## 4. Derived prices

When no direct source is available and the instrument allows it, the price is
computed. Derived values are marked `derived_fallback` and carry
`"theoretical_value": true`.

| Instrument | Formula |
| --- | --- |
| `USD_TOMAN` | `USDT_TOMAN / USDT_USD` |
| `GOLD_24K_TOMAN_GRAM` | `XAU_USD_OZ × fx × purity(24K)/purity(XAU) / 31.1034768` |
| `GOLD_18K_TOMAN_GRAM` | `GOLD_24K_TOMAN_GRAM × purity(18K)/purity(24K)`, or straight from `XAU_USD_OZ` |
| `SILVER_999_TOMAN_GRAM` | `XAG_USD_OZ × fx × purity(999)/purity(XAG) / 31.1034768` |
| `SILVER_925_TOMAN_GRAM` | `SILVER_999_TOMAN_GRAM × purity(925)/purity(999)` |
| `BTC_TOMAN` | `BTC_USD × fx` |

Purity ratios are read from the instrument definitions, not hardcoded — 18K from
24K is `0.750 / 0.9999`, not a flat `0.75`.

### The FX bridge matters

`fx` is the USD→Toman rate, chosen in this order:

1. **`USD_TOMAN`** — a real free-market rate. Preferred.
2. **`USDT_TOMAN / USDT_USD`** — a stand-in.

USDT trades at a persistent premium to free-market USD in Iran. The two bridges
disagree by percent, not basis points:

```
XAU 2400 USD, USD/TOMAN 58 000, USDT/TOMAN 60 000
  via USD_TOMAN   →  4 475 384 Toman/gram
  via USDT proxy  →  4 629 708 Toman/gram      (+3.4%)
```

Every derived quote records which bridge produced it:

```jsonc
"fx_bridge": "usdt_proxy",
"fx_bridge_is_proxy": true
```

`fx_bridge_is_proxy` is also true when `USD_TOMAN` was itself derived from
USDT — the premium is still in there, one level down. **Treat proxy-bridged
Toman metal prices as indicative.** Configure `NAVASAN_API_KEY` with an HTTPS
proxy, or `SERVIX_API_KEY`, to get a real rate.

Derived chains are depth-limited to 3, cycle-checked through provenance, and
refuse to run when `USDT_USD` sits outside `[USDT_USD_SAFE_MIN, USDT_USD_SAFE_MAX]`
— a depegged stablecoin must not silently reprice gold.

---

## 5. Freshness

Three windows per instrument, anchored on the **source** timestamp, not the
receive time (clock skew beyond 30 s in the future is rejected):

| Window | Meaning |
| --- | --- |
| `operational_ttl` | Reusable without a new call |
| `stale_after` | Displayable, visibly stale |
| `expire_after` | Not displayable as a price |

Beyond that the value reports `expired`, and it is never alert-eligible.

---

## 6. Anomaly handling

Each candidate is compared with the previous canonical value against a threshold
that adapts to recent volatility, the age of the previous value and the
provider's success rate, bounded by the instrument's configured maximum.

Crossing it does **not** publish the new price. Instead the instrument goes
`verifying`, independent verifiers are called, and the outcome is one of:

- **confirmed** — an independent source agrees within tolerance;
- **consensus** — median of an inlier cluster with quorum, ≥3 comparable quotes;
- **disagreed / insufficient** — previous value retained, anomaly recorded.

Every anomaly is persisted with its deviation, threshold, severity and decision,
and is reviewable at `/api/admin/pricing/anomalies`.

---

## 7. Egress control

Provider requests are constrained by:

- `PRICING_PROVIDER_ALLOWED_HOSTS` — an allowlist, extended automatically with
  the hostname of every configured base URL so a proxy is not silently blocked;
- HTTPS required whenever credentials are attached;
- no credentials in the URL path or query when a header will do; the request
  guard rejects URLs containing key-like query parameters;
- redirects disabled;
- response size capped and streamed with an early abort;
- per-provider minute/hour/day budgets with reserved quota for anomaly
  verification and fallback, so routine refreshes cannot exhaust the budget an
  incident needs;
- circuit breaker after consecutive failures, with a cooldown on HTTP 429 that
  honours `Retry-After`.

---

## 8. Adding a provider

1. Satisfy the onboarding gate in the operations runbook — documentation,
   fixtures, explicit semantics, redistribution rights, contacts.
2. Add a parser in `app/pricing/parsers/` and register it in
   `parsers/__init__.py`. It must return an explicit unit, currency, purity and
   source timestamp. A parser that guesses is a bug.
3. Register the provider in `app/pricing/registry.py` with its role, trust
   score, budget, semantics, `source_family`, `venue` and any
   `required_settings`.
4. Add the host to `PRICING_PROVIDER_ALLOWED_HOSTS` if it is not derived from a
   configured base URL.
5. Ship it disabled (`enabled_default=False`) and prove it with the canary:

   ```bash
   cd apps/api && python scripts/provider_canary.py <provider_id>
   ```

6. Enable via `PRICING_PROVIDER_<ID>_ENABLED=true`.

CI enforces steps 3–4: tests fail if a provider's host is not allowlisted or its
parser is not registered.

---

## 9. Failure behaviour

- A chain outage does not blank the card. The last valid value is shown with an
  honest status.
- Iranian and international legs fail independently.
- Redis unavailable suspends refreshes — the distributed locks, budgets and
  fan-out all live there — and the API reports `degraded`. Cached and stored
  values continue to serve.
- Chart error text is returned in both languages:
  - `fa` — `داده بازار در دسترس نیست`
  - `en` — `Unable to fetch market data`
