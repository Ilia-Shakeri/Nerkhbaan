# Nerkhbaan Developer Guide

Local setup, how the system is put together, and what to run before you push.
For deployment see [`README.md`](README.md); for API shapes see
[`API_DOCUMENTATION.md`](API_DOCUMENTATION.md).

---

## Stack

| Layer | Technology |
| --- | --- |
| Workspace | npm workspaces (`apps/*`, `packages/*`) |
| Backend | Python **3.12.13**, FastAPI, SQLAlchemy 2, Pydantic 2 |
| Storage | PostgreSQL 16 + TimescaleDB, Redis 7 |
| Web | React 18, TypeScript, Vite 6, Tailwind, vite-plugin-pwa |
| Admin | React 18, TypeScript, Vite 6 (separate app, separate host) |
| Desktop | Electron + the React renderer |
| Telegram worker | Python, Telethon (optional, profile-gated) |

Node **22.23.0** and npm **10.9.8** are pinned in `.nvmrc` and `package.json`.
CI enforces both. Python 3.12.13 is what the production image and CI use —
running a different local interpreter is a known source of "works here" bugs.

---

## Layout

```text
Nerkhbaan/
├── apps/
│   ├── api/                     FastAPI backend
│   │   ├── app/
│   │   │   ├── admin/           Admin subsystem: RBAC, audit, operations
│   │   │   ├── migrations/      Migration runner and state verification
│   │   │   ├── pricing/         The pricing engine (see below)
│   │   │   ├── routers/         Public HTTP surface
│   │   │   ├── services/        Alerts, delivery, assistant, background loops
│   │   │   ├── config.py        All settings, one place
│   │   │   ├── deps.py          Auth dependencies
│   │   │   └── main.py          App assembly, middleware, lifespan
│   │   ├── db/migrations/       Ordered, checksummed SQL
│   │   ├── scripts/             Canary, smoke test
│   │   └── tests/
│   ├── admin-web/               Admin SPA
│   ├── desktop/                 Electron shell + renderer
│   ├── telegram_worker/         Optional MTProto ingestion
│   └── web/                     Public PWA
├── packages/ui/                 Shared React components
├── nginx/                       Edge proxy: TLS, HSTS, rate limits, admin vhost
├── docs/                        Runbooks and operator evidence
└── scripts/                     Repo-level checks and deploy helpers
```

### The pricing engine

`apps/api/app/pricing/` is the core. Worth understanding before changing
anything in it — see [`apps/api/PRICING_SOURCES.md`](apps/api/PRICING_SOURCES.md)
for the full model.

| Module | Responsibility |
| --- | --- |
| `instruments.py` | Instrument definitions: unit, purity, windows, bounds |
| `registry.py` | Provider catalogue: roles, budgets, credentials, semantics |
| `parsers/` | One parser per provider response shape |
| `providers.py` | HTTP fetch: egress guard, budget, circuit breaker, retries |
| `canonical.py` | Which quote becomes the published price, and why |
| `anomaly.py` | Volatility-adaptive deviation thresholds |
| `derived.py` | Formula fallback and FX bridge selection |
| `freshness.py` | Live / stale / expired boundaries |
| `persistence.py` | Durable writes with a Redis-stream outbox |
| `cache.py`, `locks.py`, `budgets.py` | Redis: cache, distributed leases, quotas |
| `service.py` | Orchestrates a refresh |
| `compatibility.py` | Legacy `/api/prices` shape |

---

## Setup

### 1. Prerequisites

- Node.js 22.23.0, npm 10.9.8
- Python 3.12.13
- Docker Engine with Compose v2

### 2. Environment

There is **one** env file, at the repository root. It feeds Compose and the
backend both.

```bash
cp .env.example .env
```

Set at minimum `POSTGRES_PASSWORD`, `DATABASE_URL` and a `JWT_SECRET_KEY` of at
least 32 characters. The application refuses to start with a weak or default
key — that is deliberate.

For local work leave `PRICING_REQUIRE_PROVIDER_KEYS=false`: the API boots
without provider credentials and serves formula-derived values, clearly marked.

### 3. Infrastructure

```bash
docker compose up -d postgres redis
```

### 4. Dependencies

```bash
npm ci

cd apps/api
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cd ../..
```

### 5. Migrations

Migrations are **not** applied on startup — the API verifies they are current
and refuses to boot otherwise.

