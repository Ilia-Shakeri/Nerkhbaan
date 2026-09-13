# Project Status and Audit Baseline

**Updated:** 2026-09-13 · **Release:** `2.4.0` · **Verdict:** release candidate;
production `2.3.3` is healthy; the validated silver relay awaits deployment

## Current release update

- Release candidate `2.4.0` adds a Git-backed pull relay for XAG/USD, BTC/USD,
  and USDT/USD. A scheduled runner validates the two free public sources and
  force-replaces a one-commit `price-feed` branch. A restricted production
  sidecar fetches only that branch, repeats route/time/range checks, signs the
  payload, and sends it only to the internal worker endpoint.
- The relay builder passed a live foreign-host test with three current records:
  XAG/USD, BTC/USD, and USDT/USD. Production and scheduled-run proof remain
  pending.

- Production `2.3.3` runs on two healthy backend replicas and one healthy web
  replica. Readiness reports PostgreSQL and Redis connected, current migrations,
  operational WebSocket fanout, and zero persistence, backfill, and dead-letter
  backlog.
- The public gold 24K canonical quote is live from the no-key Iranian reference.
  Gold 18K is a persisted derived fallback with the same five-minute safe input
  boundary. The public 30-day gold chart now has real stored points and will
  continue to fill on each source cycle.
- Silver remains the only empty public asset chart. Its enabled routes still
  lack a reachable, configured source.

- Release candidate `2.3.3` makes derived prices inherit the weakest vetted
  input boundary directly, preventing a second age penalty on derived gold 18K.

- Release candidate `2.3.2` aligns gold 24K and derived 18K freshness with the
  source's five-minute cache. Production `2.3.1` already writes gold chart
  points, but its one-minute instrument window leaves the card stale too often.

- Release candidate `2.3.1` fixes canonical freshness for accepted cached
  sources. The provider and canonical quote now share the same receive-anchored
  live, stale, and expiry windows.

- Release candidate `2.3.0` adds a no-key PersianToolbox 24K gold reference.
  It checks source time, freshness, source list, and the documented IRR-per-gram
  unit before conversion to Toman. Production proof remains pending.

- The production core runs release `2.2.1` on two healthy backend replicas and
  one healthy web replica. Readiness reports PostgreSQL and Redis connected,
  current migrations, operational WebSocket fanout, and `ready=true`.
- A fresh 37,186,217-byte PostgreSQL backup passed gzip validation immediately
  before deployment. Existing PostgreSQL and Redis volumes were retained.
- The local release gate now passes 179 backend tests with one PostgreSQL-only
  concurrency test skipped when `TEST_DATABASE_URL` is absent.
- A disposable production-host test stack passed the 14-stage HTTP smoke
  against real PostgreSQL and Redis. It covers
  auth boundaries, token-family reuse, alerts, pricing, charts, instruments,
  provider redaction, and representative 401/404/409/422 responses.
- That smoke exposed an untyped optional PostgreSQL filter in source history.
  Release `2.2.1` fixes it and the full smoke then passed.
- A real-browser CI flow covers sign-up and alert create/edit/delete. Trigger
  and delivery proof remain open.
- Price refresh metrics and structured request-id logs are implemented and
  covered by tests.
- Honest empty-chart states, CoinGecko history routes, and keyed Servix free-tier
  history routes are implemented.
- Release `2.2.1` keeps the Iranian BTC/USD provider timestamp intact while
  accepting its documented five-minute cache. Each accepted response gets only
  the normal short BTC live window from receipt; older payloads remain rejected.
- The production provider canary returned HTTP 200 for `persian_toolbox_btc`.
  The public site returned HTTP 200 and its anonymous auth guard returned 401.
- Production currently exposes four assets. BTC and USDT have live values and
  partial 30-day charts with 12 and 22 persisted points. Gold and silver still
  have no current value and no chart points. Pricing readiness is degraded with
  one fresh, four expired, and six unavailable instruments; this blocks final
  data-completeness sign-off.
