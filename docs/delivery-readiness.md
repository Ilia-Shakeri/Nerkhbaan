# Delivery Readiness — 2.8.6

Updated: 2026-10-17. Code delivery and production acceptance are separate facts.
Do not change a pending marker to passed without a saved successful run for the final source snapshot.

| Gate | Command or proof | Expected marker | Proof scope |
| --- | --- | --- | --- |
| Release consistency | `npm run check:release` | version 2.8.6, no drift | Local |
| Python static/unit | `python -m pyflakes app tests scripts`; `python -m unittest discover -s tests -v` from apps/api | zero static errors; all required tests pass | Local |
| Infra fixture behavior | `python scripts/test_infra_contracts.py` | OK | Local, mocked network/data |
| Browser fixture safety | `TEST_DATABASE_URL=... python scripts/test_browser_fixture.py` | five cases pass, none skipped | Explicit loopback test PostgreSQL, run-owned schema |
| Frontend contracts/types/builds | `npm run verify` | all configured checks pass | Local |
| API contract snapshot | `python scripts/export_api_contracts.py` | API_CONTRACTS_EXPORTED | Local schema, no database startup |
| Python dependency audit | CI repository-security audits both hashed runtime locks with pip-audit 2.10.1 | no known vulnerabilities | Exact pinned package advisories; independent of service acceptance |
| Real database/Redis | CI integration job | migration, lease, HTTP and Redis checks pass | Disposable services |
| Restore | `bash scripts/ci-restore-drill.sh` with separate target | RESTORE_DRILL_OK | Disposable, read/fingerprint comparison |
| Browser flow | `npm run test:e2e` | executed cases pass | Disposable backend and browser |
| Desktop package | CI Windows desktop-package | package builds; target install smoke passes | Package plus actual target |
| Go feed and images | CI go-sidecar and docker-images | tests/build/scans pass | Containers |
| Proxy/monitoring syntax | CI compose job | nginx/promtool/amtool success | Containers |
| Staging acceptance | runbook commands, source canaries, delivery checks | fresh persisted units; alerts arrive; queues drain | Staging |
| Production acceptance | fresh private operator gate file | verifier passes, target health and browser proof | Target host |

## Acceptance rules

- Liveness alone is insufficient. Read readiness JSON, pricing health, source age and queue age.
- Do not use synthetic prices or invented chart points to pass a data gate.
- Do not accept an HTTP 202 as proof of final notification delivery.
- A dry run or listed test does not count as an executed integration/browser test.
- A backup archive that decompresses does not count as a restored Timescale database.
- Existing compressed chunks and market-price duplicates need target database checks before uniqueness changes.
- Keep production evidence outside source control and exclude secrets and customer payloads.

## Current source release — 2026-10-17

Release 2.8.4 contains the Iranian price/history work in the [step-two report](provider-step2-2026-10-17.md).
The local source suite passed 518 backend cases with zero skips, including owned PostgreSQL/Redis
and unit, SQLite/mocked cases. Replaying two captured actual Wallex responses preserved and read
back 24 hourly closing observations per pair in owned PostgreSQL. These proofs do not establish
authenticated provider coverage, source rights or complete archives. Push, final-commit hosted checks
and target deployment for 2.8.4 are pending; earlier target receipts retain their date and release.

## Step-one source validation — 2026-10-16

Release 2.8.2 closes the full first-step code audit, including the pricing, queue, mail, conversation
and interface defects after the initial session/logout/deployment fixes. The final backend run
passed **450 tests, zero skips** with explicit owned loopback PostgreSQL 17.11 and Redis 7.4.11.
The suite also contains unit, SQLite and mocked cases; not every case is a PostgreSQL/Redis test.

