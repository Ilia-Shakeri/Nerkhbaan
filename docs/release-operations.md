# Release Operations — 2.8.1

Updated: 2026-10-12. Execute against the intended host only after review of the concrete release.
This runbook does not certify a deployment; dated target evidence is in [delivery readiness](delivery-readiness.md).

## 1. Final code gates

Run `npm run verify`, `python scripts/test_infra_contracts.py` and export the final API schema.
Run every CI job on the final commit: clients, desktop package, Python, actual Timescale/Redis,
HTTP/browser, migration/restore, Go/sidecars, proxy/monitoring and security scans.
Keep logs tied to release and commit. Do not replace an executed test with test discovery.

Recorded application result: [CI run 38222923015](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38222923015)
passed all 15 jobs at `ce22c1d0487d78c58b488aff40616f3ce0a331f1`, including real plain PostgreSQL
and Timescale history golden cases. All seven image scans kept
the HIGH/CRITICAL failure gate. Later changes need a new final-commit run. Actual target migration,
rolling deployment and browser evidence are recorded separately in [delivery readiness](delivery-readiness.md).

The HTTP smoke writes a unique test user and alert. Run it only against a disposable database.
It leaves the test user/security audit rows as evidence. It waits beyond refresh duplicate grace before testing reuse.

## 2. Separate staging

Prepare a private `.env` in a separate checkout. Use different credentials, databases, Redis,
certificates, webhook file, ports and subnet. Do not reuse production volumes or project names.

```bash
COMPOSE_PROJECT_NAME=nerkhbaan-staging \
NERKHBAAN_NETWORK_SUBNET=172.30.0.0/24 \
FORWARDED_ALLOW_IPS=127.0.0.1,172.30.0.0/24 \
TRUSTED_PROXY_IPS=127.0.0.1,::1,172.30.0.0/24 \
ADMIN_TRUSTED_PROXY_IPS=127.0.0.1,::1,172.30.0.0/24 \
EDGE_HTTP_PORT=8080 EDGE_HTTPS_PORT=8443 \
PROMETHEUS_PORT=19090 ALERTMANAGER_PORT=19093 GRAFANA_PORT=13002 \
docker compose --profile edge --profile admin --profile monitoring \
  -f docker-compose.prod.yaml up -d --build --wait --scale backend=2
```

Compose proxy trust defaults follow `NERKHBAAN_NETWORK_SUBNET`. If using shared ingress,
set FORWARDED_ALLOW_IPS, TRUSTED_PROXY_IPS and ADMIN_TRUSTED_PROXY_IPS consistently
for the real proxy hops. Do not trust arbitrary client-supplied forwarded headers.
Nginx resolves service names through Docker DNS and refreshes them after container replacement.

Run isolated HTTP/browser flows, provider canaries, source timestamp/unit checks, queue retry/cancel
and an agreed staging load/soak test. The staging hostname must be in auth and admin origin settings.

## 3. Backup and migration

Record current code/image tags and configuration backup location without printing credentials.
Take and fetch an off-host PostgreSQL backup. Verify it through an isolated Timescale restore.
The CI helper requires a fresh, different target named `*_restore` or `*_restore_*`.
It refuses an existing target and cleans only the database it created for this run:

```bash
SOURCE_DATABASE=nerkhbaan_ci RESTORE_DATABASE=nerkhbaan_restore_ci \
bash scripts/ci-restore-drill.sh
```

Provide PGHOST, PGPORT, PGUSER and PGPASSWORD through a private environment.
Expected: `RESTORE_DRILL_OK` with equal data, hypertables, chunks and policies.
Before `timescaledb_post_restore()`, disable the restored policy and application cleanup jobs.
Inspect all restored jobs, including user jobs that do not have a `policy_` name. Confirm they
are unscheduled and no job is still running before taking fingerprints or testing the migration.
Keep them paused for the disposable drill. Do this only in the owned restore database; leave
production jobs alone. A cleanup job can remove data between comparisons and invalidate the drill.

The seventh migration, `20261011_001_delivery_hardening.sql`, tags legacy provider backfill
canonical rows as historical and adds a partial live-observation index. Existing compressed history
can exceed Timescale's default tuple limit. When Timescale is installed, the migration uses
`set_config('timescaledb.max_tuples_decompressed_per_dml_transaction', '0', true)` within its own
transaction. The runner still bounds statements to 300 seconds by default. The override ends with
that transaction; ordinary application transactions retain their normal limit. Test the UPDATE/index
operations against the isolated restored database before production. Record user and price row
counts and fingerprints before and after; account only for the intended `historical_backfill` flag.
Keep all six old migration files and their applied checksums unchanged. Keep the old history rows;
never delete them to make migration or live-price checks pass. A timeout or failed comparison stops
the release; review the plan before a retry.

