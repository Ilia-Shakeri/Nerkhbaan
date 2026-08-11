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

- Use `SECRET_MANAGER_PROVIDER=external` for production once a vault is connected.
- Keep all provider keys in the runtime secret store, not in source files.
- Rotate every provider key after staff changes, suspected leak, vendor incident, or public artifact exposure.
- Keep `PRICING_PROVIDER_ALLOWED_HOSTS` tight. Add hosts only after provider onboarding.
- `NAVASAN_ALLOW_INSECURE_HTTP=true` is rejected at startup. Use `NAVASAN_HTTPS_PROXY_BASE_URL` or leave Navasan disabled.

## Readiness Rules

- `/api/health/live` is process liveness.
- `/api/health/ready` is readiness and may fail when dependencies fail.
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

Run locally:

```powershell
cd apps/api
python -m compileall -q app tests
python -m pyflakes app tests
$env:JWT_SECRET_KEY='test-only-secret-key-that-is-long-enough'
$env:DEBUG='false'
python -m unittest discover -s tests -v
```

Run frontend checks from the repo root:

```powershell
npm.cmd run build:web
npm.cmd run build:admin
npm.cmd run build:desktop
npm.cmd run test:frontend
```
