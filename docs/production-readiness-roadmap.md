# Nerkhbaan — Production Readiness Roadmap

> Current correction, 2026-09-13: this file preserves the 2026-08-24 plan as a
> historical baseline. Structured metrics/logging, a two-replica production
> backend, real PostgreSQL/Redis integration gates, browser sign-up and alert
> CRUD, production deployment, and Iranian BTC fallback proof are complete.
> Current open work lives in `FUTURE_TASKS.md`; release facts live in
> `PROJECT_STATUS.md`.

Synthesizes three sources already in this repository/session: `PROJECT_STATUS.md`
(engineering audit, assessed 2026-08-20), `FUTURE_TASKS.md`, and the two prior
deliverables from this conversation — `docs/api-providers-reference.md` (data
sourcing) and `docs/iran-filtering-infrastructure-analysis.md` (cross-border
infra). Nothing here is invented; every item is traceable to one of those four
documents or to this file's own "Added recommendations" section, which is
labelled as new.

Assessed 2026-08-24. Re-run `npm run verify` and re-check `/api/prices/health`
before trusting any status claim below — this file goes stale the moment the
code moves.

---

## Verdict, in one line

**Feature-complete and internally hardened; not yet operated in production; two
compliance questions are open that the engineering audit didn't cover.**
Overall engineering score from `PROJECT_STATUS.md`: **8/10**. That score does
not include the Nobitex/Wallex OFAC exposure or the Iran-outbound filtering
question — both are tracked separately below because neither is an engineering
defect, and neither was in scope for that audit.

---

## Scorecard

| Area | Score | Blocking issue | Source |
| --- | --- | --- | --- |
| Pricing correctness | 8/10 | Toman metals mostly formula-derived without paid keys | `PROJECT_STATUS.md` |
| Security | 9/10 | No third-party review; no production pen test | `PROJECT_STATUS.md` |
| Data integrity | 9/10 | Off-host backup and restore drill unproven | `PROJECT_STATUS.md` |
| API design | 9/10 | No route-level integration tests | `PROJECT_STATUS.md` |
| Frontend | 7/10 | Web and desktop duplicated; no E2E coverage | `PROJECT_STATUS.md` |
| Observability | 5/10 | Metrics endpoint declares counters nothing increments | `PROJECT_STATUS.md` |
| Deployment | 8/10 | Single-host, single-worker; no staging environment | `PROJECT_STATUS.md` |
| Documentation | 9/10 | — | `PROJECT_STATUS.md` |
| Testing | 7/10 | Strong units, no integration or browser layer | `PROJECT_STATUS.md` |
| **Compliance (crypto sourcing)** | **not scored** | **Two of four crypto sources are OFAC SDN-listed (2026-06-02)** | `api-providers-reference.md` §0 |
| **Compliance (vendor ToS)** | **not scored** | CoinGecko's Excluded Countries clause; not checked for other Western vendors | `api-providers-reference.md` §0, `iran-filtering...` §7 |
| **Cross-border reachability** | **not scored** | No relay exists yet for the ~5-6 Western-only hostnames Iran's DPI can filter | `iran-filtering-infrastructure-analysis.md` |

---

## What is done

**Pricing engine.** 11 explicitly modelled instruments; multi-source ranking by
freshness/circuit-state/trust/budget; anomaly detection with independent
verification before publication; source-family independence enforcement;
durability-before-publication; labelled formula fallback with depeg guard;
egress control (allowlist, HTTPS-required, size caps, per-provider budgets,
circuit breakers).

**Auth.** Refresh-token family rotation with reuse detection, security-versioned
access tokens, bcrypt+SHA-256 prehash, constant-time comparison, and — for
admin — CSRF, origin pinning, UA/IP binding, RBAC, re-auth windows, full audit
trail.

**Alerts.** Idempotent triggers, `SKIP LOCKED` claiming, backoff+jitter,
dead-letter path, eligibility gating against suspicious/expired/unpersisted
prices, five delivery channels each requiring explicit verification.

**Frontend.** React PWA with live WebSocket prices and a poll-based liveness
fallback, RTL-first bilingual UI, hardened Electron shell (context isolation,
sandbox, no node integration, `safeStorage` credentials).

**Infra.** Six checksummed idempotent migrations the API verifies at startup,
health-gated Compose stack with nightly backups, edge nginx with TLS/HSTS/CSP
and per-route rate limits, CI with SHA-pinned actions, a real PostgreSQL race
test, and Trivy scans failing on HIGH/CRITICAL.

**A full internal audit already ran** (2026-08-20) and fixed 7 launch-blocking
defects, 23 high-severity issues, and ~50 medium/low findings — including a
silver instrument with zero providers, a missing egress-allowlist entry, an
IP-spoofing hole via unfiltered `X-Forwarded-For`, and a CSP that silently
wasn't being sent. Full list in `PROJECT_STATUS.md` → "What was found and
fixed."

