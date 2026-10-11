# Release Operations — 2.8.0

Updated: 2026-10-11. Execute against the intended host only after review of the concrete release.
The release delivery is source code; this document does not certify a deployment.

## 1. Final code gates

Run `npm run verify`, `python scripts/test_infra_contracts.py` and export the final API schema.
Run every CI job on the final commit: clients, desktop package, Python, actual Timescale/Redis,
HTTP/browser, migration/restore, Go/sidecars, proxy/monitoring and security scans.
Keep logs tied to release and commit. Do not replace an executed test with test discovery.

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
The 2.8.0 forward migration tags legacy provider backfill canonical rows as historical and adds
a partial live-observation index. Check those UPDATE/index operations against existing compressed
chunks in the isolated restored database first. If the target version requires decompression,
pause the relevant policy and decompress only reviewed affected chunks before retrying the unchanged
migration. Keep the old history rows; never delete them to make migration or live-price checks pass.
The helper drops only its explicitly separate restore target and cleans it on exit.
It uses Timescale pre/post restore and compares fingerprints. It is for disposable/frozen test data;
concurrent source writes invalidate a before/after fingerprint. Production-sized off-host drill needs its own evidence.
A `.gz` integrity check alone is not restore proof.

Run the dedicated migrate service before backend. Applied files are immutable.
The new forward migration adds MFA replay state, widens pricing metadata and repairs known legacy Telegram defaults.
An unknown newer migration stops an older release. Lock acquisition has a deadline.
DATABASE_URL TLS query settings remain intact, including verify-full and CA/client certificate settings.
Do not automatically roll an older API onto a newer schema. Review compatibility first.
Existing market-price duplicates/compressed chunks need a preservation plan before a new uniqueness constraint.

## 4. Target deployment

Check clock synchronization and TLS. Fill a fresh private operator evidence file and validate it.
Only a real owner can provide source rights, secret-store, restore, target health and browser proof.

```bash
OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json \
BACKEND_REPLICAS=2 \
sh scripts/deploy-nerkhbaan-prod.sh
```

The script is configured for `/opt/Nerkhbaan`; review the path on the actual target.
It refuses missing/invalid evidence and a dirty tracked worktree. Preserve all volumes.
Use reviewed immutable image/version tags and retain previous images.

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
