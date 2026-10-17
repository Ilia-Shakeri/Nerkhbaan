# Production Acceptance — 2.8.6

Updated: 2026-10-17. The current delivery matrix is [delivery-readiness.md](delivery-readiness.md).
The operational sequence is [release-operations.md](release-operations.md).
Source release 2.8.6 adds enforced source permissions and replacement contracts. Final-commit hosted checks and target deployment need their own evidence. The selected full replacement scope is blocked by source/account and target-network evidence; a reduced deployment is not approved. See [the current source review](provider-rights-2026-10-17.md).

Required final evidence: exact release/commit, fresh source canaries and usage rights,
clock/TLS health, database migration and isolated restore, replica handover, real browser and desktop,
end-to-end alert receipt, queue recovery, load/soak results and signed operator gate file.

Old scores and source assumptions are historical. Current readiness is decided by successful
checks on the final commit and intended environment, not by carrying a past numeric score forward.