**Data-sourcing groundwork (this conversation's own prior work).** Every
currently-wired provider is catalogued with cost/auth/role
(`api-providers-reference.md`), and a cross-border architecture for the
handful of Western-only providers has been fully designed, down to the exact
allowlist and config changes needed (`iran-filtering-infrastructure-analysis.md`
§4) — designed, not yet built.

---

## What is not done

### Track A — Engineering & operations (from `PROJECT_STATUS.md`)

1. **Observability.** `/metrics` declares Prometheus counters; none are ever
   incremented. No dashboard, no alert rules, no structured logging — the
   `request_id` in error responses isn't machine-parseable.
2. **No integration or E2E tests.** 158 backend tests are all units; nothing
   exercises an HTTP route against a real database; no browser test exists for
   sign-in, alert creation, or delivery.
3. **Web/desktop duplication.** `apps/desktop` carries its own ~2,500-line copy
   of `apps/web`'s API client and views, already drifting.
4. **Single-host, single-worker deployment.** No horizontal scaling proof, no
   staging environment, no blue/green deploy, no load test — even though the
   background loops are already built to be replica-safe.
5. **Off-host backup/restore unproven.** Nightly dumps exist locally; no
   confirmed off-host copy, no timed restore drill.
6. **Eight operator-evidence gates outstanding** (`FUTURE_TASKS.md`): provider
   redistribution rights, live canary proof, secret-injection proof, Navasan
   HTTPS-proxy proof, BRSAPI/TSETMC ownership record, off-host restore proof,
   production deployment/health proof, authenticated browser smoke proof.

### Track B — Data sourcing & compliance (from `api-providers-reference.md`)

7. **Nobitex/Wallex OFAC exposure — unresolved, and absent from the engineering
   audit.** Both are SDN-designated (2026-06-02) and are currently PRIMARY/
   FALLBACK for `USDT_TOMAN`/`BTC_TOMAN`. This needs a legal decision, not a
   code fix, and `PROJECT_STATUS.md` — assessed two months after the
   designation — never mentions it. Treat this as a Tier-1-equivalent
   blocker: it's a compliance risk, not a code-quality one, but it can gate a
   commercial launch just as hard as a missing backup drill can.
8. **`USD_TOMAN` has no trustworthy free source.** Every free candidate found
   scrapes/mirrors `bonbast.com` with maintainers who explicitly disclaim
   uptime. The real fix is configuring Navasan or the keyed Servix free tier (already wired, just
   disabled) — a business decision, already flagged identically in
   `PROJECT_STATUS.md`'s "Known limitations."
9. **`SILVER_925_TOMAN_GRAM` has zero providers anywhere, free or paid** —
   confirmed a thin market, not a research gap. Formula-derived is the only
   option barring a direct bullion-dealer relationship.
10. **Housekeeping debt:** CoinCap's free endpoint likely dead (needs a
    5-minute check against `pro.coincap.io`); BRSAPI's docs were never
    fetched/verified; Arzbin and Ticaro have working parsers with no registry
    entry — cheapest possible wins, hours not days.
11. **CoinGecko's Excluded-Countries clause** (and probably equivalent
    boilerplate at other US-domiciled vendors) is a *contractual* exclusion
    that a technical relay does not necessarily cure — separate legal
    question, detailed in `iran-filtering-infrastructure-analysis.md` §7.

### Track C — Cross-border infrastructure (from `iran-filtering-infrastructure-analysis.md`)

12. **No relay exists yet.** The ~5-6 Western-only hostnames
    (`GoldAPI`/`Gold-API`/`Metals.dev` for `XAU`/`XAG`, `Coinbase`/`CoinGecko`/
    `CoinCap` for the international USD legs) are still called directly from
    the Iran VPS and are exposed to Iran's outbound DPI/SNI filtering. The fix
    is designed (transparent reverse-proxy relay, §4.1) but not deployed.
13. **No empirical read on the Iran VPS's own carrier/tier.** The whole relay
    design depends on knowing whether the box's upstream (MCI, Irancell, etc.)
    and connectivity class behave the way the cited reports describe — this
    hasn't been tested against the actual production box yet.

---

## Phased plan

### Phase 0 — Quick wins (hours to ~2 days each, do these first)

| Item | Effort | Track |
| --- | --- | --- |
| Wire the Arzbin parser (registry entry + base-URL setting) — closes part of the `USD_TOMAN` gap for free | Hours | B |
| Add `xaus.com` as a second free `XAU`/`XAG` verifier | Hours | B |
| Confirm CoinCap's endpoint dead or alive; fix or remove | Hours | B |
| Verify BRSAPI's docs directly against `brsapi.ir` | ~1 hour | B |
| Ask the Iran VPS provider which upstream carrier/tier the box has | ~1 day (vendor-dependent) | C |
| Open the Nobitex/Wallex + CoinGecko-ToS question with counsel — start the clock now, even before Phase 1 finishes | Hours to initiate | B |

### Phase 1 — Required before real users (2–3 weeks, `PROJECT_STATUS.md` Tier 1)

1. Observability: increment the existing counters, structured JSON logs,
   Prometheus + Grafana with real alert rules. *3–5 days.*
