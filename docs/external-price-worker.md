# External price feeds

## Preferred Git pull route

Use this route when the Iran host cannot open public market APIs and a foreign
host cannot reach `nerkhbaan.ir`. It needs no permanent foreign VPS.

1. `.github/workflows/price-feed.yml` runs immediately when its workflow or
   builder changes on the default branch, then every five minutes. It reads
   XAG/USD from Gold API Free and BTC/USD plus USDT/USD from CoinGecko.
2. `scripts/build-price-feed.py` rejects changed units, missing routes, stale
   timestamps, non-numeric values, and values outside instrument safety ranges.
3. The workflow force-replaces the orphan `price-feed` branch. The branch always
   has one small commit, so feed history cannot grow without bound.
4. `price-feed-pull` uses Git smart HTTP over `github.com`, the GitHub route
   verified reachable from the Iran host. It repeats route, timestamp, and price
   checks, signs the exact ingest body with HMAC-SHA256, presents the trusted
   public Host, and posts inside the Compose network. Every Git pull has a hard
   60-second deadline; a failed pull is retried on the next interval.
5. The core accepts only `gold_api_free_xag -> XAG_USD_OZ`,
   `coingecko_btc -> BTC_USD`, and `coingecko_usdt -> USDT_USD`.
   Relay records use a bounded parser version; upstream parser identity is kept
   in record metadata.

The live contract is deliberately narrow. Feed and quote timestamps must be at
most ten minutes old when the Iran pull service and API receive them. Accepted
current quotes preserve the vendor observation timestamp, but start a bounded
receive-time window: up to five minutes for XAG/USD and six minutes for BTC/USD
and USDT/USD. Direct providers keep their own shorter provider windows.

The sidecar receives only `PRICING_WORKER_SHARED_SECRET`. It receives no
database URL, Redis URL, user data, or admin credential. Its filesystem is
read-only except for a 32 MB temporary directory, all Linux capabilities are
dropped, and it runs as uid/gid 1000. The production service uses the verified
Shecan resolvers `178.22.122.100` and `185.51.200.2`; replace both addresses in
`docker-compose.prod.yaml` and retest HTTPS from the container if that DNS
service changes.

### Enable and verify

The scheduled workflow must exist on the repository default branch. Run it once
manually after first merge, then verify the `price-feed` branch contains only
`prices.json`.

Build and start through the production stack:

```bash
APP_IMAGE_TAG=release-tag docker compose -f docker-compose.prod.yaml build price-feed-pull
APP_IMAGE_TAG=release-tag docker compose -f docker-compose.prod.yaml up -d --no-deps price-feed-pull
docker compose -f docker-compose.prod.yaml logs --tail 40 price-feed-pull
```

Expected log: `price feed accepted at ...`. Then verify:

```bash
curl -fsS https://nerkhbaan.ir/api/instruments/XAG_USD_OZ
curl -fsS https://nerkhbaan.ir/api/instruments/SILVER_999_TOMAN_GRAM
curl -fsS 'https://nerkhbaan.ir/api/prices/silver/history?timeframe=30d'
```

Disable only the relay if it fails. Stored prices remain and age normally:

```bash
docker compose -f docker-compose.prod.yaml stop price-feed-pull
```

If the API vendor changes, edit only `scripts/build-price-feed.py`, retain the
same normalized feed contract, add a parser test, and run the workflow manually.
If GitHub connectivity changes, replace the repository URL or the pull transport
in `apps/price-feed-pull`; do not weaken the core HMAC or route allowlist.

## Purpose

The Iran application stays the public site and source of truth. A small worker outside Iran reads the permitted free CoinGecko BTC/USD and USDT/USD routes, then sends signed price records to the application. The worker never gets database, Redis, user, or admin access.

This older push design remains a fallback for a managed foreign VPS. It was
blocked in the current hosting path because neither VPS could open the needed
direction. Prefer the Git pull route above while that network policy remains.