Frontend/runtime contracts passed 65 cases. All 26 Edge cases executed: one real public signup and
alert flow on a run-owned PostgreSQL ORM schema and 25 mocked HTTP flows. The browser schema was
removed afterwards. This fixture does not prove migrations, Timescale behavior or real delivery.
Go 1.26.9 passed ten feed checks, including local Git to loopback HTTP forwarding. Fourteen deployment
CLI tests covered 39 fake Docker/Git/HTTPS scenarios; they do not prove a real container cutover.
The 31 helper checks include five real PostgreSQL browser-schema safety cases. All three renderer
builds and Python static checks passed. These suites overlap and must not be combined as one run.

The scoped code correction loop reached 9/10 after the remaining failures were reproduced and fixed.
Original applied SQL is unchanged. The new alert-race and persistence-queue modules are wired into
hosted integration with disposable PostgreSQL/Redis.

Final hosted [run 38972610806](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38972610806)
passed all 15 jobs at `1af7521a2c1c6edf4a41c9db293ad7c021ee8587`; branch and annotated tag
`v2.8.2` were pushed and remotely verified. It includes image scans, migrations, Redis, ordinary
PostgreSQL and Timescale history checks and a disposable database restore. The preceding run
38949985484 remains failed because the Go test container lacked Git; installing that test dependency
passed the same Linux image locally and in the final hosted run without skipping the real Git test.
No live service was changed by this work.

Provider coverage is step two. Continuous source operation, actual notification receipt, publisher
signing and target release acceptance remain separate gates. The 2.8.3 Servix contract repair
passed 464 backend cases with zero skips before its metadata bump; fresh release checks are required.
It is outside the historical `v2.8.2` tag and hosted result.
[The step-two report](provider-step2-2026-10-17.md) retains the remaining input and coverage limits.

## Previously executed evidence — 2026-10-12

Current 2.8.1 acceptance is in [the remaining report](remaining-acceptance-2026-10-11.md).
The full local backend suite ran 396 cases: 383 passed and thirteen PostgreSQL cases were skipped.
The exact final API image `sha256:989b51f1b514817c4f18f0f1e0136ea9613b577b144707199181471fded1ce60`
passed 182 native cases without skips. Actual PostgreSQL 17.11 passed four delivery-state and
three history golden cases; actual Timescale 2.28.3/PostgreSQL 16.14 passed three history golden cases.
The six actual PostgreSQL refresh-concurrency cases also passed in hosted CI. These suites overlap;
do not sum their counts into one fictional complete run.
Twenty repeated SQLite tests passed after separate connection fixtures replaced unsafe StaticPool sharing.
Strict HIGH/CRITICAL image findings are zero, including unfixed findings, without exceptions.
Hosted [run 38222923015](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38222923015)
passed all 15 jobs for application commit `ce22c1d0487d78c58b488aff40616f3ce0a331f1`.
Runtime inputs and fifty frozen test files were bound to that commit with recorded SHA-256 hashes.

Actual target 2.8.1 checks passed eight migrations, 25 real admin routes, security gates,
filtered WebSocket snapshots/ping/reconnect and encrypted pre-migration backup verification.
Four original users and all sixteen non-API container IDs/start times were preserved across the
final API rollout. Ten of thirteen initial protected services remain unchanged. Three Dolphin
apps were externally recreated at 07:53–07:54 UTC before the final load run; attribution is not
established. Their historical differences are preserved alongside the freshly reviewed thirteen-service
guard baseline and a separate pre-run frontend/admin/feed three-service baseline.
Migration readiness had bounded 503 responses; an earlier API cutover had one observed 502.
The final cutover recorded two five-second readiness timeouts, followed by six final 200 probes.
Exact outage duration was not measured; zero downtime is not claimed. The periodic load watcher
does not replace these finer-grained cutover receipts.
Actual in-app notification receipt/read passed. Native Windows push failed with ConnectTimeout.
Actual unsigned NSIS installation/runtime/removal passed; trusted publisher signing is blocked.
Real provider pagination stored 720 provider and 720 canonical history rows on the owned copy,
then cleaned only its fixtures. Earlier rejected load attempts remain dated evidence. The final
image short gate passed at the unchanged caps: 900/900 HTTP 200 responses, 14.990 rps and
442.150 ms p95 over 60.039 seconds. Two hundred simultaneous cold snapshots passed with
zero errors and 1.267-second p95. The fresh clean soak passed 1800.258 seconds, 27,000/27,000
HTTP 200 responses, 14.998 rps and 323.249 ms p95. Each of three public paths completed 9,000
requests with 25 HTTP workers; 200 filtered WebSockets stayed connected with zero clean errors
or disconnects. The cold snapshot p95 in that full run was 1.087 seconds.
Separate fault windows passed the same application image and caps: 200 clients recovered from
one owned API shutdown in 3.746 seconds, 20 fault-window HTTP probes passed and filtered updates
reached every client. Redis outage returned the documented degraded/polling/1013 contract;
all 200 subscriptions resynchronized in 4.495 seconds and filtered live updates reached every client.

