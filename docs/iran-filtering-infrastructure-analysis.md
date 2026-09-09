# Iran Filtering & Cross-Border Pricing Infrastructure — Scenario Analysis

Assessed 2026-08-24. Filtering behavior, vendor ToS and sanctions designations
all change — re-verify anything load-bearing before depending on it.

## TL;DR

Keep the core (DB, auth, WebSocket, alerts, admin) on the Iranian VPS — your
users are Iranian, and domestic-to-domestic traffic is the most reliable path
you have, including during international shutdowns (§2). Stand up a small
relay outside Iran whose only job is reaching the handful of Western
providers that are actually filtered or contractually closed to Iran (§3),
and route only those specific calls through it — not the whole pricing
engine, not everything. Two separate problems are stacked here and need
separate fixes: Iran blocking outbound (technical, §2), and some vendors
contractually excluding Iran regardless of which IP calls them (legal, §7).
A relay VPS fixes the first. It does not necessarily fix, and may complicate,
the second.

---

## 1. What's actually filtered, and what isn't

Not every provider in your registry has the same problem. Splitting them
matters because it tells you exactly how small the piece you need to relay
actually is.

| Provider group | Examples | Affected by Iran's filtering? | Affected by vendor-side geo/sanctions exclusion? |
| --- | --- | --- | --- |
| Iran-domestic market data | Alanchand, TALA, Navasan, Nerkh.io, Servix, BRSAPI | No — Iran-to-Iran traffic, not crossing the filtered border | No — these vendors exist to serve the Iranian market |
| Iran-domestic crypto exchanges | Nobitex, Wallex, Tetherland | No | Nobitex & Wallex: **yes**, OFAC SDN-designated 2026-06-02 (see the API providers reference doc, §0) — a separate, non-filtering problem. Tetherland is not on that list. |
| Western financial/crypto data | Coinbase, CoinGecko, GoldAPI.io, Gold-API.com, Metals.dev, CoinCap | **Yes**, generic Iran-outbound HTTPS filtering/DPI applies | CoinGecko: the exclusion **mechanism is confirmed** — its API Terms of Service (§11.2) require you to warrant you and your entity are not under OFAC sanctions and not domiciled in a country on its Excluded Countries list. I did not independently verify that Iran is named on that specific list (comprehensive US sanctions on Iran make it near-certain, but "near-certain" isn't "confirmed"). Coinbase and other US-domiciled vendors very likely carry equivalent boilerplate — I did not find Coinbase's exact clause text. Not checked at all for GoldAPI.io/Gold-API.com/Metals.dev — verify each vendor's terms directly before relying on this table. |

So the actual list of instruments needing a foreign relay is short:
`XAU_USD_OZ`, `XAG_USD_OZ` (GoldAPI/Gold-API/Metals.dev), and the
international legs `USDT_USD`, `BTC_USD` (Coinbase/CoinGecko/CoinCap). That's
five or six hostnames, not "many websites" — your Toman-denominated instruments,
which are what most of your Iranian users actually look at, are already served
by Iran-domestic vendors and don't need this at all.

---

## 2. What Iran's filtering actually does right now (2026)

Three points that should shape the design, each sourced:

**It's bidirectional and DPI-based, not just a domain blacklist.** The
system inspects the SNI field of the HTTPS handshake, does stateful
first-packet inspection, and injects RST packets to kill connections it
doesn't like — and this applies to traffic in both directions, not just
outbound requests initiated by end users. [[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)] That
matters for your design: it means an EU-initiated *push* into the Iranian
core is not inherently safer from filtering than an Iran-initiated *pull*
from the EU relay — both cross the same inspected border.

**Since the January 2026 shutdown, the model shifted from blacklist to
allowlist for a meaningful slice of traffic.** Only pre-approved
destinations stay reliably reachable; everything else is default-closed
rather than default-open-with-exceptions. Cloudflare in particular has been
reported blocked outright at points in 2026, then partially unblocked for
specific Iranian sites — it flips. [[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)], [[net4people/bbs #133](https://github.com/net4people/bbs/issues/133)], [[net4people/bbs #429](https://github.com/net4people/bbs/issues/429)]
**Practical consequence: don't design around "put it behind a big CDN and
it'll be fine" — that assumption has failed before and could fail again.
Test empirically against your specific target, and don't build a
single-point-of-failure dependency on any one CDN or provider.**

**Access is explicitly tiered, and business/datacenter connections often
fare better than residential ones.** Iran now runs a two-track system —
ordinary filtered access, and a paid "Stable Communication Network" / "Pro
Internet" tier with materially better foreign reachability. [[Filterwatch](https://filter.watch/english/2026/03/06/network-monitoring-february-2026-a-new-phase-of-selective-internet-in-iran/)], [[CNN](https://www.cnn.com/2026/05/10/middleeast/iran-internet-pro-blackout-access-vpn-intl)]
Commercial datacenter uplinks are often provisioned differently from
residential broadband, and behavior varies by upstream carrier — one
first-hand operator report found SSH staying fast and functional on an MCI
(Hamrah Aval)-backed connection when general HTTPS to foreign sites was
blocked outright, while a different carrier (Irancell/MTN) filtered less
aggressively overall. [[LowEndTalk](https://lowendtalk.com/discussion/206643/iran-internet-update-for-hosting-providers-and-users)]
**Action: ask your Iranian VPS provider which upstream carrier and
connectivity tier the box actually has, and test reachability to specific
candidate relay IPs before committing to a design** — the answer materially
changes which of the scenarios below will actually work for you.

**One structural fact worth being deliberate about, in your favor:** Iran's
National Information Network (NIN) is built to keep *domestic* services
running even when international links are cut. [[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)]
During the February 2026 event, general users lost global internet access
while some entities retained connectivity — but Iran-to-Iran traffic is
architecturally the thing Iran's own censorship system is least likely to
break. This is the strongest argument for keeping your core, and your
Iranian users' path to it, entirely domestic.

---

## 3. Scenarios

| # | Architecture | Verdict |
| --- | --- | --- |
| A | Everything (core + all provider calls) stays on the Iran VPS, unchanged | Keeps failing intermittently on exactly the Western providers you need most for `XAU`/`XAG`/global BTC-USD reference prices. Explains why the app already leans on Iranian aggregators and needs an HTTPS proxy in front of Navasan's plain-HTTP API. Not a fix, but not wrong about anything either — it's just incomplete. |
| B | Move everything (core + collector) to a EU VPS | **Don't.** Your users are Iranian; this makes the product itself cross the filtered border for every page load and every WebSocket message, for the majority of your user base, to solve a problem that only affects a handful of upstream provider calls. Trades a small, isolated problem for a large, constant one. |
| C | **Split: core stays on the Iran VPS, a small relay outside Iran handles only the filtered/excluded Western providers** | **This is what you proposed, and it's the right shape.** Keeps the core close to your users (§2's NIN point) and isolates the actual filtering exposure to a narrow, well-understood slice of traffic. Detailed in §4. |
| D | Route the filtered calls through a third-party "unblocking" proxy/CDN service instead of your own relay VPS | Lower setup effort, but you inherit a vendor's reachability and don't control its IP reputation or uptime. Worth comparing on cost, but a self-run relay (your own registered domain, your own routing rules) gives you the redundancy and observability the split architecture actually needs. Not recommended as the primary approach. |
| E | Lean harder on Iran-domestic aggregators, shrink what needs any foreign relay at all | Already partly true — the domestic instruments are already covered. This is a refinement to layer on top of C, not an alternative to it: it reduces C's blast radius, it doesn't replace the need for it (`XAU_USD_OZ`/`XAG_USD_OZ` genuinely have no Iranian source). |
| F | Multi-region relay redundancy — two small relay VPSs in different providers/countries, not just one EU box | Not urgent on day one, but cheap to add later and maps directly onto machinery your pricing engine already has (a second relay is just another ranked `FALLBACK` provider — see §6). Recommended once C is proven, not before. |

**Recommendation: C, scoped down by E, with F as a near-term follow-up.**

---

## 4. The recommended split, in detail

**Core (Iran VPS) — unchanged:** PostgreSQL/TimescaleDB, Redis, FastAPI,
web/admin/desktop frontends, WebSocket fan-out, alert delivery, Telegram
worker. All Iran-domestic provider calls (Alanchand, TALA, Navasan, Nerkh.io,
Servix, Tetherland, and any BRSAPI/other domestic source you add) stay
called directly from here exactly as today — no relay involved, no reason to
route domestic-to-domestic traffic through a foreign hop.

**Relay (non-Iran VPS) — new, small, stateless:** its only job is to sit
between the Iran core and the five or six Western hostnames from §1's table.
Two ways to build it, in order of how little they change your existing code:

**4.1 Transparent reverse-proxy relay (recommended starting point).** The
relay runs nginx or Caddy, and for each affected provider it exposes a path
that reverse-proxies straight through to the vendor — e.g.
`https://relay.<yourdomain>/coinbase/*` → `https://api.exchange.coinbase.com/*`.
On the Iran core, you change nothing except configuration: repoint the
affected `*_api_base_url` settings in `.env` at the relay instead of the
vendor's own domain, and add the relay's hostname to
`PRICING_PROVIDER_ALLOWED_HOSTS`. The egress guard in
`apps/api/app/pricing/providers.py` (around line 551–558) does an *exact*
hostname match against that allowlist — one new hostname covers every
provider you route through the relay, and every parser in
`apps/api/app/pricing/parsers/` keeps working completely unchanged, because
as far as the parser is concerned it's still talking to Coinbase's response
shape, just through a different front door. This is the lowest-effort path
and the one to build first.

**4.2 Aggregating relay (later, if you want it).** The relay runs its own
small FastAPI/Flask app that calls the Western vendors itself, normalizes
their responses, and exposes one unified endpoint. The Iran core then has
one new `ProviderDefinition` in `registry.py` instead of several repointed
base URLs. More work, and it moves provider API keys onto the relay box
instead of the core — worth doing later if you want vendor credentials to
live outside Iran specifically, but not necessary to solve the filtering
problem on its own. Start with 4.1; move to 4.2 only if you have a concrete
reason to.

**Either way, the relay is a new trust boundary — lock it down.** At
minimum: a shared-secret header the core sends and the relay checks before
proxying, plus an IP allowlist on the relay restricting inbound to the
core's IP. mTLS if you want to go further. Don't expose the relay's proxy
paths to the open internet unauthenticated — it would otherwise let anyone
use your relay as a free anonymous proxy to Coinbase/CoinGecko, which is
exactly the kind of thing that gets a relay IP blocklisted fast.

---

## 5. Transport: how the core actually talks to the relay

Three real options, given what §2 established about Iran's filtering being
bidirectional and DPI-based:

| Method | How it works | Verdict |
| --- | --- | --- |
| **Plain HTTPS, core pulls from relay** | Core calls `https://relay.yourdomain.com/...` on a schedule, same pattern as any other provider call today | Simplest, fits the existing egress-guard/circuit-breaker code with zero new infrastructure concepts. Exposed to the same SNI/DPI inspection as any other foreign HTTPS call — works well outside acute filtering events, may degrade during them, same as everything else. **Start here.** |
| **SSH reverse tunnel, core connects out to relay, relay's local port forwards back** | The Iran core opens an outbound SSH connection to the relay (or vice versa) and tunnels the pricing-fetch traffic through it | A real operator, dealing with this exact censorship regime on an MCI-backed Iranian connection, found SSH staying fast and functional when general foreign HTTPS was blocked outright. [[LowEndTalk](https://lowendtalk.com/discussion/206643/iran-internet-update-for-hosting-providers-and-users)] Worth setting up as a **fallback transport** if plain HTTPS to the relay proves unreliable from your specific VPS/carrier — more moving parts (tunnel uptime becomes its own thing to monitor), and you pay for bandwidth on both legs. |
| **WireGuard/VPN tunnel** | Persistent encrypted tunnel between core and relay | More overhead to operate than SSH for this narrow use case, and VPN protocols have specifically been targeted by Iran's filtering in the past (§2). Doesn't obviously beat SSH here. Not recommended over the two above unless you already run one for other reasons. |

**Recommendation: build the HTTPS pull first (§4.1 already assumes this),
and keep SSH tunneling in your back pocket as the documented fallback if you
observe the plain-HTTPS path to your specific relay getting degraded.**
Don't build both on day one — instrument the simple path, see how it
actually behaves from your VPS's specific carrier, then decide.

---

## 6. How this fits the codebase you already have

You don't need a new abstraction — the pricing engine already has one that
fits this exactly:

- `PROVIDERS_BY_INSTRUMENT` in `apps/api/app/pricing/registry.py` already
  ranks multiple sources per instrument by cache freshness, circuit state,
  trust score and budget pressure (`service.py`, `_rank_candidates`). A
  second relay (Scenario F) is just another `ProviderDefinition` with a
  `FALLBACK` role — the ranking, circuit-breaker and retry logic in
  `providers.py` applies to it automatically, no new code path needed.
- The egress allowlist (`PRICING_PROVIDER_ALLOWED_HOSTS`) and the
  `configured()` gate on each `ProviderDefinition` are exactly the
  mechanism you'd use to add and later remove a relay hostname cleanly.
- `GET /api/prices/health` and `startup.instruments_without_direct_source`
  already surface when a chain has no working source — once the relay
  exists, a relay outage shows up there the same way any other provider
  outage does. Worth explicitly watching this endpoint for `XAU_USD_OZ`/
  `XAG_USD_OZ`/`USDT_USD`/`BTC_USD` after cutover, since these are exactly
  the instruments whose entire non-Telegram source chain would run through
  the new relay.
- This is also a concrete, low-effort place to start closing the
  observability gap `PROJECT_STATUS.md` already flags (declared Prometheus
  counters that nothing increments) — a relay-specific failure counter
  would have told you within minutes if the relay path degraded, instead of
  you noticing via `derived_fallback` prices later.

---

## 7. The legal question, separately from the engineering question

This is not something I can resolve for you, and I'd rather say that
plainly than guess. Two distinct things are true at once:

**Routing through a EU IP solves Iran's technical filtering.** A relay in
Germany, Finland, or wherever genuinely gets you past Iran's outbound DPI —
that part is a straightforward engineering problem with a straightforward
engineering answer (§4).

**It does not necessarily solve, and may not even touch, a vendor's
contractual exclusion of Iran.** CoinGecko's API terms (§11.2, confirmed
above) require you to warrant that you and your entity are not domiciled in
a country on their Excluded Countries list — that's a representation about
*who you are*, not *which IP address is calling*. A EU relay changes the
technical enforcement point (IP-based geofencing) without changing the
underlying fact the warranty is actually about, if the operating entity is
Iran-domiciled. Whether that distinction matters in practice — whether it's
a real problem, a theoretical one, or something CoinGecko's own enforcement
never actually looks past IP for — is a legal judgment call, not an
engineering one, and it sits next to the Nobitex/Wallex OFAC question
already raised in `docs/api-providers-reference.md` §0. Both are worth one
conversation with counsel before this goes further, particularly before any
commercial launch — not because either is necessarily disqualifying, but
because "we didn't think about it" is a worse position than "we made an
informed call," whichever way that call goes.

---

## 8. What this doesn't solve

Be honest with yourself about the ceiling here. During the acute national
shutdown in February 2026, "public access to the global internet was cut
off" for general users, and even most VPN/circumvention protocols stopped
working. [[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)] No relay architecture, no
CDN trick, no SSH tunnel survives a declared total shutdown — nothing does,
by design. What this architecture buys you is resilience through the
*normal* state of Iranian filtering (selective, DPI-based, ISP-dependent,
most of the time), not immunity during a declared national-security-driven
blackout. During those events, your product's Iran-domestic instruments
(the ones your users actually care about most) are exactly the ones NIN is
built to keep running — which is one more reason §1's scoping-down matters:
the less your core depends on anything crossing the border, the smaller
your surface during the events that matter most.

---

## 9. Action plan

1. Ask your Iranian VPS provider which upstream carrier and connectivity
   class (residential-grade vs. business/datacenter) the box has — this
   changes which relay location and transport will actually work for you.
2. Stand up one small relay VPS (Hetzner, OVH, or Contabo in the EU are
   reasonable, commonly-used starting points; also worth comparing to a
   Turkey- or UAE-based host, which some operators report as having better
   Iran-reachability than Western Europe — test, don't assume).
3. Build the transparent reverse-proxy (§4.1) for exactly the five or six
   Western hostnames identified in §1. Nothing else needs to move.
4. Add a shared-secret + IP allowlist between core and relay before it
   touches anything real.
5. Repoint the affected `*_api_base_url` settings and
   `PRICING_PROVIDER_ALLOWED_HOSTS` entry; leave every parser untouched.
6. Watch `GET /api/prices/health` for a week. If the relay path is flaky
   from your specific carrier, add the SSH-tunnel fallback (§5) before
   reaching for anything heavier.
7. Get the legal read on §7 in parallel — it doesn't block shipping the
   relay, but it should happen before you'd want to defend the decision to
   anyone outside the room.
8. Once stable, consider a second relay in a different provider/region
   (Scenario F) — cheap insurance, and it's just one more `FALLBACK`
   provider entry in code you already have.

---

<div dir="rtl" lang="fa">

# ترجمه فارسی

بررسی‌شده در تاریخ 2026-08-24. رفتار فیلترینگ، شرایط فروشندگان (vendor ToS) و وضعیت تحریم‌ها همه تغییر می‌کنند — پیش از تکیه‌کردن روی هر نکته‌ی حیاتی، دوباره راستی‌آزمایی‌اش کنید.

## خلاصه مدیریتی (TL;DR)

هسته (core) — یعنی دیتابیس، احراز هویت، WebSocket، هشدارها (alerts)، پنل ادمین — را روی VPS ایرانی نگه دارید؛ کاربران شما ایرانی هستند، و ترافیک داخلی-به-داخلی مطمئن‌ترین مسیری است که دارید، از جمله در زمان قطعی‌های بین‌المللی (بخش 2). یک relay کوچک بیرون از ایران راه‌اندازی کنید که تنها وظیفه‌اش رسیدن به همان چند Provider غربی است که واقعاً فیلتر شده‌اند یا از نظر قراردادی روی ایران بسته‌اند (بخش 3)، و فقط همان تماس‌های خاص را از آن مسیر کنید — نه کل موتور قیمت‌گیری، نه همه‌چیز. این‌جا دو مسئله جدا روی هم انباشته شده‌اند و به دو راه‌حل جدا نیاز دارند: مسدودکردن ترافیک خروجی توسط ایران (فنی، بخش 2)، و برخی فروشندگان که از نظر قراردادی ایران را کنار می‌گذارند، صرف‌نظر از این‌که کدام IP با آن‌ها تماس می‌گیرد (حقوقی، بخش 7). یک VPS relay مسئله اول را حل می‌کند. لزوماً مسئله دوم را حل نمی‌کند، و ممکن است پیچیده‌ترش هم بکند.

---

## 1. چه چیزی واقعاً فیلتر شده، و چه چیزی نشده

نه هر Provider در registry شما همین مشکل را دارد. جداکردن آن‌ها مهم است، چون دقیقاً نشان می‌دهد آن بخشی که واقعاً باید relay شود چقدر کوچک است.

| گروه Provider | نمونه‌ها | تحت‌تأثیر فیلترینگ ایران؟ | تحت‌تأثیر محدودیت جغرافیایی/تحریمی سمت فروشنده؟ |
| --- | --- | --- | --- |
| داده‌های بازار داخلی ایران | Alanchand، TALA، Navasan، Nerkh.io، Servix، BRSAPI | نه — ترافیک ایران‌به‌ایران است، از مرز فیلترشده عبور نمی‌کند | نه — این فروشندگان اساساً برای خدمت به بازار ایران وجود دارند |
| صرافی‌های کریپتوی داخلی ایران | Nobitex، Wallex، Tetherland | نه | Nobitex و Wallex: **بله**، در فهرست SDN توسط OFAC از تاریخ 2026-06-02 (به سند مرجع APIهای قیمت، بخش 0 نگاه کنید) — یک مسئله جدا و غیرمرتبط با فیلترینگ. Tetherland در آن فهرست نیست. |
| داده‌های مالی/کریپتوی غربی | Coinbase، CoinGecko، GoldAPI.io، Gold-API.com، Metals.dev، CoinCap | **بله**، فیلترینگ/DPI عمومی خروجی ایران در مورد این‌ها اعمال می‌شود | CoinGecko: **مکانیزم** محدودیت تأیید شده است — شرایط استفاده API آن (بخش 11.2) از شما می‌خواهد ضمانت دهید که خودتان و نهادتان تحت تحریم OFAC نیستید و در کشوری که در فهرست «کشورهای مستثنا»ی آن‌هاست اقامت ندارید. من مستقلاً تأیید نکردم که ایران دقیقاً در آن فهرست خاص نام‌برده شده باشد (تحریم‌های جامع آمریکا علیه ایران این را تقریباً قطعی می‌کند، اما «تقریباً قطعی» با «تأییدشده» فرق دارد). Coinbase و دیگر فروشندگان مستقر در آمریکا به‌احتمال زیاد بندهای مشابهی دارند — متن دقیق بند Coinbase پیدا نشد. برای GoldAPI.io/Gold-API.com/Metals.dev اصلاً بررسی نشده — پیش از تکیه‌کردن روی این جدول، شرایط هر فروشنده را مستقیماً بررسی کنید. |

پس فهرست واقعی instrumentهایی که نیاز به relay خارجی دارند کوتاه است:
`XAU_USD_OZ`، `XAG_USD_OZ` (از GoldAPI/Gold-API/Metals.dev)، و پاهای بین‌المللی
`USDT_USD`، `BTC_USD` (از Coinbase/CoinGecko/CoinCap). این یعنی پنج یا شش
هاست‌نیم، نه «خیلی از وب‌سایت‌ها» — instrumentهای تومانی شما، که همان چیزی
است که اکثر کاربران ایرانی‌تان واقعاً نگاهش می‌کنند، از قبل توسط فروشندگان
داخلی ایران سرویس‌دهی می‌شوند و اصلاً نیازی به این ندارند.

---

## 2. کاری که فیلترینگ ایران همین الان (2026) واقعاً انجام می‌دهد

سه نکته که باید طراحی را شکل دهد، هرکدام مستند به منبع:

**دوطرفه است و مبتنی‌بر DPI، نه فقط یک فهرست سیاه دامنه.** این سیستم فیلد
SNI در handshake پروتکل HTTPS را بازرسی می‌کند، بازرسی حالت‌مند (stateful)
اولین بسته را انجام می‌دهد، و بسته‌های RST برای قطع اتصال‌هایی که دوست
ندارد تزریق می‌کند — و این هم برای ترافیک در هر دو جهت اعمال می‌شود، نه فقط
درخواست‌های خروجی که کاربر نهایی شروع می‌کند.
[[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)] این برای طراحی
شما مهم است: یعنی یک *push* که از اروپا به‌سمت هسته ایرانی شروع می‌شود،
ذاتاً از یک *pull* که از ایران به‌سمت relay اروپایی شروع می‌شود امن‌تر
نیست — هردو از همان مرز بازرسی‌شده عبور می‌کنند.

**از زمان قطعی ژانویه 2026، مدل برای بخش قابل‌توجهی از ترافیک از فهرست
سیاه به فهرست سفید تغییر کرد.** فقط مقصدهای از‌پیش‌تأییدشده به‌طور
قابل‌اعتماد در دسترس می‌مانند؛ بقیه به‌جای پیش‌فرض‌باز-با-استثنا،
پیش‌فرض‌بسته‌اند. به‌طور خاص Cloudflare در نقاطی از 2026 گزارش شده که کاملاً
مسدود بوده، و بعد برای سایت‌های ایرانی خاص جزئی باز شده — این وضعیت نوسان
دارد. [[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)]،
[[net4people/bbs #133](https://github.com/net4people/bbs/issues/133)]،
[[net4people/bbs #429](https://github.com/net4people/bbs/issues/429)]
**نتیجه عملی: طراحی را بر پایه‌ی «بگذاریمش پشت یک CDN بزرگ و مشکلی نخواهد
بود» نچینید — این فرض قبلاً شکست خورده و می‌تواند دوباره هم بشکند. تجربی و
روی هدف مشخص خودتان تست کنید، و وابستگی تک‌نقطه‌شکست به یک CDN یا Provider
خاص نسازید.**

**دسترسی صریحاً لایه‌بندی‌شده است، و اتصال‌های تجاری/دیتاسنتری اغلب بهتر از
اتصال‌های خانگی (residential) عمل می‌کنند.** ایران الان یک سیستم دوگانه
دارد — دسترسی عادی فیلترشده، و یک لایه‌ی پولی «شبکه ارتباطی پایدار» /
«اینترنت Pro» که دسترسی خارجی به‌مراتب بهتری دارد.
[[Filterwatch](https://filter.watch/english/2026/03/06/network-monitoring-february-2026-a-new-phase-of-selective-internet-in-iran/)]،
[[CNN](https://www.cnn.com/2026/05/10/middleeast/iran-internet-pro-blackout-access-vpn-intl)]
اتصال‌های uplink دیتاسنتر تجاری اغلب به‌شکل متفاوتی از اینترنت پهن‌باند
خانگی تأمین می‌شوند، و رفتار بسته به اپراتور بالادستی فرق می‌کند — یک گزارش
دست‌اول از یک اپراتور نشان داد که SSH روی یک اتصال مبتنی‌بر MCI (همراه اول)
سریع و کارآمد باقی ماند، درحالی‌که HTTPS عمومی به سایت‌های خارجی کاملاً
مسدود بود، ولی یک اپراتور دیگر (ایرانسل/MTN) فیلترینگ کمتر شدیدی داشت.
[[LowEndTalk](https://lowendtalk.com/discussion/206643/iran-internet-update-for-hosting-providers-and-users)]
**اقدام: از ارائه‌دهنده VPS ایرانی‌تان بپرسید سرور واقعاً از چه اپراتور
بالادستی و چه سطح اتصالی استفاده می‌کند، و پیش از قطعی‌کردن روی یک طراحی،
دسترسی به IPهای کاندید relay را تست کنید** — پاسخ این سؤال به‌طور محسوسی
تعیین می‌کند کدام‌یک از سناریوهای زیر واقعاً برای شما کار می‌کند.

**یک واقعیت ساختاری که ارزش دارد عمداً روی آن حساب کنید، به‌نفع شماست:**
شبکه ملی اطلاعات ایران (NIN) طوری ساخته شده که سرویس‌های *داخلی* را حتی
وقتی لینک‌های بین‌المللی قطع می‌شوند، فعال نگه دارد.
[[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)] در رویداد
فوریه 2026، کاربران عادی دسترسی اینترنت جهانی را از دست دادند، درحالی‌که
برخی نهادها اتصال خود را حفظ کردند — اما ترافیک ایران‌به‌ایران از نظر
ساختاری همان چیزی است که سیستم سانسور خودِ ایران کمترین احتمال را دارد که
آن را بشکند. این قوی‌ترین استدلال است برای این‌که هسته‌ی شما، و مسیر
کاربران ایرانی‌تان به آن، کاملاً داخلی بماند.

---

## 3. سناریوها

| # | معماری | نتیجه‌گیری |
| --- | --- | --- |
| A | همه‌چیز (هسته + همه تماس‌های Provider) بدون تغییر روی VPS ایران می‌ماند | همچنان به‌طور متناوب دقیقاً روی همان Providerهای غربی که بیشتر برای `XAU`/`XAG`/قیمت مرجع جهانی BTC-USD لازم دارید شکست می‌خورد. همین توضیح می‌دهد چرا اپ از قبل به aggregatorهای ایرانی تکیه می‌کند و نیاز به یک HTTPS proxy جلوی API متن‌ساده Navasan دارد. راه‌حل نیست، ولی در هیچ‌چیزش هم اشتباه نیست — فقط ناقص است. |
| B | همه‌چیز (هسته + جمع‌آوری‌کننده) به یک VPS اروپایی منتقل شود | **این کار را نکنید.** کاربران شما ایرانی هستند؛ این کار خودِ محصول را برای هر بارگذاری صفحه و هر پیام WebSocket، برای اکثریت کاربرانتان، مجبور به عبور از مرز فیلترشده می‌کند — تا مشکلی حل شود که فقط چند تماس محدود به Providerهای بالادستی را تحت‌تأثیر قرار می‌دهد. یک مشکل کوچک و ایزوله را با یک مشکل بزرگ و دائمی معاوضه می‌کند. |
| C | **تفکیک: هسته روی VPS ایران بماند، یک relay کوچک بیرون از ایران فقط Providerهای غربی فیلترشده/مستثناشده را مدیریت کند** | **این همان چیزی است که شما پیشنهاد دادید، و شکل درستی دارد.** هسته را نزدیک کاربرانتان نگه می‌دارد (نکته NIN در بخش 2) و قرارگیری واقعی در معرض فیلترینگ را به یک بخش محدود و شناخته‌شده از ترافیک محدود می‌کند. جزئیات در بخش 4. |
| D | تماس‌های فیلترشده را از طریق یک سرویس پراکسی/CDN «رفع‌مسدودسازی» شخص‌ثالث مسیر کنید، به‌جای VPS relay خودتان | تلاش راه‌اندازی کمتر است، اما قابلیت‌دسترسی و اعتبار IP و uptime آن به یک فروشنده وابسته می‌شود و کنترلی رویش ندارید. از نظر هزینه ارزش مقایسه دارد، اما یک relay خودگردان (دامنه ثبت‌شده خودتان، قوانین مسیریابی خودتان) همان افزونگی و رصدپذیری‌ای را می‌دهد که معماری تفکیک‌شده واقعاً به آن نیاز دارد. به‌عنوان رویکرد اصلی توصیه نمی‌شود. |
| E | بیشتر روی aggregatorهای داخلی ایران تکیه کنید، هرچیزی که نیاز به relay خارجی دارد را کوچک‌تر کنید | تا حدی از قبل درست است — instrumentهای داخلی از قبل پوشش داده شده‌اند. این یک بهبود روی C است، نه جایگزین آن: شعاع تأثیر C را کم می‌کند، ولی نیاز به آن را از بین نمی‌برد (`XAU_USD_OZ`/`XAG_USD_OZ` واقعاً هیچ منبع ایرانی ندارند). |
| F | افزونگی relay چندمنطقه‌ای — دو VPS relay کوچک در دو Provider/کشور متفاوت، نه فقط یک باکس اروپایی | در روز اول ضروری نیست، ولی بعداً افزودنش ارزان است و دقیقاً روی زیرساختی می‌نشیند که موتور قیمت‌گیری شما از قبل دارد (یک relay دوم فقط یک `FALLBACK` Provider رتبه‌بندی‌شده دیگر است — به بخش 6 نگاه کنید). توصیه می‌شود پس از اثبات C، نه پیش از آن. |

**توصیه: C، محدودشده توسط E، با F به‌عنوان یک پیگیری کوتاه‌مدت بعدی.**

---

## 4. تفکیک پیشنهادی، با جزئیات

**هسته (VPS ایران) — بدون تغییر:** PostgreSQL/TimescaleDB، Redis، FastAPI،
فرانت‌اندهای web/admin/desktop، پخش WebSocket (fan-out)، تحویل هشدار،
worker تلگرام. تمام تماس‌های Provider داخلی ایران (Alanchand، TALA،
Navasan، Nerkh.io، Servix، Tetherland، و هر منبع داخلی BRSAPI/دیگری که
اضافه کنید) دقیقاً مثل امروز مستقیماً از همین‌جا فراخوانی می‌شوند — بدون
relay، بدون دلیلی برای مسیرکردن ترافیک داخلی-به-داخلی از یک پرش خارجی.

**Relay (VPS غیر-ایران) — جدید، کوچک، بدون‌حالت (stateless):** تنها کارش
این است که بین هسته ایران و آن پنج یا شش هاست‌نیم غربی جدول بخش 1 بنشیند.
دو راه برای ساختنش هست، به‌ترتیب کمترین تغییر در کد فعلی‌تان:

**4.1 Relay پراکسی معکوس شفاف (نقطه شروع پیشنهادی).** relay با nginx یا
Caddy اجرا می‌شود، و برای هر Provider تحت‌تأثیر یک مسیر ارائه می‌کند که
مستقیماً به‌سمت فروشنده reverse-proxy می‌شود — مثلاً
`https://relay.<yourdomain>/coinbase/*` → `https://api.exchange.coinbase.com/*`.
روی هسته ایران، چیزی جز پیکربندی تغییر نمی‌کند: تنظیمات `*_api_base_url`
تحت‌تأثیر را در `.env` به‌سمت relay به‌جای دامنه خود فروشنده هدایت کنید، و
هاست‌نیم relay را به `PRICING_PROVIDER_ALLOWED_HOSTS` اضافه کنید. گارد
egress در `apps/api/app/pricing/providers.py` (حدود خط 551 تا 558) یک
تطبیق *دقیق* هاست‌نیم در برابر آن allowlist انجام می‌دهد — یک هاست‌نیم جدید
همه‌ی Providerهایی که از طریق relay مسیر می‌کنید را پوشش می‌دهد، و هر
parser در `apps/api/app/pricing/parsers/` کاملاً بدون تغییر کار می‌کند،
چون از دید parser هنوز دارد با شکل پاسخ Coinbase صحبت می‌کند، فقط از یک درِ
ورودی متفاوت. این کم‌هزینه‌ترین مسیر است و اولین چیزی است که باید ساخته
شود.

**4.2 Relay تجمیع‌کننده (بعداً، اگر بخواهید).** relay اپلیکیشن کوچک
FastAPI/Flask خودش را اجرا می‌کند که خودش با فروشندگان غربی تماس می‌گیرد،
پاسخ‌هایشان را نرمال‌سازی می‌کند، و یک endpoint یکپارچه ارائه می‌دهد. هسته
ایران در این حالت به‌جای چند base URL هدایت‌شده، فقط یک `ProviderDefinition`
جدید در `registry.py` دارد. کار بیشتری می‌برد، و کلیدهای API Provider را
از هسته به باکس relay منتقل می‌کند — اگر می‌خواهید مدارک اعتباری فروشنده
مشخصاً بیرون از ایران باشد، بعداً ارزش انجام‌دادن دارد، ولی برای حل مسئله
فیلترینگ به‌تنهایی لازم نیست. با 4.1 شروع کنید؛ فقط اگر دلیل مشخصی داشتید
به 4.2 بروید.

**در هر صورت، relay یک مرز اعتماد (trust boundary) جدید است — آن را قفل
کنید.** حداقلش: یک هدر رمز مشترک (shared-secret) که هسته می‌فرستد و relay
پیش از پراکسی‌کردن بررسی می‌کند، به‌علاوه یک allowlist آی‌پی روی relay که
ورودی را به IP هسته محدود می‌کند. اگر می‌خواهید فراتر بروید، mTLS. مسیرهای
پراکسی relay را بدون احراز هویت روی اینترنت باز رها نکنید — وگرنه هرکسی
می‌تواند از relay شما به‌عنوان یک پراکسی ناشناس رایگان به Coinbase/CoinGecko
استفاده کند، که دقیقاً همان چیزی است که باعث می‌شود IP یک relay سریع در
فهرست سیاه قرار بگیرد.

---

## 5. لایه انتقال: هسته چطور واقعاً با relay صحبت می‌کند

سه گزینه واقعی، با توجه به آنچه بخش 2 درباره‌ی دوطرفه و مبتنی‌بر DPI بودن
فیلترینگ ایران نشان داد:

| روش | چطور کار می‌کند | نتیجه‌گیری |
| --- | --- | --- |
| **HTTPS ساده، هسته از relay می‌کشد (pull)** | هسته طبق زمان‌بندی به `https://relay.yourdomain.com/...` تماس می‌گیرد، دقیقاً همان الگوی هر تماس Provider دیگری امروز | ساده‌ترین حالت، با صفر مفهوم زیرساختی جدید، دقیقاً با کد egress-guard/circuit-breaker موجود جور در می‌آید. در معرض همان بازرسی SNI/DPI هر تماس HTTPS خارجی دیگری است — خارج از رویدادهای فیلترینگ حاد خوب کار می‌کند، ممکن است در طول آن‌ها افت کند، مثل هرچیز دیگری. **از این‌جا شروع کنید.** |
| **تونل معکوس SSH، هسته به‌سمت relay اتصال خروجی می‌زند، relay از طریق پورت محلی برمی‌گرداند** | هسته ایران یک اتصال SSH خروجی به relay باز می‌کند (یا برعکس) و ترافیک دریافت قیمت را از آن تونل عبور می‌دهد | یک اپراتور واقعی که دقیقاً با همین رژیم سانسور روی یک اتصال ایرانی مبتنی‌بر MCI سروکار داشت، دید که SSH وقتی HTTPS عمومی خارجی کاملاً مسدود بود، سریع و کارآمد باقی ماند. [[LowEndTalk](https://lowendtalk.com/discussion/206643/iran-internet-update-for-hosting-providers-and-users)] ارزش راه‌اندازی به‌عنوان یک **انتقال fallback** دارد، اگر HTTPS ساده به relay از VPS/اپراتور خاص شما غیرقابل‌اعتماد ثابت شد — قطعات متحرک بیشتری دارد (uptime تونل خودش یک چیز جدا برای رصد می‌شود)، و هزینه پهنای‌باند را در هر دو پا می‌پردازید. |
| **تونل WireGuard/VPN** | تونل رمزنگاری‌شده دائمی بین هسته و relay | برای این کاربرد محدود، سربار بیشتری نسبت به SSH برای اجرا دارد، و پروتکل‌های VPN قبلاً مشخصاً هدف فیلترینگ ایران بوده‌اند (بخش 2). آشکارا از SSH در این‌جا بهتر نیست. توصیه نمی‌شود مگر این‌که از قبل به دلایل دیگری یکی را اجرا می‌کنید. |

**توصیه: اول HTTPS pull را بسازید (بخش 4.1 از قبل همین را فرض می‌کند)، و
تونل SSH را به‌عنوان fallback مستند در جیب پشتی نگه دارید اگر دیدید مسیر
HTTPS ساده به relay خاص شما افت می‌کند.** هردو را در روز اول نسازید —
مسیر ساده را بسنجید، ببینید واقعاً از اپراتور خاص VPS شما چطور رفتار
می‌کند، بعد تصمیم بگیرید.

---

## 6. این چطور با کدبیسی که از قبل دارید جور در می‌آید

نیازی به یک انتزاع (abstraction) جدید ندارید — موتور قیمت‌گیری از قبل یکی
دارد که دقیقاً با این جور در می‌آید:

- `PROVIDERS_BY_INSTRUMENT` در `apps/api/app/pricing/registry.py` از قبل
  چند منبع به‌ازای هر instrument را بر اساس تازگی کش، وضعیت circuit، امتیاز
  اعتماد و فشار بودجه رتبه‌بندی می‌کند (`service.py`، `_rank_candidates`).
  یک relay دوم (سناریو F) فقط یک `ProviderDefinition` دیگر با نقش
  `FALLBACK` است — منطق رتبه‌بندی، circuit-breaker و retry در
  `providers.py` به‌طور خودکار روی آن هم اعمال می‌شود، بدون نیاز به مسیر
  کد جدید.
- allowlist خروجی (`PRICING_PROVIDER_ALLOWED_HOSTS`) و گارد `configured()`
  روی هر `ProviderDefinition` دقیقاً همان مکانیزمی است که برای افزودن و
  بعداً حذف تمیز یک هاست‌نیم relay استفاده می‌کنید.
- `GET /api/prices/health` و `startup.instruments_without_direct_source`
  از قبل نشان می‌دهند وقتی یک زنجیره منبع کارآمدی ندارد — به‌محض این‌که
  relay وجود داشته باشد، یک قطعی relay دقیقاً همان‌طور که هر قطعی Provider
  دیگری نمایان می‌شود، آن‌جا نمایان خواهد شد. ارزش دارد پس از cutover
  مشخصاً این endpoint را برای `XAU_USD_OZ`/`XAG_USD_OZ`/`USDT_USD`/`BTC_USD`
  تحت‌نظر بگیرید، چون این‌ها دقیقاً همان instrumentهایی هستند که کل زنجیره
  منبع غیر-تلگرامی‌شان از طریق relay جدید عبور می‌کند.
- این هم‌چنین یک نقطه شروع مشخص و کم‌هزینه برای بستن شکاف رصدپذیری‌ای است
  که `PROJECT_STATUS.md` از قبل به آن اشاره کرده (شمارنده‌های Prometheus
  اعلام‌شده که هیچ‌چیزی آن‌ها را افزایش نمی‌دهد) — یک شمارنده خطای مخصوص
  relay می‌توانست در عرض چند دقیقه به شما بگوید مسیر relay افت کرده،
  به‌جای این‌که بعداً از طریق قیمت‌های `derived_fallback` متوجه شوید.

---

## 7. سؤال حقوقی، جدا از سؤال مهندسی

این چیزی نیست که من بتوانم برایتان حل کنم، و ترجیح می‌دهم این را صریح بگویم
تا حدس بزنم. دو چیز مجزا هم‌زمان درست‌اند:

**مسیرکردن از طریق یک IP اروپایی، فیلترینگ فنی ایران را حل می‌کند.** یک
relay در آلمان، فنلاند، یا هرجای دیگر واقعاً شما را از DPI خروجی ایران عبور
می‌دهد — آن بخش یک مسئله مهندسی سرراست با یک پاسخ مهندسی سرراست است (بخش
4).

**لزوماً محدودیت قراردادی یک فروشنده روی ایران را حل نمی‌کند، و ممکن است
اصلاً به آن دست هم نزند.** شرایط API کوین‌گکو (بخش 11.2، تأییدشده در بالا)
از شما می‌خواهد ضمانت دهید که شما و نهادتان در کشوری که در فهرست
«کشورهای مستثنا»ی آن‌هاست اقامت ندارید — این یک اظهار درباره‌ی *این‌که شما
کی هستید* است، نه *کدام آدرس IP دارد تماس می‌گیرد*. یک relay اروپایی نقطه
اجرای فنی (geofencing مبتنی‌بر IP) را تغییر می‌دهد، بدون این‌که واقعیت
زیربنایی‌ای که آن ضمانت‌نامه واقعاً درباره‌اش است تغییر کند، اگر نهاد
بهره‌بردار مستقر در ایران باشد. این‌که آیا این تفاوت در عمل اهمیتی دارد —
آیا یک مشکل واقعی است، یک مشکل نظری، یا چیزی که اجرای خودِ CoinGecko
هیچ‌وقت فراتر از IP به آن نگاه نمی‌کند — یک قضاوت حقوقی است، نه یک قضاوت
مهندسی، و درست کنار سؤال OFAC مربوط به Nobitex/Wallex قرار می‌گیرد که در
`docs/api-providers-reference.md` بخش 0 قبلاً مطرح شده. هردو ارزش یک
گفت‌وگو با وکیل را دارند پیش از این‌که این مسیر جلوتر برود، به‌ویژه پیش از
هر راه‌اندازی تجاری — نه به‌این‌خاطر که هرکدام لزوماً مانع ادامه‌کار است،
بلکه چون «به آن فکر نکردیم» موضعی ضعیف‌تر از «تصمیمی آگاهانه گرفتیم» است،
هرطرفی که آن تصمیم برود.

---

## 8. چیزی که این حل نمی‌کند

با خودتان درباره‌ی سقف این کار صادق باشید. در طول قطعی حاد ملی فوریه 2026،
«دسترسی عمومی به اینترنت جهانی» برای کاربران عادی «قطع شد»، و حتی بیشتر
پروتکل‌های VPN/دورزدن هم از کار افتادند.
[[arxiv.org/2603.28753](https://arxiv.org/html/2603.28753v1)] هیچ معماری
relay، هیچ ترفند CDN، هیچ تونل SSH از یک قطعی کامل اعلام‌شده جان سالم به‌در
نمی‌برد — هیچ‌چیز، به‌طور ذاتی. آنچه این معماری برایتان می‌خرد، تاب‌آوری در
برابر وضعیت *عادی* فیلترینگ ایران است (انتخابی، مبتنی‌بر DPI، وابسته به
ISP، بیشتر اوقات)، نه مصونیت در طول یک قطعی کامل با انگیزه امنیت‌ملی. در
طول چنین رویدادهایی، instrumentهای داخلی محصول شما (همان‌هایی که
کاربرانتان واقعاً بیشترین اهمیت را برایشان قائل‌اند) دقیقاً همان‌هایی
هستند که NIN طوری ساخته شده که فعال بمانند — که یک دلیل دیگر است برای
این‌که کوچک‌کردن دامنه در بخش 1 اهمیت دارد: هرچه هسته‌تان کمتر به چیزی که
از مرز عبور می‌کند وابسته باشد، سطح در معرض‌خطرتان در مهم‌ترین رویدادها
کوچک‌تر است.

---

## 9. برنامه اقدام

1. از ارائه‌دهنده VPS ایرانی‌تان بپرسید سرور از چه اپراتور بالادستی و چه
   سطح اتصالی (درجه خانگی در برابر تجاری/دیتاسنتر) استفاده می‌کند — این
   تعیین می‌کند کدام موقعیت relay و کدام لایه انتقال واقعاً برای شما کار
   می‌کند.
2. یک VPS relay کوچک راه‌اندازی کنید (Hetzner، OVH یا Contabo در اروپا
   نقطه‌های شروع معقول و پراستفاده‌ای هستند؛ هم‌چنین ارزش مقایسه با یک
   میزبان مستقر در ترکیه یا امارات را دارد، که برخی اپراتورها گزارش
   می‌دهند دسترسی بهتری به ایران نسبت به اروپای غربی دارد — تست کنید، فرض
   نکنید).
3. پراکسی معکوس شفاف (بخش 4.1) را دقیقاً برای همان پنج یا شش هاست‌نیم
   غربی شناسایی‌شده در بخش 1 بسازید. هیچ‌چیز دیگری نیازی به جابه‌جایی
   ندارد.
4. پیش از این‌که relay به چیز واقعی‌ای دست بزند، یک رمز مشترک + allowlist
   آی‌پی بین هسته و relay اضافه کنید.
5. تنظیمات `*_api_base_url` تحت‌تأثیر و مدخل `PRICING_PROVIDER_ALLOWED_HOSTS`
   را هدایت مجدد کنید؛ هر parser را دست‌نخورده بگذارید.
6. یک هفته `GET /api/prices/health` را تحت‌نظر بگیرید. اگر مسیر relay از
   اپراتور خاص شما ناپایدار بود، پیش از رفتن به‌سمت چیز سنگین‌تر، fallback
   تونل SSH (بخش 5) را اضافه کنید.
7. هم‌زمان نظر حقوقی بخش 7 را بگیرید — مانع عرضه relay نمی‌شود، ولی باید
   پیش از این‌که بخواهید این تصمیم را جلوی هرکسی خارج از این اتاق توجیه
   کنید، انجام‌شده باشد.
8. به‌محض پایدارشدن، افزودن یک relay دوم در یک Provider/منطقه متفاوت را
   در نظر بگیرید (سناریو F) — بیمه‌ای ارزان، و فقط یک مدخل `FALLBACK`
   دیگر در کدی است که از قبل دارید.

</div>
