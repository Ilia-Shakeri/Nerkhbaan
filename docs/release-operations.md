# Release Operations — 2.8.11

Updated: 2026-10-18. Execute against the intended host only after review of the concrete release.
This runbook does not certify a deployment; dated target evidence is in [delivery readiness](delivery-readiness.md).

The application tag `v2.8.11` points to `9a569550685175f3f7c2859e1474af38edb0f9d5`. Its fifteen source jobs and four hosted runtime builds and strict scans passed. The initial ordinary rollout failed after stopping its first old API; the first explicit recovery then exceeded its 30-second retirement budget because strict API probes ran serially. Both failed receipts remain immutable.

Guard-only commit `25510b00eb4d9ef5fbdb68d5ce1a89c34b19f5f1` batches image inspection and runs the two strict same-ledger API probes concurrently, preserving every validation and the 30-second deadline through removal. Its 48 frozen local cases, 20 independent cases and fifteen hosted jobs in run 39137799260 passed. The actual recovery completed at 15:08:51 UTC on October 18 without rerunning migration. Postdeployment checks completed at 15:10:14, public home/admin browser checks at 15:11:06 and the atomic release pointer at 15:11:42 passed. The two APIs have the exact nine-migration ledger; all five application services use the prepared images. All 22 containers and 17 protected identities were retained through acceptance.

The installed native endpoint completed in 1.683645 seconds. Six prices were present: one live, one fresh cache and four stale; five native contracts were unavailable. The three separate references persisted 887 daily records (297/295/295 days), with 67/69/69 internal missing days across 364 days. All three remain delayed. These receipts do not establish all-live or direct global-dollar/physical-9999 coverage. The original last-change clock remains 14:20 UTC. Follow [the exact recovery contract](normal-deploy-recovery.md) and keep the failed predecessors. Step-three notification source remains Unreleased and outside these application images; actual SMTP, signed Windows installation and device receipt are separate gates.

The following 2.8.8 description and October 17 observations are historical.
Release 2.8.8 adds three separately labelled reference contracts authorized by
the user, without asserting physical 9999 gold or global USD market quotes.
The ninth migration creates a separate reference table; the first eight files
remain immutable. Test the migration on an owned restored copy before the live
application update. Preserve last-change clocks, original receipts and visible
delayed status; source update latency remains unresolved. See the
[reference scope and limits](iranian-references-2026-10-17.md). The previous scope
and dated 2.8.7 results below remain historical evidence.

The 2.8.7 candidate replaces Servix with free Iranian routes for eight of eleven instruments and their actual published archives. All nine Servix routes are hard retired; environment settings, keys or a rights manifest cannot reactivate them. Permitted older history remains available. No new keys are needed for the eight instruments. Physical 9999 gold/Toman, BTC/USD and USDT/USD still lack a proven free Iranian source; quote currency and purity must not be substituted. Final-commit hosted checks and target deployment need separate receipts. The target remained 2.8.1 during the October 17 review. The chosen replacement scope must pass before deployment; reduced coverage is not authorized. See [the source review](provider-rights-2026-10-17.md) and [the replacement evidence and exact archive limits](iranian-replacement-2026-10-17.md).

At the October 17 12:08 UTC target receipt, four Nerkhsanj URLs returned HTTP 200, but all seven current prices were 1,321.66 seconds old and were rejected. Two Wallgold quotes and two Nobitex books passed only at their original receipt times. Wallgold quotes were about 58.79 seconds old; the final registry uses the existing instrument limits of 300 seconds for gold and 120 seconds for silver, with a 60-second request interval. Its roughly 24-hour declared quote expiry does not extend those limits. The separately sampled GTA Silver quote was about 7,757 seconds old and rejected. Nobitex UDF returned 403 from the target and remains disabled. Do not reset the source or original receipt clock, relax age limits, or treat those dated receipts as current live availability.

Nerkhsanj and GTA Silver allow at most one request per minute per URL. Use the shared snapshot cache and retain its original receipt time. Keep source credit and published-time semantics in storage and output. The narrow own-product permission inference for Wallgold and Nobitex is documented in the source review; it is not a resale, derivative-data or external-processing contract. The new grants require review by January 15, 2027. The actual Nobitex runtime already used `apiv2.nobitex.ir`; failure of the obsolete hostname did not justify a DNS, firewall or TLS change.

