# Pricing Operations Runbook

## Provider Onboarding Gate

Before enabling a new provider route, the operator must have all of this evidence:

- official endpoint documentation and endpoint version;
- representative response fixtures for success, missing field, invalid unit, stale timestamp, and rate limit;
- explicit unit, currency, purity, source timestamp, and selected price semantic;
- credential placement that never puts a secret in the path or an unapproved plain HTTP request;
- commercial and redistribution authorization for this product;
- owner, rate limit, attribution requirement, and incident contact;
- parser tests and route-specific enable flag.

Tier B routes remain disabled until this gate is complete. Pending vendors such as BRSAPI, TSETMC, SourceArena, api.ir, IranMarketData.ir, Oanor, legacy nerkh-api.ir, TGJU paid API, NovinAPI, and TabanGohar must not be added to active pricing until the gate is satisfied.

## Canary Command

Run from `apps/api`:

```powershell
$env:JWT_SECRET_KEY='operator-owned-non-production-value'
python scripts/provider_canary.py
```

Run one route:

```powershell
$env:JWT_SECRET_KEY='operator-owned-non-production-value'
python scripts/provider_canary.py coinbase_btc_usd
```

The command uses the live request guard, credentials, response-size cap, retry rule, and parser. It emits sanitized JSON. It does not print headers, query strings, keys, prices, or payload bodies. A non-2xx response, bad payload, or unknown provider fails the command.

## Operator Gate Evidence

Keep production proof outside source control. Use `docs/operator-gates.evidence.example.json` as the shape for internal evidence, then validate a local copy:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-operator-gates.ps1 -EvidencePath path\to\operator-gates.evidence.json
```

The example is a shape only and must fail validation. The private file must name the production environment, a real owner, a fresh UTC timestamp, and one typed proof URI for each gate. Core production gates must pass. Only the disabled Navasan route and future market domain may use `not_applicable`, and both need a reason. The verifier rejects stale proof, future dates, placeholders, and secret-like values.

## Secret And Egress Rules

- Keep all provider keys in the runtime secret store or the deployment's `.env`,
  never in source files. There is no in-application secret-manager integration;
  injection is the deployment's responsibility.
- Rotate every provider key after staff changes, suspected leak, vendor incident, or public artifact exposure.
- Keep `PRICING_PROVIDER_ALLOWED_HOSTS` tight. Add hosts only after provider onboarding.
  The allowlist is extended automatically with the hostname of every configured
  provider base URL, so a proxy set through configuration stays reachable
  without widening the list by hand.
- `NAVASAN_ALLOW_INSECURE_HTTP=true` is rejected at startup. Use `NAVASAN_HTTPS_PROXY_BASE_URL` or leave Navasan disabled.

## Source Coverage Gate

An instrument with no configured provider still publishes a price — a formula
result marked `derived_fallback`. That is legitimate, but it must be a known
state, not a surprise. Before declaring a chain live:

- check `startup.instruments_without_direct_source` in `GET /api/prices/health`;
- confirm each entry there is intentional;
- for Toman metals, check `fx_bridge_is_proxy` on the derived quote. A `true`
  means the USD→Toman rate came from USDT, which carries a market premium; the
  published value will run percent-level high.

`instruments_unservable` must always be empty. CI fails if it is not.

## Readiness Rules

- `/api/health/live` is process liveness.
- `/api/health/ready` is readiness and may fail when dependencies fail.
- `/api/prices/health` includes refresh-loop state. `degraded` means no usable
  canonical result in the last completed cycle. `failed` means the cycle itself
  raised an error. Check this before changing a provider.
- An expired canonical quote is not an anomaly baseline. A new valid provider
  quote must be assessed like an initial quote, not held against an old market
  level that can no longer be displayed or used by alerts.
- Provider canary output is operational evidence, not licensing evidence.
- A local unit-test pass is not a production deploy proof.

## Backup And Restore Gate

Before production enablement:

- verify off-host PostgreSQL backups;
- run a restore drill into a disposable database;
- verify Redis AOF compatibility after image upgrades;
- keep production volumes intact during recovery;
- deploy through `cd /opt/Nerkhbaan && COMPOSE_FILE=docker-compose.prod.yaml sh scripts/deploy-nerkhbaan-prod.sh`.

## Release Check Commands

One command from the repository root runs every gate — backend static checks,
the backend suite, the frontend contract tests, and all three builds:

```bash
npm run verify
```

Individually, if you need to isolate a failure:

```bash
cd apps/api
python -m compileall -q app tests scripts
python -m pyflakes app tests scripts
JWT_SECRET_KEY='test-only-secret-key-that-is-long-enough' \
DATABASE_URL='postgresql+psycopg://test:test@127.0.0.1:5432/test' \
REDIS_URL='' python -m unittest discover -s tests -v
```

```bash
npm run test:frontend
npm run build:web && npm run build:admin && npm run build:desktop
```

The web build needs `VITE_VAPID_PUBLIC_KEY` set to produce an image with working
web push. A build without it succeeds but ships push disabled.

## Capacity Watchpoints

| Signal | Threshold | Consequence of ignoring it |
| --- | --- | --- |
| Redis `used_memory` vs `REDIS_MAXMEMORY` | 80% | Policy is `noeviction`: a full Redis stops every price refresh |
| PostgreSQL connections | `max_connections` | Peak per API process is `(pool + overflow) x 2`; migrate, backup and worker add more |
| `dead_letter_backlog` | any sustained growth | Alerts are being generated and not delivered |
| `anomaly_count` | any sustained growth | Anomalies are opening faster than they are reviewed |