## Trust boundary

The application accepts only `coingecko_btc` for `BTC_USD` and `coingecko_usdt` for `USDT_USD`. Every request needs:

- `X-Pricing-Worker-Timestamp`, within five minutes of server time.
- `X-Pricing-Worker-Signature`, HMAC-SHA256 of `timestamp + "." + raw JSON body`.
- a Redis replay claim. A repeated signature is rejected.

Use one new random secret of at least 32 characters. Put the same value only in the core production environment and the worker environment. Never commit it, paste it in tickets, or add it to this document.

## Install or replace the worker

On the replacement foreign VPS, create the restricted service account and install the tracked worker files:

```bash
sudo adduser --system --group --home /var/lib/nerkhbaan-sync nerkhbaan-sync
sudo install -d -m 750 -o nerkhbaan-sync -g nerkhbaan-sync /opt/nerkhbaan-price-worker /var/lib/nerkhbaan-price-worker
sudo install -m 755 -o root -g root infra/price-worker/worker.py /opt/nerkhbaan-price-worker/worker.py
sudo install -m 644 -o root -g root infra/price-worker/nerkhbaan-price-worker.service /etc/systemd/system/nerkhbaan-price-worker.service
sudo install -m 644 -o root -g root infra/price-worker/nerkhbaan-price-worker.timer /etc/systemd/system/nerkhbaan-price-worker.timer
```

Create `/etc/nerkhbaan-price-worker.env` with mode `600`, owner `root:root`:

```ini
NERKHBAAN_WORKER_ENDPOINT=https://nerkhbaan.ir/api/internal/pricing-worker
NERKHBAAN_WORKER_SECRET=the-shared-secret
NERKHBAAN_WORKER_STATE_FILE=/var/lib/nerkhbaan-price-worker/history-complete
```

Enable and verify:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nerkhbaan-price-worker.timer
sudo systemctl start nerkhbaan-price-worker.service
sudo systemctl status nerkhbaan-price-worker.timer --no-pager
sudo journalctl -u nerkhbaan-price-worker.service -n 80 --no-pager
```

The first successful run imports up to one year of daily BTC/USD and USDT/USD history. Later runs submit live records each minute. To intentionally import again after changing source policy, stop the timer, remove only `/var/lib/nerkhbaan-price-worker/history-complete`, run the service once, then re-enable the timer.

## Core configuration

Add this setting to the production environment on the Iran host, using the same secret as the worker:

```ini
PRICING_WORKER_SHARED_SECRET=the-shared-secret
```

Deploy the reviewed release. Verify only from trusted operator access:

```bash
curl -fsS https://nerkhbaan.ir/api/prices/health
curl -fsS https://nerkhbaan.ir/api/prices/btc/history?timeframe=1y
curl -fsS https://nerkhbaan.ir/api/prices/usdt/history?timeframe=1y
```

The history responses must contain points and report `complete` or `partial`; they must never be replaced by invented chart points.

## Cutover and rollback

1. Keep the old worker running until the new worker posts a successful live update and both chart endpoints have points.
2. Disable the old timer: `sudo systemctl disable --now nerkhbaan-price-worker.timer`.
3. Rotate the shared secret on both hosts in one short change window, then restart the worker and core services.
4. If the new worker fails, disable its timer. Existing stored prices remain visible and age normally. Do not delete PostgreSQL, Redis, or worker state while investigating.

## Routine checks

```bash
sudo systemctl list-timers nerkhbaan-price-worker.timer
sudo journalctl -u nerkhbaan-price-worker.service --since "24 hours ago" --no-pager
curl -fsS https://nerkhbaan.ir/api/prices/health
```

Investigate a failed timer, `401`, `409`, or `503` response before resetting state. A `401` usually means the two secrets differ; a `409` is a safe replay rejection; a `503` means the core storage or Redis needs attention.
