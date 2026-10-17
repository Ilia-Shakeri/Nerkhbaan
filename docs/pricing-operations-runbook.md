# Pricing Operations Runbook — 2.8.3

Updated: 2026-10-17. Dated target evidence is recorded separately in the delivery matrix.
The 2.8.3 Servix parser requires explicit quoteUnit and timezone-bearing businessTime. Contract
fixtures do not replace authenticated source proof; unknown data remains rejected.

## Provider onboarding

Before enabling a source, capture official route documentation, permitted product usage,
representative fixtures, exact currency/weight/purity/semantic, source timestamp, rate limits,
attribution, incident owner and secret-store placement. Canary success is not licensing evidence.
Unknown or sample-only vendor routes stay disabled. Do not weaken HTTPS or timestamp checks to
make a canary pass. Use the actual configured Settings object for endpoint and parser configuration.

Run a provider canary from `apps/api` with private runtime settings already injected:

```bash
python scripts/provider_canary.py wallgold_gold18
```

A sanitized successful result proves that exact route at that time. It does not prove every route,
long-term uptime, redistribution rights or production alert delivery. Keep credential values out of reports.
Use an explicit provider ID to bound requests. Disabled or unconfigured providers return skipped;
that result is not price proof. Supplying a Servix key alone does not enable its disabled routes.

## Instrument and canonical rules

- Read instrument identity, currency, unit, purity, source observation, validity and persistence.
- Gold gram and spot-ounce legs are independent. Gold formulas are forbidden.
- Missing direct gold remains unavailable. Do not synthesize it in the client or startup report.
- Approved non-gold formulas remain theoretical and inherit input validity; USD/Toman is not USDT/Toman.
- Source timestamps remain source timestamps. Receipt may start a provider-specific short window only
  within the vetted maximum source-age boundary; validity never extends past that boundary.
- A rejected stale primary does not block a valid fresh fallback.
- Worker live ingestion follows canonical anomaly, priority and independence rules under an instrument lock.
  Older observations cannot replace newer ones; fresh primary data is not replaced by a lower-ranked worker.
- Independent fallback sources may participate in anomaly verification within its budget.
  Same-family sources cannot prove independence.
- Telegram can verify only when explicitly approved, whitelisted, fresh, persisted and above policy
  trust/confidence. Telegram observation alone does not become a market quote.
- Suspicious, expired and unpersisted results are ineligible for ordinary alerts.

Admin settings show scope, stored override and effective value. Changing the database value alone
is not success: refresh the runtime and inspect its effective policy. Startup inserts catalogue defaults;
it must not overwrite operator decisions. Reconcile system-role permissions through the release migration/bootstrap.

## Telegram

Channel identity uses marked `-100...`, consistently in UI, API, database and worker.
Parser names: `strict_explicit` and `strict_hashtag`. Default: `strict_explicit`.
Use the panel preview before enabling a source. Explicit Toman/Rial is required; Rial converts to Toman
once. Decimal separators remain decimals. Mixed units and ambiguous prices are rejected.
`strict_hashtag` requires an actual matching hashtag. Unlisted channels and non-channel events are ignored.
Legacy unsupported parsers are disabled by the forward migration; known `strict_generic` becomes `strict_explicit`.
A raw/marked duplicate identity needs operator review; the migration does not silently merge its records.

## History and backfill

History is stored data with coverage and gap checks. Do not fill gaps using the current exchange rate.
Backfill uses bounded batches and resumes pending points. It completes only after required durable writes.
A temporary live-priority deferral is retryable. Missing enabled history routes remain unavailable.
Zero trade volume is valid; nonfinite or negative volume is not. Price remains strictly positive.
CoinGecko history is USD history, never a direct Iranian Toman source.
Nobitex history uses bounded 500-point pages and resumes only after durable writes.
The version-two feed carries each fresh quote independently, including XAU USD per troy ounce.
See the dated [39-route coverage and durable month proof](provider-coverage-2026-10-11.md).
Scheduled workflows do not prove continuous collection; inspect actual source times and gaps.

## Health and monitoring

`/api/health/live`: process only. `/api/health/ready`: required storage/schema readiness.
`/api/prices/health`: coverage and completed refresh health. `fresh` cache results count as usable.

Check the private Prometheus targets and these signals:

- `nerkhbaan_pricing_observed_timestamp_seconds{instrument_id}`;
- `nerkhbaan_pricing_expires_timestamp_seconds{instrument_id}` against `time()`;
- `nerkhbaan_pricing_refresh_timestamp_seconds` against `time()`;
- canonical status, provider failure rate, persistence backlog and dead-letter queue;
- DB/Redis readiness, worker heartbeat and oldest pending work.

Age/status are evaluated against scrape time. Frozen refreshes must age into failure.
An absent scrape target is a failure, not a green zero. Dashboards must show data age.

## Recovery

1. Check clock with [time-sync-runbook](time-sync-runbook.md); never widen timestamp tolerance to mask drift.
2. Check DB, Redis and schema. Redis holds leases, budgets and outbox; preserve AOF.
3. Inspect failed provider IDs and sanitized reasons; run only the needed canary.
4. Retry history/queue work idempotently after dependencies recover. Do not reset state to fake completion.
5. For alert cancellation, inspect the current worker lease. Already transmitted messages cannot be recalled.
6. Restore only to a separate database first; compare data, hypertables, chunks and policies.
7. Recheck source units, timestamps, persisted prices, history and actual channel receipt.

## Production evidence

Use the private copy of `docs/operator-gates.evidence.example.json` and run
`python scripts/verify_operator_gates.py /private/path/operator-gates.json`.
All applicable gates need fresh owner-backed proof. Example placeholders must fail.
See [release operations](release-operations.md), [delivery readiness](delivery-readiness.md)
and [external workers](external-price-worker.md).
