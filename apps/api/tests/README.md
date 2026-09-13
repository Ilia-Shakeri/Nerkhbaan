# Backend tests

```bash
cd apps/api
JWT_SECRET_KEY=local-test-key-not-for-runtime-00000000 \
DATABASE_URL='postgresql+psycopg://test:test@127.0.0.1:5432/test' \
REDIS_URL='' \
python -m unittest discover -s tests -v
```

The unit suite needs no live database or Redis — `DATABASE_URL` only has to
parse, and an empty `REDIS_URL` puts rate limiting into its process-local mode.
`JWT_SECRET_KEY` must be ≥32 characters or `Settings` refuses to construct.

Or through the repository root, alongside the frontend and build checks:

```bash
npm run verify
```

## What is here

| File | Covers |
| --- | --- |
| `test_derived_fx_bridge.py` | FX bridge preference, purity ratios, proxy labelling |
| `test_security_regressions.py` | Client-IP resolution, migration checksums, webhook targets, snapshot size, spread gate |
| `test_pricing_provider_repair.py` | Instrument coverage, provider hosts, parser registration |
| `test_phase2_*.py` | Canonical selection, freshness semantics, alert eligibility, retry-after |
| `test_auth_refresh_rotation.py` | Refresh-token family rotation and reuse detection |
| `test_auth_response_contract.py` | Cookie vs bearer response shapes |
| `test_pricing_persistence.py` | Outbox behaviour and idempotency |
| `test_admin_anomaly_review.py` | Anomaly review permissions and transitions |
| `test_notifications.py`, `test_telegram_deeplink.py` | Channel verification flows |
| `test_insights.py`, `test_insight_router_contracts.py` | Assistant provider fallback and quotas |
| `test_request_body_limit.py` | Body-size middleware |
| `test_provider_contracts.py`, `test_provider_canary.py` | Parser contracts, sanitised canary output |

`ci_migration_check.py`, `ci_service_smoke.py`, and
`scripts/integration_smoke_test.py` are not unit tests. They run in CI against
real PostgreSQL and Redis services after migrations are applied. The HTTP smoke
covers 14 stages across auth, sessions, alerts, pricing, charts, instruments,
provider redaction, error contracts, and refresh-token family reuse.

## Writing tests here

**Assert the invariant, not the snapshot.** `assertEqual(len(INSTRUMENTS), 10)`
only proves a number did not change, and it broke the moment a legitimate
instrument was added. `"no instrument may lack both a configured source and a
formula"` catches the class of bug that let silver publish theoretical values
while every dashboard reported it healthy.

**A security fix needs a test that fails without it.** `test_security_regressions.py`
is organised that way: each class names the behaviour that was wrong and asserts
the corrected one, so a future refactor cannot quietly restore it.

**Prefer pure units.** The pricing core — instruments, canonical policy, derived
formulas, freshness, anomaly detection — is deliberately free of I/O so it can
be tested with plain values. Keep it that way.