Recorded target stage: `TARGET_MIGRATION_STAGE_OK` passed with the `b9f5538` API image on the
verified 47-table restore, using Timescale 2.28.3 and PostgreSQL 16.14. It retained three hypertables,
37 chunks and four users, with seven migrations applied. Before/after fingerprints matched for
`provider_quotes` (520,444 rows), `canonical_quotes` (325,486), `market_prices` (26,662) and `users` (4).
The canonical comparison excluded only the intended `historical_backfill` flag. The tested target
needed no manual chunk decompression. The ordinary application tuple guard remained 100,000.
This records the isolated restore stage. The same migration subsequently passed on live data;
see the separate target receipt in the delivery matrix. Applied migration files remain immutable.
The helper drops only its explicitly separate restore target and cleans it on exit.
It uses Timescale pre/post restore and compares fingerprints. It is for disposable/frozen test data;
concurrent source writes invalidate a before/after fingerprint. Production-sized off-host drill needs its own evidence.
A `.gz` integrity check alone is not restore proof.

Run the dedicated migrate service before backend. Applied files are immutable.
The eighth migration, `20261011_002_notification_sending_state.sql`, adds `sending` to the
delivery-state CHECK constraint. Test it on the owned restored copy before live execution.
Record original user/delivery fingerprints. Preserve all seven previously applied migration files.
Strict readiness can return 503 while the migration ledger is ahead of the old API image;
capture that transition separately from business-route health and final readiness.
The new forward migration adds MFA replay state, widens pricing metadata and repairs known legacy Telegram defaults.
An unknown newer migration stops an older release. Lock acquisition has a deadline.
DATABASE_URL TLS query settings remain intact, including verify-full and CA/client certificate settings.
Do not automatically roll an older API onto a newer schema. Review compatibility first.
Existing market-price duplicates/compressed chunks need a preservation plan before a new uniqueness constraint.

## 4. Target deployment

Check clock synchronization and TLS. Fill a fresh private operator evidence file and validate it.
The responsible owner supplies source rights and private-store evidence. Record actual restore,
target health and browser proof separately; do not fill them from a build result or a placeholder.

```bash
OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json \
BACKEND_REPLICAS=2 \
sh scripts/deploy-nerkhbaan-prod.sh
```

The script is configured for `/opt/Nerkhbaan`; review the path on the actual target.
It refuses missing/invalid evidence and a dirty tracked worktree. Preserve all volumes.
Use reviewed immutable image/version tags and retain previous images.

### Existing stack with shared ingress

Use a reviewed release checkout at `/opt/Nerkhbaan/.releases/<commit>` and a private
`runtime.override.json` for the existing target. Keep `/opt/Nerkhbaan/.env` private. The override
must preserve the existing project name, database/Redis volumes, data-service configuration and
network. Record those names and mounts before any change. Use exact loaded image tags in the
override when components come from different verified commits. `APP_IMAGE_TAG` alone does not
describe such a release.

For this host, the shared ingress runs from `/opt/edge/compose.json`. Use the `admin` profile
without the `edge` profile. Do not start a second listener on ports 80/443. Validate the reviewed
shared-ingress configuration and its service aliases separately. Build admin with
`VITE_ADMIN_BASE_PATH=/admin/`; serve its assets under `/admin/assets/`. Keep API requests under
`/api/` with the reviewed same-host admin origin and cookie settings. The public service worker
must bypass both `/admin` and every `/admin/` navigation.

After the isolated restore/migration gate passes, validate configuration and run the migration:

```bash
: "${RELEASE_DIR:?Set the reviewed absolute release checkout}"
docker compose -p nerkhbaan --env-file /opt/Nerkhbaan/.env \
  -f "$RELEASE_DIR/docker-compose.prod.yaml" -f "$RELEASE_DIR/runtime.override.json" \
  --profile admin config --quiet
docker compose -p nerkhbaan --env-file /opt/Nerkhbaan/.env \
  -f "$RELEASE_DIR/docker-compose.prod.yaml" -f "$RELEASE_DIR/runtime.override.json" \
  --profile admin run --rm --no-deps --pull never migrate
```

For an existing two-replica API, use healthy overlap. Record the exact two old backend container IDs
and their image IDs before changing the override. Keep both running while adding the first new replica:

```bash
docker compose -p nerkhbaan --env-file /opt/Nerkhbaan/.env \
  -f "$RELEASE_DIR/docker-compose.prod.yaml" -f "$RELEASE_DIR/runtime.override.json" \
  --profile admin up -d --no-build --no-deps --pull never --no-recreate \
  --wait --wait-timeout 120 --scale backend=3 backend
```