Local evidence is kept outside Git in the delivery folder `iranian-replacement-20261017`. `target-source-http-proof.json`, `target-parser-replay-proof.json` and `runtime-endpoint-cause.json` record read-only target probes. `target-owned-database-replay-proof.json` records real isolated PostgreSQL and Timescale replays of the first and last observation for each of eight archives: 16 provider and 16 canonical rows in each database, with public fingerprints unchanged. This is neither a full-year import nor a production write. Final local discovery passed 937 backend cases with zero skips; 78 frontend contracts, ten focused mocked browser cases and three renderer builds passed. Two failed earlier full-suite receipts remain separate. Hosted CI, deployment and real SMTP/device acceptance retain their own final-commit receipts.

Mount identities retain every field and compare deterministic mount order; Docker response ordering alone is not a change. The private operator-evidence requirement remains mandatory.

## 1. Final code gates

Run `npm run verify`, `python scripts/test_infra_contracts.py` and export the final API schema.
Run every CI job on the final commit: clients, desktop package, Python, actual Timescale/Redis,
HTTP/browser, migration/restore, Go/sidecars, proxy/monitoring and security scans.
Keep logs tied to release and commit. Do not replace an executed test with test discovery.

Historical 2.8.1 application result, not a 2.8.7 receipt: [CI run 38222923015](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38222923015)
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

