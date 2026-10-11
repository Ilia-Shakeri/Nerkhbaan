# Project Status

Code release: **2.8.0**. Record updated: 2026-10-11.

## Current code

The October audit drove fixes to price units, source freshness, canonical verification,
resumable history, alert validation, session lifecycle, admin operations, Telegram parsing,
desktop integration, migration safety, CI coverage and operational documentation.
The exact delivered change set is in `CHANGELOG.md`; every HTTP contract is generated in `docs/api-contracts.json`.

## Proof boundary

This document describes the code delivery. It does not assert that release 2.8.0 is deployed.
Local unit, static, build and fixture checks belong to the delivery evidence.
The local record includes 298 backend cases, 49 frontend cases, 10 executed Edge browser cases,
all three client builds, an actual unpacked desktop smoke, real disposable PostgreSQL concurrency/fixture
checks and zero reported npm/API/Telegram dependency advisories. The exact limits are in the delivery matrix.
Container builds, Timescale/Redis integration, signed target installation and live operational acceptance
still need their own successful run. Production needs fresh operator evidence.
A historical success, a compressed backup and a green process are not proof of a current restore,
current provider rights, current clock health or delivered alerts.

[Delivery readiness](docs/delivery-readiness.md) is the acceptance matrix.
[Release operations](docs/release-operations.md) is the data-safe deployment sequence.
[Future work](FUTURE_TASKS.md) lists external evidence and optional scale work.

## Historical records

Earlier deployment records remain in the changelog and dated provider/legal reports.
Their dates and versions remain historical. No past version is called the current live version here.
Refresh live release, schema, readiness, source time, price unit, delivery and backup evidence on the target host.
