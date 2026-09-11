# Nerkhbaan

Live gold, silver, currency and crypto prices for the Iranian and international
markets, with verified pricing, price alerts and a market assistant.

[![CI](https://github.com/your-org/nerkhbaan/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

---

## What it does

Nerkhbaan publishes a **canonical price** per instrument: one value, with a
recorded reason for why it was chosen, where it came from, and how much to trust
it right now.

That last part is the point. A price platform that shows a number without
saying whether it is a live trade, a cached value, a disputed candidate or
arithmetic is worse than useless to someone about to trade on it. Every price
this API returns carries its status, its age, its source semantics and whether
it was observed or computed.

- **Multi-source verification.** Providers are ranked per refresh. A candidate
  that deviates beyond a volatility-adaptive threshold is not published — it is
  checked against independent sources first, and the previous value is held
  while that happens.
- **Explicit units.** Gold in USD is a troy ounce at 0.9999 fine on the global
  spot market. Gold in Toman is one gram at 0.750 fine in the Iranian physical
  market. These are different instruments and the API says so.
- **Honest degradation.** When no direct source is available, values are derived
  from a formula and marked as such. Nothing is dressed up as an observation.
- **Durable alerts.** Triggers are idempotent, delivery is a work queue with
  backoff, retry and a dead-letter path, and an alert never fires on a
  suspicious, expired or unpersisted price.

---

## Contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Production deployment](#production-deployment)
- [Configuration](#configuration)
- [Operating it](#operating-it)
- [Reading a price correctly](#reading-a-price-correctly)
- [Documentation](#documentation)
- [Releases](#releases)

---

## Architecture

```
                    ┌──────────────────────────────────────┐
   browser  ───────▶│  edge (nginx)                        │
   admin    ───────▶│  TLS · HSTS · CSP · rate limits      │
                    └───┬──────────────┬───────────────┬───┘
                        │              │               │
                 ┌──────▼─────┐  ┌─────▼──────┐  ┌─────▼────────┐
                 │  web PWA   │  │ admin SPA  │  │  backend     │
                 │  (nginx)   │  │  (nginx)   │  │  (FastAPI)   │
                 └────────────┘  └────────────┘  └───┬──────┬───┘
                                                     │      │
                                      ┌──────────────▼──┐ ┌─▼──────────┐
                                      │ PostgreSQL 16   │ │  Redis 7   │
                                      │ + TimescaleDB   │ │            │
                                      │ prices, alerts, │ │ cache      │
                                      │ audit, history  │ │ locks      │
                                      └─────────────────┘ │ budgets    │
                                                          │ fan-out    │
                                                          │ outbox     │
                                                          └────────────┘
```

**PostgreSQL** is the system of record — canonical quotes, provider quotes,
alerts, deliveries, audit. TimescaleDB hypertables carry the time series.

**Redis is required, not a cache layer you can drop.** It holds the distributed
refresh leases, the per-provider request budgets, the WebSocket fan-out and the
persistence outbox. Its eviction policy is `noeviction`: if it fills, refreshes
stop rather than silently losing writes.

Background work runs as three independent loops — price refresh, alert
evaluation, and maintenance — so a slow upstream provider cannot stall alert
delivery.

---

## Quick start

Local development, five minutes:

```bash
git clone <repository-url> Nerkhbaan && cd Nerkhbaan
cp .env.example .env
```

Set `POSTGRES_PASSWORD`, a matching `DATABASE_URL`, and a `JWT_SECRET_KEY` of at
least 32 random characters. Then:

```bash
docker compose up -d postgres redis
npm ci

cd apps/api
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
MIGRATIONS_DIR="$PWD/db/migrations" python -m app.migrations.runner
cd ../..

npm run dev:api    # http://127.0.0.1:8000
npm run dev:web    # http://127.0.0.1:5173
```

Full setup, conventions and troubleshooting: [`README.developer.md`](README.developer.md).

---

## Releases

Current release: **2.0.0**. The authoritative value is [`VERSION`](VERSION).
Every release updates [`CHANGELOG.md`](CHANGELOG.md), package manifests and API
health metadata together. Run this check before a release:

```bash
npm run check:release
```

---

## Production deployment

Ubuntu 22.04 or 24.04, non-root sudo user.

### 1. System packages and Docker

```bash
sudo apt update && sudo apt install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER" && newgrp docker
docker compose version
```

### 2. Clone and configure

```bash
git clone <repository-url> Nerkhbaan && cd Nerkhbaan
cp .env.example .env && nano .env
```

**Required before first start:**

| Variable | Notes |
| --- | --- |
| `COMPOSE_FILE=docker-compose.prod.yaml` | Keeps Compose on the production stack |
| `POSTGRES_PASSWORD` | Long and random |
| `DATABASE_URL` | Must carry the same password |
| `JWT_SECRET_KEY` | ≥32 random characters. Startup fails otherwise. |
| `ALLOWED_ORIGINS` | Exact public origins |
| `ADMIN_FRONTEND_ORIGIN` | The admin host. A mismatch 403s every admin write. |
| `TRUSTED_PROXY_IPS` | **Must match `FORWARDED_ALLOW_IPS`** — see below |
| `ADMIN_BOOTSTRAP_*` | All four, or none |

> ### Set `VAPID_PUBLIC_KEY` before you build
>
> It is compiled into the web bundle at **image build time**, not read at
> runtime. A frontend image built without it has web push permanently disabled
> until the image is rebuilt.
>
> ```bash
> docker run --rm python:3.12-slim sh -c \
>   "pip install -q py-vapid && vapid --gen --applicationServerKey" 
> ```

> ### `TRUSTED_PROXY_IPS` must match `FORWARDED_ALLOW_IPS`
>
> Both decide which hop may set `X-Forwarded-For`, and that value drives rate
> limiting, the admin IP allowlist, and the hashed IP in the audit trail. If
> they disagree, either every client shares one bucket or a caller can choose
> their own address. The Compose network is `172.28.0.0/24`.
>
> If you terminate TLS yourself instead of using the `edge` service, your proxy
> must set `X-Forwarded-For` **by replacement**. `$proxy_add_x_forwarded_for`
> appends to whatever the caller sent, leaving the head of the chain under their
> control.

### 3. Start

```bash
docker compose up -d --build
```

Brings up `postgres`, `redis`, `migrate` (runs once), `backend`, `frontend` and
`db-backup`. `backend` waits for migrations to complete successfully.

### 4. TLS and the admin host

`frontend` and `backend` publish on loopback only and speak plain HTTP. The
`edge` service terminates TLS, sets HSTS and the browser security headers,
applies rate limits and serves the admin vhost. It is profile-gated because it
needs certificates:

```bash
docker compose --profile edge up -d
```

It expects Let's Encrypt material at `/etc/letsencrypt` (`LETSENCRYPT_DIR`) and
an ACME webroot at `./certbot-webroot` (`CERTBOT_WEBROOT`). Enabling the profile
also starts `admin-frontend`.

### 5. Verify

```bash
docker compose ps
curl -fsS http://127.0.0.1:8000/api/health/ready | jq
curl -fsS http://127.0.0.1:8000/api/prices/health | jq .startup
```

`ready` is `503` unless the database is reachable **and** migrations are
current. Check `startup.instruments_without_direct_source` — anything listed
there is publishing formula output rather than an observed market price.

### 6. First administrator

Created by the migration job from `ADMIN_BOOTSTRAP_*` when no super
administrator exists. It is created with `must_change_password` set; sign in at
the admin host and change it immediately.

### 7. Optional: Telegram ingestion

```bash
docker compose --profile telegram up -d --build telegram-worker
```

Requires MTProto credentials. See
[`apps/telegram_worker/telegram_setup_guide.txt`](apps/telegram_worker/telegram_setup_guide.txt).

---

## Configuration

Every setting is declared in [`apps/api/app/config.py`](apps/api/app/config.py)
and documented in [`.env.example`](.env.example). The ones most likely to matter:

### Security

| Variable | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET_KEY` | — | ≥32 chars. Rotating invalidates all sessions. |
| `JWT_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `AUTH_REFRESH_DAYS` | `30` | Refresh token lifetime |
| `AUTH_COOKIE_SECURE` | `true` | Never `false` in production |
| `AUTH_COOKIE_SAMESITE` | `strict` | |
| `TRUSTED_PROXY_IPS` | loopback | Which hops may set `X-Forwarded-For` |
| `METRICS_ALLOWED_NETWORKS` | loopback | `/metrics` is `404` elsewhere |
| `ADMIN_IP_ALLOWLIST` | empty | CIDR list; empty means no IP restriction |
| `ADMIN_SESSION_MINUTES` | `30` | 5–240 |
| `ADMIN_REAUTH_MINUTES` | `10` | Window for destructive operations |

### Pricing

| Variable | Default | Notes |
| --- | --- | --- |
| `PRICING_REFRESH_INTERVAL_SECONDS` | `20` | Refresh cadence |
| `PRICING_LOCK_TTL_SECONDS` | `45` | Lease, renewed while held |
| `PRICING_SHORT_HISTORY_RETENTION_HOURS` | `6` | Redis volatility window |
| `PRICING_PROVIDER_ALLOWED_HOSTS` | see config | Egress allowlist |
| `PRICING_REQUIRE_PROVIDER_KEYS` | `false` | `true` fails startup on missing keys |
| `REDIS_MAXMEMORY` | `384mb` | Policy is `noeviction` |

### Capacity

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_POOL_SIZE` | `5` | Sync pool |
| `DATABASE_ASYNC_POOL_SIZE` | `5` | Async pool |
| `DATABASE_MAX_OVERFLOW` | `3` | Applies to both |

Peak connections per API process ≈ `(pool + overflow) × 2`. Keep the total
across all services under the server's `max_connections` (60 in the shipped
Compose file).

### Optional providers

Without these, Iranian metal chains fall back to formula values:

```env
GOLDAPI_API_KEY=            # XAU/XAG spot
METALS_DEV_API_KEY=         # spot fallback
ALANCHAND_API_TOKEN=        # 18K gold, Toman
TALA_API_KEY=               # Toman metals
TALA_SILVER999_TOMAN_KEY=   # required for a real silver price
NAVASAN_API_KEY=            # free-market USD/Toman
NAVASAN_HTTPS_PROXY_BASE_URL=
```

---

## Operating it

### Health

| Endpoint | Use |
| --- | --- |
| `/api/health/live` | Liveness. Process is up. |
| `/api/health/ready` | Readiness. Gates traffic. |
| `/api/health` | Database, Redis, migration version, backlogs |
| `/api/prices/health` | Per-chain status and source coverage |
| `/metrics` | Prometheus, private networks only |

### Watch these

| Signal | Why |
| --- | --- |
| Redis `used_memory` vs `REDIS_MAXMEMORY` | `noeviction` means a full Redis stops refreshes |
| `startup.instruments_without_direct_source` | Those chains are publishing arithmetic |
| `dead_letter_backlog` | Alerts that exhausted retries |
| `anomaly_count` | Open, unreviewed pricing anomalies |
| `migration_current` | `false` means the backend will not restart cleanly |

### Backups

`db-backup` writes nightly to the `db_backups` volume with 7-day, 2-week and
2-month retention. **Copy them off the host** — a volume on the same machine is
not a backup. Restore drills are in the operator gate list.

### Redis recovery

[`docs/redis-recovery.md`](docs/redis-recovery.md). Redis refuses to start
rather than silently discard an unreadable AOF file — that is deliberate.

### Routine notes

- Keep `.env` out of version control.
- Rotate `JWT_SECRET_KEY` only during a planned session-invalidation window.
- Migrations run as a separate job; the backend verifies and refuses to start if
  they are not current. Never apply them from the running API.

---

## Reading a price correctly

If you are integrating against this API, three things matter.

**1. Check the status.** Only `live`, `confirmed` and `fresh_cache` are safe to
treat as a market price. `derived_fallback` is arithmetic. `suspicious`,
`verifying`, `stale` and `expired` are not tradeable.

**2. Check the unit.** `price_usd` and `price_toman` on the same row are
different instruments. Use `unit_usd` and `unit_toman`.

**3. Check the FX bridge on derived values.** Toman metal prices with no direct
source are reconstructed from the international reference through a USD/Toman
rate. When no free-market USD source is configured, USDT stands in — and USDT
trades at a persistent premium in Iran. Those values carry:

```json
{ "fx_bridge": "usdt_proxy", "fx_bridge_is_proxy": true }
```

In a representative case that is a **3.4%** difference. Treat proxy-bridged
values as indicative, and configure a real USD/Toman source for anything else.

Full detail: [`apps/api/PRICING_SOURCES.md`](apps/api/PRICING_SOURCES.md).

---

## Documentation

| Document | Covers |
| --- | --- |
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | What is done, what is not, what production readiness still needs |
| [`README.developer.md`](README.developer.md) | Local setup, layout, conventions, verification |
| [`API_DOCUMENTATION.md`](API_DOCUMENTATION.md) | Every endpoint, auth, errors, rate limits |
| [`apps/api/PRICING_SOURCES.md`](apps/api/PRICING_SOURCES.md) | Instruments, providers, verification, derived pricing |
| [`docs/pricing-operations-runbook.md`](docs/pricing-operations-runbook.md) | Provider onboarding gate, canary, operator evidence |
| [`docs/redis-recovery.md`](docs/redis-recovery.md) | Redis data safety and recovery |
| [`docs/production-hardening-report.md`](docs/production-hardening-report.md) | Historical hardening record |
| [`.github/security-exceptions/POLICY.md`](.github/security-exceptions/POLICY.md) | CI scan exception policy |

### API surface

```
GET    /api/prices                       aggregate snapshot
GET    /api/prices/{asset}/history       ?timeframe=1h|24h|7d|30d|1y
GET    /api/prices/health                chain status and source coverage
GET    /api/instruments[/{id}]           canonical instrument data
WS     /api/ws/prices                    live canonical updates
POST   /api/auth/signup|signin|refresh   authentication
GET    /api/alerts                       price alerts (CRUD)
GET    /api/providers                    provider catalogue
GET    /api/health[/live|/ready]         health
GET    /metrics                          Prometheus (private networks)
```

---

## Licence and disclaimer

Nerkhbaan reports market data from third-party sources. Prices may be delayed,
incorrect or unavailable, and derived values are explicitly theoretical. Nothing
this platform produces is investment advice. Provider redistribution rights are
the operator's responsibility — see the onboarding gate in the operations
runbook.
