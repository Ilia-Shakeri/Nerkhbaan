# Pricing API Providers — Reference

Companion to `.env` / `.env.example`. Where those two files say *which variable
holds a key*, this document says *what the provider is, whether it costs
money, what it covers, and what else exists*. Read `apps/api/PRICING_SOURCES.md`
first for the instrument model; this file is the provider-level detail behind
`apps/api/app/pricing/registry.py` and `apps/api/app/config.py`, plus market
research beyond what is currently wired in.

Assessed 2026-08-24. Provider terms, pricing and sanctions status change —
re-verify anything load-bearing before relying on it in production.

---

## 0. Urgent — two of the four crypto sources currently in production are OFAC-sanctioned entities

**On 2026-06-02, OFAC added Nobitex, Wallex, Bitpin and Ramzinex to the SDN
list** — sanctions evasion, terrorist financing, propping up the Iranian
regime. Nobitex alone processed over 50% of Iranian digital-asset inflows;
Wallex ~12%. Four Nobitex executives were individually designated. Secondary
sanctions apply: non-US persons and foreign financial institutions that
transact with these entities risk being cut off from the US financial system,
and the 50%-ownership rule auto-blocks any entity majority-owned by a
designated person.

**Nerkhbaan currently sources `USDT_TOMAN` and `BTC_TOMAN` primarily from
Nobitex, with Wallex as a fallback:**

| Registry entry | Instrument | Role |
| --- | --- | --- |
| `nobitex_stats_usdt` | `USDT_TOMAN` | **PRIMARY** |
| `nobitex_orderbook_usdt` | `USDT_TOMAN` | VERIFIER |
| `nobitex_stats_btc` | `BTC_TOMAN` | **PRIMARY** |
| `nobitex_orderbook_btc` | `BTC_TOMAN` | VERIFIER |
| `wallex_usdt_toman` | `USDT_TOMAN` | FALLBACK |
| `wallex_btc_toman` | `BTC_TOMAN` | FALLBACK |

OFAC's public FAQs (updated 2026-06-02) describe the transaction-based
prohibitions and secondary-sanctions exposure but do not explicitly address
whether unauthenticated, read-only HTTP requests to a sanctioned exchange's
public market-data endpoint constitute a prohibited "dealing." That is a real
gap, not a clean answer either way — **this is not legal advice; get counsel
before deciding whether to keep, restrict, or drop these two integrations**,
especially before commercial launch or if the platform has any US nexus.

Practically, whatever the legal conclusion: `apps/api/app/pricing/registry.py`
currently has no non-sanctioned PRIMARY for `USDT_TOMAN`/`BTC_TOMAN` if Nobitex
and Wallex are both pulled — `tetherland_usdt`/`tetherland_btc` (FALLBACK,
role 3) is the only remaining registered path and is not sanctioned as of this
writing. Section 4.4 below lists further non-sanctioned candidates.

