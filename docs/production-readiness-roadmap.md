# Production Acceptance — 2.8.8

Updated: 2026-10-18. The current delivery matrix is [delivery-readiness.md](delivery-readiness.md).
The operational sequence is [release-operations.md](release-operations.md).
Source release 2.8.8 adds three separately labelled published/calculated Iranian references after user approval. Native contracts retain their identities. Final-commit hosted checks, target backup/restore, operator gates and deployment need separate evidence. Clock semantics are fixed; upstream source freshness remains limited. See [the reference scope and remaining acceptance](iranian-references-2026-10-17.md).

Required final evidence: exact release/commit, fresh source canaries and usage rights,
clock/TLS health, database migration and isolated restore, replica handover, real browser and desktop,
end-to-end alert receipt, queue recovery, load/soak results and signed operator gate file.

Old scores and source assumptions are historical. Current readiness is decided by successful
checks on the final commit and intended environment, not by carrying a past numeric score forward.
