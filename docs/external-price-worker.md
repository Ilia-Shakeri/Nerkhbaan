# External price worker

## Purpose

The Iran application stays the public site and source of truth. A small worker outside Iran reads the permitted free CoinGecko BTC/USD and USDT/USD routes, then sends signed price records to the application. The worker never gets database, Redis, user, or admin access.

This push design is used because the Iran host resolved CoinGecko but its TCP connection to port 443 was refused. It also avoids relying on the Iran host reaching a foreign relay.

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
