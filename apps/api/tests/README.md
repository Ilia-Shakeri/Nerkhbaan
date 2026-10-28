# Backend tests — 2.8.0

<!-- delivery-docs:2.8.16 -->
> مرور سند: ۲۸اکتبر۲۰۲۶؛ منبع/سند **۲.۸.۱۶**، آخرین نصبِ پذیرفته **۲.۸.۱۵**. راهنما؛ وضع جاری در نقشه. عددها، شکست‌ها و قبولی‌های قدیم، شاهد تازه نیستند. [نقشهٔ جاری و فلوچارت](../../../docs/project-completion-roadmap-fa.md) · [فهرست سندها](../../../docs/documentation-index-fa.md).

Current source/docs **2.8.16**. The dated suite below is historical; select checks from the current workflow and code. For the default local legacy-fixture suite use process-only `PRICING_RIGHTS_ENFORCED=false`; focused rights tests override and test enforcement. Never apply this test setting to production. Real database/Redis suites require disposable owned resources; skips are not passes. Installed 2.8.15 recorded 1194 local cases, 137 skipped, with hosted integration evidence separately recorded. New source needs fresh CI; Telegram live messages and physical-device receipt remain separate gates.

Updated: 2026-10-11.

```bash
cd apps/api
JWT_SECRET_KEY=local-test-key-not-for-runtime-00000000 \
DATABASE_URL='postgresql+psycopg://test:test@127.0.0.1:5432/test' \
REDIS_URL='' \
python -m unittest discover -s tests -v
```

The ordinary unit suite needs no live database or Redis — `DATABASE_URL` only has to
parse, and an empty `REDIS_URL` puts rate limiting into its process-local mode.
`JWT_SECRET_KEY` must be ≥32 characters or `Settings` refuses to construct.
An explicit loopback `TEST_DATABASE_URL` enables the separate real PostgreSQL concurrency cases.
Their database name must identify a disposable test/CI database; they clean only their run-owned schema.

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
| `test_price_feed_builder.py` | Public feed routes, units, ranges, and freshness |
| `test_pricing_worker_auth.py`, `test_pricing_worker_service.py` | HMAC replay guard, exact relay allowlist, and quote-time limits |

`ci_migration_check.py`, `ci_service_smoke.py`, and
`scripts/integration_smoke_test.py` are not unit tests. They run in CI against
real PostgreSQL and Redis services after migrations are applied. The HTTP smoke
covers 14 stages across auth, sessions, alerts, pricing, charts, instruments,
provider redaction, error contracts, and refresh-token family reuse.

## Writing tests here

**Assert the invariant, not the snapshot.** `assertEqual(len(INSTRUMENTS), 10)`
only proves a number did not change, and it broke the moment a legitimate
instrument was added. `"every enabled instrument has honest coverage or an explicit unavailable state"` catches the class of bug that let silver publish theoretical values
while every dashboard reported it healthy.

**A security fix needs a test that fails without it.** `test_security_regressions.py`
is organised that way: each class names the behaviour that was wrong and asserts
the corrected one, so a future refactor cannot quietly restore it.

**Prefer pure units.** The pricing core — instruments, canonical policy, derived
formulas, freshness, anomaly detection — is deliberately free of I/O so it can
be tested with plain values. Keep it that way.

## Delivery regression checks (2.8.0)

`test_migration_delivery.py` checks preserved TLS options, bounded advisory lock acquisition and refusal
to call an unknown newer database schema current. Run `python ../../scripts/test_infra_contracts.py` for
Telegram Rial/decimal/unit/hashtag/channel identity, source timestamps, independent live/history work and feed expiry.
CI additionally tests the Go feed sidecar and builds/scans relay and feed images.
`ci-restore-drill.sh` uses Timescale pre/post restore and compares data, chunks, hypertables and policies.
That real service check is not replaced by local mocks.
