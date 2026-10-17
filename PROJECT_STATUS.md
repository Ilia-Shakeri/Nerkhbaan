# Project Status

Code release: **2.8.3**. Record updated: 2026-10-17. This release contains the step-two Servix contract repair; operational provider coverage remains incomplete.

## Step-one code acceptance — 2026-10-16

The complete code-fix scope is closed: user/admin session closure, durable logout, scoped deployment,
provider budgets/health/currency/feed isolation, immutable alert occurrences, alert-cap and channel
completion races, durable queue backpressure/quarantine, SMTP, worker authentication, conversation
responses and the public/admin interface fixes. Applied SQL and dependency versions are unchanged.

The final local suite passed 450 backend tests with zero skips, 65 frontend checks and 26 Edge cases.
Owned PostgreSQL 17.11 and Redis 7.4.11 exercised the database/queue races; other cases use unit,
SQLite and mocked fixtures. Ten Go feed cases, fourteen fake deployment CLI tests and 31 helper
checks passed. Public/admin/desktop renderer builds passed. The scoped code correction loop reached
9/10. These counts are separate suites; they do not represent a complete target acceptance run.

Release tag `v2.8.2` and its branch were pushed and remotely verified at
`1af7521a2c1c6edf4a41c9db293ad7c021ee8587`.
Hosted [run 38972610806](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38972610806)
passed all 15 jobs, including real database/Redis cases, disposable restore and image scans.
The earlier [run 38949985484](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38949985484)
remains failed: the Go test container lacked Git. The one-line environment repair passed the same
image locally and in the final hosted run; the real Git case was retained.

Provider coverage is the next roadmap step. Source rights, direct 24K/cash-dollar inputs, continuous
collection, real notification receipt, trusted signing and target acceptance retain their own gates.
No live service or customer data was changed. Hosted results for older commits below are historical.

## Step two — 2.8.3 source validation

The Servix current-price parser now requires explicit `quoteUnit` and timezone-bearing
`businessTime`, accepts the documented array/single-object shapes and rejects duplicate selected
codes. Parser/registry provenance is `servix-assets/1.1.0`. The preceding local run passed all 464
backend tests with zero skips, including 14 new contract cases. The suite uses owned PostgreSQL/Redis
and unit, SQLite/mocked cases; no authenticated provider payload was obtained. The repair is included
in 2.8.3. Its release checks are separate from the historical `v2.8.2` hosted run above.

The initial empty-venv attempt failed imports. A second attempt passed with three history cases
skipped; its receipt remains partial. The final run explicitly selected ordinary PostgreSQL history
and passed all 464 cases. Neither earlier receipt was relabelled passed.

[Step-two source report](docs/provider-step2-2026-10-17.md) records the October 16 read-only
canaries, official source links and remaining inputs. No provider was enabled and no key was added.

## Previous release context — 2.8.1

The October fixes cover units, source freshness, persisted history, notification delivery,
sessions, admin operations, desktop installation, migrations and operational documents.
Release 2.8.1 adds independent version-two feed quotes, real month pagination, bounded relay
freshness, XAU HTTP validation, shared unfinished WebSocket/history reads, batched runtime policy
reads, bounded automatic history enqueue and verified streaming history aggregates.
The changelog lists changes. Generated API contracts cover 117 paths.

## Previously executed checks — 2026-10-12

The backend suite ran 396 cases: 383 passed and thirteen PostgreSQL cases skipped locally.
The exact final API runtime passed 182 targeted cases without skips. Real PostgreSQL 17.11
passed four notification-state and three history golden cases; Timescale 2.28.3/PostgreSQL 16.14
passed three history golden cases. These overlapping suites are separate proofs, not additive totals.
The repaired SQLite fixtures passed 20 repeated runs without
shared connection overlap. Earlier failed runs remain in the proof bundle.
The final API image has zero HIGH/CRITICAL findings, including unfixed findings, without waivers.
Web, admin and feed images passed the same gate. The 2.8.1 hosted run
[38222923015](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38222923015)
passed all 15 jobs for application commit `ce22c1d0487d78c58b488aff40616f3ce0a331f1`.
Both actual PostgreSQL history backends also passed in CI.
Earlier frontend, Edge, restore and admin results remain dated evidence in the delivery matrix.