Historical target stage, not a 2.8.7 receipt: `TARGET_MIGRATION_STAGE_OK` passed with the `b9f5538` API image on the
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
export RELEASE_DIR="/opt/Nerkhbaan/.releases/${REVIEWED_COMMIT:?Set the reviewed full commit}"
COMPOSE_PROJECT_NAME=nerkhbaan \
COMPOSE_ENV_FILE=/opt/Nerkhbaan/.env \
COMPOSE_OVERRIDE_FILE="$RELEASE_DIR/runtime.override.json" \
DEPLOY_IMAGE_MANIFEST=/run/nerkhbaan/reviewed-images.json \
DEPLOY_READINESS_URL="${DEPLOY_READINESS_URL:?Set the reviewed target HTTPS readiness URL}" \
OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json \
BACKEND_REPLICAS=2 \
sh "$RELEASE_DIR/scripts/deploy-nerkhbaan-prod.sh"
```

The helper updates an existing healthy stack only. Initial infrastructure creation is separate.
It requires the reviewed absolute checkout, explicit existing project, private environment/override,
operator evidence, HTTPS readiness route and image manifest. It refuses a dirty tracked checkout,
missing/unhealthy PostgreSQL, Redis or backup service, a changed network or an ambiguous replica count.
It never pulls source/images or builds. Load reviewed images separately; pin digest or commit tags in
the override and retain previous images. `COMPOSE_FILE` is no longer a deployment input.

The private `DEPLOY_IMAGE_MANIFEST` binds review to the exact checkout and loaded image IDs:

```json
{
  "commit": "<full 40-character checkout commit>",
  "images": {
    "backend": "sha256:<reviewed loaded API image ID>",
    "migrate": "sha256:<same reviewed loaded API image ID>",
    "frontend": "sha256:<reviewed loaded public image ID>",
    "admin-frontend": "sha256:<reviewed loaded admin image ID>",
    "price-feed-pull": "sha256:<reviewed loaded feed image ID>"
  }
}
```

Include only the currently installed client/feed services; admin is updated only if already present.
Use `docker image inspect --format '{{.Id}}' <reviewed-reference>` to record each loaded ID.
The helper checks the migration/API identity, loaded IDs and resolved configuration before mutations.
It verifies backend/migrate `env_file` paths resolve to `COMPOSE_ENV_FILE`; `--env-file` alone only
sets interpolation inputs. Keep the release `.env` as a private link to the selected runtime file,
or use a reviewed override that replaces the service file list. Competing files cause refusal.
Expected service hashes come from that fully resolved Compose model, passed in memory through
stdin to the same Compose CLI with the original project name and directory. In Compose 5.1.4,
plain `config --hash` skips service `env_file` resolution and can differ from the hash written by
`up` even with identical files. Private resolved values never enter command arguments, logs or
temporary files. The actual container label must still match the independently predicted hash;
image, configuration, environment binding and all other deployment checks remain required.
It probes SQL checksums from the exact desired image in an ephemeral read-only container with no
network, environment file or volumes, then compares the checkout, old API's migration files and a
read-only ledger query. By default all four must match before the migration service runs. Changed
or unknown ledger entries always stop deployment. The one reviewed additive transition below
requires its separate private plan and restore proof. It runs the service explicitly with `--no-deps --pull never`,
adds one backend with `--no-recreate`,
checks all replicas and HTTPS, then stops/removes only the recorded old ID after rechecking its
project/service labels, image, static configuration, mounts, network identity and start time.
With an unchanged ledger, each replacement keeps the requested number of healthy replicas. Same-image configuration changes
also roll; an already current backend retains its IDs. Client/feed changes use explicit targets and
`--no-deps --no-build --pull never`. Data, backup, ingress, monitoring and unrelated containers are
compared against their original IDs/configuration/mounts/start times throughout the update.

Redirect deployment output to a private release log. On any health/identity/configuration failure,
the helper stops and keeps remaining replicas. Reconcile the actual stack before retrying; an extra
replica from a partial attempt causes preflight refusal. No automatic rollback, volume removal,
infrastructure recreation or replica scale-down is performed. Without the reviewed additive plan,
a different schema stops before the migration service, retaining the old API's strict ledger readiness.
Passing mocked CLI tests is not target deployment evidence. Compose must support
[`config --no-env-resolution` and `--hash`](https://docs.docker.com/reference/cli/docker/compose/config/).

### Reviewed reference-table addition: 2.8.1 to 2.8.8

`DEPLOY_MIGRATION_PLAN` may name a private absolute JSON file for exactly one transition: the
unchanged eight-migration 2.8.1 baseline plus `20261017_001_iranian_reference_records.sql`.
The helper pins that migration's normalized SQL SHA-256 to
`05ba325399df2b031459b6484d5cc02b4071f12dd708cdad7e65e5a8cd1e642b`.
It creates only `public.pricing_reference_records` and its index, with a five-second lock timeout.
Changes to old migrations, extra migrations, an already advanced live ledger, or another SQL body
remain forbidden. This is not a general schema bypass. Do not invoke the manual migration/scale
examples below for this transition; supply the plan to the guarded helper above.

The plan has exactly these fields:

| Field | Required value |
| --- | --- |
| `schema_version`, `kind` | `1`, `iranian-reference-addition-v1` |
| `commit`, `project`, `readiness_url` | Exact reviewed checkout, existing project and HTTPS URL |
| `images` | Exact service-to-loaded-image-ID mapping from the image manifest |
| `baseline_backends` | Every current backend as `{id, image, release_version: "2.8.1"}`; one old image |
| `baseline_migrations` | All eight exact filename-to-normalized-SQL-checksum entries |
| `target_migrations` | The same eight entries plus the pinned ninth migration |
| `evidence` | `{path, sha256}` for the actual isolated restore/compatibility report |

The report must contain `schema_version: 1`, the same `kind`, and a UTC `checked_at` no more than
24 hours old or five minutes in the future. Its `release` object repeats exactly `commit`, `project`,
`readiness_url`, `images`, `baseline_backends`, `baseline_migrations` and `target_migrations` from
the plan. Do not put `schema_version`, `kind` or `evidence` inside `release`.

The report's `restore` object records `isolated: true`, the actual live PostgreSQL container ID as
`source_database_container_id`, exact `baseline_migrations` and `target_migrations`,
`migration_image` equal to the exact target migrate image ID,
`migration_command: ["python", "-m", "app.migrations.runner"]`, and equal
`existing_data_sha256_before`/`existing_data_sha256_after` fingerprints of every pre-existing table
except the migration ledger, `new_table: "public.pricing_reference_records"` and `new_table_rows: 0`.
Produce these facts from an owned restored copy, run the exact migration service there with the
reviewed runtime settings (redirect database and Redis to the owned copy), and
retain the failed receipts as well as the passing transcript. No production restore is performed.
The full runner also reconciles the admin role/permission catalog; raw SQL-only execution cannot
prove that existing data remains unchanged. The helper refuses a different migrate command or an
overridden entrypoint for this additive transition.

The report's `compatibility` object records exact image IDs as `old_image` and `new_image`,
`old_release_version: "2.8.1"`,
`old_ready_status: 503`, the actual `old_ready_payload`, `old_migration_state`,
`new_ready_status: 200`, and actual `new_ready_payload` from the exact target image. Both payloads
must have connected database and Redis. The old payload alone must report `ready: false`,
`migration_current: false`, `status: "degraded"`; its exact migration state must be
`{current: false, version: "20261017_001_iranian_reference_records.sql", applied_count: 9,
expected_count: 8, missing: [], changed: [], unknown: ["20261017_001_iranian_reference_records.sql"]}`.
The new payload must report release `2.8.8`, `ready: true`, `migration_current: true`, `status: "ok"`
and the ninth migration version. `business_probes` must contain old-image read-only `/api/prices`
and `/api/instruments` responses, each with `status: 200` and its actual `body_sha256`.
The report's `transcript` is `{path, sha256}` for its nonempty private raw restore/probe transcript.
These checks validate supplied evidence bindings; operators remain responsible for truthful receipts.

Plan, report and transcript must be regular files owned by the deploying user, without group/other
permissions on Linux. Their content hashes and report freshness are rechecked before further
mutations. Finalize the reviewed commit and loaded image IDs before creating these files.
The existing operator, environment, image, network, data-service and old-replica gates still apply.

After migration the helper directly verifies every old container's files, exact nine-entry ledger,
and readiness JSON. Old replicas remain running but their strict readiness is **503**, solely from
the known ninth unknown migration. They are not counted as Docker-healthy. Scale-up skips Compose's
all-container `--wait`, then polls new-image health within `DEPLOY_WAIT_SECONDS`; child commands and
HTTPS readiness share the remaining startup deadline, and a late successful probe is rejected. Every new
replica must pass Docker health, direct strict readiness and the exact nine-entry manifest before
an old ID can be stopped. From migration until the last old ID retires, only the validated old migration-only HTTPS 503 or
strict new-image HTTPS 200 is accepted; all other errors stop. Final acceptance requires only new
replicas and strict HTTPS 200. Transition steps are recorded in the private release output.

Any failure leaves remaining containers in place. The forward ledger remains recorded; there is
no automatic rollback onto the older schema expectation. Review actual old/new IDs and the private
failure log before a separately reviewed recovery. Business-route compatibility on the restored
copy does not establish zero downtime on production.

### Explicit recovery after the first reference-release candidate

`DEPLOY_RESUME_PLAN` is a separate, narrow continuation of a failed guarded update. It accepts
only the recorded state after the pinned ninth migration and first candidate startup: both
original 2.8.1 APIs remain running with unchanged identities, exactly one recorded 2.8.8 API is
already Docker-healthy and directly ready, and every original container fingerprint is unchanged.
The original failed attempt, failed completion receipt and private log remain immutable. A generic
rerun, adopting an unknown extra replica, accepting an observed label as the expected configuration,
or rerunning the migration service is refused.

Keep application `RELEASE_DIR` at its original clean commit and keep its image manifest, runtime
override, private environment and migration plan. Stage the guard-only correction in another clean
Git checkout. Invoke that checkout's `scripts/deploy-nerkhbaan-prod.sh`; the wrapper executes its
own adjacent Python file after changing to application `RELEASE_DIR`. This separates the tested
`guard_commit` from `application_commit` without editing an immutable application release or
retagging its images. The guard also rejects differences in packaged API sources, database files,
dependency lock or API recipe between these commits. Validate the exact application's runtime
image/source proof before preparing recovery evidence; no replacement image is selected here.

The resume plan is a deploy-owned private regular file with exactly these keys:

| Field | Required value |
| --- | --- |
| `schema_version`, `kind` | `1`, `iranian-reference-resume-after-first-candidate-v1` |
| `application_commit`, `guard_commit` | Exact clean application and guard Git revisions |
| `application_version`, `project`, `readiness_url` | `2.8.8`, existing project, exact HTTPS readiness URL |
| `images`, `baseline_backends`, `target_migrations` | Original five image IDs, two recorded old API identities, exact nine-entry ledger |
| `added_backend` | `{id, image, config_hash}` for the single recorded candidate; expected hash comes from the reviewed fully resolved model |
| `files` | The twelve exact file/hash references below |

Each `files` value is exactly `{path, sha256}`. The required names are `failed_attempt`, `failed_proof`,
`failed_log`, `migration_plan`, `image_manifest`, `restore_report`, `restore_transcript`,
`operator_evidence`, `compose_override`, `private_environment`, `guard_ci`, and `fresh_observation`.
Keep original evidence at its original path. Put new recovery plans, observations, CI receipts,
attempts and completion receipts in a separate private recovery directory. Existing migration and
restore report/transcript bindings must agree with this additional chain. Every bound file and both
clean source revisions are rechecked before later mutations; a changed file stops the continuation.

`guard_ci` contains `schema_version: 1`, `guard_commit`, positive integer `run_id`, its exact
`https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/<run_id>` URL as `run_url`,
`status: "completed"`, `conclusion: "success"`, and fifteen uniquely named `jobs`, each with
`name`, `status: "completed"`, and `conclusion: "success"`. Obtain these fields from the actual
hosted run on the finalized guard commit. A local passing test or another commit's workflow is
insufficient.

`fresh_observation` contains `schema_version: 1`, the same `kind`, `source: "actual_target_read_only"`,
and UTC `checked_at` no older than 900 seconds or more than 30 seconds in the future. Its `binding`
repeats exactly the plan's nine fields from `application_commit` through `target_migrations`, without
`schema_version`, `kind` or `files`. Its other fields are:

- `baseline_container_fingerprints`: the original attempt's complete ID-to-hash map.
- `current_container_fingerprints`: the same original identities plus only the recorded added ID.
- `current_container_roles`: every current ID mapped to `{project, service}`.
- `resolved_config_sha256`: SHA-256 of UTF-8 `json.dumps(config, sort_keys=True, separators=(",", ":"))`.
- `service_hashes`: independently predicted resolved-model hashes for backend, frontend,
  admin-frontend and price-feed-pull.
- `probes`: three direct `backend_probe` results, each with its actual `id` and `image`.
- `semantic_checks`: exactly `environment`, `command`, `entrypoint`, `user`, `working_dir`,
  `stop_signal`, `custom_labels`, `exposed_ports`, `healthcheck`, `cap_drop`, `security_options`,
  `read_only_rootfs`, `restart_policy`, `published_ports`, `mounts`, and `networks`, all Boolean true.

Container fingerprints use SHA-256 of `json.dumps(identity(container) | {"Running": running},
sort_keys=True)` with the default separators, matching the original deployment attempt. Mounts
are ordered by destination, type and source; networks contain their actual network IDs. The semantic
checks compare the resolved model and image defaults with the actual candidate, handling inherited
null commands, literal dollar signs and health duration units. They expose neither environment
values nor secret destinations. The fresh fingerprint binds those results to the still unchanged
candidate. Live probes independently recheck exact packaged files, ledger, database/Redis and the
known old migration-only 503 versus strict new 200 contract.

After preflight, continuation first verifies the existing candidate again, then stops/removes the
first recorded old API while retaining the candidate and second old API. It then performs the usual
healthy overlap to replace the second old API, verifies two strict new APIs, and updates only the
three existing application targets. The migration runner is never invoked in resume mode. Protected
containers are derived from the original roles rather than a new baseline; data, backup and unrelated
services retain their original fingerprints. If continuation fails, retain its separate failed receipt
and remaining replicas, inspect the exact state, and prepare a new reviewed recovery. No automatic
retry, rollback or broader recovery state is enabled by this plan.

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
and mounts after the application update. The checked script now implements the scoped application
sequence; the manual commands above document its review gates. Do not use `down`, volume
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