2. Integration test layer against a real Postgres/Redis. *4–6 days.*
3. Off-host encrypted backups + a timed restore drill. *1–2 days.*
4. Full production deployment proof (edge profile, TLS chain, 24h stable
   refresh). *2–3 days.*
5. Provider agreements for `USD_TOMAN` and Iranian silver — business decision,
   not estimated in engineering time.

**Run in parallel, not after:**

6. Build the reverse-proxy relay (Track C item 12) — independent of the above,
   ~1 week end to end once the carrier question (Phase 0) is answered.
7. Land the Nobitex/Wallex legal decision (Track B item 7) — this should be
   **closed, one way or another, before Phase 1 exits**, exactly like the
   backup-restore drill is. An unresolved compliance question at commercial
   launch is not a lesser risk than an unproven backup.

### Phase 2 — Genuinely 10/10 (3–4 weeks, `PROJECT_STATUS.md` Tier 2)

8. Playwright E2E: sign in → create alert → trigger → receive notification.
   *4–5 days.*
9. Extract `packages/app-core`, delete the ~2,500 duplicated desktop lines.
   *5–8 days.*
10. Load/soak testing — WebSocket ceiling, `/api/prices` throughput, 10k
    active alerts, 72h leak watch. *3–4 days.*
11. Multi-replica verification — no duplicate refreshes/deliveries, correct
    lease handover. *2–3 days.*
12. Third-party security review of auth, admin surface, alert webhook path.
    *external.*

### Phase 3 — Polish / ongoing

13. Blue/green or canary deploys with rollback.
14. Staging environment mirroring production.
15. Formal SLOs (price freshness, alert latency, availability) with error
    budgets.
16. Per-user API keys/quotas if the API is ever exposed to third parties.
17. WCAG 2.1 AA accessibility audit.
18. Multi-region relay redundancy (Track C, Scenario F) — cheap once the
    first relay is proven; just another `FALLBACK` provider entry.

### Estimated total

| Tier | Effort | Outcome |
| --- | --- | --- |
| Phase 0 | ~2–3 days | Cheap cleanups done, legal clock started |
| Phase 1 | 2–3 weeks | Safe for real users, compliance question closed, relay live |
| Phase 2 | 3–4 weeks | Genuinely 10/10 |
| Phase 3 | ongoing | Mature operation |

---

## Added recommendations (new in this document — not in `PROJECT_STATUS.md` or the prior two docs)

**1. Turn the relay into a synthetic monitor, not just a proxy.** Once the
Track-C relay exists (Phase 1, item 6), also have it poll the public API from
outside Iran on a schedule. That gives you a second vantage point for free:
when a health check fails, you can tell "our server is down" apart from "Iran
is blocking us right now" — a distinction that matters a lot for a
majority-Iranian-user product and costs nothing beyond a cron job on a box
you're building anyway.

**2. Surface trust, don't just log it.** `/api/prices/health` already reports
which instruments are formula-derived (`derived_fallback`,
`fx_bridge_is_proxy`), but that's operator-only visibility. For a product
whose entire value proposition is "you can trust this price," put a small,
honest indicator in the PWA/desktop UI itself when a displayed price is
formula-derived rather than sourced directly — this is a small frontend change
that closes the gap between what the system knows and what the user sees.

**3. Sequence the desktop/web de-duplication earlier than Tier 2 suggests.**
`PROJECT_STATUS.md` places this at Phase 2 (item 9), after observability and
integration tests. If desktop has real users today, every Phase-1 change that
touches pricing/alert UI has to be written twice and can drift twice in the
meantime. Moving the `packages/app-core` extraction to the front of Phase 1 —
before, not after, the bulk of Phase-1 UI-adjacent work — pays for itself if
more than a couple of Phase-1/Phase-2 items touch shared UI. If desktop usage
is low, the original ordering is fine as-is.

**4. Give the legal questions a hard deadline, not a "someday."** Both the
OFAC exposure and the CoinGecko/vendor ToS question are flagged "get counsel"
in the prior docs with no date attached. Recommend treating "counsel's answer
received and a decision made" as a literal go/no-go gate on the same list as
the Phase-1 production-deployment proof — otherwise open-ended legal items
are exactly the kind that quietly slide past a launch date.

**5. Document backup-encryption key custody now, while it's cheap.**
Phase-1 item 3 (off-host encrypted backups) doesn't yet specify who holds the
encryption key, how it's rotated, or what the recovery procedure is if it's
lost. Two paragraphs in `redis-recovery.md` or a new `backup-recovery.md`
avoids finding this out during an actual incident.

**6. Write the incident/on-call runbook before Phase 1 exits, not after.**
The project already has strong individual runbooks (Redis recovery, pricing
operations) but nothing that says who gets paged, in what order, for what
severity. Cheap to write now; expensive to improvise during the first real
production incident — which, per this roadmap, is likely to land not long
after Phase 1 completes.

**7. Bundle the Phase-0 provider housekeeping into one sprint, not scattered
tickets.** CoinCap, BRSAPI, Arzbin, and xaus.com are each individually tiny,
but scattered across the backlog they tend to never get picked up because no
single one looks worth a dedicated ticket. Grouped as a single half-day
sprint, they're a fast, visible win before the multi-week Phase-1 push starts.

