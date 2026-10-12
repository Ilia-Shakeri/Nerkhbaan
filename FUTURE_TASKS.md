# Remaining Acceptance and Optional Work

Code baseline: **2.8.1**. Updated: 2026-10-11.
A task here is external acceptance or optional product work; it is not a substitute for fixing a known code defect.

## Completed target checks — 2026-10-11

- All 15 hosted jobs passed for the recorded source snapshot in the delivery matrix.
- Encrypted off-host backup retrieval passed; isolated target restore matched 47 tables and 1,404,468 rows.
- Eight migrations passed on the Timescale copy and live data; applied SQL and existing users were preserved.
- Target clock, TLS, shared ingress, two-replica failover and 25 real admin routes passed.
- Final API rolling update passed six HTTPS probes with healthy overlap; data/other-service IDs stayed equal.
- Final client update and actual public/admin service-worker navigation passed on the target.
- Actual in-app notification receipt/read and unsigned 2.8.1 NSIS install/runtime/removal passed.
- All 39 provider routes were inspected; a real 720-point month passed durable storage and owned cleanup.
- The 200 simultaneous cold WebSocket gate passed; earlier HTTP throughput and p95 gates failed.

## Remaining external acceptance

- Obtain current provider usage/redistribution rights and canary fixtures from the operator.
- Supply reachable continuous external collection and approved direct GOLD_24K/cash USD sources.
  The user has no external host or proxy; manual hosted feed success is not continuous coverage.
- Restore verified target access to Windows push. Real Edge subscription/outbox passed;
  native receipt failed with ConnectTimeout on both container and host. In-app receipt/read passed.
- Supply a trusted publisher certificate or signing service, then execute the signed installer gate.
  The user has no certificate. Actual unsigned NSIS install/runtime/removal passed; no signature is claimed.
- Supply current privacy/retention/operator details and confirm legal text with the responsible owner.
- Close the staging 15 rps / 1-second p95 gate, then run a clean 1800 seconds with 200 WebSockets
  and separate replica/Redis fault windows. The latest short run reached 7.963 rps / 6.200-second p95.
  It exposed repeated history eligibility reads and duplicate automatic backfill jobs; fix before acceptance.

Use `docs/operator-gates.evidence.example.json` as the shape; the placeholder file must fail validation.
No local script can invent provider rights, secret-store activation or live-server proof.
The operator evidence file is separate from the completed target health, restore and admin receipts.

## Optional product and scale work

- Multiple independent hosts and disaster recovery beyond a single Compose host.
- Agreed data retention/export controls, localization coverage and accessibility review on target devices.
- Provider contracts for uncovered instruments; keep unavailable instruments honestly unavailable meanwhile.
- Performance budgets and an operator-owned alert escalation schedule.
- Before adding any new market-price uniqueness constraint, inventory duplicates and preserve conflicting rows.
  The delivered migration does not silently delete those rows or enforce that future constraint.

See [delivery readiness](docs/delivery-readiness.md) for commands and expected markers.
