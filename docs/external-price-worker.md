# External Pricing Transports — 2.8.1

Updated: 2026-10-11. Choose a transport based on a fresh test from the intended host.
Neither a relay nor a worker grants provider usage or redistribution rights.

## Public Git feed

`.github/workflows/price-feed.yml` requests a normalized public feed on a five-minute cron.
That schedule is not an execution guarantee. The 2026-10-11 workflow receipts include gaps of several
hours; a manual successful run proves one publication, not continuous price coverage.
It validates source currency, ranges and original observation timestamps. The maximum accepted
observation age is 600 seconds in the producer and Go consumer. Publication time is not source time.
Version 1 requires its original three routes. Version 2 publishes one to four independently valid
routes: XAG/USD per troy ounce, XAU/USD per troy ounce, BTC/USD and USDT/USD. An invalid source is
omitted while healthy sources may still publish. No valid route means the previous feed remains;
its original timestamps continue aging. Gold and silver spot routes remain separate from Iranian
physical gram quotes. The XAU route cannot substitute for domestic 24-karat gold.

The bot publishes only `prices.json` in a one-commit orphan `price-feed` branch using force-with-lease.
Enable lease-protected replacement for this bot/output branch only. A branch protection rule that rejects
replacement must be adjusted by the repository owner or publication will fail. Source branches remain protected.
Previous output commits are not a history store; canonical history is persisted by the core.

`apps/price-feed-pull` fetches the feed and signs approved records for the core. The sidecar has no
DB, Redis, user or admin credentials. Its only application credential is PRICING_WORKER_SHARED_SECRET.
Inspect scheduled workflow success and consumer acceptance, not just the process being up.

```bash
docker compose -f docker-compose.prod.yaml logs --tail 40 price-feed-pull
curl -fsS https://nerkhbaan.ir/api/instruments/XAG_USD_OZ
curl -fsS 'https://nerkhbaan.ir/api/prices/silver/history?timeframe=30d'
```

Expected consumer log: `price feed accepted at ...`. Then check source observation, unit,
persistence and current validity. An accepted feed does not guarantee every instrument is available.
To stop the transport, stop only price-feed-pull; preserve stored prices and let them age normally.

## Signed push worker

`infra/price-worker/worker.py` is a restricted worker for a managed external host.
Use the tracked systemd service/timer and a root-owned private environment file, mode 600.
Set endpoint to the HTTPS `/api/internal/pricing-worker` URL; store a shared random secret of at least 32 characters.
Worker state is per-asset JSON under NERKHBAAN_WORKER_STATE_FILE and records acknowledged progress.
Never share the secret, session credentials, environment file or state through the public feed.

Each timer run sends live data first. It requests CoinGecko `include_last_updated_at=true`, preserves
that timestamp and rejects missing/stale observations. Missing one asset does not prevent valid others being sent.
This tracked signed push worker currently supports the two crypto routes only. It does not fetch
XAU or XAG, and no managed external host was verified during this delivery. The timer configuration
alone does not prove scheduled execution or source coverage.
History runs independently, one bounded chunk per asset per run. A failed asset retains progress while other
assets may advance. The full year may need several runs. No empty/failed history is marked complete.
Repeated points remain idempotent in the core. The worker advances a history watermark only when
`history_persisted` equals the historical batch size; an ignored/disabled route keeps that batch pending.
Do not delete state during an outage.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nerkhbaan-price-worker.timer
sudo systemctl start nerkhbaan-price-worker.service
sudo systemctl status nerkhbaan-price-worker.timer --no-pager
sudo journalctl -u nerkhbaan-price-worker.service -n 80 --no-pager
```

## Core trust boundary

The server uses a route-specific provider/instrument allowlist. A request needs:

- timestamp within the allowed server-clock window;
- HMAC-SHA256 of timestamp, a dot and the exact raw JSON body;
- X-Pricing-Worker-Timestamp and X-Pricing-Worker-Signature;
- a Redis replay claim; repeated signed requests are rejected.

Live ingestion uses the same canonical lock, freshness, anomaly and independence rules as direct providers.
It cannot move canonical observation backwards or replace a fresh primary with a lower-ranked worker.
A successful ingest status proves acknowledgement, not final alert delivery.
The Gold API XAG and verified XAU relay routes are FALLBACK routes. Stored runtime roles remain
authoritative; the 2026-10-11 XAU role change was applied separately and audited. VERIFIER/COMPARE
roles cannot publish a worker canonical. Both schema allowlists and the provider/instrument pair
check must accept the route; a valid four-quote feed formerly failed with HTTP 422 until the XAU
schema entries were added. Signed HTTP tests cover acceptance and rejection of an incorrect pair.
Live relay TTL is at most 360 seconds and is further limited by the runtime provider TTL;
maximum original source age is 600 seconds.
The source time and canonical expiry remain bounded; receipt time cannot fabricate freshness.
Persisted relay freshness anchors retain that vetted receive window on later reads. Current admin
policy may shorten the stored bounds; reads cannot extend them. A cache status is not proof that
`valid_until` is still open, and HTTP 202 is not proof that a particular quote became canonical.

The 2026-10-11 production acceptance did verify all four version-two routes: the
ordinary consumer retry received HTTP 202 at 14:05:47 UTC after an earlier 503,
and four accepted provider records joined to four persisted canonicals with equal
original observation times and prices. The XAU source time was 14:04:07 UTC;
its USD/troy-ounce reference quote matched the real public instrument response.
That observation became `fresh_cache` after its 14:10:47 UTC live deadline.
`provider-live-persistence-proof.json` and `provider-final-relay-metadata.json`
record the actual producer, acknowledgement and database joins. This is proof of
one delivered feed; continuous scheduled delivery still needs separate evidence.

## Cutover and incident recovery

1. Verify the new transport and actual fresh persisted instrument before stopping the old one.
2. Stop the old timer/sidecar only; preserve DB, Redis and worker progress.
3. Rotate the shared key across both ends in a controlled window using the secret store.
4. Check timestamp/clock, 401 auth, 409 replay/conflict and 503 storage failures separately.
5. After recovery, inspect history coverage, queue state and actual notification receipt.

Historical September hosting/network observations are not claims about today's server.
Use fresh canaries and the [release runbook](release-operations.md) for production acceptance.
The [current provider coverage report](provider-coverage-2026-10-11.md) records direct-route failures,
the uncovered 24-karat quote, original source timestamps, history pagination and acceptance receipts.
