# Project Status

Code release: **2.8.1**. Record updated: 2026-10-11.

## Current code

The October audit drove fixes to price units, source freshness, canonical verification,
resumable history, alert validation, session lifecycle, admin operations, Telegram parsing,
desktop integration, migration safety, CI coverage and operational documentation.
The exact delivered change set is in `CHANGELOG.md`; every HTTP contract is generated in `docs/api-contracts.json`.

## Executed checks

Backend: 306 local cases plus six real PostgreSQL concurrency cases inside the final API image passed.
The local PostgreSQL class was skipped after a loopback-fixture connection failure; those six cases
were executed separately with direct Docker DNS. All 312 cases thus have execution evidence.
Also passed: 49 frontend cases, 10 Edge browser cases, three builds and an unpacked desktop smoke.
Package advisories: zero. Hosted
[run 38136644783](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38136644783)
passed all 15 jobs for `a53842359ff147fe8946131f007dbcade7074adc`.
This includes real Timescale/Redis, migrations, restore, browser, desktop packaging, Go,
Compose/monitoring and seven strict HIGH/CRITICAL image scans.

## Live target — 2026-10-11

[Site](https://nerkhbaan.ir/) and [panel](https://nerkhbaan.ir/admin/) run 2.8.0.
HTTPS readiness reports `ready=true`; PostgreSQL and Redis connect; seven migrations are current.
Two API replicas run. Five HTTPS probes passed while one replica was stopped; it returned healthy.
The final `a538423` API rollout added healthy replacements before removing old replicas;
all six HTTPS probes returned 200 and every non-API container ID was preserved.
Web/admin `1edbe77` startup passed on the actual target in 7.234 seconds.
Existing data services, Redis AOF and other business services remain in place.
The shared ingress serves the panel under `/admin/`; a second listener was not added.

An isolated restore matched all 47 tables and 1,404,468 rows before and after enabling normal restore mode.
User jobs stayed idle during comparison. The seventh migration passed on that full copy and then on live data.
Price/user fingerprints matched across the intended historical metadata repair.
Encrypted database, Redis and configuration backups were retrieved and verified off-host.
The admin canary passed 25 real read routes, CSRF, reauthentication, MFA/recovery and verified backup status.
Only its temporary account was removed; existing users and roles stayed intact.
Final post-update checks passed on both API replicas, including all seven migration checksums.
An actual filtered WebSocket reconnect and a fresh Edge public/admin service-worker flow also passed.

## Proof limits

Freshness differs by source. Expired or uncovered instruments stay labelled unavailable.
Provider rights, actual device notification receipt, a signed installer and long load/soak acceptance
remain external gates. A green process or build does not prove them.
Read the delivery matrix for exact checks and private receipt names.

[Delivery readiness](docs/delivery-readiness.md) is the acceptance matrix.
[Release operations](docs/release-operations.md) is the data-safe deployment sequence.
[Server handoff](docs/production-handoff-fa.md) gives live paths and health commands.
[Future work](FUTURE_TASKS.md) lists external evidence and optional scale work.

## Historical records

Earlier deployment records remain in the changelog and dated provider/legal reports.
Their dates and versions remain historical. No past version is called the current live version here.
Refresh live release, schema, readiness, source time, price unit, delivery and backup evidence on the target host.