## Last target record — 2026-10-12

[Site](https://nerkhbaan.ir/) and [panel](https://nerkhbaan.ir/admin/) run 2.8.1.
HTTPS readiness reports `ready=true`; PostgreSQL and Redis connect; eight migrations are current.
Two API replicas run. Migration eight passed on the isolated full copy and live database;
four existing users and delivery rows were preserved. Applied SQL files stayed unchanged.
The migration transition included bounded HTTP 503 readiness responses. The final API cutover
recorded two five-second readiness timeouts, then six successful HTTPS checks; zero downtime is not claimed.
Web/admin/feed `7402757` startup passed on the target in 7.154 seconds.
Existing database, Redis AOF, volumes and shared ingress remain in place. All sixteen non-API
container IDs/start times matched the baseline captured before the final API rollout. Ten of the
original thirteen protected services remained unchanged; three Dolphin app containers had been
recreated at 07:53–07:54 UTC before final acceptance. Their external actor is not established.
The freshly reviewed thirteen-service baseline is the subsequent load/cleanup guard.

An earlier full restore matched 47 tables and 1,404,468 rows. Encrypted database, Redis and
configuration backups were retrieved and verified off-host. The newer pre-migration-eight dump
was separately captured, encrypted and verified; it was not independently restored again.
The earlier admin canary passed 25 real routes, CSRF, reauthentication, MFA and recovery.
Only the temporary account was removed. New release and load proofs have separate receipts.

## Proof limits

All 39 provider routes and 11 instruments were inspected. A real 720-point month was paginated,
durably stored and precisely cleaned on the isolated database. Continuous external collection,
missing approved GOLD_24K and cash USD inputs, and provider rights remain external gates.
Actual in-app receipt and read passed. Native Windows push failed with ConnectTimeout on both
the container and host; the user has no external relay. The unsigned 2.8.1 NSIS installer passed
actual install/runtime/removal checks. No publisher certificate exists; signed release correctly fails.
Earlier failed load attempts are preserved. After fixing repeated history policy reads, duplicate
automatic enqueue and history aggregate cost, the final image passed its short gate: 900/900 HTTP
200 responses in 60.039 seconds, 14.990 rps and 442.150 ms p95. Two hundred simultaneous cold
connections passed with zero errors and 1.267-second p95 first snapshots. Resource caps and
thresholds were unchanged. The fresh clean soak passed 1800.258 seconds: 27,000/27,000 HTTP 200
responses, 14.998 rps, 323.249 ms p95 and 200 continuously connected filtered WebSockets with
zero errors/disconnects. Separate fault windows then passed: all 200 connections recovered from
one API shutdown in 3.746 seconds; Redis outage exposed polling degradation/1013 and all 200
subscriptions resynchronized in 4.495 seconds with filtered live updates verified.
The first post-soak fault sequence failed its synthetic publisher's closed Redis pool after
application resync. That failed receipt remains intact; a corrected, independently recorded
fault-only run reused the proved clean soak and exact unchanged application image. It did not
repeat or claim a second half-hour run.
The owned five-container test stack, internal network and labelled database volume were removed
after proof capture. Its 64 new pending jobs existed only in that copy; all 13,358 legacy rows
were fingerprinted unchanged before teardown. All eighteen nonowned containers retained IDs/start
times and final production readiness returned HTTP 200.
Expired, uncovered, suspicious and unpersisted quotes stay unavailable.

The correction loop reached **9/10 for the tested code and single-host infrastructure scope**
after policy/queue/current-price/history repairs and actual load/fault proof. Full operational
acceptance remains incomplete because trusted signing, native push and continuous all-source
coverage need unavailable external inputs. This score does not certify those gates.

[Delivery readiness](docs/delivery-readiness.md) holds the acceptance matrix.
[Remaining acceptance](docs/remaining-acceptance-2026-10-11.md) records current proof and limits.
[Server handoff](docs/production-handoff-fa.md) gives live paths and commands.
[Future work](FUTURE_TASKS.md) lists external evidence and optional scale work.

Older dated records remain historical. Refresh target health, source time, unit, delivery,
backup and release evidence when deploying a later change.
