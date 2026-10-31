# Nerkhbaan

**Keyless local web review:** `npm.cmd run preview:local`, then open [the local website](http://127.0.0.1:43188). Local accounts and saved alerts use a separate persistent database; charts are explicitly synthetic and external delivery is disabled. [Persian start/stop and test guide](docs/local-web-preview-fa.md). This Unreleased work does not change the published 2.8.19 tag or establish production/device acceptance.

Source **2.8.19**, tag `v2.8.19`, commit `7978e8938d17c4749ba7c43044a5e3e22bcf0ad2`, is published. Source CI, fixed runtime images/scans and the isolated full-background-pool authentication/pricing canary passed on **2026-10-28**. This is source and isolated-test evidence, not a production acceptance receipt. [Exact tests and release record](docs/request-pool-release-2.8.19-fa.md).

**Production observation, 2026-10-31:** access returned after the owner renewed the VPS through today; the owner says it will then be deleted. Both API replicas match the 2.8.19 image and report healthy. The recovered guard receipt passed on October 28; the last observed accepted pointer remains 2.8.15. A fresh browser check passed registration, desktop login and logout, but timed out at email login in a narrow viewport; full application acceptance remains open. [Dated rescue and test record](docs/server-rescue-2026-10-31-fa.md).

Unreleased web corrections wait for the initial session check and cleanup before enabling authentication, explain that wait, and handle browser subscription-storage failures during background push synchronization. Local validation is separate from installed 2.8.19 images; fresh production and real-device acceptance remain required on a replacement host.

A fresh full database dump is saved locally and passed an isolated workstation restore: 55 public tables and ten migrations. Historical rate backups, private configuration, certificates and runtime artifacts are preserved separately. Snapshots have separate clocks and are not a continuous or atomic backup of the whole server. [Recovery guide](docs/server-recovery-guide-fa.md).

Telegram channel/group reading code is implemented and tested, but real collection remains disabled: no reading account or approved sources are available. [Private configuration and activation gates](docs/telegram-ingestion-guide-fa.md). Actual device notification receipt and configured external services retain separate acceptance gates. [Current roadmap](docs/project-completion-roadmap-fa.md) · [Document index](docs/documentation-index-fa.md).

Pricing quality validation and the bounded USD reference clock: [source policy](docs/source-quality-validation-2026-10-28.md).
The full database backup passed an isolated restore and has two verified copies on this workstation. Actual notification receipt on physical devices remains unproved. See the [historical administrator acceptance and provider gates](docs/admin-release-2.8.13-fa.md).

The administrator console now connects Kavenegar SMS and Asterisk ARI calls,
with encrypted credentials, permission checks, critical-call rules, consented
test recipients and paged delivery history. Follow the Persian
[SMS and VoIP connection guide](docs/admin-guide.md#راهنمای-اتصال-پیامک-و-تماس).
Both providers start disabled; an accepted provider request is not a received
SMS or an answered call. Email alarms are required follow-up delivery work; no configured sending service or real mailbox receipt is accepted. Account verification and password-reset mail also require a working mail service.

Three separately labelled Iranian reference valuations are now available for
24K gold, BTC/USD and USDT/USD. Published/calculated values retain source age,
parent prices and actual daily gaps; they do not replace native market contracts.
See [the reference scope and operational limits](docs/iranian-references-2026-10-17.md).

Previous source/documentation release: **2.8.16**; its scope and checks remain historical.
Read [the 2.8.16 source release scope and checks](docs/source-release-2.8.16-fa.md).
Telegram channel/group price ingestion is required delivery scope. The 2.8.17 candidate implements collection, group typing, bounded recovery and retraction. Real account/source and end-to-end receipt acceptance are still open.
Read the [Persian completion roadmap and flowcharts](docs/project-completion-roadmap-fa.md), [Telegram ingestion guide](docs/telegram-ingestion-guide-fa.md), [document index](docs/documentation-index-fa.md), and [current deployment/backup evidence](docs/pricing-release-2.8.15-fa.md).

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

## Code signing policy and source license

Initial customer delivery targets the website and installed web app, including real web-push
delivery. Windows publisher signing is a separate native-distribution gate, not a prerequisite
for that web delivery. See the [initial web delivery scope and checks](docs/web-initial-delivery-fa.md).

Owner-controlled original source code is licensed under [MIT](LICENSE); see
[license scope](docs/license-scope.md) and preserve [third-party notices](NOTICE).
The [Code signing policy](docs/code-signing-policy.md) describes the proposed
SignPath route. **Foundation application declined; signing is not enabled.**
See the [submission evidence](docs/signpath-submission-2026-10-24.md).
No unsigned download is represented as a signed release.
[Desktop pre-sign review](docs/desktop-pre-sign-review-2026-10-24.md) records
isolated installer tests and bundled notices; [required access](docs/step5-access-fa.md)
separates signing access from real device and optional provider receipts.

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
python scripts/build_delivery_archive.py C:/path/outside/repository/nerkhbaan-2.8.5-source.zip
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