The first post-soak Redis publication failed because the fixture publisher reused its closed pool;
the actual application had already resynchronized all clients. Its overall failed receipt remains
unchanged. After 22 helper checks passed, a separate fault-only attempt replaced that fixture pool
once after application resync and passed. Its receipt explicitly records no renewed HTTP soak and
links the original server-byte-identical clean receipts. Combined acceptance uses both attempts;
the failed original overall receipt was not relabelled passed.

Resource caps stayed at PostgreSQL 0.75 CPU/1536 MiB, Redis 0.25/512, each API 0.75/768,
edge 0.25/160 and client 0.5/384. The isolated stack had background scheduling disabled and
synthetic ephemeral PubSub; this proof covers anonymous price/history and filtered streaming,
not arbitrary authenticated/admin traffic or every future workload.
All four copied users, price counts and 13,358 original backfill rows stayed intact. Automatic
history GETs created 64 pending jobs only on the owned copy. Its five labelled containers, internal
network and database volume were then removed; all eighteen nonowned IDs/start times remained
equal and final public readiness returned 200. Proof files and production storage were preserved.

The tested code/infrastructure correction loop reached **9/10**. All-provider continuity,
native Windows push and trusted publisher signing remain blocked; the score is scoped and does
not turn these external acceptance gates into passes.

### Historical 2.8.0 results

These results apply to the 2.8.0 source delivery on this Windows host. They are separate from
the container, Timescale/Redis, staging and production gates below.

| Check | Executed result | Exact scope |
| --- | --- | --- |
| Backend suite | 312 executed cases passed across local and container runs | 306 local unit/SQLite/mocked cases; six real PostgreSQL 17.11 concurrency cases rerun inside the exact API runtime image. The local runner could not reach its PostgreSQL fixture and skipped that class; it is not reported as one complete local run |
| Backend static check | pyflakes passed for app, tests and scripts | Python names/imports |
| Frontend suite | 49 passed | 35 source-contract checks and 14 executed runtime behavior cases |
| Version/lock/document consistency | passed | Release 2.8.0, manifest-lock dependencies, API version and active document headers |
| Clean dependency installation | npm ci passed, 835 packages | Locked workspace dependencies |
| Dependency advisories | npm audit: 0; API Python lock: 0; Telegram Python lock: 0 | Pinned dependencies at scan time; pip-audit 2.10.1 |
| Client builds | web, admin and desktop renderer passed | Build artifacts; separate from target installation |
| Final API runtime | 80 targeted cases and native imports passed; no skips | Exact `a538423` image; backfill fairness, delivery/persistence/provider repairs and WebSocket admission; separate from real target database acceptance |
| Desktop runtime | DESKTOP_SMOKE_OK | Actual unpacked desktop package, builder 26.15.3 / Electron 42.11.9; secure custom origin, assets/path guards and isolated encrypted synthetic credentials |
| Browser suite | 10 executed cases passed on Edge | Eight admin mocks, one real public HTTP flow on the isolated PostgreSQL ORM fixture, and one assistant mock |
| Infrastructure fixtures | 18 passed | Telegram parser/preview parity, units/IDs, source time, history acknowledgement/progress, feed age, restore-target preservation and source archive exclusions/completeness |
| Migration safety unit tests | 3 passed | TLS DSN option preservation, lock deadline and unknown newer version rejection |
| Database connection regressions | 2 passed, included in backend suite | Complete PostgreSQL DSN reaches asyncpg with supported options; driver selection and timeout checks. Real sync/async PostgreSQL queries also pass in the fixture; target certificates are a separate gate |
| Browser database fixture | 5 passed; none skipped | Real PostgreSQL sync/async schema isolation, ownership/refusal/cleanup, JSONB live query and forward SQL fixture checks; legacy history/default role repair preserves data and explicit role overrides |
| Compose configuration | development and production passed; staging trust/subnet assertions passed | Compose configuration only, using synthetic values; no daemon/container proof |
| Documentation/API snapshot | 117 paths exported; local document links passed | Generated schema/route index and local links |