Sources: [Chainalysis](https://www.chainalysis.com/blog/ofac-sanctions-iranian-crypto-exchanges-june-2026/), [Elliptic](https://www.elliptic.co/insights/ofac-sanctions-nobitex-and-three-other-iranian-cryptoasset-exchanges/), [OFAC FAQs added 2026-06-02](https://ofac.treasury.gov/faqs/added/2026-06-02), [MEXC News](https://www.mexc.com/news/1126101)

---

## 1. How this maps to `.env`

Every provider below corresponds to a `_provider(...)` entry in
`apps/api/app/pricing/registry.py`. Its base URL and credentials come from
`apps/api/app/config.py` settings, set via `.env` (see `.env.example`). Two
independent things gate a provider:

1. **`configured()`** — does it have the settings it needs (key, symbol,
   proxy base) per `ProviderDefinition.configured()`.
2. **`enabled`** — `PRICING_PROVIDER_<ID>_ENABLED` (default varies per
   provider; see `enabled_default` column below).

A provider that is `enabled` but not `configured` is skipped silently at
runtime — it shows up as absent from `GET /api/prices/health`, not as an
error. `PRICING_PROVIDER_ALLOWED_HOSTS` must also list the provider's host
(the app auto-adds hosts derived from any configured `*_api_base_url`
setting, but a hardcoded or history URL still needs manual allowlisting).

---

## 2. Currently integrated providers

"Free" below means the endpoint itself needs no paid subscription. Several
"free" providers still require a registration/API key (free tier); those are
marked **freemium**.

### 2.1 `XAU_USD_OZ` / `XAG_USD_OZ` — international gold & silver spot

| Provider | Role | Cost | Auth (env var) | Enabled by default | Notes |
| --- | --- | --- | --- | --- | --- |
| GoldAPI.io (`goldapi_xau`/`goldapi_xag`) | PRIMARY | **Freemium** | `GOLDAPI_API_KEY` (header) | Yes, but skipped if no key | Free tier historically ~100 req/month; paid plans scale up. Verify current terms at goldapi.io before relying on it. |
| Gold-API.com (`gold_api_free_xau`/`gold_api_free_xag`) | VERIFIER | **Free, no key** | none | Yes | `gold-api.com` — genuinely free, unauthenticated JSON. Also covers crypto. Good independent verifier already in use. |
| Metals.dev (`metals_dev_gold`/`metals_dev_silver`) | FALLBACK | **Freemium** | `METALS_DEV_API_KEY` (query) | Yes, but skipped if no key | Confirmed free tier: **100 requests/month**, 60s update cadence. Paid from $1.79/mo (2,000 req) up to $99.99/mo (500,000 req). |

### 2.2 `GOLD_18K_TOMAN_GRAM` / `GOLD_24K_TOMAN_GRAM` — Iran physical gold, Toman

| Provider | Role | Cost | Auth (env var) | Enabled by default | Notes |
| --- | --- | --- | --- | --- | --- |
| Alanchand (`alanchand_gold18`) | PRIMARY for 18K | **Freemium (very limited)** | `ALANCHAND_API_TOKEN` (Bearer) | Yes, but skipped if no key | Confirmed: free tier is **1 request/hour per user** via a Telegram-bot-issued test token; unlimited access requires contacting Alanchand directly (negotiated/paid). Registry throttles it to one call per 2 hours already, consistent with this. |
| TALA.ir (`tala_gold24_toman` primary, `tala_gold18_toman` verifier) | PRIMARY / VERIFIER | **Paid** (terms not published) | `TALA_API_KEY` (header) + per-symbol key setting | **Disabled by default** | api.tala.ir did not disclose pricing publicly at time of writing — contact them directly. Registered but off; needs a key and an explicit `PRICING_PROVIDER_TALA_*_ENABLED=true`. |
| Nerkh.io (`nerkh_io_gold24`) | FALLBACK | **Paid** | `NERKH_IO_BEARER_TOKEN` or `NERKH_IO_API_KEY` | **Disabled by default** | Commercial Iranian rates API; distinct from the legacy, un-onboarded `nerkh-api.ir` named in the operator gate list. |

`SILVER_999_TOMAN_GRAM` has one key-gated provider (`tala_silver999_toman`,
disabled by default, needs `TALA_SILVER999_TOMAN_KEY`).
**`SILVER_925_TOMAN_GRAM` has no registered provider at all** — formula-only,
derived from `SILVER_999_TOMAN_GRAM` by purity ratio. This is the single
clearest gap in the current source set (see 4.3).

### 2.3 `USD_TOMAN` — Iran free-market USD rate

| Provider | Role | Cost | Auth (env var) | Enabled by default | Notes |
| --- | --- | --- | --- | --- | --- |
| Navasan (`navasan_usd_toman`) | PRIMARY | **Paid** | `NAVASAN_API_KEY` (query) + `NAVASAN_HTTPS_PROXY_BASE_URL` | **Disabled by default** | Navasan's direct API (`api.navasan.tech`) is plain HTTP; the app *requires* an HTTPS proxy in front of it (`NAVASAN_ALLOW_INSECURE_HTTP` is rejected at startup on purpose) — you need both a paid key and your own HTTPS relay. |
| Servix (`servix_usd_toman`) | FALLBACK | **Free tier: 50 successful requests/day** | `SERVIX_API_KEY` (header) | **Disabled by default** | Permanent free tier, no payment method; registration and a key are required. |
| PersianToolbox (`persian_toolbox_usd_toman`) | FALLBACK | Free, no key; fair-use quota is not guaranteed | none | **Disabled by default** | Technical USD/IRR reference converted from rial to Toman. The provider explicitly does not promise a free-market or tradable rate. |

**This is the biggest real gap in the platform.** Without one of the above,
every Toman metal price is bridged through `USDT_TOMAN / USDT_USD` instead of
a real USD rate, and runs ~3.4% high (see `PRICING_SOURCES.md` §4). See 4.2
for free/near-free candidates to close this.

### 2.4 `USDT_TOMAN` / `BTC_TOMAN` — Iran crypto/Toman

| Provider | Role | Cost | Auth | Enabled | Notes |
| --- | --- | --- | --- | --- | --- |
| Nobitex (`nobitex_stats_usdt`, `nobitex_orderbook_usdt`, `nobitex_stats_btc`, `nobitex_orderbook_btc`) | **PRIMARY** + VERIFIER | Free, no key | none | Yes | **OFAC SDN-listed 2026-06-02 — see §0.** |
| Wallex (`wallex_usdt_toman`, `wallex_btc_toman`) | FALLBACK | Free, no key | none | **Disabled by default** | **OFAC SDN-listed 2026-06-02 — see §0.** |
| Tetherland (`tetherland_usdt`, `tetherland_btc`) | FALLBACK | Free, no key | none | USDT yes; BTC disabled | Not sanctioned as of this writing. BTC was quarantined after its live payload lacked the registered symbol. |
| TALA (`tala_usdt_toman`) | FALLBACK | Paid | `TALA_API_KEY` | **Disabled by default** | |
| Navasan (`navasan_usdt`) | FALLBACK | Paid | `NAVASAN_API_KEY` + HTTPS proxy | **Disabled by default** | |

### 2.5 `USDT_USD` / `BTC_USD` — global crypto/USD

| Provider | Role | Cost | Auth | Enabled | Notes |
| --- | --- | --- | --- | --- | --- |
| Coinbase Exchange (`coinbase_usdt_usd`, `coinbase_btc_usd`) | PRIMARY | Free, no key | none | Yes | Public ticker endpoint, no auth. |
| CoinGecko (`coingecko_usdt`, `coingecko_btc`) | FALLBACK | Free, no key (rate-limited) | none | Yes | Confirmed public-plan limit: **5–15 calls/minute**, no monthly cap published, throttled dynamically by CoinGecko's own load. A free Demo API key raises this to a stable 30/min — worth adding `x-cg-demo-api-key` support if this route gets hit often. |
| PersianToolbox (`persian_toolbox_btc`) | FALLBACK | Free, no key; fair-use quota is not guaranteed | none | Yes | Iranian wrapper for BTC/USD reference data. Five-minute request floor; strict source timestamp, freshness, source list, symbol, and unit checks. No history endpoint. |
| CoinCap (`coincap_usdt`, `coincap_btc`) | FALLBACK, lowest priority | **Likely broken** | none configured | **Disabled by default** | CoinCap has moved to a "3.0" prepaid-credit model (`pro.coincap.io`, pay with USDC) — the free, keyless `api.coincap.io/v2` endpoint this integration targets appears to be sunset or degraded. Treat as dead until re-verified; do not re-enable without checking `pro.coincap.io` first. |
| Servix (`servix_btc_usd`, `servix_usdt_usd`) | FALLBACK + history | Free tier: 50 successful requests/day | `SERVIX_API_KEY` | **Disabled by default** | BTC/USD and USDT/USD history; registration, attribution, and a key are required. Three routes are capped to 48 calls/day combined. |

---

## 3. Built but not wired — parser exists, no live route

`apps/api/app/pricing/parsers/__init__.py` registers more parsers than
`registry.py` has provider entries for. The parsing/validation work is
already done for these; they just need a `_provider(...)` registration (and,
for Ticaro/Arzbin, a base-URL setting in `config.py` that doesn't exist yet):

| Parser | Would cover | What's missing |
| --- | --- | --- |
| `ticaro_usdt_toman_v1`, `ticaro_btc_toman_v1`, `ticaro_gold18_toman_v1` | `USDT_TOMAN`, `BTC_TOMAN`, `GOLD_18K_TOMAN_GRAM` | No `ticaro_api_base_url` setting in `config.py`, no registry entry. `ticaro.ir` is already in the allowed-hosts list in `.env.example`, suggesting this was mid-integration. |
| `arzbin_usd_v1` | `USD_TOMAN` | No `arzbin_api_base_url` setting, no registry entry. `hub.arzbin.com` is likewise pre-allowlisted. **Worth finishing first** — it directly targets the platform's biggest gap. |
| `navasan_btc_v1`, `navasan_gold18_v1`, `navasan_xau_v1` | `BTC_TOMAN`, `GOLD_18K_TOMAN_GRAM`, `XAU_USD_OZ` | Registry only wires Navasan's `usd` and `usdt` items. Same `NAVASAN_API_KEY` would cover these — essentially free additional coverage once Navasan is configured for anything. |
| `nerkh_io_usd_v1`, `nerkh_io_usdt_v1`, `nerkh_io_btc_v1`, `nerkh_io_xau_v1`, `nerkh_io_xag_v1` | `USD_TOMAN`, `USDT_TOMAN`, `BTC_TOMAN`, `XAU_USD_OZ`, `XAG_USD_OZ` | Registry only wires Nerkh.io's `gold24` symbol. Same token would unlock these. |
| `tala_xau_usd_v1`, `tala_xag_usd_v1` | `XAU_USD_OZ`, `XAG_USD_OZ` | Registry only wires Tala's Toman metals. Same `TALA_API_KEY` would add international-ounce verifiers. |
| `servix_gold18_rls_v1` | `GOLD_18K_TOMAN_GRAM` | Parser exists (`servix_gold18_rls_v1`), no registry entry alongside the three Servix providers that are registered. |

Net effect: **if you ever pay for one of TALA, Navasan, or Nerkh.io, you get
several instruments' worth of coverage almost for free** — the marginal
engineering cost is a `registry.py` entry, not a new parser.

---

## 4. Free/freemium APIs not yet integrated

Found by searching specifically for no-key or generous-free-tier options,
since that's the operating mode right now. Confidence varies — marked per
entry. None of these have parsers in the codebase; each needs one written
against `apps/api/app/pricing/parsers/base.py`'s `ExplicitParser` contract
before it can be wired into `registry.py`.

### 4.1 Global gold/silver spot (`XAU_USD_OZ` / `XAG_USD_OZ`) — supplements to what's already used

| Service | Cost | Auth | Coverage | Notes |
| --- | --- | --- | --- | --- |
| [xaus.com](https://xaus.com/api/) | **Free, no key, "no rate limits for reasonable use"** | none | XAU spot/history/intraday, XAG in the spot response, BTC comparison | Best free find of this pass — genuinely keyless, explicitly says cache 30s+ and contact them past 10k req/day. Worth adding as a second free `VERIFIER` alongside `gold_api_free_*`. |
| [goldprice.dev](https://goldprice.dev/) | **Free tier: 1,000 calls/month, 30/min, with a no-cost API key** (or 100 req/IP/hour keyless) | Optional key | XAU, XAG, copper; 31 quote currencies; carat conversion | More generous limits than Metals.dev's free tier if a key is registered. |
| [MetalpriceAPI](https://metalpriceapi.com/) | Free: **100 req/month**, daily-only refresh | Key required | Gold, silver, FX | Same ballpark as Metals.dev's free tier — not an upgrade, just an alternative verifier if you want a third independent family. |
| Metals-API.com | **No free tier** — paid from $19.99/mo | Key | Gold, silver, FX | Listed for completeness; not usable free. |

### 4.2 `USD_TOMAN` free-market rate — closing the biggest gap

This is the instrument with the most upside from a free source, and the
weakest options. All of these scrape or mirror **bonbast.com**, the reference
site for Iran's free-market rate — none are an official first-party API, so
treat all as unstable/best-effort, not production-primary without a fallback:

| Service | Cost | Auth | Notes | Confidence |
| --- | --- | --- | --- | --- |
| [Bonbast-API mirror](https://github.com/itsamirhn/Bonbast-API) — hosted at `bonbast.amirhn.com` | **Free, no key** | none | Third-party FastAPI wrapper around bonbast.com, source on GitHub, self-hostable. Maintainer's own words: "might be slow or occasionally blocked," "could be taken down at any time." | Verified live-hosted instance exists; **not vetted for uptime/accuracy** — treat as a stopgap FALLBACK, never PRIMARY. |
| TGJU Sana rate service (`tgju.org/sanarate-service`) | **Free, no key** | none | This is Iran's official currency-oversight-system ("Sana") rate, not the free-market rate — a *different*, semi-official number. Useful as a distinct reference/comparison point, not a substitute for a true free-market feed. | Found via community API list; endpoint shape not independently confirmed — verify before wiring. |
| [margani/pricedb](https://github.com/margani/pricedb) (`prices.readme.io`) | Free, no key | none | Auto-updated via GitHub Actions; maintainer states "meant for personal use only" and "subject to change at any time." | Low confidence for production use. |
| [HosseinOdd/Navasan-API](https://github.com/HosseinOdd/Navasan-API) | Free, but **not a hosted API** | n/a | Self-hosted Selenium scraper of navasan.net producing static JSON on a 10-minute GitHub Actions cadence — you'd run this yourself, not call a live endpoint. Scraping ToS risk noted by the maintainer. | Not directly usable as a `ProviderDefinition` without standing up your own scraper infra. |
| BRSAPI (`brsapi.ir/free-api-gold-currency-webservice/`) | Advertised as **free, no registration** | none per their marketing copy | Public sample endpoint was reachable from production. | The tested response was dated 1404/02/28 and is fixture/sample data, not a live feed. Do not integrate it as a live route. |
| `api.zipodo.ir/usdt/` | Free, no key | none | Single-purpose USDT/Toman JSON endpoint. Narrow scope, unknown maintainer/reliability. | Low confidence, small blast radius if it breaks (one instrument only). |

**Recommendation for this instrument specifically:** none of the free options
above is trustworthy enough to be a sole `PRIMARY`. The pragmatic path is
either (a) configure Navasan or a free-tier Servix key — both already fully
wired, just disabled — or (b) register 2–3 of the free scrapers above as low-priority
`VERIFIER`/`FALLBACK` roles so the anomaly/consensus machinery in
`canonical.py` can cross-check them against each other rather than trusting
any single one.

### 4.3 `SILVER_925_TOMAN_GRAM` — currently zero providers

No dedicated silver-925 source was found anywhere, free or paid — this
appears to be a genuinely thin market internationally, not just in this
codebase. The realistic options remain what `PROJECT_STATUS.md` already
says: keep it formula-derived from `SILVER_999_TOMAN_GRAM`, or pursue a
direct commercial relationship with an Iranian bullion dealer.

### 4.4 Non-sanctioned crypto sources for `USDT_TOMAN` / `BTC_TOMAN`

Given §0, these are worth evaluating as additions or Nobitex/Wallex
replacements. None are currently integrated:

| Exchange | Cost | Auth | Notes |
| --- | --- | --- | --- |
| Kraken | Free, no key | none | Public `Ticker` REST endpoint; no Toman pairs, but a clean independent USD/USDT/BTC source for the `USDT_USD`/`BTC_USD` side. |
| Binance | Free, no key | none | Public ticker endpoints; large liquidity for BTC/USDT globally. No Toman pairs. Some jurisdictions restrict Binance access — check applicability before depending on it from your hosting region. |
| Bitfinex, KuCoin, OKX | Free, no key | none | Same story as Kraken/Binance — global USD/USDT pairs, no direct Toman coverage, useful only for the international legs (`USDT_USD`, `BTC_USD`), not as Nobitex/Wallex replacements for the Toman legs. |

**None of the above have a Toman pair** — that's the actual problem. Iran's
liquid Toman crypto exchanges are now overwhelmingly the sanctioned four
(Nobitex, Wallex, Bitpin, Ramzinex) plus Tetherland (already integrated,
clean) and Ramzinex (sanctioned, do not add). Smaller/newer Iranian exchanges
exist but none surfaced with a documented public price API in this pass —
this is worth a dedicated follow-up search focused specifically on exchange
compliance status rather than API availability.

---

## 5. Paid/commercial options — summary

For completeness, since not everything needs to stay free forever:

| Provider | Covers | Entry price | Status in codebase |
| --- | --- | --- | --- |
| GoldAPI.io | XAU/XAG USD | Freemium, paid tiers undisclosed here — check goldapi.io | Integrated, PRIMARY |
| goldprice.dev | XAU/XAG/copper, multi-currency | $10/mo (Physical) → $80/mo (Realtime Pro + WebSocket) | Not integrated |
| Metals-API.com | XAU/XAG/FX | $19.99/mo (2,500 calls) → $999/mo | Not integrated |
| MetalpriceAPI | XAU/XAG/FX | $5/mo (billed yearly, 1,000 calls) → $132/mo | Not integrated |
| Metals.dev | XAU/XAG | $1.79/mo (2,000 calls) → $99.99/mo | Integrated, FALLBACK |
| TALA.ir | Gold/silver/USD/USDT Toman | Undisclosed, contact vendor | Integrated, disabled |
| Navasan.tech | USD/USDT/BTC Toman, gold | Undisclosed, contact vendor | Integrated, disabled |
| Nerkh.io | Gold/USD/USDT/BTC Toman | Undisclosed, contact vendor | Integrated, disabled (gold24 only) |
| Servix.cc | USD/BTC and market history | Permanent free tier: 50 successful requests/day; paid tiers add quota | Integrated, disabled until keyed |
| PersianToolbox | BTC/USD and technical USD/IRR reference | Free, no key; fair use and caching required | Integrated; BTC enabled, USD/IRR disabled |
| Alanchand | Gold 18K Toman | Free (1 req/hr) → negotiated unlimited | Integrated, PRIMARY |

None of the three "undisclosed" vendors published pricing in this pass —
their sign-up flows are Telegram-bot or contact-form gated, typical for
Iranian B2B data vendors. Getting real figures requires reaching out
directly.

---

## 6. Recommendations, in order

1. **Resolve the Nobitex/Wallex question (§0) before anything else.** This is
   a legal/business decision, not an engineering one — get counsel, then
   either accept the risk explicitly, restrict these two to non-production
   use, or migrate `USDT_TOMAN`/`BTC_TOMAN` primary sourcing to Tetherland
   plus new verifiers.
2. **Finish the Arzbin parser wiring (§3).** It's the cheapest path to a
   second `USD_TOMAN` source — the parser exists, only the base-URL setting
   and registry entry are missing — and `USD_TOMAN` is the platform's
   documented #1 pricing-accuracy gap.
3. **Add `xaus.com` as a second free `XAU_USD_OZ`/`XAG_USD_OZ` verifier** —
   confirmed genuinely free and keyless, strengthens independence (currently
   `gold_api_free_*` is the only zero-cost verifier on that chain).
4. **Register 2–3 of the §4.2 free USD_TOMAN scrapers as low-priority
   FALLBACK/VERIFIER**, never PRIMARY, so `canonical.py`'s consensus logic
   can use them defensively rather than trusting any single scraper.
5. **Do not use the BRSAPI public sample as live data.** Reconsider BRSAPI only
   if the vendor supplies a documented live endpoint, timestamp contract, and
   fair-use limit.
6. **Drop or re-verify CoinCap** — the currently-registered free integration
   likely targets a sunset endpoint; either confirm `api.coincap.io/v2`
   still works keyless or remove the dead entries.

---

<div dir="rtl" lang="fa">

# ترجمه فارسی

همراه فایل `.env` / `.env.example`. اگر آن دو فایل می‌گویند *کدام متغیر، کدام کلید را نگه می‌دارد*، این سند می‌گوید *هر Provider چیست، هزینه دارد یا نه، چه چیزی را پوشش می‌دهد، و چه گزینه‌های دیگری در بازار وجود دارد*. برای مدل instrumentها ابتدا `apps/api/PRICING_SOURCES.md` را بخوانید؛ این فایل جزئیات سطح Provider، پشت `apps/api/app/pricing/registry.py` و `apps/api/app/config.py` است، به‌همراه تحقیق بازار فراتر از چیزهایی که الان متصل (wire) شده‌اند.

بررسی‌شده در تاریخ 2026-08-24. شرایط Providerها، قیمت‌گذاری و وضعیت تحریم‌ها دائم تغییر می‌کند — پیش از تکیه‌کردن روی هر نکته‌ی حیاتی در Production، دوباره راستی‌آزمایی‌اش کنید.

---

## 0. فوری — دو مورد از چهار منبع کریپتوی فعلی در Production، نهادهای تحریم‌شده OFAC هستند

**در تاریخ 2026-06-02، OFAC چهار صرافی Nobitex، Wallex، Bitpin و Ramzinex را به فهرست SDN اضافه کرد** — به دلیل دور زدن تحریم‌ها، تأمین مالی تروریسم، و کمک به تداوم حکومت ایران. تنها Nobitex بیش از 50% از ورودی دارایی دیجیتال ایران را پردازش می‌کرده؛ سهم Wallex حدود 12% بوده. چهار نفر از مدیران Nobitex هم به‌صورت جداگانه تحریم شدند. تحریم‌های ثانویه (secondary sanctions) هم اعمال می‌شود: اشخاص غیرآمریکایی و مؤسسات مالی خارجی که با این نهادها تراکنش انجام دهند، در معرض خطر قطع‌شدن از سیستم مالی آمریکا هستند، و قاعده «مالکیت 50%» هر نهادی را که اکثریتش متعلق به یک شخص تحریم‌شده باشد، به‌طور خودکار مسدود می‌کند.

**Nerkhbaan در حال حاضر `USDT_TOMAN` و `BTC_TOMAN` را عمدتاً از Nobitex می‌گیرد، با Wallex به‌عنوان fallback:**

| مدخل Registry | Instrument | نقش |
| --- | --- | --- |
| `nobitex_stats_usdt` | `USDT_TOMAN` | **PRIMARY** |
| `nobitex_orderbook_usdt` | `USDT_TOMAN` | VERIFIER |
| `nobitex_stats_btc` | `BTC_TOMAN` | **PRIMARY** |
| `nobitex_orderbook_btc` | `BTC_TOMAN` | VERIFIER |
| `wallex_usdt_toman` | `USDT_TOMAN` | FALLBACK |
| `wallex_btc_toman` | `BTC_TOMAN` | FALLBACK |

سؤالات متداول عمومی OFAC (به‌روزشده در 2026-06-02) ممنوعیت‌های مبتنی‌بر تراکنش و ریسک تحریم‌های ثانویه را توضیح می‌دهند، اما صریحاً مشخص نمی‌کنند که آیا درخواست‌های HTTP فقط‌خواندنی (read-only) و بدون احراز هویت به یک endpoint عمومی داده‌ی بازار متعلق به صرافی تحریم‌شده، مصداق «معامله» (dealing) ممنوع محسوب می‌شود یا نه. این یک خلأ واقعی است، نه یک پاسخ روشن در هیچ‌کدام از دو جهت — **این توصیه حقوقی نیست؛ پیش از تصمیم به نگه‌داشتن، محدودکردن یا حذف این دو یکپارچه‌سازی، با وکیل مشورت کنید**، به‌خصوص پیش از راه‌اندازی تجاری یا اگر پلتفرم هرگونه ارتباط (nexus) با ایالات متحده داشته باشد.

در عمل، صرف‌نظر از نتیجه حقوقی: `apps/api/app/pricing/registry.py` در حال حاضر هیچ PRIMARY غیرتحریم‌شده‌ای برای `USDT_TOMAN`/`BTC_TOMAN` ندارد اگر Nobitex و Wallex هر دو کنار گذاشته شوند — `tetherland_usdt`/`tetherland_btc` (نقش FALLBACK، اولویت 3) تنها مسیر ثبت‌شده باقی‌مانده است و تا زمان نگارش این سند تحریم نشده. بخش 4.4 در ادامه، گزینه‌های غیرتحریم‌شده بیشتری را فهرست می‌کند.

منابع: [Chainalysis](https://www.chainalysis.com/blog/ofac-sanctions-iranian-crypto-exchanges-june-2026/)، [Elliptic](https://www.elliptic.co/insights/ofac-sanctions-nobitex-and-three-other-iranian-cryptoasset-exchanges/)، [OFAC FAQs](https://ofac.treasury.gov/faqs/added/2026-06-02)، [MEXC News](https://www.mexc.com/news/1126101)

---

## 1. این سند چطور به `.env` نگاشت می‌شود

هر Provider در ادامه، متناظر با یک مدخل `_provider(...)` در `apps/api/app/pricing/registry.py` است. آدرس پایه (base URL) و اعتبارنامه‌های آن از تنظیمات `apps/api/app/config.py` می‌آید که از طریق `.env` تنظیم می‌شود (به `.env.example` نگاه کنید). دو چیز مستقل، فعال‌بودن یک Provider را کنترل می‌کند:

1. **`configured()`** — آیا تنظیمات لازم (کلید، نماد، آدرس proxy) را طبق `ProviderDefinition.configured()` دارد.
2. **`enabled`** — `PRICING_PROVIDER_<ID>_ENABLED` (مقدار پیش‌فرض بسته به Provider فرق می‌کند؛ به ستون `enabled_default` نگاه کنید).

Providerای که `enabled` است ولی `configured` نیست، در زمان اجرا به‌آرامی نادیده گرفته می‌شود — در `GET /api/prices/health` به‌صورت «غایب» دیده می‌شود، نه خطا. `PRICING_PROVIDER_ALLOWED_HOSTS` هم باید هاست Provider را فهرست کند (اپ به‌صورت خودکار هاست‌های مربوط به هر `*_api_base_url` تنظیم‌شده را اضافه می‌کند، اما یک URL هاردکد یا تاریخی هنوز نیاز به allowlist دستی دارد).

---

## 2. Providerهای فعلاً یکپارچه‌شده

«رایگان» در ادامه یعنی خود endpoint نیازی به اشتراک پولی ندارد. چند Provider «رایگان» هنوز به ثبت‌نام/کلید API (در سطح رایگان) نیاز دارند؛ این‌ها **freemium** علامت‌گذاری شده‌اند.

### 2.1 `XAU_USD_OZ` / `XAG_USD_OZ` — طلا و نقره نقدی بین‌المللی

| Provider | نقش | هزینه | احراز هویت (متغیر env) | فعال به‌صورت پیش‌فرض | یادداشت |
| --- | --- | --- | --- | --- | --- |
| GoldAPI.io (`goldapi_xau`/`goldapi_xag`) | PRIMARY | **Freemium** | `GOLDAPI_API_KEY` (هدر) | بله، ولی بدون کلید نادیده گرفته می‌شود | سطح رایگان تاریخاً حدود 100 درخواست در ماه؛ پلن‌های پولی مقیاس‌پذیرترند. پیش از تکیه‌کردن، شرایط فعلی را در goldapi.io بررسی کنید. |
| Gold-API.com (`gold_api_free_xau`/`gold_api_free_xag`) | VERIFIER | **رایگان، بدون کلید** | ندارد | بله | `gold-api.com` — واقعاً رایگان، JSON بدون احراز هویت. کریپتو را هم پوشش می‌دهد. یک verifier مستقل خوب که الان هم استفاده می‌شود. |
| Metals.dev (`metals_dev_gold`/`metals_dev_silver`) | FALLBACK | **Freemium** | `METALS_DEV_API_KEY` (query) | بله، ولی بدون کلید نادیده گرفته می‌شود | سطح رایگان تأییدشده: **100 درخواست در ماه**، به‌روزرسانی هر 60 ثانیه. پلن‌های پولی از 1.79$ در ماه (2,000 درخواست) تا 99.99$ در ماه (500,000 درخواست). |

### 2.2 `GOLD_18K_TOMAN_GRAM` / `GOLD_24K_TOMAN_GRAM` — طلای فیزیکی ایران، تومان

| Provider | نقش | هزینه | احراز هویت (متغیر env) | فعال به‌صورت پیش‌فرض | یادداشت |
| --- | --- | --- | --- | --- | --- |
| Alanchand (`alanchand_gold18`) | PRIMARY برای 18K | **Freemium (بسیار محدود)** | `ALANCHAND_API_TOKEN` (Bearer) | بله، ولی بدون کلید نادیده گرفته می‌شود | تأییدشده: سطح رایگان **1 درخواست در ساعت به‌ازای هر کاربر** از طریق توکن تستِ صادرشده توسط ربات تلگرام است؛ دسترسی نامحدود نیاز به تماس مستقیم با Alanchand دارد (مذاکره‌شده/پولی). Registry از قبل این Provider را به یک فراخوانی هر 2 ساعت محدود کرده، که با این موضوع هم‌خوانی دارد. |
| TALA.ir (`tala_gold24_toman` به‌عنوان primary، `tala_gold18_toman` به‌عنوان verifier) | PRIMARY / VERIFIER | **پولی** (شرایط منتشر نشده) | `TALA_API_KEY` (هدر) + تنظیم کلید به‌ازای هر symbol | **به‌صورت پیش‌فرض غیرفعال** | api.tala.ir در زمان نگارش این سند قیمت‌گذاری را عمومی منتشر نکرده بود — مستقیماً با آن‌ها تماس بگیرید. ثبت‌شده اما خاموش؛ نیاز به کلید و `PRICING_PROVIDER_TALA_*_ENABLED=true` صریح دارد. |
| Nerkh.io (`nerkh_io_gold24`) | FALLBACK | **پولی** | `NERKH_IO_BEARER_TOKEN` یا `NERKH_IO_API_KEY` | **به‌صورت پیش‌فرض غیرفعال** | یک API تجاری نرخ ایرانی؛ متفاوت از `nerkh-api.ir` قدیمی که در فهرست operator gate آمده و هنوز onboard نشده. |

`SILVER_999_TOMAN_GRAM` یک Provider کلید-محور دارد (`tala_silver999_toman`، به‌صورت پیش‌فرض غیرفعال، نیازمند `TALA_SILVER999_TOMAN_KEY`).
**`SILVER_925_TOMAN_GRAM` اصلاً هیچ Provider ثبت‌شده‌ای ندارد** — فقط فرمولی است، و از `SILVER_999_TOMAN_GRAM` با نسبت عیار مشتق می‌شود. این روشن‌ترین شکاف در مجموعه منابع فعلی است (به 4.3 نگاه کنید).

### 2.3 `USD_TOMAN` — نرخ دلار بازار آزاد ایران

| Provider | نقش | هزینه | احراز هویت (متغیر env) | فعال به‌صورت پیش‌فرض | یادداشت |
| --- | --- | --- | --- | --- | --- |
| Navasan (`navasan_usd_toman`) | PRIMARY | **پولی** | `NAVASAN_API_KEY` (query) + `NAVASAN_HTTPS_PROXY_BASE_URL` | **به‌صورت پیش‌فرض غیرفعال** | API مستقیم Navasan (`api.navasan.tech`) به‌صورت HTTP ساده است؛ اپ *الزاماً* یک HTTPS proxy جلوی آن می‌خواهد (`NAVASAN_ALLOW_INSECURE_HTTP` عمداً در زمان راه‌اندازی رد می‌شود) — هم به کلید پولی و هم به relay/proxy HTTPS خودتان نیاز دارید. |
| Servix (`servix_usd_toman`) | FALLBACK | **سطح رایگان: روزی 50 درخواست موفق** | `SERVIX_API_KEY` (هدر) | **به‌صورت پیش‌فرض غیرفعال** | سطح رایگان دائمی است؛ ثبت‌نام و کلید لازم است، اطلاعات پرداخت نه. |
| PersianToolbox (`persian_toolbox_usd_toman`) | FALLBACK | رایگان، بدون کلید؛ سهمیه عمومی تضمین نشده | ندارد | **به‌صورت پیش‌فرض غیرفعال** | مرجع فنی USD/IRR با تبدیل ریال به تومان. Provider نرخ بازار آزاد یا قابل معامله را تضمین نمی‌کند. |

**این بزرگ‌ترین شکاف واقعی پلتفرم است.** بدون یکی از موارد بالا، هر قیمت فلز به تومان از طریق `USDT_TOMAN / USDT_USD` به‌جای یک نرخ واقعی دلار پل زده می‌شود، و حدود 3.4% بالاتر از واقعیت درمی‌آید (به بخش 4 در `PRICING_SOURCES.md` نگاه کنید). برای گزینه‌های رایگان/نزدیک‌به‌رایگان جهت پرکردن این شکاف، به 4.2 نگاه کنید.

### 2.4 `USDT_TOMAN` / `BTC_TOMAN` — کریپتو/تومان ایران

| Provider | نقش | هزینه | احراز هویت | فعال | یادداشت |
| --- | --- | --- | --- | --- | --- |
| Nobitex (`nobitex_stats_usdt`، `nobitex_orderbook_usdt`، `nobitex_stats_btc`، `nobitex_orderbook_btc`) | **PRIMARY** + VERIFIER | رایگان، بدون کلید | ندارد | بله | **در فهرست SDN توسط OFAC از 2026-06-02 — به بخش 0 نگاه کنید.** |
| Wallex (`wallex_usdt_toman`، `wallex_btc_toman`) | FALLBACK | رایگان، بدون کلید | ندارد | **به‌صورت پیش‌فرض غیرفعال** | **در فهرست SDN توسط OFAC از 2026-06-02 — به بخش 0 نگاه کنید.** |
| Tetherland (`tetherland_usdt`، `tetherland_btc`) | FALLBACK | رایگان، بدون کلید | ندارد | USDT فعال؛ BTC غیرفعال | تا این تاریخ تحریم نشده. BTC بعد از نبود نماد ثبت‌شده در پاسخ زنده قرنطینه شد. |
| TALA (`tala_usdt_toman`) | FALLBACK | پولی | `TALA_API_KEY` | **به‌صورت پیش‌فرض غیرفعال** | |
| Navasan (`navasan_usdt`) | FALLBACK | پولی | `NAVASAN_API_KEY` + HTTPS proxy | **به‌صورت پیش‌فرض غیرفعال** | |

### 2.5 `USDT_USD` / `BTC_USD` — کریپتو/دلار جهانی

| Provider | نقش | هزینه | احراز هویت | فعال | یادداشت |
| --- | --- | --- | --- | --- | --- |
| Coinbase Exchange (`coinbase_usdt_usd`، `coinbase_btc_usd`) | PRIMARY | رایگان، بدون کلید | ندارد | بله | endpoint عمومی ticker، بدون احراز هویت. |
| CoinGecko (`coingecko_usdt`، `coingecko_btc`) | FALLBACK | رایگان، بدون کلید (rate-limited) | ندارد | بله | محدودیت پلن عمومی تأییدشده: **5 تا 15 فراخوانی در دقیقه**، بدون سقف ماهانه منتشرشده، و به‌صورت پویا بسته به بار خود CoinGecko محدود می‌شود. یک کلید API رایگان از نوع Demo این را به 30 در دقیقه پایدار می‌رساند — اگر این مسیر پراستفاده شد، افزودن پشتیبانی از هدر `x-cg-demo-api-key` ارزش دارد. |
| PersianToolbox (`persian_toolbox_btc`) | FALLBACK | رایگان، بدون کلید؛ سهمیه عمومی تضمین نشده | ندارد | بله | پوشش ایرانی برای مرجع BTC/USD. کف درخواست پنج دقیقه؛ کنترل سخت زمان، تازگی، منبع، نماد و واحد. تاریخچه ندارد. |
| CoinCap (`coincap_usdt`، `coincap_btc`) | FALLBACK، کم‌اولویت‌ترین | **احتمالاً از کار افتاده** | چیزی پیکربندی نشده | **به‌صورت پیش‌فرض غیرفعال** | CoinCap به مدل «3.0» با اعتبار پیش‌پرداختی (`pro.coincap.io`، پرداخت با USDC) منتقل شده — به‌نظر می‌رسد endpoint رایگان و بدون‌کلید `api.coincap.io/v2` که این یکپارچه‌سازی هدف قرار داده، متوقف یا افت‌کیفیت‌یافته باشد. تا راستی‌آزمایی دوباره، آن را مرده در نظر بگیرید؛ بدون بررسی اول `pro.coincap.io`، دوباره فعالش نکنید. |
| Servix (`servix_btc_usd`، `servix_usdt_usd`) | FALLBACK + تاریخچه | سطح رایگان: روزی 50 درخواست موفق | `SERVIX_API_KEY` | **به‌صورت پیش‌فرض غیرفعال** | تاریخچه BTC/USD و USDT/USD؛ ثبت‌نام، درج منبع و کلید لازم است. سه مسیر روی‌هم به 48 تماس در روز محدودند. |

---

## 3. ساخته‌شده ولی متصل‌نشده — parser وجود دارد، مسیر زنده ندارد

`apps/api/app/pricing/parsers/__init__.py` تعداد parserهایی بیشتر از مدخل‌های Provider موجود در `registry.py` را ثبت کرده. کار parse/validation برای این‌ها از قبل انجام شده؛ فقط یک ثبت `_provider(...)` کم دارند (و برای Ticaro/Arzbin، یک تنظیم base-URL در `config.py` که هنوز وجود ندارد):

| Parser | چه چیزی را پوشش می‌دهد | چه چیزی کم است |
| --- | --- | --- |
| `ticaro_usdt_toman_v1`، `ticaro_btc_toman_v1`، `ticaro_gold18_toman_v1` | `USDT_TOMAN`، `BTC_TOMAN`، `GOLD_18K_TOMAN_GRAM` | تنظیم `ticaro_api_base_url` در `config.py` وجود ندارد، مدخل registry هم نه. `ticaro.ir` از قبل در فهرست allowed-hosts در `.env.example` هست، که نشان می‌دهد این یکپارچه‌سازی نیمه‌کاره مانده. |
| `arzbin_usd_v1` | `USD_TOMAN` | تنظیم `arzbin_api_base_url` وجود ندارد، مدخل registry هم نه. `hub.arzbin.com` هم به همین شکل از قبل allowlist شده. **ارزش دارد اول این یکی تمام شود** — مستقیماً بزرگ‌ترین شکاف پلتفرم را هدف می‌گیرد. |
| `navasan_btc_v1`، `navasan_gold18_v1`، `navasan_xau_v1` | `BTC_TOMAN`، `GOLD_18K_TOMAN_GRAM`، `XAU_USD_OZ` | Registry فقط آیتم‌های `usd` و `usdt` نوسان را متصل کرده. همان `NAVASAN_API_KEY` این‌ها را هم پوشش می‌دهد — عملاً پوشش اضافی رایگان به‌محض این‌که Navasan برای هرچیزی پیکربندی شود. |
| `nerkh_io_usd_v1`، `nerkh_io_usdt_v1`، `nerkh_io_btc_v1`، `nerkh_io_xau_v1`، `nerkh_io_xag_v1` | `USD_TOMAN`، `USDT_TOMAN`، `BTC_TOMAN`، `XAU_USD_OZ`، `XAG_USD_OZ` | Registry فقط symbol مربوط به `gold24` نرخ.io را متصل کرده. همان توکن این‌ها را هم باز می‌کند. |
| `tala_xau_usd_v1`، `tala_xag_usd_v1` | `XAU_USD_OZ`، `XAG_USD_OZ` | Registry فقط فلزات تومانی Tala را متصل کرده. همان `TALA_API_KEY` می‌تواند verifierهای اونس بین‌المللی هم اضافه کند. |
| `servix_gold18_rls_v1` | `GOLD_18K_TOMAN_GRAM` | parser وجود دارد (`servix_gold18_rls_v1`)، ولی در کنار سه Provider ثبت‌شده Servix، مدخل registry ندارد. |

نتیجه خالص: **اگر روزی برای TALA، Navasan یا Nerkh.io هزینه کنید، تقریباً رایگان به‌اندازه چند instrument دیگر پوشش می‌گیرید** — هزینه مهندسی نهایی فقط یک مدخل در `registry.py` است، نه یک parser جدید.

---

## 4. APIهای رایگان/freemium که هنوز یکپارچه نشده‌اند

با جست‌وجوی هدفمند برای گزینه‌های بدون‌کلید یا با سطح رایگان سخاوتمندانه پیدا شده‌اند، چون این حالت فعلی عملیاتی شماست. اطمینان (confidence) هرکدام فرق می‌کند — کنار هرمورد علامت‌گذاری شده. هیچ‌کدام از این‌ها parser در کدبیس ندارند؛ هرکدام پیش از این‌که بشود در `registry.py` متصل‌شان کرد، نیاز به نوشتن یک parser بر اساس قرارداد `ExplicitParser` در `apps/api/app/pricing/parsers/base.py` دارند.

### 4.1 طلا/نقره نقدی جهانی (`XAU_USD_OZ` / `XAG_USD_OZ`) — مکمل‌های چیزی که الان استفاده می‌شود

| سرویس | هزینه | احراز هویت | پوشش | یادداشت |
| --- | --- | --- | --- | --- |
| [xaus.com](https://xaus.com/api/) | **رایگان، بدون کلید، «بدون محدودیت نرخ برای استفاده معقول»** | ندارد | Spot/تاریخچه/intraday طلا، نقره در پاسخ spot، مقایسه با BTC | بهترین یافته رایگان این دور تحقیق — واقعاً بدون کلید، صریحاً می‌گوید حداقل 30 ثانیه کش کنید و برای بیش از 10,000 درخواست در روز با آن‌ها تماس بگیرید. ارزش دارد به‌عنوان دومین VERIFIER رایگان در کنار `gold_api_free_*` اضافه شود. |
| [goldprice.dev](https://goldprice.dev/) | **سطح رایگان: 1,000 فراخوانی در ماه، 30 در دقیقه، با یک کلید API بدون‌هزینه** (یا 100 درخواست/IP/ساعت بدون کلید) | کلید اختیاری | طلا، نقره، مس؛ 31 ارز مرجع؛ تبدیل عیار | با ثبت یک کلید، محدودیت‌های سخاوتمندانه‌تری نسبت به سطح رایگان Metals.dev دارد. |
| [MetalpriceAPI](https://metalpriceapi.com/) | رایگان: **100 درخواست در ماه**، فقط به‌روزرسانی روزانه | کلید لازم است | طلا، نقره، FX | تقریباً هم‌رده سطح رایگان Metals.dev — ارتقا نیست، فقط اگر خانواده مستقل سومی می‌خواهید یک verifier جایگزین است. |
| Metals-API.com | **بدون سطح رایگان** — از 19.99$ در ماه شروع می‌شود | کلید | طلا، نقره، FX | برای کامل‌بودن فهرست آورده شده؛ رایگان قابل‌استفاده نیست. |

### 4.2 نرخ بازار آزاد `USD_TOMAN` — پرکردن بزرگ‌ترین شکاف

این instrumentی است که بیشترین پتانسیل را از یک منبع رایگان دارد، و ضعیف‌ترین گزینه‌ها را هم. همه این‌ها **bonbast.com**، سایت مرجع نرخ بازار آزاد ایران را اسکرپ یا آینه (mirror) می‌کنند — هیچ‌کدام یک API رسمی درجه‌یک نیستند، پس همه را ناپایدار/best-effort در نظر بگیرید، نه PRIMARY در Production بدون fallback:

| سرویس | هزینه | احراز هویت | یادداشت | اطمینان |
| --- | --- | --- | --- | --- |
| [آینه Bonbast-API](https://github.com/itsamirhn/Bonbast-API) — میزبانی‌شده در `bonbast.amirhn.com` | **رایگان، بدون کلید** | ندارد | یک wrapper شخص‌ثالث FastAPI دور bonbast.com، سورس در GitHub، قابل self-host. به‌قول خود نگهدارنده: «ممکن است کند باشد یا گاهی مسدود شود»، «هر لحظه ممکن است از دسترس خارج شود». | نمونه زنده میزبانی‌شده تأیید شد که وجود دارد؛ **از نظر uptime/دقت راستی‌آزمایی نشده** — به‌عنوان یک FALLBACK موقت رفتار کنید، هرگز PRIMARY نه. |
| سرویس نرخ سنای TGJU (`tgju.org/sanarate-service`) | **رایگان، بدون کلید** | ندارد | این نرخ رسمی سامانه نظارت ارزی («سنا») است، نه نرخ بازار آزاد — یک عدد نیمه‌رسمی *متفاوت*. برای مرجع/مقایسه مفید است، نه جایگزینی برای یک فید واقعی بازار آزاد. | از طریق فهرست API جامعه پیدا شده؛ شکل endpoint مستقل تأیید نشده — پیش از اتصال راستی‌آزمایی کنید. |
| [margani/pricedb](https://github.com/margani/pricedb) (`prices.readme.io`) | رایگان، بدون کلید | ندارد | به‌صورت خودکار از طریق GitHub Actions به‌روز می‌شود؛ نگهدارنده می‌گوید «فقط برای استفاده شخصی» و «هر لحظه ممکن است تغییر کند». | اطمینان پایین برای استفاده Production. |
| [HosseinOdd/Navasan-API](https://github.com/HosseinOdd/Navasan-API) | رایگان، ولی **یک API میزبانی‌شده نیست** | ندارد | یک اسکرپر Selenium خودمیزبان از navasan.net که هر 10 دقیقه از طریق GitHub Actions یک JSON استاتیک تولید می‌کند — باید خودتان اجرایش کنید، نه این‌که یک endpoint زنده صدا بزنید. نگهدارنده به ریسک ToS مربوط به اسکرپینگ هم اشاره کرده. | بدون راه‌اندازی زیرساخت اسکرپر خودتان، مستقیماً به‌عنوان `ProviderDefinition` قابل‌استفاده نیست. |
| BRSAPI (`brsapi.ir/free-api-gold-currency-webservice/`) | تبلیغ‌شده به‌عنوان **رایگان، بدون ثبت‌نام** | طبق تبلیغاتشان چیزی لازم نیست | endpoint نمونه عمومی از Production در دسترس بود. | پاسخ تست‌شده تاریخ 1404/02/28 داشت و داده نمونه/fixture است، نه خوراک زنده. به‌عنوان مسیر زنده یکپارچه نشود. |
| `api.zipodo.ir/usdt/` | رایگان، بدون کلید | ندارد | یک endpoint تک‌منظوره JSON برای تتر/تومان. دامنه محدود، نگهدارنده/قابلیت‌اطمینان نامعلوم. | اطمینان پایین، ولی اگر خراب شود شعاع آسیبش کوچک است (فقط یک instrument). |

**توصیه برای این instrument به‌طور خاص:** هیچ‌کدام از گزینه‌های رایگان بالا آن‌قدر قابل‌اعتماد نیستند که تنها PRIMARY باشند. مسیر عملی یا (الف) تنظیم Navasan یا کلید سطح رایگان Servix است — که هردو از قبل کاملاً متصل‌اند، فقط غیرفعال‌اند — یا (ب) ثبت 2 تا 3 مورد از اسکرپرهای رایگان بالا با نقش‌های کم‌اولویت `VERIFIER`/`FALLBACK`، تا موتور anomaly/consensus در `canonical.py` بتواند آن‌ها را در برابر هم صلیب‌چک (cross-check) کند، نه این‌که به هیچ‌کدام به‌تنهایی اعتماد کند.

### 4.3 `SILVER_925_TOMAN_GRAM` — در حال حاضر صفر Provider

هیچ منبع اختصاصی نقره 925 در هیچ‌کجا — رایگان یا پولی — پیدا نشد. به‌نظر می‌رسد این واقعاً یک بازار کم‌عمق در سطح بین‌المللی باشد، نه فقط در این کدبیس. گزینه‌های واقع‌بینانه همان چیزی است که `PROJECT_STATUS.md` از قبل گفته: نگه‌داشتنش به‌صورت فرمولی و مشتق از `SILVER_999_TOMAN_GRAM`، یا پیگیری یک رابطه تجاری مستقیم با یک فروشنده شمش ایرانی.

### 4.4 منابع کریپتوی غیرتحریم‌شده برای `USDT_TOMAN` / `BTC_TOMAN`

با توجه به بخش 0، این‌ها ارزش بررسی دارند، چه به‌عنوان افزودنی و چه به‌عنوان جایگزین Nobitex/Wallex. هیچ‌کدام هنوز یکپارچه نشده‌اند:

| صرافی | هزینه | احراز هویت | یادداشت |
| --- | --- | --- | --- |
| Kraken | رایگان، بدون کلید | ندارد | endpoint عمومی `Ticker` REST؛ جفت تومانی ندارد، ولی یک منبع مستقل و تمیز برای سمت `USDT_USD`/`BTC_USD` است. |
| Binance | رایگان، بدون کلید | ندارد | endpointهای عمومی ticker؛ نقدینگی بالا برای BTC/USDT در سطح جهانی. جفت تومانی ندارد. برخی حوزه‌های قضایی دسترسی به Binance را محدود می‌کنند — پیش از تکیه‌کردن از منطقه میزبانی خودتان، کاربردپذیری را بررسی کنید. |
| Bitfinex، KuCoin، OKX | رایگان، بدون کلید | ندارد | همان داستان Kraken/Binance — جفت‌های جهانی USD/USDT، بدون پوشش مستقیم تومان، فقط برای پاهای بین‌المللی (`USDT_USD`، `BTC_USD`) مفیدند، نه به‌عنوان جایگزین Nobitex/Wallex برای پاهای تومانی. |

**هیچ‌کدام از موارد بالا جفت تومانی ندارند** — مشکل واقعی همین‌جاست. صرافی‌های نقدشونده تومانی ایران الان تقریباً به‌طور کامل همان چهار مورد تحریم‌شده (Nobitex، Wallex، Bitpin، Ramzinex) به‌علاوه Tetherland (که از قبل یکپارچه و «تمیز» است) هستند و Ramzinex هم تحریم است (اضافه نکنید). صرافی‌های ایرانی کوچک‌تر/جدیدتر وجود دارند اما در این دور تحقیق هیچ‌کدام با یک API عمومی مستند قیمت پیدا نشدند — این موضوع ارزش یک جست‌وجوی پیگیری اختصاصی، با تمرکز روی وضعیت compliance صرافی‌ها به‌جای در دسترس‌بودن API، را دارد.

---

## 5. گزینه‌های پولی/تجاری — خلاصه

برای کامل‌بودن، چون قرار نیست همه‌چیز برای همیشه رایگان بماند:

| Provider | پوشش | قیمت ورودی | وضعیت در کدبیس |
| --- | --- | --- | --- |
| GoldAPI.io | XAU/XAG به دلار | Freemium، پلن‌های پولی این‌جا اعلام نشده — goldapi.io را بررسی کنید | یکپارچه، PRIMARY |
| goldprice.dev | XAU/XAG/مس، چندارزی | 10$ در ماه (Physical) تا 80$ در ماه (Realtime Pro + WebSocket) | یکپارچه نشده |
| Metals-API.com | XAU/XAG/FX | 19.99$ در ماه (2,500 فراخوانی) تا 999$ در ماه | یکپارچه نشده |
| MetalpriceAPI | XAU/XAG/FX | 5$ در ماه (سالانه، 1,000 فراخوانی) تا 132$ در ماه | یکپارچه نشده |
| Metals.dev | XAU/XAG | 1.79$ در ماه (2,000 فراخوانی) تا 99.99$ در ماه | یکپارچه، FALLBACK |
| TALA.ir | طلا/نقره/دلار/تتر به تومان | اعلام‌نشده، با فروشنده تماس بگیرید | یکپارچه، غیرفعال |
| Navasan.tech | دلار/تتر/BTC به تومان، طلا | اعلام‌نشده، با فروشنده تماس بگیرید | یکپارچه، غیرفعال |
| Nerkh.io | طلا/دلار/تتر/BTC به تومان | اعلام‌نشده، با فروشنده تماس بگیرید | یکپارچه، غیرفعال (فقط gold24) |
| Servix.cc | دلار/BTC و تاریخچه بازار | سطح رایگان دائمی: روزی 50 درخواست موفق؛ پلن پولی سهمیه را بیشتر می‌کند | یکپارچه، تا زمان ورود کلید غیرفعال |
| PersianToolbox | BTC/USD و مرجع فنی USD/IRR | رایگان، بدون کلید؛ مصرف منصفانه و cache لازم | یکپارچه؛ BTC فعال، USD/IRR غیرفعال |
| Alanchand | طلای 18 عیار به تومان | رایگان (1 درخواست در ساعت) تا نامحدود مذاکره‌شده | یکپارچه، PRIMARY |

هیچ‌کدام از سه فروشنده «اعلام‌نشده» در این دور تحقیق قیمتی منتشر نکردند؛ جریان ثبت‌نامشان از طریق ربات تلگرام یا فرم تماس دروازه‌بانی می‌شود، که برای فروشندگان داده B2B ایرانی معمول است. برای اعداد واقعی باید مستقیماً تماس بگیرید.

---

## 6. توصیه‌ها، به‌ترتیب

1. **پیش از هرچیز، مسئله Nobitex/Wallex (بخش 0) را حل کنید.** این یک تصمیم حقوقی/تجاری است، نه مهندسی — با وکیل مشورت کنید، سپس یا ریسک را صراحتاً بپذیرید، یا این دو را به غیر-Production محدود کنید، یا منبع اصلی `USDT_TOMAN`/`BTC_TOMAN` را به Tetherland به‌علاوه verifierهای جدید منتقل کنید.
2. **اتصال parser Arzbin (بخش 3) را تمام کنید.** ارزان‌ترین مسیر برای یک منبع دوم `USD_TOMAN` است — parser وجود دارد، فقط تنظیم base-URL و مدخل registry کم است — و `USD_TOMAN` شکاف #1 مستندشده دقت قیمت‌گذاری پلتفرم است.
3. **`xaus.com` را به‌عنوان دومین verifier رایگان `XAU_USD_OZ`/`XAG_USD_OZ` اضافه کنید** — واقعاً رایگان و بدون‌کلید بودنش تأیید شده، استقلال را تقویت می‌کند (در حال حاضر `gold_api_free_*` تنها verifier بدون‌هزینه این زنجیره است).
4. **2 تا 3 مورد از اسکرپرهای رایگان `USD_TOMAN` در بخش 4.2 را با نقش کم‌اولویت FALLBACK/VERIFIER ثبت کنید**، هرگز PRIMARY، تا منطق consensus در `canonical.py` بتواند تدافعی از آن‌ها استفاده کند، نه با اعتماد به یک اسکرپر تنها.
5. **نمونه عمومی BRSAPI را داده زنده ندانید.** فقط وقتی دوباره بررسی شود که فروشنده endpoint زنده مستند، قرارداد timestamp و سقف مصرف منصفانه بدهد.
6. **CoinCap را کنار بگذارید یا دوباره راستی‌آزمایی کنید** — یکپارچه‌سازی رایگان فعلاً ثبت‌شده احتمالاً یک endpoint متوقف‌شده را هدف گرفته؛ یا تأیید کنید `api.coincap.io/v2` هنوز بدون کلید کار می‌کند، یا مدخل‌های مرده را حذف کنید.

</div>