```bash
cd apps/api
MIGRATIONS_DIR="$PWD/db/migrations" python -m app.migrations.runner
```

This also creates the bootstrap super administrator when the four
`ADMIN_BOOTSTRAP_*` variables are set and no super admin exists yet.

### 6. Run

```bash
npm run dev:api        # http://127.0.0.1:8000
npm run dev:web        # http://127.0.0.1:5173
npm run dev:admin      # http://127.0.0.1:4174
npm run dev:desktop
```

With `DEBUG=true`, OpenAPI is at `/api/docs`. It is disabled otherwise.

---

## Verify before pushing

```bash
npm run verify
```

Runs, in order:

| Step | What it catches |
| --- | --- |
| `check:api` | Syntax, undefined names, unused imports |
| `test:api` | 158 backend tests |
| `test:frontend` | Proxy, service worker, push and asset contracts |
| `build` | Type errors across web, admin and desktop |

Individually:

```bash
cd apps/api && python -m pyflakes app tests scripts
cd apps/api && python -m unittest discover -s tests -v
npm run test:frontend
npm run build:web
```

The frontend contract tests are structural, not cosmetic. They assert things a
reviewer will not spot: that every nginx `location` includes the security-header
snippet (nginx silently drops inherited `add_header` in any block that declares
its own), that no proxy forwards a caller-supplied `X-Forwarded-For`, that the
service worker has a `push` handler, and that no unreferenced font is shipped.

### Provider canary

Exercises the real request guard, credentials, size cap, retry policy and parser
against a live endpoint. Output is sanitised — no headers, keys, or payloads.

```bash
cd apps/api
JWT_SECRET_KEY='local-non-production-value' python scripts/provider_canary.py
JWT_SECRET_KEY='local-non-production-value' python scripts/provider_canary.py coinbase_btc_usd
```

### Integration smoke test

Against a running backend:

```bash
python apps/api/scripts/integration_smoke_test.py --base-url http://127.0.0.1:8000
```

---

## Conventions

### Configuration

Every setting is declared in `app/config.py` and read through `settings`. Do not
add `os.getenv` calls in application code: pydantic-settings loads `.env`
**without** exporting it, so a direct environment read silently sees a different
value than the rest of the app — and only outside Docker, where it is hardest to
notice.

The exceptions are deliberate and documented in place: per-provider budget
overrides and per-instrument window overrides, which are dynamic key names.

A setting with no reader is not neutral — it advertises a knob that does
nothing. Wire it up or delete it.

### Migrations

- Ordered, immutable, checksummed. Editing an applied migration is detected and
  fails the run.
- The checksum normalises line endings, so a CRLF checkout does not invalidate
  every migration. `.gitattributes` enforces LF regardless.
- Every migration must be idempotent — CI applies each one twice.

### Money

The pricing core uses `Decimal` end to end and `Numeric` columns. Do not
introduce `float` into a path that produces a published price.

### Tests

Prefer asserting an invariant over a snapshot. `assertEqual(len(INSTRUMENTS), 10)`
only proves the number did not change; `"no instrument may lack both a source
and a formula"` catches the class of bug that made silver publish theoretical
values while looking healthy.

### Security-relevant code

`app/security.py`, `app/deps.py` and `app/admin/deps.py` are the trust boundary.
Changes there need a test that fails without the fix.

---

## Things that will bite you

| Symptom | Cause |
| --- | --- |
| API exits with "migrations are not current" | Run the migration runner. If it just ran, a migration file changed after being applied. |
| Prices all show `derived_fallback` | No provider credentials configured. Check `startup.instruments_without_direct_source` in `/api/prices/health`. |
| Everything rate-limits as one client | `TRUSTED_PROXY_IPS` does not match `FORWARDED_ALLOW_IPS`, so every request resolves to the proxy address. |
| Push notifications never arrive | `VAPID_PUBLIC_KEY` is compiled in at **image build time**. A frontend built without it has push disabled until rebuilt. |
| Admin API returns 403 on every write | `ADMIN_FRONTEND_ORIGIN` does not match the browser's origin. |
| Refresh stops after a few days | Redis at `maxmemory` with `noeviction`. Watch `used_memory`. |
| Service worker serves stale bundles | It is disabled in dev on purpose. In production the update prompt is user-driven. |