---

## Sources

- `PROJECT_STATUS.md` (this repo, assessed 2026-08-20) — engineering audit,
  scorecard, Tiers 1–3.
- `FUTURE_TASKS.md` (this repo) — operator-evidence checklist.
- `docs/api-providers-reference.md` (this conversation, 2026-08-24) — provider
  inventory, OFAC exposure, free/paid options.
- `docs/iran-filtering-infrastructure-analysis.md` (this conversation,
  2026-08-24) — cross-border relay architecture and legal-vs-technical
  distinction.

---

<div dir="rtl" lang="fa">

# نقشه راه آمادگی برای Production

این سند سه منبعی که از قبل در این ریپازیتوری/سشن وجود دارند را با هم ترکیب
می‌کند: `PROJECT_STATUS.md` (ممیزی مهندسی، بررسی‌شده در 2026-08-20)،
`FUTURE_TASKS.md`، و دو سند تحویلی قبلی همین گفت‌وگو — `docs/api-providers-reference.md`
(منابع داده) و `docs/iran-filtering-infrastructure-analysis.md` (زیرساخت
فرامرزی). هیچ‌چیز این‌جا از خودم اختراع نشده؛ هر مورد قابل‌ردیابی به یکی از
این چهار سند است، یا بخش «پیشنهادهای اضافه» همین فایل، که به‌صراحت به‌عنوان
جدید علامت‌گذاری شده.

بررسی‌شده در تاریخ 2026-08-24. پیش از اعتماد به هر ادعای وضعیتی در ادامه،
`npm run verify` را دوباره اجرا کنید و `/api/prices/health` را دوباره بررسی
کنید — این فایل به‌محض حرکت کد، قدیمی می‌شود.

---

## نتیجه‌گیری، در یک خط

**از نظر ویژگی کامل و از نظر داخلی سخت‌شده است؛ هنوز در Production عملیاتی
نشده؛ و دو سؤال حقوقی باز است که ممیزی مهندسی اصلاً آن‌ها را پوشش نداده.**
امتیاز کلی مهندسی از `PROJECT_STATUS.md`: **8 از 10**. این امتیاز شامل
ریسک OFAC مربوط به Nobitex/Wallex یا سؤال فیلترینگ خروجی ایران نمی‌شود —
هردو جدا در ادامه پیگیری شده‌اند، چون هیچ‌کدام یک نقص مهندسی نیستند، و
هیچ‌کدام در محدوده آن ممیزی نبودند.

---

## کارنامه (Scorecard)

| حوزه | امتیاز | مسئله مسدودکننده | منبع |
| --- | --- | --- | --- |
| صحت قیمت‌گذاری | 8/10 | فلزات تومانی عمدتاً بدون کلید پولی فرمولی‌اند | `PROJECT_STATUS.md` |
| امنیت | 9/10 | بدون بازبینی شخص‌ثالث؛ بدون تست نفوذ Production | `PROJECT_STATUS.md` |
| یکپارچگی داده | 9/10 | بکاپ خارج از هاست و تمرین بازیابی اثبات‌نشده | `PROJECT_STATUS.md` |
| طراحی API | 9/10 | بدون تست یکپارچگی سطح route | `PROJECT_STATUS.md` |
| فرانت‌اند | 7/10 | Web و Desktop تکراری؛ بدون پوشش E2E | `PROJECT_STATUS.md` |
| رصدپذیری (Observability) | 5/10 | endpoint متریک، شمارنده‌هایی اعلام می‌کند که هیچ‌چیز آن‌ها را افزایش نمی‌دهد | `PROJECT_STATUS.md` |
| استقرار (Deployment) | 8/10 | تک‌هاست، تک‌worker؛ بدون محیط staging | `PROJECT_STATUS.md` |
| مستندسازی | 9/10 | — | `PROJECT_STATUS.md` |
| تست | 7/10 | Unit testهای قوی، بدون لایه یکپارچگی یا مرورگر | `PROJECT_STATUS.md` |
| **Compliance (منابع کریپتو)** | **امتیازدهی نشده** | **دو مورد از چهار منبع کریپتو در فهرست SDN توسط OFAC هستند (2026-06-02)** | `api-providers-reference.md` بخش 0 |
| **Compliance (شرایط فروشندگان)** | **امتیازدهی نشده** | بند «کشورهای مستثنا»ی CoinGecko؛ برای فروشندگان غربی دیگر بررسی نشده | `api-providers-reference.md` بخش 0، `iran-filtering...` بخش 7 |
| **دسترسی فرامرزی** | **امتیازدهی نشده** | هنوز هیچ relay-ای برای آن 5 تا 6 هاست‌نیم غربی که DPI ایران می‌تواند فیلتر کند وجود ندارد | `iran-filtering-infrastructure-analysis.md` |

---

## چه چیزی انجام شده

