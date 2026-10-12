# Nerkhbaan API Reference

Code release: **2.8.1**. Updated: 2026-10-12.
The complete generated contract is [docs/api-contracts.json](docs/api-contracts.json).
The [route index](docs/api-route-index.md) lists all HTTP methods, paths and request schemas.
Regenerate both with `python scripts/export_api_contracts.py` after route or model changes.

## General contract

- Base path: `/api`. JSON bodies. UTC timestamps with explicit timezone.
- Typical errors: 401 auth, 403 permission/CSRF/reauth, 404 missing resource, 409 conflict,
  422 invalid input, 429 rate limit, 503 dependency unavailable.
- Error body uses `detail`; it may be a string or field-error list. Do not parse message text as a status code.
- Use the route's exact pagination parameters and success status from the generated schema.
- A missing optional property differs from explicit `null`. Updates validate the merged resource.
- Never send provider credentials in requests to admin setting endpoints or in URLs.

## User auth and consent

Browser requests include credentials. Unsafe cookie-auth requests must pass the explicit origin guard; admin writes also need CSRF.
Desktop sends `X-Client-Type: desktop`, uses the controlled desktop origin and bearer access token;
its refresh credential is held by the secure bridge. Web responses do not expose refresh tokens.

`POST /api/auth/signup`:

```json
{
  "username": "sample_user",
  "full_name": "Sample User",
  "email": "sample@example.com",
  "password": "ExampleOnly123!",
  "accepted_terms": true,
  "account_data_consent": true,
  "policy_version": "2026-09-19.2"
}
```

Both agreements must be explicit `true`. A current policy version is required.
Old clients missing these fields receive 422; the server never infers agreement.
Signin uses `username_or_email` and `password`. Session listing and revocation are under `/api/auth/sessions`.
Changing or resetting a privileged account password uses its stronger password policy and invalidates all auth planes.

Refresh rotates credentials. A same-device duplicate within five seconds returns 409 without a token;
reload session state rather than treating it as compromise. Reuse outside that narrow window or from another
identity revokes the family and returns 401. Clients must share one refresh promise and coordinate tabs.
Signout must finish independently of service-worker cleanup.

## Prices and history

Prefer `/api/instruments` and `/api/instruments/{instrument_id}` over asset aliases.
The canonical result includes instrument identity, source, source observation, receipt time,
validity, status and persistence metadata. Check all eligibility fields before ordinary use.

| Instrument | Currency and unit |
| --- | --- |
| XAU_USD_OZ | USD per troy ounce, gold spot |
| XAG_USD_OZ | USD per troy ounce, silver spot |
| GOLD_18K_TOMAN_GRAM | Toman per gram, purity 750 |
| GOLD_24K_TOMAN_GRAM | Toman per gram, purity 9999 |
| SILVER_999_TOMAN_GRAM | Toman per gram, purity 999 |
| SILVER_925_TOMAN_GRAM | Toman per gram, purity 925 |
| BTC_USD / BTC_TOMAN | USD / Toman per BTC |
| USDT_USD / USDT_TOMAN | USD / Toman per USDT |
| USD_TOMAN | Toman per USD |

Gold has no formula fallback. Missing direct gold is unavailable. Approved non-gold derived prices
remain theoretical and inherit the weakest input validity. Toman and USD percentages are independent.
Historical points keep their original instrument and unit. Completeness includes coverage and gaps;
partial data is returned as partial, not fabricated. Backfill is resumable and requires durable writes.
`GET /api/prices` sends `Cache-Control: no-store`. Current quotes and runtime policy are read after
chart inputs, and expiry is evaluated when each caller receives its payload. Only unfinished input
reads are shared; completed current-price payloads are not retained. The old aggregate-cache environment
setting is accepted for compatibility and does not permit stale current-price responses.
Partial history may request automatic backfill only for instruments with an explicit history route.
An owner-checked 60-second Redis guard bounds repeated automatic requests for the same instrument
and bucket range. Redis failure returns deferred without an unguarded enqueue. Manual requests keep
their exact ranges and retry behavior; a queued job is not evidence of durable history completion.

`WS /api/ws/prices` streams updates. Reconnect or a detected sequence gap requires a fresh HTTP snapshot.
Periodic HTTP refresh remains a recovery path. WebSocket transport health does not prove source price freshness.

## Alerts and notification channels

`POST /api/alerts` and `PATCH /api/alerts/{id}` use the exact AlertCreate/AlertUpdate schemas.
`instrument_id` selects the actual price. Keep asset and currency compatible with that instrument.
Use `ordinary`, `reference` or `derived` source mode deliberately; derived is an explicit theoretical opt-in.
Price alerts require a valid target and condition. Formula alerts require a valid formula after every update.
Null cannot clear required fields. Cooldown and per-day limits apply to repeating alerts.

Preferences do not create a browser subscription. Push enablement needs browser permission,
a service-worker subscription and successful `/api/push/subscribe`. SMS, email and Telegram need their
channel verification. Silent mode and user channel preferences remain authoritative.
Delivery retry/cancel uses atomic state transitions. Cancellation cannot undo an already transmitted message.

## Support and Smart Assistant

Support ticket/message requests require the explicit consent fields in their current generated schemas.
Do not reuse account consent as support-transmission consent. Internal support notes are admin-only.

Create ticket body:

```json
{"subject":"Sample issue","message":"Sample details","support_data_consent":true,"policy_version":"2026-09-19.2"}
```

Reply body uses `content` instead of `subject`/`message`, with the same explicit support consent and policy version.
Smart Assistant consent is separate. A chat request includes `processing_consent:true`,
`policy_version:"2026-09-19.2"`, `messages:[{"role":"user","content":"Sample question"}]`,
`language:"fa"` and an optional existing `session_id`. The final message must be from the user. Session messages are scoped to their session ID; stale replies cannot
replace the current conversation. Provider identity, quotas and availability are not inferred from a request succeeding.

## Admin

Admin routes live under `/api/admin` on the separate configured admin origin.
They require admin session cookies, `X-CSRF-Token` on unsafe writes, current RBAC permissions and
reauthentication for sensitive work. TOTP and recovery flows are described in [admin guide](docs/admin-guide.md).
The generated request schemas include confirmation text, review notes, expected versions and filters.
Use those fields as specified. Never build a sensitive payload by copying an old screenshot.

The route index covers auth/MFA, users/security/sessions, roles, support, instruments/canonical history,
provider drafts and impact, Telegram policies/preview, anomaly reviews, jobs/DLQ/backfill, settings,
audit, alerts and backup status where provided. See the guide for UI and API capability details.
Backup status is read-only evidence. It is not an in-panel production restore.

## Health and worker ingress

`/api/health/live` is liveness. `/api/health/ready` checks required dependencies and schema.
`/api/prices/health` checks operational pricing and freshness. `/metrics` is private.

`POST /api/internal/pricing-worker/ingest` requires HMAC-SHA256 of `timestamp + '.' + raw body`,
`X-Pricing-Worker-Timestamp`, `X-Pricing-Worker-Signature` and a Redis replay claim.
Only approved instrument/provider pairs are accepted. Live quotes retain real upstream timestamps,
follow the same anomaly and independence rules, and cannot move canonical observations backwards.
See [external workers](docs/external-price-worker.md).
