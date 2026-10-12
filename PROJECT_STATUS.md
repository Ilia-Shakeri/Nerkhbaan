# Project Status

Code release: **2.8.1**. Record updated: 2026-10-11.

## Current code

The October fixes cover units, source freshness, persisted history, notification delivery,
sessions, admin operations, desktop installation, migrations and operational documents.
Release 2.8.1 adds independent version-two feed quotes, real month pagination, bounded relay
freshness, XAU HTTP validation, shared unfinished WebSocket reads and batched runtime policy reads.
The changelog lists changes. Generated API contracts cover 117 paths.

## Executed checks

The backend suite ran 363 cases: 353 passed and ten PostgreSQL cases skipped locally.
The final API runtime passed 152 targeted cases without skips and four real PostgreSQL
notification-state cases. The repaired SQLite fixtures passed 20 repeated runs without
shared connection overlap. Earlier failed runs remain in the proof bundle.
The final API image has zero HIGH/CRITICAL findings, including unfixed findings, without waivers.
Web, admin and feed images passed the same gate. The 2.8.1 hosted run
[38145319047](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38145319047)
passed all 15 jobs for `2c8c45b615ec3927be681e19f751a5377930fc33`.
Earlier frontend, Edge, restore and admin results remain dated evidence in the delivery matrix.

## Live target

[Site](https://nerkhbaan.ir/) and [panel](https://nerkhbaan.ir/admin/) run 2.8.1.
HTTPS readiness reports `ready=true`; PostgreSQL and Redis connect; eight migrations are current.
Two API replicas run. Migration eight passed on the isolated full copy and live database;
four existing users and delivery rows were preserved. Applied SQL files stayed unchanged.
The migration transition included bounded HTTP 503 readiness responses; zero downtime is not claimed.
Web/admin/feed `7402757` startup passed on the target in 7.154 seconds.
Existing database, Redis AOF, volumes, shared ingress and other business services remain in place.

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
The final image passed 200 simultaneous cold connections with zero errors and 1.347-second p95
first snapshots. Its short HTTP gate failed: 7.963 rps and 6.200-second p95 against 15 rps
and a 1-second limit. Repeated history eligibility reads and duplicate automatic queue jobs remain
under repair; no clean 1800-second soak or fault-window acceptance is claimed.
Expired, uncovered, suspicious and unpersisted quotes stay unavailable.

[Delivery readiness](docs/delivery-readiness.md) holds the acceptance matrix.
[Remaining acceptance](docs/remaining-acceptance-2026-10-11.md) records current proof and limits.
[Server handoff](docs/production-handoff-fa.md) gives live paths and commands.
[Future work](FUTURE_TASKS.md) lists external evidence and optional scale work.

Older dated records remain historical. Refresh target health, source time, unit, delivery,
backup and release evidence when deploying a later change.