**موتور قیمت‌گذاری.** 11 instrument مدل‌شده صریح؛ رتبه‌بندی چندمنبعی بر اساس
تازگی/وضعیت circuit/اعتماد/بودجه؛ تشخیص anomaly با راستی‌آزمایی مستقل پیش از
انتشار؛ اجرای استقلال source-family؛ ماندگاری پیش از انتشار؛ fallback فرمولی
برچسب‌خورده با گارد depeg؛ کنترل egress (allowlist، HTTPS اجباری، سقف اندازه،
بودجه به‌ازای هر Provider، circuit breaker).

**احراز هویت.** چرخش خانواده refresh-token با تشخیص استفاده‌ی مجدد، توکن‌های
دسترسی با نسخه امنیتی، bcrypt به‌همراه prehash با SHA-256، مقایسه زمان‌ثابت،
و برای پنل ادمین — CSRF، پین‌کردن origin، بایند UA/IP، RBAC، پنجره‌های
احراز مجدد، ردیابی کامل audit.

**هشدارها.** trigger های idempotent، claim با `SKIP LOCKED`، backoff همراه با
jitter، مسیر dead-letter، gate واجدشرایطی در برابر قیمت‌های مشکوک/منقضی/ذخیره‌نشده،
پنج کانال تحویل که هرکدام به تأیید صریح نیاز دارند.

**فرانت‌اند.** React PWA با قیمت‌های زنده WebSocket و یک fallback poll-محور
برای liveness، رابط کاربری دوزبانه RTL-first، پوسته Electron سخت‌شده
(context isolation، sandbox، بدون node integration، اعتبارنامه‌ها در
`safeStorage`).

**زیرساخت.** شش migration idempotent و checksum‌شده که API در startup آن‌ها
را تأیید می‌کند، استک Compose با ترتیب health-gated و بکاپ شبانه، nginx لبه
با TLS/HSTS/CSP و rate limit به‌ازای هر route، CI با action های SHA-pin‌شده،
یک تست race واقعی PostgreSQL، و اسکن Trivy که روی HIGH/CRITICAL رد می‌شود.

**یک ممیزی کامل داخلی قبلاً انجام شده** (2026-08-20) و 7 نقص مسدودکننده
راه‌اندازی، 23 مسئله شدت‌بالا، و حدود 50 یافته متوسط/کم را برطرف کرده — از
جمله یک instrument نقره بدون هیچ Provider، یک مدخل گم‌شده در egress-allowlist،
یک حفره جعل IP از طریق `X-Forwarded-For` فیلترنشده، و یک CSP که به‌طور خاموش
اصلاً ارسال نمی‌شد. فهرست کامل در `PROJECT_STATUS.md` ← «What was found and
fixed».

**زمینه‌سازی منبع داده (کار قبلی خودِ همین گفت‌وگو).** هر Provider فعلاً
متصل، با هزینه/احراز هویت/نقش کاتالوگ شده (`api-providers-reference.md`)، و
یک معماری فرامرزی برای آن چند Provider غربی کاملاً طراحی شده، تا سطح دقیق
تغییرات allowlist و پیکربندی لازم
(`iran-filtering-infrastructure-analysis.md` بخش 4) — طراحی‌شده، هنوز
ساخته‌نشده.

---

## چه چیزی انجام نشده

### مسیر A — مهندسی و عملیات (از `PROJECT_STATUS.md`)

1. **رصدپذیری.** `/metrics` شمارنده‌های Prometheus اعلام می‌کند؛ هیچ‌کدام
   هرگز افزایش نمی‌یابند. بدون داشبورد، بدون قانون هشدار، بدون لاگ ساخت‌یافته
   — `request_id` در پاسخ‌های خطا به‌صورت ماشین‌خوان نیست.
2. **بدون تست یکپارچگی یا E2E.** 158 تست بک‌اند همگی unit هستند؛ هیچ‌کدام یک
   route HTTP را در برابر دیتابیس واقعی امتحان نمی‌کند؛ هیچ تست مرورگری برای
   ورود، ساخت هشدار، یا تحویل وجود ندارد.
3. **تکرار Web/Desktop.** `apps/desktop` نسخه خودش، حدود 2,500 خط، از
   API client و view های `apps/web` را حمل می‌کند که از قبل در حال انحراف است.
4. **استقرار تک‌هاست، تک‌worker.** بدون اثبات مقیاس‌پذیری افقی، بدون محیط
   staging، بدون استقرار blue/green، بدون تست بار — با این‌که حلقه‌های
   پس‌زمینه از قبل برای امنیت در چند replica ساخته شده‌اند.
5. **بکاپ/بازیابی خارج از هاست اثبات‌نشده.** dump شبانه به‌صورت محلی وجود
   دارد؛ بدون نسخه خارج از هاست تأییدشده، بدون تمرین بازیابی زمان‌سنجی‌شده.
6. **هشت gate شواهد عملیاتی هنوز باز است** (`FUTURE_TASKS.md`): حقوق
   بازتوزیع Provider، اثبات canary زنده، اثبات تزریق secret، اثبات proxy
   HTTPS نوسان، رکورد مالکیت BRSAPI/TSETMC، اثبات بازیابی خارج از هاست،
   اثبات استقرار/سلامت Production، اثبات smoke مرورگری احراز‌هویت‌شده.

