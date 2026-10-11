# Delivery Readiness — 2.8.0

Updated: 2026-10-11. Code delivery and production acceptance are separate facts.
Do not change a pending marker to passed without a saved successful run for the final source snapshot.

| Gate | Command or proof | Expected marker | Proof scope |
| --- | --- | --- | --- |
| Release consistency | `npm run check:release` | version 2.8.0, no drift | Local |
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

## Executed local evidence — 2026-10-11

These results apply to the 2.8.0 source delivery on this Windows host. They are separate from
the container, Timescale/Redis, staging and production gates below.

| Check | Executed result | Exact scope |
| --- | --- | --- |
| Backend suite | 298 passed; none skipped | Unit/SQLite/mocked cases plus six real PostgreSQL concurrency cases on a disposable PostgreSQL 17.11 test database |
| Backend static check | pyflakes passed for app, tests and scripts | Python names/imports |
| Frontend suite | 49 passed | 35 source-contract checks and 14 executed runtime behavior cases |
| Version/lock/document consistency | passed | Release 2.8.0, manifest-lock dependencies, API version and active document headers |
| Clean dependency installation | npm ci passed, 835 packages | Locked workspace dependencies |
| Dependency advisories | npm audit: 0; API Python lock: 0; Telegram Python lock: 0 | Pinned dependencies at scan time; pip-audit 2.10.1 |
| Client builds | web, admin and desktop renderer passed | Build artifacts; separate from target installation |
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
a separate acceptance step. CI definitions were updated but were not reported as completed remote runs.

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

## Remaining environment gates

Until successful final-source evidence exists, Docker/Timescale/Redis integration, Go execution,
signed installer and target installation, target TLS certificates, provider licensing/canaries,
staging soak and live production checks remain pending.
Local green checks must never be reported as those proofs.
