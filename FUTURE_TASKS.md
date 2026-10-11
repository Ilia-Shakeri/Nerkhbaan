# Remaining Acceptance and Optional Work

Code baseline: **2.8.0**. Updated: 2026-10-11.
A task here is external acceptance or optional product work; it is not a substitute for fixing a known code defect.

## Required target evidence

- Run all CI jobs on the final commit: unit/static, all client builds, real browser, desktop package,
  Timescale/Redis integration, migration idempotency, restore, Compose/Nginx/relay and sidecar images.
- Check existing database duplicates before any new market-price uniqueness constraint.
  Preserve conflicting rows; resolve with a documented data migration before enforcing uniqueness.
- Prove off-host backup retrieval and isolated Timescale restore against the target data size.
- Prove synchronized target clock, TLS, ingress and two-replica failover.
- Obtain current provider usage/redistribution rights and canary fixtures from the operator.
- Verify each enabled source, exact units and timestamps, fresh charts, alert delivery and dead-letter recovery.
- Supply current privacy/retention/operator details and confirm legal text with the responsible owner.
- Run a load/soak test against staging with agreed users, alert volume, latency and loss limits.

Use `docs/operator-gates.evidence.example.json` as the shape; the placeholder file must fail validation.
No local script can invent provider rights, secret-store activation or live-server proof.

## Optional product and scale work

- Multiple independent hosts and disaster recovery beyond a single Compose host.
- Agreed data retention/export controls, localization coverage and accessibility review on target devices.
- Provider contracts for uncovered instruments; keep unavailable instruments honestly unavailable meanwhile.
- Performance budgets and an operator-owned alert escalation schedule.

See [delivery readiness](docs/delivery-readiness.md) for commands and expected markers.