### مسیر B — منابع داده و Compliance (از `api-providers-reference.md`)

7. **ریسک OFAC مربوط به Nobitex/Wallex — حل‌نشده، و غایب از ممیزی مهندسی.**
   هردو در فهرست SDN هستند (2026-06-02) و در حال حاضر PRIMARY/FALLBACK برای
   `USDT_TOMAN`/`BTC_TOMAN` هستند. این نیاز به یک تصمیم حقوقی دارد، نه یک
   رفع کد، و `PROJECT_STATUS.md` — که دو ماه بعد از این تحریم بررسی شده —
   اصلاً به آن اشاره نمی‌کند. این را به‌عنوان یک مسدودکننده هم‌ارز Tier-1 در
   نظر بگیرید: یک ریسک compliance است، نه یک ریسک کیفیت کد، ولی می‌تواند
   راه‌اندازی تجاری را دقیقاً به‌همان‌اندازه یک تمرین بکاپ ناقص مسدود کند.
8. **`USD_TOMAN` هیچ منبع رایگان قابل‌اعتمادی ندارد.** هر کاندید رایگان
   پیداشده، bonbast.com را اسکرپ یا آینه می‌کند و نگهدارنده‌هایش صراحتاً
   uptime را ضمانت نمی‌کنند. راه‌حل واقعی تنظیم Navasan یا سطح رایگان کلیددار Servix است
   (از قبل متصل، فقط غیرفعال) — یک تصمیم تجاری که در «Known limitations»ی
   `PROJECT_STATUS.md` هم عیناً همین‌طور علامت‌گذاری شده.
9. **`SILVER_925_TOMAN_GRAM` در هیچ‌کجا، رایگان یا پولی، هیچ Provider ندارد**
   — تأییدشده که یک بازار کم‌عمق است، نه یک شکاف تحقیقاتی. فرمولی‌بودن تنها
   گزینه است مگر یک رابطه مستقیم با فروشنده شمش.
10. **بدهی نظافت (housekeeping):** endpoint رایگان CoinCap احتمالاً مرده است
    (نیاز به 5 دقیقه بررسی در برابر `pro.coincap.io`)؛ مستندات BRSAPI هرگز
    fetch/تأیید نشده؛ Arzbin و Ticaro parser کارآمد دارند اما مدخل registry
    ندارند — ارزان‌ترین برد ممکن، ساعت است نه روز.
11. **بند «کشورهای مستثنا»ی CoinGecko** (و احتمالاً بندهای مشابه در دیگر
    فروشندگان مستقر در آمریکا) یک محدودیت *قراردادی* است که یک relay فنی
    لزوماً آن را برطرف نمی‌کند — یک سؤال حقوقی جدا، با جزئیات در
    `iran-filtering-infrastructure-analysis.md` بخش 7.

### مسیر C — زیرساخت فرامرزی (از `iran-filtering-infrastructure-analysis.md`)

12. **هنوز هیچ relay-ای وجود ندارد.** آن 5 تا 6 هاست‌نیم غربی
    (`GoldAPI`/`Gold-API`/`Metals.dev` برای `XAU`/`XAG`، `Coinbase`/`CoinGecko`/
    `CoinCap` برای پاهای بین‌المللی دلار) هنوز مستقیماً از VPS ایران فراخوانی
    می‌شوند و در معرض فیلترینگ DPI/SNI خروجی ایران هستند. راه‌حل طراحی شده
    (relay پراکسی معکوس شفاف، بخش 4.1) ولی مستقر نشده.
13. **بدون خوانش تجربی از اپراتور/سطح اتصال خودِ VPS ایران.** کل طراحی relay
    به این بستگی دارد که بدانید uplink باکس (MCI، ایرانسل، و غیره) و سطح
    اتصالش دقیقاً همان‌طور که در گزارش‌های نقل‌شده آمده رفتار می‌کند یا نه —
    این هنوز روی باکس واقعی Production تست نشده.

---

## برنامه فازبندی‌شده

### فاز 0 — بردهای سریع (چند ساعت تا حدود 2 روز هرکدام، اول این‌ها)

| مورد | تلاش | مسیر |
| --- | --- | --- |
| اتصال parser Arzbin (مدخل registry + تنظیم base-URL) — بخشی از شکاف `USD_TOMAN` را رایگان می‌بندد | چند ساعت | B |
| افزودن `xaus.com` به‌عنوان دومین verifier رایگان `XAU`/`XAG` | چند ساعت | B |
| تأیید مرده یا زنده‌بودن endpoint کوین‌کپ؛ رفع یا حذف | چند ساعت | B |
| راستی‌آزمایی مستقیم مستندات BRSAPI در `brsapi.ir` | حدود 1 ساعت | B |
| پرسیدن از ارائه‌دهنده VPS ایران درباره اپراتور بالادستی/سطح اتصال باکس | حدود 1 روز (بسته به فروشنده) | C |
| باز کردن سؤال Nobitex/Wallex + شرایط CoinGecko با وکیل — ساعت را همین حالا شروع کنید، حتی پیش از پایان فاز 1 | چند ساعت برای شروع | B |

