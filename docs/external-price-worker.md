# External pricing transports — 2.8.6

Updated: 2026-10-17. This document describes code. It does not confirm an installed timer, current host reachability, or continuous delivery.

## Allowed application routes

The signed worker and version-three consumer accept these exact pairs:

| Provider | Instrument | Currency and unit | Source endpoint |
| --- | --- | --- | --- |
| gold_api_free_xau | XAU_USD_OZ | USD per troy ounce | https://api.gold-api.com/price/XAU |
| gold_api_free_xag | XAG_USD_OZ | USD per troy ounce | https://api.gold-api.com/price/XAG |
| gold_api_free_btc | BTC_USD | USD per bitcoin | https://api.gold-api.com/price/BTC |

There is no stablecoin substitute. USDT/USD is not set to one. These routes cannot stand in for Iranian physical gold, local currency, or domestic gram prices. The old crypto and alternate silver sources are absent from the executable worker and feed route lists.

Each observation needs the exact asset symbol, explicit USD currency, a finite price within instrument bounds, and the original timezone-aware source timestamp. Missing currency or time makes that observation unavailable. Receipt time cannot create freshness. Quotes older than 600 seconds are rejected or omitted; quotes over five minutes in the future are rejected. One unavailable source does not invent a replacement.

The code uses the current reviewed source grants. Their built-in review window ends on 2027-01-15. Source terms and coverage still need the release gates in [release-operations.md](release-operations.md).

## Signed private worker

`infra/price-worker/worker.py` has only standard-library dependencies. Install that file with the tracked service and timer on the separately reviewed worker host. Use a private root-owned environment file with mode 600. Set the HTTPS endpoint to `/api/internal/pricing-worker` and use the shared secret store for the same random secret at both ends, at least 32 characters. Do not place secrets in a feed, repository, command history, or log.

Every collection and private send requires `collect`, `store`, and `own_app_transport`. The latter is a narrow application transport gate. It does not enable public resale or general redistribution. An optional absolute `PRICING_RIGHTS_MANIFEST_PATH` replaces the built-in grants. A missing, expired, malformed, or revoked private grant blocks use. Host entries must be exact strings in a list. The worker does not have an enforcement-off switch.

A private manifest uses schema version 1, environment `production`, and a `providers` object. Each selected provider needs a permission list, timezone-aware `checked_at` and `expires_at`, an HTTPS `evidence_ref`, and an exact `hosts` list containing `api.gold-api.com`. The review window must not exceed 366 days. Use the same reviewed grant policy as the core.

A run fetches the three allowed live endpoints separately. It preserves each observation time, rechecks permissions after a response, and sends only valid records. Redirects are refused. The signed core response must acknowledge both accepted and published counts. A partial or ignored response is not reported as full delivery.

Historical backfill is unavailable: the approved free source has no implemented historical endpoint. No historical request runs, no empty range is marked complete, and the old `NERKHBAAN_WORKER_STATE_FILE` remains intact. The timer does not retry a removed historical source.

The service and timer files describe installation; they do not prove execution. After a separately approved activation, inspect worker logs, original source time, actual core persistence, and a current instrument response. A running process or HTTP 202 alone is not enough.

## Public feed and pull consumer

The public publisher is disabled by default. Scheduled and push-triggered publication are removed. A manual workflow also needs its explicit workflow approval gate and a reviewed `relay` grant. Built-in grants do not include `relay`. The builder stops before provider requests and before changing the output when that grant is absent. No publication was executed for this code change.

Version 3 keeps the JSON quote envelope and adds an explicit own-application audience, source URLs, currency, unit, credits, and original observation times. It contains one to three valid routes from the table. Versions 1 and 2, unknown pairs, duplicate instruments, invented stablecoin values, wrong units, and missing credits are refused. If no quote is valid, the previous feed is preserved and continues aging.

`apps/price-feed-pull` checks current `collect`, `store`, and `own_app_transport` grants before repository access and again before sending. It signs only fresh approved observations for the private ingest endpoint. It has no user, administrator, database, or cache credentials. Its application secret is `NERKHBAAN_WORKER_SECRET`. The pull process does not authorize a public publishing platform or a public redistribution use.

Repository preflight requires grants for the whole three-source bundle. A custom manifest that allows only one source keeps the pull process stopped, even if the available file is partial. The private direct worker can collect an approved subset; unavailable routes remain unavailable.

Public publication remains a separate blocked gate until the intended hosting use and source permissions are approved. An internal transport grant alone cannot open it.

## Core boundary and acceptance

The core schema, router, and service all accept only the three exact provider/instrument pairs. Historical worker records are rejected before storage. Current grants must permit collection, storage, and private application transport.

Requests need a bounded server-clock timestamp, HMAC-SHA256 over timestamp plus a dot plus exact body bytes, and a Redis replay claim. The core applies its canonical lock, enabled provider role, source freshness, anomaly, and persistence rules. A lower-priority fallback cannot replace a fresh primary. Current source permissions also gate old cache and history reads.

Before any transport cutover, require current provider terms, host clock and reachability, durable source/canonical joins, correct units, original observation timestamps, and actual consumer acknowledgement. Preserve data, old worker progress, other services, and the old transport until that acceptance passes. Use the guarded application release path. This document does not authorize a deployment or a timer change.

Older dated transport receipts describe their original observations only. They do not approve current source rights, current continuous coverage, or this new release.
