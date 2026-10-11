# Pricing Sources and Semantics — 2.8.0

Updated: 2026-10-11. Definitions are in `app/pricing/instruments.py`; source roles and budgets
are in the registry plus persisted operator overrides. Read [operations](../../docs/pricing-operations-runbook.md).

A price identifies instrument, currency, weight, purity, market and original source observation.
Gold spot USD per troy ounce and physical Iranian Toman per gram are distinct instruments.
Gold has no derived fallback. Missing direct gold remains unavailable.
Approved silver/crypto/FX derived routes remain explicitly theoretical and obey their configured policy.
No frontend fills a missing leg by multiplying unrelated units or the current exchange rate.

Canonical selection requires a fresh valid persisted observation, instrument sanity/spread bounds,
source priority/trust/budget, circuit policy and independent anomaly confirmation.
A stale primary is excluded before selection. A fresh fallback is considered next.
Anomaly verification may use independent fallback routes; same-family routes are not independent.
Approved Telegram verification requires whitelist, freshness, persistence and trust/confidence policy.

Source observation and receipt are distinct. Receive-anchored windows are capped by the vetted upstream
maximum source age. Worker ingestion runs under the same instrument lock and checks;
old observations cannot move canonical time backwards or displace a fresh higher-priority source.
Only approved instrument/provider pairs can enter through signed worker ingress.
`gold_api_free_xag` is a FALLBACK route for direct XAG. Worker relay ingress never promotes a
VERIFIER or COMPARE route into a canonical source. Live relay validity is capped at the smaller
of 360 seconds and the runtime provider TTL, with a 600-second maximum original source age.

History retains original instrument and unit. Coverage checks include gaps and the end of the requested range.
Backfill is resumable, idempotent and complete only after durable writes. Zero volume is valid.
Unsupported history returns unavailable/partial; no synthetic points are inserted to satisfy a chart.

Use ordinary market values only when live, persisted and eligible. Reference-rate and derived modes
require explicit selection; suspicious, expired and unpersisted values are ineligible for ordinary alerts.

Provider rights, rate limits and exact contracts need current operator evidence.
Environment flags cannot replace a licensing review or a stale canary. Runtime settings are loaded through
one Settings contract, not a second direct environment parser.