Require three healthy replicas, a healthy new-image replica and HTTPS readiness before stopping
and removing only the first recorded old backend ID. Check its Compose project/service labels and
old image again immediately before removal; never infer its identity from a numeric name suffix.
Use `docker stop --time 20 <verified-old-id>` and `docker rm <verified-old-id>` without `-v`.
Recheck HTTPS and repeat the same scale-three command to add the second new replica. Require both
new-image replicas healthy before removing the second recorded old ID. Finish with:

```bash
docker compose -p nerkhbaan --env-file /opt/Nerkhbaan/.env \
  -f "$RELEASE_DIR/docker-compose.prod.yaml" -f "$RELEASE_DIR/runtime.override.json" \
  --profile admin up -d --no-build --no-deps --pull never --no-recreate \
  --wait --wait-timeout 120 --scale backend=2 backend
docker compose -p nerkhbaan --env-file /opt/Nerkhbaan/.env \
  -f "$RELEASE_DIR/docker-compose.prod.yaml" -f "$RELEASE_DIR/runtime.override.json" \
  --profile admin up -d --no-build --no-deps --pull never --wait --wait-timeout 120 \
  frontend admin-frontend price-feed-pull
```

Stop the sequence on a failed health or identity check; keep the surviving healthy replicas and
inspect the scoped private log before continuing. Do not rerun old-ID removal after a partial update.
The earlier 2.8.0 API update passed six HTTPS probes. The 2.8.1 migration transition recorded
503 readiness responses; an earlier API cutover recorded one 502 before recovery. The final
`ce22c1d` cutover recorded two five-second timeouts before recovery and six final HTTPS 200 probes.
All sixteen non-API IDs/start times matched its pre-rollout baseline. Three earlier Dolphin
recreations are retained as differences from the original thirteen-service baseline; a fresh
reviewed baseline and pre-run frontend/admin/feed baseline protect subsequent acceptance.
Exact outage duration was not measured; zero downtime is not claimed. Keep the failed check receipt and reconcile
the actual running replicas before resuming after a partial update. The separate client update
preserved every nonclient container ID.

Keep PostgreSQL, Redis, their containers and their volumes running. Compare their recorded IDs
and mounts after the application update. The generic full-stack script above recreates services;
use this scoped rolling sequence for an existing stack with shared ingress. Do not use `down`, volume
removal or an unscoped forced recreation. The admin health probe uses `http://127.0.0.1/` with a
ten-second `start_period`; this avoids a loopback IPv6 mismatch and early startup failures.
The four custom Nginx images remove the default IPv6-rewrite helper at build time. Their listeners
are already explicit; startup must not fetch Alpine package metadata. Keep image update checks on
the target network and its actual CPU/capability limits, not only on a local unrestricted container.

## 5. Acceptance

Probe `/api/health/ready` through HTTPS ingress or inside the backend container; host port 8000 is not published.
Inspect the JSON, migration version, release, Redis/DB, live source times, persisted units and worker health.
Prometheus scrapes `backend:8000/metrics` privately; neither public nor admin ingress exposes metrics.
Recreate one backend and prove DNS/replica recovery. Verify admin permissions, MFA/recovery, support,
setting effects, draft conflicts, audit and backups status. Verify actual notification receipt.
Install the desktop package on the intended OS and verify controlled-origin login, secure refresh,
external links, chart consent, assets and logout. Run the public browser flow on supported devices.

## Rollback

Keep previous configuration, code and images. Do not remove data volumes, AOF or backups.
If a forward migration makes the older image incompatible, prefer a reviewed forward fix.
Otherwise redeploy the recorded compatible images and rerun readiness, pricing and delivery checks.
Never edit migration checksums or mark failed work completed to make the gate green.

## Relay and feed

The relay is stateless, core-IP restricted and token-gated. Upstream TLS verifies against CA roots.
It solves reachability only; provider rights still need proof.
The public `price-feed` branch is bot-owned output with one orphan commit. It requires permission for
lease-protected replacement of that branch only. Never allow force updates on the source release branch.
See [external workers](external-price-worker.md) and [delivery readiness](delivery-readiness.md).

## Read-only panel backup status

The panel may read ADMIN_BACKUP_STATUS_FILE, a JSON manifest. It does not infer restore success from a backup file.
When an isolated restore drill completes, set BACKUP_STATUS_FILE to an operator-owned manifest path to write
last backup/restore times, size and verified fingerprint result atomically. Mount that single file read-only
into backend and set ADMIN_BACKUP_STATUS_FILE to the in-container path. Keep the runtime manifest out of Git.
Do not mount the whole backup directory just to show status. Without a configured/fresh manifest the panel
reports not-configured or stale. Evidence belongs to the source database and environment named in the manifest.