- The external foreign worker remains disabled because direct traffic between
  the two current VPS networks is blocked. Core operation does not depend on it.

The detailed assessment below is the 2026-08-20 audit baseline. Later fixes are
tracked in [`CHANGELOG.md`](CHANGELOG.md), and open work in
[`FUTURE_TASKS.md`](FUTURE_TASKS.md).

Claims under "What is not done" and the tier plan are historical baseline text.
Use this current-release section and `FUTURE_TASKS.md` for present status.

An audit account of what existed, what worked, and what stood between the
repository and a 10/10 production system at the baseline date.

---

## Contents

- [Summary](#summary)
- [Scorecard](#scorecard)
- [What is done](#what-is-done)
- [What was found and fixed](#what-was-found-and-fixed)
- [What is not done](#what-is-not-done)
- [The road to 10/10](#the-road-to-1010)
- [Known limitations to accept or fund](#known-limitations-to-accept-or-fund)

---

## Baseline summary

Nerkhbaan is a full-stack market price platform: FastAPI backend, TimescaleDB
time-series storage, Redis for coordination, a React PWA, an admin console, an
Electron desktop shell, and an optional Telegram ingestion worker.

| | |
| --- | --- |
| Backend | 20,800 lines Python |
| Backend tests | 4,782 lines · **158 tests passing** |
| Web PWA | 6,239 lines TypeScript |
| Desktop | 4,310 lines |
| Admin console | 1,153 lines |
| Shared UI | 5,278 lines |
| SQL migrations | 1,395 lines, 6 files, checksummed |
| Frontend contracts | 18 tests passing |

The engineering quality of the core is high. The pricing engine's canonical-quote
state machine, the refresh-token family rotation, and the admin RBAC are all
better than typical for a project this size.

**The gap is not code quality. It is operational proof.** No component of this
system has been observed running in production under real load with real
provider credentials. Everything below distinguishes "verified by tests" from
"verified in production", because on a platform people trade on, that distinction
is the whole thing.

---

## Baseline scorecard

| Area | Score | Blocking issue |
| --- | --- | --- |
| Pricing correctness | 8/10 | Toman metals mostly formula-derived without paid keys |
| Security | 9/10 | No third-party review; no production pen test |
| Data integrity | 9/10 | Off-host backup and restore drill unproven |
| API design | 9/10 | No route-level integration tests |
| Frontend | 7/10 | Web and desktop duplicated; no E2E coverage |
| Observability | 5/10 | Metrics endpoint declares counters nothing increments |
| Deployment | 8/10 | Single-host, single-worker; no staging environment |
| Documentation | 9/10 | — |
| Testing | 7/10 | Strong units, no integration or browser layer |
| **Overall** | **8/10** | **Operational proof, observability, E2E** |

---

## What is done

### Pricing engine — the core

- **Instrument model.** 11 instruments, each with an explicit unit, purity,
  market, refresh/stale/expire windows, sanity bounds, anomaly thresholds and
  maximum acceptable spread. "Gold" is not a price; `XAU_USD_OZ` is.
- **Multi-source verification.** Providers ranked per refresh by cache
  freshness, credential state, circuit state, success rate, trust score,
  remaining budget and cost. External calls capped per cycle.
- **Anomaly handling.** Deviation thresholds adapt to recent volatility, the age
  of the previous value and provider reliability. A suspicious candidate is not
  published: the instrument goes `verifying`, independent verifiers are called,
  and the outcome is confirmation, median consensus over an inlier cluster, or
  retention of the previous value. Every anomaly is persisted and reviewable.
- **Independence enforcement.** A verifier only counts when its `source_family`
  *and* `venue` both differ. Two endpoints of one exchange do not corroborate
  each other; resellers are marked `opaque_aggregator`.
- **Durability before publication.** A quote must be durably stored before it can
  become canonical. Redis-only values report `unpersisted` and cannot fire alerts.
- **Derived pricing, labelled.** Formula fallback with purity ratios read from
  instrument definitions, depth limiting, cycle detection, and a depeg guard that
  refuses to reprice metals when USDT leaves its safe band.
- **Egress control.** Host allowlist, HTTPS-required-with-credentials, redirects
  disabled, streamed response size caps, per-provider minute/hour/day budgets
  with reserved quota for anomaly verification, circuit breakers honouring
  `Retry-After`.

### Authentication and authorisation

- Refresh-token rotation with family tracking; presenting an already-exchanged
  token revokes the entire family.
- Access tokens carry a security version; a password change invalidates every
  outstanding token immediately.
- bcrypt with SHA-256 prehash, correctly handling the 72-byte boundary.
- Constant-time comparison against a dummy hash for unknown users.
- Admin: session cookies, hashed double-submit CSRF, origin pinning, user-agent
  binding, optional IP binding and CIDR allowlist, per-permission RBAC,
  re-authentication windows and typed confirmations for destructive operations,
  last-super-admin protection, full audit trail.

### Alerts and delivery

- Idempotent triggers; one delivery job per channel with a unique constraint.
- `SKIP LOCKED` claiming, stuck-job reclaim, exponential backoff with jitter,
  dead-letter path, permanent-vs-transient failure classification.
- Eligibility policy: an alert never fires on a suspicious, expired or
  unpersisted price, on a source semantic the alert did not opt into, or when
  the order-book spread exceeds the instrument's bound.
- Channels: in-app, web push, email, Telegram, webhook. Each requires explicit
  verification before it delivers.

### Frontend

- React PWA with live WebSocket prices, sequence-deduplicated merging, and a
  slow poll retained as a liveness check.
- Service worker with real push and notification-click handlers, user-driven
  updates.
- RTL-first, Persian and English throughout.
- Electron shell hardened: context isolation, sandbox, no node integration,
  permission handlers denied, navigation allowlisted, credentials in
  `safeStorage`.

### Infrastructure

- Six ordered, checksummed, idempotent SQL migrations. The API verifies they are
  current and refuses to start otherwise.
- Compose stack with health-gated ordering, capability dropping, resource limits
  and a nightly backup job.
- Edge nginx with TLS, HSTS, CSP, per-route rate limits and a separate admin
  vhost.
- CI: SHA-pinned actions, lockfile drift check, migration idempotency proof, a
  real PostgreSQL race test for refresh rotation, Trivy secret/dependency/image
  scans failing on HIGH and CRITICAL, and nginx config validation against real
  nginx.

---

## What was found and fixed

A full production audit was performed against this repository. It found **7
launch-blocking defects, 23 high-severity issues, and roughly 50 medium and low
findings.** All were remediated. The ones that mattered most:

| Defect | Impact | Status |
| --- | --- | --- |
| Silver in Toman had zero registered providers | The flagship product served theoretical values with no indication | Fixed — provider added, coverage now computed and reported |
| One live gold provider's host was missing from the egress allowlist | Permanently failed as if the upstream were down | Fixed |
| Redis short-history retained 31 days of full payloads against a 256 MB `noeviction` cap | Would have filled and halted all pricing within days | Fixed — 6-hour bounded window |
| Every nginx block appended a caller-supplied `X-Forwarded-For` | Client IP forgeable: rate limits, admin IP allowlist and audit trail all bypassable | Fixed |
| `add_header` inheritance dropped CSP and X-Frame-Options in every content-serving location | The public site had no CSP and no clickjacking protection | Fixed — enforced by a structural test |
| Web push broken three ways | The primary alert channel never delivered | Fixed |
| Migration checksums computed two different ways | API refused to boot on any CRLF checkout | Fixed |
| Refresh lock expired mid-refresh, never renewed | Duplicate provider spend, racing writes | Fixed |
| One Redis pub/sub connection per WebSocket client | Redis exhausted long before the worker | Fixed — shared fan-out |
| Alert snapshots stored the entire price payload with history | Hundreds of KB per trigger row, re-read on every retry | Fixed |
| Spread eligibility gate read a bound nothing ever wrote | A dead safety control with a passing test | Fixed |
| Background loops chained | A slow provider stalled alert delivery | Fixed — independent loops |
| ~1,800 lines of dead pricing code, tested but unreachable | False CI confidence | Deleted |

### A note on the FX bridge

The audit found that Toman metal prices are reconstructed through a USD→Toman
rate, and that when no free-market USD source is configured, USDT stands in.
USDT trades at a persistent premium in Iran. Measured on representative inputs:

```
XAU 2400 USD · USD/TOMAN 58,000 · USDT/TOMAN 60,000
  via real USD rate  →  4,475,384 Toman/gram
  via USDT proxy     →  4,629,708 Toman/gram    (+3.4%)
```

A dedicated `USD_TOMAN` instrument was added and is preferred. Every derived
quote now records which bridge produced it (`fx_bridge_is_proxy`). **This is
mitigated, not solved** — see below.

---

## What is not done

### 1. Observability — the largest gap

`/metrics` exists and declares three Prometheus collectors. **None of them are
ever incremented.** There is no dashboard, no alerting rule, and no structured
logging: the `request_id` returned in every error response is not emitted as a
machine-parseable field, so correlating a user report to a log line means
grepping plain text.

For a system whose value proposition is *knowing whether a price is
trustworthy*, not being able to see its own behaviour in production is the
sharpest contradiction in the project.

### 2. No integration or end-to-end tests

158 backend tests, all units. Not one exercises an HTTP route against a real
database. There is no browser test for sign-in, alert creation, or delivery.
The layer where authentication, transactions and serialisation actually meet is
unverified.

### 3. Iranian price sources are thin

Without paid credentials the entire Toman metal side is formula output:

| Instrument | Reality without keys |
| --- | --- |
| `GOLD_18K_TOMAN_GRAM` | one key-gated provider, else derived |
| `GOLD_24K_TOMAN_GRAM` | key-gated and disabled by default, else derived |
| `SILVER_999_TOMAN_GRAM` | one key-gated provider, else derived |
| `SILVER_925_TOMAN_GRAM` | **formula only, no provider exists** |
| `USD_TOMAN` | key-gated, else derived from USDT |

This is now visible rather than silent — `/api/prices/health` reports it and
startup logs it — but visibility is not a price. **Commercial provider
agreements are the fix, and that is a business decision, not an engineering
task.**

### 4. Web and desktop are duplicated

`apps/desktop` carries its own copy of the API client and every view — roughly
2,500 lines already drifting from `apps/web`. A bug fixed in one is not fixed in
the other.

### 5. Single-host, single-worker deployment

One uvicorn worker. No horizontal scaling story, no staging environment, no
blue/green or canary deploy, no load test. The background loops are safe to run
in multiple replicas (distributed locks, `SKIP LOCKED` claiming) but this has
never been exercised.

### 6. Operator evidence outstanding

Eight gates in [`FUTURE_TASKS.md`](FUTURE_TASKS.md) remain unproven, including
provider redistribution rights, an off-host restore drill, and a production
deployment health record.

---

## The road to 10/10

Ordered by what actually removes risk.

### Tier 1 — required before taking real users (2–3 weeks)

**1. Observability.** *Est. 3–5 days.*
Increment the metrics that already exist: refresh outcome by instrument and
status, provider latency and failure by provider, canonical age, alert delivery
outcome, queue depths. Switch logging to structured JSON with `request_id`,
`instrument_id` and `provider_id` as fields. Stand up Prometheus and Grafana
with alert rules on: Redis memory >80%, any instrument `expired`, dead-letter
growth, migration drift, provider circuit open >5 minutes.
*Without this you cannot tell a healthy system from a broken one.*

**2. Integration test layer.** *Est. 4–6 days.*
`httpx.AsyncClient` against the real app with an ephemeral PostgreSQL and Redis.
Cover: signup → signin → refresh → rotation-reuse rejection; alert create →
trigger → delivery job → DLQ; admin auth including CSRF and origin rejection;
every endpoint's happy path and its 401/403/422. Run it in CI beside the
existing migration job.

**3. Off-host backups and a restore drill.** *Est. 1–2 days.*
Ship the nightly dump to object storage with retention and encryption. Perform a
timed restore into a disposable database and record the RTO. A backup nobody has
restored is a hypothesis.

**4. Production deployment proof.** *Est. 2–3 days.*
Deploy the full stack including the `edge` profile. Record health output,
certificate chain, header verification against an external scanner, and 24 hours
of stable refresh cycles.

**5. Provider agreements.** *Business, not engineering.*
At minimum a real free-market USD/Toman source, and a direct Iranian silver
source. Everything downstream of the FX bridge is approximate until this lands.

### Tier 2 — required to call it 10/10 (3–4 weeks)

**6. End-to-end browser tests.** *Est. 4–5 days.* Playwright: sign in, create an
alert, trigger it against a seeded price, receive the notification. Run against
the real Compose stack in CI.

**7. Extract the shared frontend package.** *Est. 5–8 days.* Move the API client,
types, hooks and views into `packages/app-core`. Deletes ~2,500 duplicated lines
and closes the drift.

**8. Load and soak testing.** *Est. 3–4 days.* Establish the ceiling for
concurrent WebSocket clients, `/api/prices` throughput, and alert evaluation with
10k active alerts. Run 72 hours and watch for leaks and unbounded growth.

**9. Multi-replica verification.** *Est. 2–3 days.* Run two backend replicas and
confirm no duplicate refreshes, no duplicate deliveries, correct lease handover
on kill, and shared rate limiting.

**10. Third-party security review.** *Est. external.* The audit that produced
this document was internal. Authentication, the admin surface and the alert
webhook path warrant independent eyes.

### Tier 3 — polish

11. Blue/green or canary deploys with automated rollback.
12. A staging environment mirroring production.
13. Formal SLOs — price freshness, alert latency, availability — with error budgets.
14. Per-user API keys and quotas if the API is ever exposed to third parties.
15. Accessibility audit of the web app (WCAG 2.1 AA).

### Estimated total

| Tier | Effort | Outcome |
| --- | --- | --- |
| Tier 1 | 2–3 weeks | Safe for real users |
| Tier 2 | 3–4 weeks | Genuinely 10/10 |
| Tier 3 | ongoing | Mature operation |

---

## Known limitations to accept or fund

Documented deliberately. Each is a decision, not an oversight.

| Limitation | Why it stands | Cost to remove |
| --- | --- | --- |
| Toman metals are formula-derived without paid keys | No free reliable Iranian source exists | Commercial agreements |
| USDT proxy carries a market premium | Only a real USD/Toman feed fixes it | Provider contract |
| `SILVER_925_TOMAN_GRAM` has no direct provider | No source identified | Provider contract |
| `float` columns on the legacy `market_prices` table and `alerts.target_price` | Exact at these magnitudes; the pricing core uses `Decimal` throughout | A risky hypertable migration for no measurable gain |
| Single uvicorn worker | Keeps the connection budget predictable | Load testing plus a connection-pool review |
| Telegram ingestion is unverified input | Whitelisted, confidence-scored and deviation-checked, but a compromised channel could still influence a fallback | Restrict to verification-only, or drop |
| No secret-manager integration | Injection is the deployment's job | Vault or cloud KMS integration |
| Assistant forwards client-supplied history | Quota-capped and disclaimed | Server-side conversation reconstruction |

---

## Verifying this document

Every claim above is reproducible:

```bash
npm run verify                    # 158 backend + 18 frontend tests, 3 builds
cd apps/api && python -m pyflakes app tests scripts
curl -fsS localhost:8000/api/prices/health | jq .startup
```

If a statement here conflicts with what those commands report, the commands are
right and this file is stale. Fix it.
