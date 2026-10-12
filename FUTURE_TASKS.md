# Remaining Acceptance and Optional Work

Code baseline: **2.8.1**. Updated: 2026-10-12.
A task here is external acceptance or optional product work; it is not a substitute for fixing a known code defect.

## Completed target checks — 2026-10-11–12

- All 15 hosted jobs passed for the recorded source snapshot in the delivery matrix.
- Encrypted off-host backup retrieval passed; isolated target restore matched 47 tables and 1,404,468 rows.
- Eight migrations passed on the Timescale copy and live data; applied SQL and existing users were preserved.
- Target clock, TLS, shared ingress, two-replica failover and 25 real admin routes passed.
- Final API rolling update passed six final HTTPS probes with healthy overlap; four users and
  the sixteen current non-API container IDs/start times stayed equal. Two five-second readiness
  timeouts were recorded during cutover; zero downtime is not claimed. Three earlier Dolphin
  recreations are separately documented; they are not erased by the fresh baseline.
- Final client update and actual public/admin service-worker navigation passed on the target.
- Actual in-app notification receipt/read and unsigned 2.8.1 NSIS install/runtime/removal passed.
- All 39 provider routes were inspected; a real 720-point month passed durable storage and owned cleanup.
- The final image passed 200 simultaneous cold WebSockets and a 60-second HTTP gate:
  900/900 responses, 14.990 rps and 442.150 ms p95 with unchanged resource caps. Earlier failures remain evidence.
- The fresh 1800.258-second clean soak passed: 27,000 HTTP 200 responses, 14.998 rps,
  323.249 ms p95 and 200 stable WebSockets with no clean errors/disconnects. Separate API and
  Redis fault windows passed all-client recovery in 3.746 and 4.495 seconds respectively.
  The failed earlier fixture publisher receipt is retained alongside the corrected fault-only run.
- The owned acceptance containers/network/database volume were removed after receipts were saved;
  all eighteen nonowned container IDs/start times remained equal and production readiness passed.

## Remaining external acceptance

- Obtain current provider usage/redistribution rights and canary fixtures from the operator.
- Supply reachable continuous external collection and approved direct GOLD_24K/cash USD sources.
  The user has no external host or proxy; manual hosted feed success is not continuous coverage.
- Restore verified target access to Windows push. Real Edge subscription/outbox passed;
  native receipt failed with ConnectTimeout on both container and host. In-app receipt/read passed.
- Supply a trusted publisher certificate or signing service, then execute the signed installer gate.
  The user has no certificate. Actual unsigned NSIS install/runtime/removal passed; no signature is claimed.
- Supply current privacy/retention/operator details and confirm legal text with the responsible owner.

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
