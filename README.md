# Nerkhbaan

Current code release: **2.8.4**. `VERSION` is the source of release truth.
Step-one fixes and the step-two Iranian price/history work are recorded in the [changelog](CHANGELOG.md) and
[delivery matrix](docs/delivery-readiness.md). This source release has not been deployed by this change.
Target checked on 2026-10-12: [site](https://nerkhbaan.ir/) and [admin](https://nerkhbaan.ir/admin/) run 2.8.1.
See the [server handoff](docs/production-handoff-fa.md) and [saved proof](docs/delivery-readiness.md).
The [remaining acceptance report](docs/remaining-acceptance-2026-10-11.md) separates real
in-app receipt and unsigned installation from blocked native push, publisher signing and source coverage.

## Components

- FastAPI API; PostgreSQL 16 with TimescaleDB; Redis with AOF.
- React web and admin panel; Electron desktop renderer shares the web UI.
- Instrument-based pricing, independent verification, durable history and backfill.
- Alerts, delivery queue, dead letters, verified notification channels and support.
- Telegram whitelist worker; signed external pricing worker; Git feed pull sidecar.
- Nginx ingress and relay; Prometheus, Alertmanager and Grafana.

## Start locally

Use a supported Node/npm pair from `.github/workflows/ci.yml` and Python 3.12.
Use a clean virtual environment. Windows uses `npm.cmd` when PowerShell blocks `npm.ps1`.

```powershell
Copy-Item .env.example .env
npm.cmd ci
cd apps/api
python -m venv venv
.\venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\venv\Scripts\python.exe -m pip check
```

Fill runtime credentials in the private `.env`. Never commit it. Do not print it.
For Docker, review the environment first, then run from the repository root:

```bash
docker compose -f docker-compose.yaml config --quiet
docker compose --profile admin -f docker-compose.yaml up -d --build --wait
```

Database startup uses tracked forward migrations. Do not call `create_all` on production.
Do not edit an applied SQL migration. Do not use `down -v` during an upgrade.

## Checks

```powershell
npm.cmd run verify
python scripts/test_infra_contracts.py
```

Local checks and CI check different environments. Read [delivery readiness](docs/delivery-readiness.md)
for the exact commands, output markers and required target-host proof. Browser discovery is not execution.

## Read prices correctly

A price belongs to one instrument, currency, weight unit, purity, market and source time.
`XAU_USD_OZ` is USD per troy ounce. `GOLD_18K_TOMAN_GRAM` is Toman per gram of 18K gold.
They are not converted by multiplying the price by an exchange rate.
Iranian gold formulas are prohibited. Missing direct gold stays unavailable.
Other approved derived instruments remain explicitly labelled and bounded by input validity.
A USD/Toman leg has its own status, change percent, source, observation and expiry.
Never treat stale, suspicious, expired, unpersisted or theoretical values as an ordinary market quote.
History is persisted history; it is not reconstructed with today's exchange rate.

## Authentication and panel

Web auth uses cookies. Desktop uses a controlled `nerkhbaan://app` origin and secure credential bridge.
Keep web, admin and desktop origins explicit; never add `null` or wildcard CORS credentials.
The admin host uses separate session cookies, CSRF, permissions, reauthentication and TOTP MFA.
Production Compose requires MFA enrollment by default; local settings allow an optional test setup.
Sensitive writes require the current permission and any confirmation required by the endpoint.
See [admin guide](docs/admin-guide.md) and the generated [route index](docs/api-route-index.md).

## Production

[Release operations](docs/release-operations.md) covers staging, migration, backup, restore, TLS,
clock synchronization, rollback and final acceptance. Preserve all database and Redis volumes.
Production API port 8000 is internal. Probe it with container `exec`, or use the HTTPS ingress.
A separate staging project also needs a separate subnet, port set, credentials and storage.

```bash
docker compose -f docker-compose.prod.yaml exec -T backend \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready').status)"
```

Expected marker: `200`. Also inspect the JSON readiness and pricing health; process liveness is insufficient.
Prometheus scrapes `backend:8000/metrics` privately. Metrics are not exposed through public ingress.

## Documentation

| Document | Use |
| --- | --- |
| [API reference](API_DOCUMENTATION.md) | Auth, consent, prices, errors and contracts |
| [API route index](docs/api-route-index.md) | Every generated HTTP route |
| [API schemas](docs/api-contracts.json) | Request/response models and constraints |
| [Admin guide](docs/admin-guide.md) | Panel options and permission workflow |
| [Delivery fixes](docs/delivery-fixes-fa.md) | Audit findings, changes and proof boundaries |
| [Pricing semantics](apps/api/PRICING_SOURCES.md) | Instruments, source roles and validation |
| [Pricing runbook](docs/pricing-operations-runbook.md) | Provider onboarding and failure recovery |
| [External workers](docs/external-price-worker.md) | Signed ingress and bounded public feed |
| [Release operations](docs/release-operations.md) | Data-safe staging and production gates |
| [Server handoff](docs/production-handoff-fa.md) | Live URLs, release path, health and backup care |
| [Delivery readiness](docs/delivery-readiness.md) | Executed checks, target proof and external gates |
| [Project status](PROJECT_STATUS.md) | Current code and proof boundary |
| [Changelog](CHANGELOG.md) | Historical changes; not live deployment proof |

Dated vendor/legal reports and historical audits remain dated records. They do not replace a fresh operator check.

## Source delivery

```powershell
python scripts/build_delivery_archive.py C:/path/outside/repository/nerkhbaan-2.8.4-source.zip
```

The builder excludes private environments, keys, databases, logs, dependencies and generated artifacts.
The ZIP contains a file hash manifest and is verified after creation. Review it before sharing.
Runtime credentials and production data must be supplied separately through the deployment secret store.

## Dependency maintenance

Install Python from the hash locks, not an unbounded transitive solve. API and development locks
are universal with Python 3.12 as the resolver baseline; Telegram has its own lock. Regenerate with
`uv pip compile --python-version 3.12 --universal --generate-hashes` after changing a manifest, then
run `pip check`, regressions and image scans. Lock generation is not a container-runtime test.
CI audits the exact API and Telegram locks with pip-audit 2.10.1 before delivery.
The frontend uses Tailwind 4. Browser baseline: Safari 16.4+, Chrome 111+, Firefox 128+.
Test the actual supported browser/device list before expanding it.