The real PostgreSQL fixture does not contain a forged migration ledger. Its successful queries
do not prove the release migrations against Timescale hypertables or existing compressed chunks.
Browser mocks do not prove administrator HTTP/database integration or real assistant-provider service.
The desktop smoke proves the unpacked local runtime; a signed installer on every supported target remains
a separate acceptance step. Hosted results below are separate executed checks.

## Container and hosted application evidence — 2026-10-11

- [Hosted run 38130107435](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38130107435), commit `581fe7a`: Node, Python, desktop package, actual Timescale/Redis/migration/restore, browser, Go and repository security jobs passed. The full run failed its nginx fixture and image scans; those failures must not be reported as a successful full CI run.
- The nginx fixture now creates synthetic certificates on the runner and resolves backend hostnames. Actual edge/web/admin nginx syntax checks pass on disposable local Docker containers.
- Patched API, web, admin, Telegram, feed-pull, relay and edge images all build. Trivy 0.70.0 reports zero HIGH/CRITICAL findings on all seven, with unfixed findings included and no waiver file. The `/admin/` image also passes the same scan.
- The initial patched Alpine API imported native drivers and passed 20 auth/JWT/body-limit/connection tests; the final API's 80 targeted cases are recorded above. The Telegram worker imports successfully. Go 1.26.9 tests pass. These checks validate runtime compatibility and do not replace target acceptance.
- The `/admin/` build is checked in an actual Edge browser: JavaScript and CSS load, the login form appears and no page error occurs. API paths remain `/api/admin`.

Source manifest and Python lock scans are separate from OS image scans. Evidence belongs to the
recorded image/source snapshot. The corrected source completed all 15 jobs in
[run 38136644783](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38136644783),
commit `a53842359ff147fe8946131f007dbcade7074adc`.
Earlier corrected runs `38132278978`, `38132616228` and `38132847881` also completed all 15 jobs.
Nginx startup correction `1edbe775` completed all 15 jobs in run `38134832791`.
Saved result receipts name the exact run and source commit. Later delivery-document changes
need their own CI result; they do not alter the verified application image source contexts.

## Executed production evidence — 2026-10-11