### فاز 1 — لازم پیش از کاربران واقعی (2 تا 3 هفته، Tier 1 در `PROJECT_STATUS.md`)

1. رصدپذیری: افزایش شمارنده‌های موجود، لاگ JSON ساخت‌یافته، Prometheus +
   Grafana با قوانین هشدار واقعی. *3 تا 5 روز.*
2. لایه تست یکپارچگی در برابر Postgres/Redis واقعی. *4 تا 6 روز.*
3. بکاپ رمزنگاری‌شده خارج از هاست + یک تمرین بازیابی زمان‌سنجی‌شده. *1 تا 2 روز.*
4. اثبات کامل استقرار Production (پروفایل edge، زنجیره TLS، 24 ساعت refresh
   پایدار). *2 تا 3 روز.*
5. توافق‌نامه Provider برای `USD_TOMAN` و نقره ایرانی — تصمیم تجاری، بدون
   برآورد زمان مهندسی.

**موازی اجرا کنید، نه بعد از این‌ها:**

6. ساخت relay پراکسی معکوس (مسیر C، مورد 12) — مستقل از موارد بالا، حدود 1
   هفته سرتاسر به‌محض پاسخ‌دادن سؤال اپراتور (فاز 0).
7. رساندن تصمیم حقوقی Nobitex/Wallex به سرانجام (مسیر B، مورد 7) — این باید
   **پیش از پایان فاز 1، به یک نتیجه برسد**، دقیقاً مثل تمرین بازیابی بکاپ.
   یک سؤال compliance حل‌نشده در زمان راه‌اندازی تجاری، ریسک کمتری از یک
   بکاپ اثبات‌نشده ندارد.

### فاز 2 — واقعاً 10 از 10 (3 تا 4 هفته، Tier 2 در `PROJECT_STATUS.md`)

8. E2E با Playwright: ورود ← ساخت هشدار ← trigger ← دریافت اعلان. *4 تا 5 روز.*
9. استخراج `packages/app-core`، حذف حدود 2,500 خط تکراری desktop. *5 تا 8 روز.*
10. تست بار/soak — سقف WebSocket، throughput `/api/prices`، 10,000 هشدار
    فعال، رصد نشتی 72 ساعته. *3 تا 4 روز.*
11. راستی‌آزمایی چند-replica — بدون refresh/تحویل تکراری، تحویل صحیح lease.
    *2 تا 3 روز.*
12. بازبینی امنیتی شخص‌ثالث برای احراز هویت، سطح ادمین، مسیر webhook هشدار.
    *خارجی.*

### فاز 3 — پرداخت نهایی (Polish) / مستمر

13. استقرار blue/green یا canary با rollback خودکار.
14. محیط staging که Production را آینه می‌کند.
15. SLO رسمی (تازگی قیمت، تأخیر هشدار، در دسترس‌بودن) با error budget.
16. کلید/سهمیه API به‌ازای هر کاربر، اگر API روزی برای شخص‌ثالث باز شود.
17. ممیزی دسترسی‌پذیری WCAG 2.1 AA برای اپ وب.
18. افزونگی relay چندمنطقه‌ای (مسیر C، سناریو F) — به‌محض اثبات relay اول
    ارزان است؛ فقط یک مدخل `FALLBACK` Provider دیگر.

### برآورد کل

| فاز | تلاش | نتیجه |
| --- | --- | --- |
| فاز 0 | حدود 2 تا 3 روز | نظافت‌های ارزان انجام‌شده، ساعت حقوقی شروع‌شده |
| فاز 1 | 2 تا 3 هفته | امن برای کاربران واقعی، سؤال compliance بسته‌شده، relay زنده |
| فاز 2 | 3 تا 4 هفته | واقعاً 10 از 10 |
| فاز 3 | مستمر | عملیات بالغ |

---

## پیشنهادهای اضافه (جدید در این سند — نه در `PROJECT_STATUS.md` یا دو سند قبلی)

**1. relay را یک مانیتور مصنوعی (synthetic) هم بکنید، نه فقط یک پراکسی.**
به‌محض این‌که relay مسیر C وجود داشته باشد (فاز 1، مورد 6)، آن را طوری هم
تنظیم کنید که طبق زمان‌بندی از بیرون ایران، API عمومی خودتان را poll کند.
این رایگان یک نقطه‌دید دوم به شما می‌دهد: وقتی یک health check شکست
می‌خورد، می‌توانید تشخیص دهید «سرور ما خراب است» در برابر «همین الان ایران
دارد ما را مسدود می‌کند» — تمایزی که برای محصولی با اکثریت کاربران ایرانی
خیلی مهم است و چیزی جز یک cron job روی باکسی که به‌هرحال دارید می‌سازید
هزینه ندارد.

