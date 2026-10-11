# Remaining Acceptance and Optional Work

Code baseline: **2.8.1**. Updated: 2026-10-11.
A task here is external acceptance or optional product work; it is not a substitute for fixing a known code defect.

## Completed target checks — 2026-10-11

- All 15 hosted jobs passed for the recorded source snapshot in the delivery matrix.
- Encrypted off-host backup retrieval passed; isolated target restore matched 47 tables and 1,404,468 rows.
- Seven migrations passed on a full Timescale copy and live data; core price/user fingerprints were preserved.
- Target clock, TLS, shared ingress, two-replica failover and 25 real admin routes passed.
- Final API rolling update passed six HTTPS probes with healthy overlap; data/other-service IDs stayed equal.
- Final client update and actual public/admin service-worker navigation passed on the target.

## Remaining external acceptance

- Obtain current provider usage/redistribution rights and canary fixtures from the operator.
- Complete canaries for each enabled source and missing instrument. Keep expired/uncovered quotes unavailable.
- Verify actual notification receipt on intended user devices and external delivery channels.
- Test a signed desktop installer on every supported target OS. The local unpacked runtime and hosted package already pass.
- Supply current privacy/retention/operator details and confirm legal text with the responsible owner.
- Run a load/soak test against staging with agreed users, alert volume, latency and loss limits.

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