Live URLs: [public site](https://nerkhbaan.ir/) and [admin panel](https://nerkhbaan.ir/admin/).
Read the [server handoff](production-handoff-fa.md) for the release checkout and safe health commands.
Target is the existing single-host Compose project. No customer payload or credential is copied into Git.

| Check | Executed result | Exact scope |
| --- | --- | --- |
| Full target restore | 47 tables and 1,404,468 rows matched source fingerprints | Exported snapshot from Timescale 2.28.3 / PostgreSQL 16.14; three hypertables, 37 chunks, four aggregates and 12 policies preserved |
| Restore isolation | All 11 user jobs held idle; fingerprints matched before and after post-restore | Owned separate database; retention/purge jobs could not remove rows during comparison; original database/jobs preserved |
| Off-host backups | Database, consistent Redis RDB and configuration ciphertext retrieved; decrypt/tag/hash verified | AES-256-GCM with RSA-OAEP wrapping; private key protected by the delivery Windows profile; plaintext secrets/customer data not exported |
| Target migration staging | Seventh migration passed on the full restored copy | Users and core price fingerprints equal across the intended historical-backfill metadata repair; six applied migration checksums unchanged |
| Actual history claim SQL | FIFO and separate-backend `SKIP LOCKED` passed on the owned full Timescale copy | Exact `a538423` image selected a supported job past 8,702 older unsupported jobs; all 13,358 job rows had equal count/fingerprint after outer rollback; temporary limited role/container removed |
| Live migration/readiness | Seven migrations current; HTTPS 200, `release_version=2.8.0`, `ready=true` | PostgreSQL and Redis connected; migration applied with the verified `b9f5538` API image |
| API failover | Five HTTPS readiness probes returned 200 while one replica was stopped | Second replica served requests; stopped replica restarted healthy; two replicas restored |
| Final API rolling update | Two `a538423` replicas healthy; all six HTTPS probes returned 200 | New replicas admitted with three-replica healthy overlap before each old replica was removed; every non-API container ID preserved |
| Client startup | Actual two-client update completed healthy in 7.234 seconds | Exact `1edbe77` images on target resource/capability limits; all nonclient container IDs preserved; isolated late-backend and address-change checks passed |
| Shared ingress | Syntax check, isolated TLS staging and scoped reload passed | Existing certificate, listeners and other virtual hosts preserved; `/admin/` assets and `/api/admin/` routed separately |
| Admin HTTP canary | 25 real read routes returned 200 | Actual target TLS/API/database; dashboard, users, roles/permissions, providers/drafts, Telegram, instruments, anomalies, jobs/DLQ, settings, alerts, audit, backups and security |
| Admin security canary | MFA required, CSRF refusal, reauthentication, TOTP and recovery login passed | Host-only Secure/HttpOnly cookies with `/api/admin` scope; own temporary account/sessions removed; prior users/roles retained |
| Actual browser/SW route | Edge public page and admin sign-in passed | New public service worker controlled the page before navigation; admin document came from the network; JS/CSS 200 and zero admin page errors; owner account not used |
| Public layout | Stable desktop and mobile login passed | Settled transform/opacity, visible focusable controls, click hit-test, no horizontal overflow, no page errors or failed assets; no user login submitted |
| Public live stream | HTTPS WebSocket handshake 101 and reconnect snapshot passed | Nine unique stored instruments in snapshots; separate eight USD/Toman legs in HTTP price response had instrument IDs, weight units and purity; no values/user data saved |
| Target stream admission fixture | Six cases passed in the final target image | Capacity rejection and Redis-down skip snapshot reads; admitted read and failure cleanup pass. Synthetic mocked callbacks, no real traffic flood or customer changes |
| Backup panel | Verified restore status visible | Only the status JSON file mounted read-only; dump directory not mounted into API |
| Data/other-service preservation | Existing data-service image/config/volumes equal to initial inspection | Data and other business services started before the delivery day with zero restarts; current IDs saved for subsequent exact comparisons |
| Target clock/TLS | Synchronization enabled; HTTPS hostname verification passed | Current target check; a valid certificate does not prove provider usage rights |
| Final post-update acceptance | Both final API replicas and a fresh actual Edge context passed | Internal/external HTTPS readiness 200; seven migration checksums current on each replica; filtered BTC WebSocket snapshot, ping/pong and reconnect passed twice; public/admin assets 200 with zero page errors and no user login |

Private evidence stays in the separate `Nerkhbaan-Delivery` folder and the target's
`nerkhbaan-release-safety` folder. Key receipts include `restore-manifest-gate2-27fcb894.json`,
`offhost-verification-receipt.json`, `migration-stage-receipt.json`, `replica-failover-receipt.json`,
`production-admin-canary-result.json`, `production-public-surface-result.json`
`production-public-login-layout-result.json`, `target-public-stream-1edbe77.json`
`client-rollout-1edbe77-receipt.json`, `api-rollout-a538423-receipt.json` and `target-container-preservation-evidence-79ae69c.json`.
Final runtime receipts: `api-native-a538423.json`, `api-postgres-a538423.json`,
`runtime-api-transfer-a538423.verified.json` and `target-websocket-admission-a538423.json`.
The target also stores `backfill-claim-proof-a538423-fb815544679a4fac.json` under its release-safety folder.
Final post-update receipts are `production-final-api-stream-result.json` and
`production-final-public-surface-result.json`, observed at 12:00–12:01 UTC on 2026-10-11.
The initial container-ID baseline was not saved. Preservation of the earlier data/container creation
and start times, restart counts, image/config and mounts is proven; an unavailable old-ID comparison is not claimed.

Historical quotes were preserved. Source freshness still differs by instrument. Expired, suspect,
uncovered or historical-only data stays gated. Availability checks do not certify fresh coverage of every instrument.
The target queue snapshot found 13,040 older deferred jobs whose last recorded error was
`no_explicit_history_provider`, 187 older live-priority deferrals, 92 older failed jobs and 39 older retrying jobs. Those jobs predate
the release and were preserved. New requests with no history provider return `unsupported` instead
of creating a new job. The panel exposes their state; no queue was wiped or marked complete to pass acceptance.
The last error is historical; current route policy can differ. Some old BTC/USDT jobs now have a history route.
Counts change during normal processing. `target-price-queue-diagnosis-79ae69c.json` records this snapshot.

## Local database browser fixture

`scripts/prepare-browser-db.py` and `apps/api/scripts/browser_test_server.py` require an explicit
loopback `TEST_DATABASE_URL` whose database name has a test marker. They create only a generated
`browser_fixture_<uuid>` schema, set that schema for sync and async database connections, and check
its owner marker before cleanup. They never create a migration ledger or alter production readiness.

Run the fixture server from the repository root with
`python -m uvicorn browser_test_server:app --app-dir apps/api/scripts --host 127.0.0.1 --port 8000`.
Probe `/__fixture__/health`; `/api/health/ready` remains the ordinary readiness contract.
This harness proves real HTTP/ORM/browser behavior on ordinary PostgreSQL. It cannot prove
Timescale migration, compressed chunks, restore, Redis leases, or provider data.
Normal shutdown removes the run-owned schema. After abrupt termination, read the exact schema
from fixture health/logs and run `python scripts/prepare-browser-db.py --cleanup --schema <exact-schema>`
with the same explicit test URL. Never clean `public` or drop the database.
When reusing an earlier owned fixture created before PostgreSQL JSONB type alignment, run
`python scripts/prepare-browser-db.py --schema <exact-schema> --align-json-types` once. This aligns
only columns expected to be JSONB by the current ORM, after the same owner check; it is fixture
maintenance and does not apply or certify release migrations.

## Delivery package

The source ZIP builder copies tracked and eligible new source files, not runtime state.
`DELIVERY_MANIFEST.json` records version, file bytes and SHA-256 hashes. The archive is read back and tested.
Review the file list and run a current secret scan before sharing. Dependencies install from their lock/manifests.
Runtime environments, signing certificates, provider keys, session strings and database backups travel separately.
The ZIP manifest describes source contents and does not attest all external production gates.
Target results are recorded above and remain distinct from provider/legal/device acceptance.

## Remaining environment gates

Docker/Timescale/Redis integration, Go, target restore/migration, TLS, clock, API failover and admin HTTP
checks above have successful evidence. Remaining external gates are provider rights and uncovered-source
canaries, actual notification receipt, signed installation on supported targets, operator privacy details
and a load/soak run with agreed limits. See [remaining work](../FUTURE_TASKS.md).
Keep these gates separate from completed service availability and data-preservation checks.