**2. اعتماد را نمایش دهید، نه فقط لاگ کنید.** `/api/prices/health` از قبل
نشان می‌دهد کدام instrumentها فرمولی هستند (`derived_fallback`،
`fx_bridge_is_proxy`)، ولی این فقط برای اپراتور قابل‌مشاهده است. برای
محصولی که کل ارزش‌پیشنهادی‌اش «می‌توانید به این قیمت اعتماد کنید» است، یک
نشانگر کوچک و صادقانه در خودِ رابط PWA/desktop بگذارید وقتی قیمت
نمایش‌داده‌شده فرمولی است، نه مستقیماً منبع‌دار — این یک تغییر فرانت‌اند کوچک
است که شکاف بین چیزی که سیستم می‌داند و چیزی که کاربر می‌بیند را می‌بندد.

**3. جداسازی desktop/web را زودتر از چیزی که Tier 2 پیشنهاد می‌دهد ترتیب
دهید.** `PROJECT_STATUS.md` این را در فاز 2 (مورد 9) قرار می‌دهد، بعد از
رصدپذیری و تست یکپارچگی. اگر desktop امروز کاربر واقعی دارد، هر تغییر
فاز-1 که به UI قیمت‌گذاری/هشدار دست می‌زند باید دوبار نوشته شود و می‌تواند
در این فاصله دوبار هم منحرف شود. جابه‌جایی استخراج `packages/app-core` به
جلوی فاز 1 — پیش از، نه بعد از، بخش عمده کار UI-محور فاز 1 — اگر بیش از
چند مورد فاز-1/فاز-2 به UI مشترک دست بزنند، هزینه‌اش را جبران می‌کند. اگر
استفاده از desktop کم است، ترتیب اصلی همین‌طور که هست خوب است.

**4. به سؤالات حقوقی یک مهلت قطعی بدهید، نه یک «یک روزی».** هم ریسک OFAC و
هم سؤال شرایط CoinGecko/فروشنده در اسناد قبلی با «با وکیل مشورت کنید» بدون
هیچ تاریخی علامت‌گذاری شده‌اند. توصیه می‌شود «پاسخ وکیل دریافت‌شده و تصمیم
گرفته‌شده» را دقیقاً مثل اثبات استقرار Production فاز 1، یک gate واقعی
برو/نرو در همان فهرست در نظر بگیرید — وگرنه موارد حقوقی بازمانده دقیقاً از
همان جنسی هستند که بی‌سروصدا از تاریخ راه‌اندازی عبور می‌کنند.

**5. مالکیت کلید رمزنگاری بکاپ را همین حالا مستند کنید، وقتی هنوز ارزان
است.** مورد 3 فاز 1 (بکاپ رمزنگاری‌شده خارج از هاست) هنوز مشخص نمی‌کند چه
کسی کلید رمزنگاری را نگه می‌دارد، چطور چرخانده می‌شود، یا اگر گم شود روال
بازیابی چیست. دو پاراگراف در `redis-recovery.md` یا یک `backup-recovery.md`
جدید، از فهمیدن این موضوع در وسط یک حادثه واقعی جلوگیری می‌کند.

**6. runbook حادثه/on-call را پیش از پایان فاز 1 بنویسید، نه بعد از آن.**
پروژه از قبل runbook های تک‌به‌تک قوی دارد (بازیابی Redis، عملیات قیمت‌گذاری)
ولی چیزی نیست که بگوید چه کسی، به چه ترتیبی، برای چه شدتی page می‌شود.
همین حالا نوشتنش ارزان است؛ در طول اولین حادثه واقعی Production
بداهه‌سازی‌اش گران است — که طبق همین نقشه راه، احتمالاً کمی بعد از پایان
فاز 1 اتفاق می‌افتد.

**7. نظافت Provider فاز 0 را در یک اسپرینت جمع کنید، نه تیکت‌های پراکنده.**
CoinCap، BRSAPI، Arzbin و xaus.com هرکدام به‌تنهایی خیلی کوچک‌اند، ولی
پراکنده در backlog معمولاً هرگز گرفته نمی‌شوند چون هیچ‌کدام به‌تنهایی ارزش
یک تیکت اختصاصی به‌نظر نمی‌رسد. گروه‌شده به‌عنوان یک اسپرینت نیم‌روزه، یک برد
سریع و قابل‌مشاهده پیش از شروع فشار چندهفته‌ای فاز 1 هستند.

---

## منابع

- `PROJECT_STATUS.md` (این ریپازیتوری، بررسی‌شده در 2026-08-20) — ممیزی
  مهندسی، کارنامه، Tier های 1 تا 3.
- `FUTURE_TASKS.md` (این ریپازیتوری) — چک‌لیست شواهد عملیاتی.
- `docs/api-providers-reference.md` (این گفت‌وگو، 2026-08-24) — فهرست
  Providerها، ریسک OFAC، گزینه‌های رایگان/پولی.
- `docs/iran-filtering-infrastructure-analysis.md` (این گفت‌وگو، 2026-08-24)
  — معماری relay فرامرزی و تمایز حقوقی-در-برابر-فنی.

</div>
