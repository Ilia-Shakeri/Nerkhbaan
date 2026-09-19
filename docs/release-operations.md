# Release operations

## Code gates

Run `npm run verify`. CI then proves PostgreSQL migrations and restore, Redis round trips and replica lease exclusion, live HTTP routes, browser auth/alert flow, Compose/nginx/relay/monitoring syntax, desktop packaging, image builds, and security scans.

The live HTTP gate has 14 stages. It creates a unique user and alert, exercises
auth, session, pricing, chart, instrument, provider, and error contracts, then
removes the alert. Run it only against a disposable test database; the user and
security audit rows intentionally remain as transaction evidence.

## Staging

Use the production Compose file under a separate project name and separate ports. Keep its database, Redis, certificates, webhook file, and provider keys separate from production.

```bash
COMPOSE_PROJECT_NAME=nerkhbaan-staging \
EDGE_HTTP_PORT=8080 EDGE_HTTPS_PORT=8443 \
PROMETHEUS_PORT=19090 ALERTMANAGER_PORT=19093 GRAFANA_PORT=13002 \
docker compose --profile edge --profile admin --profile monitoring \
  -f docker-compose.prod.yaml up -d --build --wait --scale backend=2
```

Run route smoke, browser smoke, then load smoke against staging. A long soak uses the same load script with a larger request count and an external process supervisor.

```bash
python apps/api/scripts/integration_smoke_test.py --base-url https://staging.example.com
python scripts/load_test.py --base-url https://staging.example.com --requests 10000 --concurrency 100
```

## Production

Create an evidence file from `docs/operator-gates.evidence.example.json`. Evidence links hold reports only; never put secrets in the file. Validate it with `python scripts/verify_operator_gates.py <path>`.

The deploy refuses to run without all eight current gates. External owners must supply provider rights, live canaries, secret-store proof, relay/transport decisions, off-host restore proof, target health, and browser proof. Code cannot truthfully create those facts.

```bash
OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json \
BACKEND_REPLICAS=2 \
sh scripts/deploy-nerkhbaan-prod.sh
```

Before deploy, record the current commit and database backup. After deploy, check readiness, Prometheus targets, active alerts, queue depth, provider failure rate, and price age. If health fails, keep data volumes, return to the recorded commit with a new reviewed deploy, and rerun the same gates.

Before provider or login verification, require a synchronized host clock. Follow
[`time-sync-runbook.md`](time-sync-runbook.md); a large correction needs a short
maintenance window because old sessions and timers can expire.

## Relay

`infra/relay` is a separate stateless stack. It accepts TLS from only the core IP range and requires `X-Relay-Token`. The core adds that header only when `PRICING_RELAY_BASE_URL` matches a configured provider URL host. Point only affected provider base URLs at the matching relay path, add the relay host to the provider allowlist, and set a secret-store token of at least 32 characters.

This relay solves reachability only. It does not grant redistribution rights or override vendor terms. Those remain hard launch gates.
# Offline package build fallback

The frontend image installer tries configured npm registries first. If every
registry is unavailable, it retries with the BuildKit npm cache and the locked
dependency set. A cache miss remains a hard failure; never replace the lockfile
or install unpinned packages during a production deploy.
# Limited 2.5.1 release
Historical release; see the current 2.6.1 record below.

The user explicitly approved a limited provider-fix deployment on 2026-09-19,
with database backup and live readiness checks despite missing formal gate
evidence. This exception does not satisfy or remove any normal release gate.
Retain previous images and commit for rollback; preserve all volumes. Use
the new version as the image tag so rollback does not depend on mutable tags.
See [provider validation](free-provider-validation-2026-09-19.md) for the known
24K gap and source timestamp/redistribution limitations.

Final code: `2a26ca5d`, images tagged `2.5.1`. Previous code: `2b2972d8`;
previous images tagged `c580745` are retained. Prior configuration is protected
at `/home/deploy/nerkhbaan-release-backups/pre-2.5.0.env` (mode 600). Do not
commit or print that file. An operator-approved rollback should restore the
prior configuration and image selection, then check readiness; never remove
data volumes. No schema migration was added by this release.

## Limited 2.6.1 release

On 2026-09-19 the owner explicitly approved deploying the privacy/accessibility
changes plus supplied identity and free-service facts with a database backup and
live health checks, despite the listed missing address, data-rights, retention and
restore evidence. Normal gate scripts remain unchanged; no evidence is fabricated.
Scope includes 2.6.0 and 2.6.1 together. Existing auth flip stays unchanged.
Old clients lacking the new consent fields need an update; never infer acceptance.
Use versioned images, preserve prior 2.5.1 images and all PostgreSQL/Redis volumes.
Do not touch untracked server .gitea, gitea_data or gitea_runner_data directories.
Deployment verified on 2026-09-19 at approximately 11:56 UTC:

- Code `2cf2c17`, tag `v2.6.1`; API, web and price-feed-pull images `2.6.1`.
- Pre-release database dump `/backups/last/nerkhbaan-20260919-115138.sql.gz`,
  45.3 MiB, passed `gzip -t`. Dump warned about Timescale circular foreign-key
  constraints; successful dump/compression checks are not restore-drill evidence.
- Protected config backup `/home/deploy/nerkhbaan-release-backups/pre-2.6.1.env`
  mode 600. Do not print or commit it. Previous images `2.5.1` retained.
- Version persisted in `.env`; built migrate/frontend/price-feed-pull images,
  then recreated only backend (two replicas), frontend and price-feed-pull with
  `--no-deps --wait`. No new schema changes; database/Redis/backup containers
  remained running. Price-feed-pull runs but has no configured healthcheck.
- Public liveness and readiness returned 200, `release_version=2.6.1`, database
  and Redis connected, current migration and operational websocket fanout.
- Five legal routes returned 200. Empty signup returned 422 without creating
  an account. Runtime `AUTH_REFRESH_DAYS=30` confirmed.
- Live browser verified all five public pages, public email links, owner details
  in both languages, and the existing update prompt from 2.5.1 to the new bundle.
  Returning installed clients must select the update/reload prompt.
- Local validation: 207 backend tests passed, one PostgreSQL concurrency test
  skipped; 34 frontend contracts passed; web/admin/desktop builds passed.
  Browser-test discovery is not a full end-to-end account test. No consent accepted
  on behalf of the owner and no support/chat message submitted during smoke tests.
- Disk after deployment: 3.7 GiB available, 87% used. No data or image pruning.
- Existing price gaps remain: readiness snapshot included expired/unavailable
  sources and 94 anomaly records. This legal release does not claim to fix them.

Rollback, if approved: restore the protected configuration or select retained
`2.5.1` images for these same services, then repeat health checks. Preserve all
data and consent receipts. Do not roll back schema or remove volumes.
