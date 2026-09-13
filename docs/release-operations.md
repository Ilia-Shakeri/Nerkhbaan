# Release operations

## Code gates

Run `npm run verify`. CI then proves PostgreSQL migrations and restore, Redis round trips and replica lease exclusion, live HTTP routes, browser auth/alert flow, Compose/nginx/relay/monitoring syntax, desktop packaging, image builds, and security scans.

The live HTTP gate has 14 stages. It creates a unique user and alert, exercises
auth, session, pricing, chart, instrument, provider, and error contracts, then
removes the alert. Run it only against a disposable test database; the user and
security audit rows intentionally remain as transaction evidence.

## Staging

Use the production Compose file under a separate project name and separate ports. Keep its database, Redis, certificates, webhook file, and provider keys separate from production.

```bash
COMPOSE_PROJECT_NAME=nerkhbaan-staging \
EDGE_HTTP_PORT=8080 EDGE_HTTPS_PORT=8443 \
PROMETHEUS_PORT=19090 ALERTMANAGER_PORT=19093 GRAFANA_PORT=13002 \
docker compose --profile edge --profile admin --profile monitoring \
  -f docker-compose.prod.yaml up -d --build --wait --scale backend=2
```

Run route smoke, browser smoke, then load smoke against staging. A long soak uses the same load script with a larger request count and an external process supervisor.

```bash
python apps/api/scripts/integration_smoke_test.py --base-url https://staging.example.com
python scripts/load_test.py --base-url https://staging.example.com --requests 10000 --concurrency 100
```

## Production

Create an evidence file from `docs/operator-gates.evidence.example.json`. Evidence links hold reports only; never put secrets in the file. Validate it with `python scripts/verify_operator_gates.py <path>`.

The deploy refuses to run without all eight current gates. External owners must supply provider rights, live canaries, secret-store proof, relay/transport decisions, off-host restore proof, target health, and browser proof. Code cannot truthfully create those facts.

```bash
OPERATOR_EVIDENCE_PATH=/run/nerkhbaan/operator-gates.json \
BACKEND_REPLICAS=2 \
sh scripts/deploy-nerkhbaan-prod.sh
```

Before deploy, record the current commit and database backup. After deploy, check readiness, Prometheus targets, active alerts, queue depth, provider failure rate, and price age. If health fails, keep data volumes, return to the recorded commit with a new reviewed deploy, and rerun the same gates.

Before provider or login verification, require a synchronized host clock. Follow
[`time-sync-runbook.md`](time-sync-runbook.md); a large correction needs a short
maintenance window because old sessions and timers can expire.

## Relay

`infra/relay` is a separate stateless stack. It accepts TLS from only the core IP range and requires `X-Relay-Token`. The core adds that header only when `PRICING_RELAY_BASE_URL` matches a configured provider URL host. Point only affected provider base URLs at the matching relay path, add the relay host to the provider allowlist, and set a secret-store token of at least 32 characters.

This relay solves reachability only. It does not grant redistribution rights or override vendor terms. Those remain hard launch gates.
# Offline package build fallback

The frontend image installer tries configured npm registries first. If every
registry is unavailable, it retries with the BuildKit npm cache and the locked
dependency set. A cache miss remains a hard failure; never replace the lockfile
or install unpinned packages during a production deploy.
