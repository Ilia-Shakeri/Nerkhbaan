# Nerkhbaan API Reference

Base path: `/api`. All responses are JSON. All timestamps are RFC 3339 in UTC.

- **Instrument model and price semantics** — [`apps/api/PRICING_SOURCES.md`](apps/api/PRICING_SOURCES.md)
- **Provider onboarding and operations** — [`docs/pricing-operations-runbook.md`](docs/pricing-operations-runbook.md)
- **Deployment** — [`README.md`](README.md)

Interactive OpenAPI is served at `/api/docs` **only when `DEBUG=true`**. It is
disabled in production, so this file is the reference.

---

## Contents

- [Conventions](#conventions)
- [Authentication](#authentication)
- [Prices (legacy shape)](#prices-legacy-shape)
- [Instruments (canonical shape)](#instruments-canonical-shape)
- [Live price stream](#live-price-stream)
- [Alerts](#alerts)
- [Notifications](#notifications)
- [Web push](#web-push)
- [Market assistant](#market-assistant)
- [Support](#support)
- [Providers](#providers)
- [System](#system)
- [Admin](#admin)
- [Rate limits](#rate-limits)

---

## Conventions

### Errors

Every error carries a `request_id` that also appears in the `X-Request-ID`
response header and in the server log line for the same request.

```json
{ "detail": "Invalid credentials", "request_id": "9f2c1ab34e..." }
```

| Status | Meaning in this API |
| --- | --- |
| `400` | Malformed input that schema validation cannot express |
| `401` | Missing, expired, or revoked credentials |
| `403` | Authenticated but not permitted, or an origin/CSRF check failed |
| `404` | Not found, or deliberately hidden (admin routes off the admin host) |
| `409` | Conflict — duplicate identity, quota reached, or unusable state |
| `413` | Body exceeded `MAX_REQUEST_BODY_BYTES` (1 MiB by default) |
| `422` | Schema validation failure; `detail` is a list of field errors |
| `429` | Rate limited. `Retry-After` is always set |
| `503` | A dependency is unavailable — distinct from `429` |

### Request identity

Send `X-Request-ID` (`[A-Za-z0-9._-]{1,128}`) to correlate your logs with the
server's. Anything else is replaced with a generated value.

### CSRF

Cookie-authenticated `POST`/`PUT`/`PATCH`/`DELETE` requests must carry an
`Origin` header matching a configured origin, otherwise they are rejected with
`403`. Bearer-token clients are unaffected. Admin routes additionally require
the `X-CSRF-Token` header (see [Admin](#admin)).

---

## Authentication

Two interchangeable mechanisms:

| Client | Mechanism |
| --- | --- |
| Web / PWA | `HttpOnly` cookies set by the server. Send `credentials: include`. |
| Desktop / native | Bearer token. Send `X-Client-Type: desktop` to receive tokens in the response body. |

Access tokens are short-lived (`JWT_EXPIRE_MINUTES`, default 15). Refresh
tokens rotate on every use and are tracked as a family: presenting a token that
has already been exchanged revokes the whole family, on the assumption that a
replayed token means it leaked.

### `POST /api/auth/signup`

```json
{ "username": "trader", "full_name": "A Trader", "email": "a@example.com", "password": "Str0ngPassphrase" }
```

`username` is `[a-zA-Z0-9._-]{3,50}`. It may not contain `@`, and it may not
collide with any existing account's **email** either — sign-in matches an
identifier against both columns, so an overlap would make the lookup ambiguous.

`password` is 10–128 characters with at least one lower case, one upper case,
and one digit.

**`201`** → `AuthResponse`. **`409`** if the identity is taken.

### `POST /api/auth/signin`

```json
{ "username_or_email": "trader", "password": "Str0ngPassphrase" }
```

**`200`** → `AuthResponse`. **`401`** on bad credentials, **`403`** if the
account is disabled, **`429`** after 5 failures in 15 minutes per IP+identifier.
Five consecutive failures also lock the account for 15 minutes.

```jsonc
// AuthResponse
{
  "access_token": null,          // populated only for X-Client-Type: desktop
  "refresh_token": null,         // ditto
  "token_type": "bearer",
  "user": { "id": 1, "username": "trader", "full_name": "A Trader",
            "email": "a@example.com", "is_active": true,
            "must_change_password": false, "created_at": "2026-08-20T09:00:00Z" }
}
```

### `POST /api/auth/refresh`

Cookie clients send nothing; desktop clients send `{"refresh_token": "..."}`.
Returns a fresh `AuthResponse` and rotates the refresh token.

**`401`** if the token is unknown, expired, revoked, or already exchanged.

### `GET /api/auth/me`

Returns the current `UserResponse`.

### `POST /api/auth/change-password`

```json
{ "current_password": "...", "new_password": "..." }
```

Revokes **every** session for the account, including the caller's, and
increments the account's security version so outstanding access tokens stop
validating. The client must sign in again.

### `POST /api/auth/forgot-password` · `POST /api/auth/reset-password`

`forgot-password` takes `{"email": "..."}` and always answers `200` with the
same message, whether or not the address exists. A six-digit code valid for 15
minutes is emailed when it does.

`reset-password` takes `{"email", "code", "new_password"}`. Success revokes
every session. **`400`** covers both a wrong code and an expired one — they are
deliberately indistinguishable.

### `GET /api/auth/sessions` · `DELETE /api/auth/sessions/{session_id}`

Lists live sessions, marking the caller's with `"current": true`. Deleting
returns **`204`**.

### `POST /api/auth/signout`

Revokes the presented session and clears cookies. **`204`**. Idempotent.

---

## Prices (legacy shape)

The compatibility surface consumed by the web and desktop dashboards.

### `GET /api/prices`

Public. Cached server-side for `PRICING_PROVIDER_AGGREGATE_CACHE_SECONDS`.

> **The USD and Toman figures on one row are different instruments.** Gold's USD
> leg is a troy ounce at 0.9999 fine on the global spot market; its Toman leg is
> one gram at 0.750 fine in the Iranian physical market. They are not one asset
> in two currencies. Use `unit_usd` / `unit_toman` to label them, and
> `change_percent_usd` / `change_percent_toman` rather than the combined
> `change_percent`, which follows whichever leg is available.

```jsonc
{
  "refreshed_at": "2026-08-20T09:14:02Z",
  "source": { "usd": "canonical", "toman": "canonical" },
  "assets": [
    {
      "asset": "gold",
      "label_fa": "طلا", "label_en": "Gold",

      "price_usd": 2400.15,
      "price_toman": 4476000,

      "instrument_id_usd": "XAU_USD_OZ",
      "instrument_id_toman": "GOLD_18K_TOMAN_GRAM",
      "unit_usd":   { "instrument_id": "XAU_USD_OZ", "quote_currency": "USD",
                      "weight_unit": "troy_ounce", "purity": 0.9999,
                      "market": "global_spot", "display_decimals": 2 },
      "unit_toman": { "instrument_id": "GOLD_18K_TOMAN_GRAM", "quote_currency": "TOMAN",
                      "weight_unit": "gram", "purity": 0.75,
                      "market": "iran_physical", "display_decimals": 0 },

      "change_percent_usd": 0.42,
      "change_percent_toman": 0.61,
      "change_percent": 0.61,
      "trend": "up",

      "usd_status": "live", "toman_status": "derived_fallback",
      "source_usd": "canonical", "source_toman": "derived",
      "stale_minutes": 1,
      "history": [ { "timestamp": "...", "value_usd": 2399.8, "value_toman": 4470000 } ],
      "chart_error": false,
      "chart_error_message": { "fa": "...", "en": "..." },

      "usd_is_persisted": true,  "toman_is_persisted": true,
      "usd_live_eligible": true, "toman_live_eligible": true,
      "usd_is_suspicious": false, "toman_is_suspicious": false,
      "usd_source_semantic": "reference_rate", "toman_source_semantic": "derived",
      "usd_derivation_depth": 0, "toman_derivation_depth": 2,
      "usd_spread_bps": null, "usd_maximum_spread_bps": 150
    }
  ]
}
```

Assets: `gold`, `silver`, `usdt`, `btc`.

#### Status values

| Status | Meaning |
| --- | --- |
| `live` | Fresh direct quote |
| `confirmed` | Anomalous but corroborated by an independent source |
| `fresh_cache` | Past its refresh interval, still inside its validity window |
| `verifying` | A suspicious candidate is being checked; the previous value is shown |
| `suspicious` / `suspicious_unconfirmed` | Candidate rejected; previous value retained |
| `derived_fallback` | Computed from a formula, not observed. See below. |
| `stale` | Past `stale_after`, still displayable |
| `expired` | Past `expire_after`. Do not trade on it. |
| `unpersisted` | Accepted but not yet durably stored |
| `unavailable` | No value at all |

**Only `live`, `confirmed` and `fresh_cache` are safe to treat as a market
price.** `derived_fallback` is arithmetic, not an observation.

### `GET /api/prices/{asset}/history`

`?timeframe=1h|24h|7d|30d|1y` (default `30d`). Public, `Cache-Control: public, max-age=60`.

`status` is `complete` or `partial`; `partial` means a backfill was queued for
the missing range.

### `GET /api/prices/health`

Public. Chain status per asset plus a `startup` block:

```jsonc
"startup": {
  "strict_mode": false,
  "optional_env_keys": ["goldapi_api_key", "..."],
  "missing_optional_env_keys": ["tala_api_key"],
  "instruments_without_direct_source": ["SILVER_999_TOMAN_GRAM"],  // formula only
  "instruments_unservable": [],                                    // no price at all
  "ok": true
}
```

`instruments_without_direct_source` is the one to watch: those chains publish
computed values, not observed ones.

---

## Instruments (canonical shape)

The precise surface. Every instrument is a single unambiguous quote.

| Instrument | Unit | Purity | Market |
| --- | --- | --- | --- |
| `XAU_USD_OZ` | troy ounce | 0.9999 | global spot |
| `XAG_USD_OZ` | troy ounce | 0.9999 | global spot |
| `GOLD_18K_TOMAN_GRAM` | gram | 0.750 | Iran physical |
| `GOLD_24K_TOMAN_GRAM` | gram | 0.9999 | Iran physical |
| `SILVER_999_TOMAN_GRAM` | gram | 0.999 | Iran physical |
| `SILVER_925_TOMAN_GRAM` | gram | 0.925 | Iran physical |
| `USD_TOMAN` | unit | — | Iran exchange |
| `USDT_TOMAN` | unit | — | Iran exchange |
| `USDT_USD` | unit | — | global exchange |
| `BTC_TOMAN` | unit | — | Iran exchange |
| `BTC_USD` | unit | — | global exchange |

### `GET /api/instruments` · `GET /api/instruments/{id}`

Authentication is optional and widens the response: anonymous callers get the
price and status; authenticated callers additionally get `provider_id`,
`route_id`, `provenance`, decision reasons and the full source summary.

### `GET /api/instruments/{id}/history`

`?timeframe=1h|24h|7d|30d|1y` (default `24h`). OHLC buckets sized to the
timeframe.

### `GET /api/instruments/{id}/sources`

Per-provider quotes behind the canonical value. Anonymous callers receive counts
only.

### `GET /api/instruments/{id}/sources/history`

**Requires authentication** (`401` otherwise). Optional `?provider_id=`.

### `GET /api/instruments/{id}/verification` · `GET /api/instruments/{id}/health`

Anomaly review trail, and freshness/circuit state for one instrument.

---

## Live price stream

### `WS /api/ws/prices`

Optional `?instruments=BTC_USD,XAU_USD_OZ` (max 100).

A browser client must connect from a configured origin; the handshake is closed
with `1008` otherwise. Native clients send no `Origin` and are accepted.

On connect the server sends a snapshot, then one event per canonical change:

```jsonc
{ "event_type": "snapshot", "connection_id": "...", "heartbeat_seconds": 20,
  "poll_fallback_seconds": 30, "prices": [ /* canonical events */ ] }

{ "event_type": "canonical_update", "instrument_id": "BTC_USD",
  "compatibility_asset": "btc", "price": 64210.5, "status": "live",
  "sequence": 88421, "currency": "USD", "unit": "unit", "purity": null,
  "canonical_at": "...", "age_seconds": 3, "persistence_status": "persisted" }

{ "event_type": "heartbeat", "server_time": 1766221000.5 }
```

Change your subscription at any time:

```json
{ "event_type": "subscribe", "instruments": ["XAU_USD_OZ"] }
```

**Do not stop polling while the socket is open.** Events are published only when
a canonical value *changes*, so a stalled pricing pipeline produces heartbeats
and no updates — indistinguishable from a quiet market. The reference client
keeps a slow poll running as a liveness check.

Limits: `WEBSOCKET_MAX_CONNECTIONS_PER_WORKER` (default 1000); 30 client frames
per minute; close code `1013` when the worker is at capacity or Redis fan-out is
unavailable.

---

## Alerts

All routes require authentication. Maximum **50 active alerts per account** —
every one is re-evaluated each cycle.

### `POST /api/alerts`

```jsonc
{
  "asset": "gold",
  "alert_type": "price",              // or "formula"
  "target_price": 4500000,
  "condition": "above",               // or "below"
  "currency_mode": "toman",           // or "usd"
  "price_source_mode": "ordinary",    // "ordinary" | "reference" | "derived"
  "mode": "one_time",                 // or "recurring"
  "cooldown_seconds": 900,            // 60 .. 604800
  "max_notifications_per_day": 10,    // 1 .. 100
  "notify_app": true,
  "notify_email": false,
  "notify_telegram": false,
  "notify_webhook": false,
  "webhook_url": null,
  "enable_dlq": false
}
```

**`price_source_mode` decides which prices may fire the alert:**

| Mode | Fires on |
| --- | --- |
| `ordinary` | Direct market observations only — exchange trades, order books, physical market quotes |
| `reference` | Reference rates (e.g. metal fixings) |
| `derived` | Formula output. Explicitly opting in to computed values. |

An alert never fires on a `suspicious`, `expired` or unpersisted price, nor when
the order-book spread exceeds the instrument's `maximum_spread_bps`.

**Formula alerts** set `alert_type: "formula"` and supply an expression such as
`gold > btc * 0.05`. Names are asset ids, optionally suffixed with a normalised
source name; `x` binds to `target_price`. The grammar allows `+ - * /`,
comparison, parentheses and numeric literals — nothing else, evaluated over a
restricted AST with a node cap.

**Webhooks** must be HTTPS, must not carry credentials, and must resolve to a
public address. The host is re-validated at delivery and the connection is
checked against the addresses that were vetted.

**`201`** → `AlertResponse`. **`409`** at the alert cap. **`422`** for an invalid
formula, an unreachable webhook, or a channel that is not configured.

### `PATCH /api/alerts/{id}`

Partial update. Editing re-arms the alert: `triggered_at`, `last_condition_state`
and `next_eligible_trigger_at` are cleared, so a moved target takes effect
immediately without losing the alert's identity.

### `GET /api/alerts`

`?limit=1..200&offset=0`. Active alerts, newest first.

### `DELETE /api/alerts/{id}`

Soft-deletes (`is_active = false`). **`204`**.

### Delivery

A trigger writes one `alert_trigger_events` row and one `alert_delivery_jobs`
row per channel, each with an idempotency key. A worker claims jobs with
`SKIP LOCKED`. With `enable_dlq`, failures retry with exponential backoff and
jitter up to `ALERT_DELIVERY_MAX_ATTEMPTS`, then land in the DLQ. Permanent
failures — an unsubscribed push endpoint, a disabled channel — never retry.

Webhook payload:

```json
{ "alert_id": 12, "asset": "gold", "target_price": 4500000,
  "condition": "above", "currency": "toman",
  "triggered_at": "2026-08-20T09:14:02Z",
  "price": 4501200,
  "price_context": { "status": "live", "source_semantic": "physical_market_quote",
                     "price_source_mode": "ordinary", "source_summary": {} } }
```

---

## Notifications

All routes require authentication.

| Route | Purpose |
| --- | --- |
| `GET /api/notifications` | `?limit=1..200&offset=0&unread_only=false` |
| `PATCH /api/notifications/{id}/read` | Mark one read |
| `POST /api/notifications/read-all` | Mark all read — `204` |
| `GET /api/notifications/preferences` | Current preferences and channel availability |
| `PATCH /api/notifications/preferences/{key}` | `push_app`, `silent_mode`, `aggressive_alerts` |
| `POST /api/notifications/otp/start` | Send a code to an email address |
| `POST /api/notifications/otp/confirm` | Verify it; enables the channel |
| `POST /api/notifications/telegram/deep-link` | One-time `t.me` link — the recommended flow |
| `POST /api/notifications/telegram` · `/confirm` | Manual chat-id flow |
| `DELETE /api/notifications/{channel}` | Disable `sms`, `email` or `telegram` |

A channel only delivers once it is both **enabled and verified**. SMS is not
implemented and returns `503`.

`POST /api/notifications/telegram/webhook` is for Telegram itself and requires
the `X-Telegram-Bot-Api-Secret-Token` header.

---

## Web push

### `POST /api/push/subscribe`

Body is the browser's `PushSubscription.toJSON()`. The endpoint host must be a
known push service (`PUSH_ALLOWED_HOSTS`).

Authentication is optional but **matters**: a subscription created while signed
out is stored with no account and receives nothing. The web client re-sends it
after sign-in for exactly this reason. Re-subscribing rebinds an existing
endpoint to the current account.

### `POST /api/push/unsubscribe`

`{"endpoint": "..."}` → **`204`**. Called on sign-out so the next user of a
shared device does not inherit the previous account's alerts.

> `VAPID_PUBLIC_KEY` is compiled into the web bundle at **image build time**. A
> frontend image built without it has push permanently disabled until rebuilt.

---

## Market assistant

Authenticated. Backed by a chat-completions provider with an ordered fallback
chain (`AI_PROVIDER_ORDER`).

| Route | Purpose |
| --- | --- |
| `POST /api/insights/analyze` | `{"asset", "language"}` → short read on one asset |
| `POST /api/insights/chat` | `{"messages", "language", "session_id"}` |
| `GET /api/insights/chat/sessions` | List |
| `GET`/`PATCH`/`DELETE /api/insights/chat/sessions/{id}` | Fetch, rename, delete |

`analyze` returns **`409`** when no verified market data is available — it will
not narrate a stale or suspicious price.

Quotas: 15 requests/minute, `AI_USER_DAILY_REQUEST_LIMIT` per day per user, and
`AI_GLOBAL_DAILY_REQUEST_LIMIT` across the deployment. Exhaustion is **`429`**;
a provider outage is **`503`**. Identical consecutive requests are deduplicated.

Replies carry a disclaimer. This is general information, not investment advice.

---

## Support

| Route | Purpose |
| --- | --- |
| `POST /api/support/ticket` | `{"subject", "message"}` |
| `GET /api/support/tickets` | Caller's tickets |
| `GET /api/support/ticket/{id}/messages` | Thread |
| `POST /api/support/ticket/{id}/message` | Reply |

30 writes per minute per user. Internal admin notes are never returned here.

---

## Providers

### `GET /api/providers`

Anonymous callers get counts per instrument:

```json
{ "checked_at": "...", "authentication_required_for_details": true,
  "instruments": { "BTC_USD": { "provider_count": 4, "healthy_count": 2 } } }
```

Authenticated callers get the full catalogue with provider ids, roles, circuit
state and which credentials are configured. That detail names every upstream the
platform depends on, which is why it is not public.

---

## System

| Route | Purpose |
| --- | --- |
| `GET /health`, `GET /api/health/live` | Liveness. Always `200` if the process is up. |
| `GET /api/health/ready` | Readiness. `503` unless the database is reachable **and** migrations are current. |
| `GET /api/health` | Full snapshot: database, Redis, migration version, backlogs. |
| `GET /metrics` | Prometheus. Loopback/private networks plus `METRICS_ALLOWED_NETWORKS`; `404` otherwise. |

Readiness deliberately requires the database. Authentication, alerts and admin
all go through PostgreSQL, so a cache-only instance cannot serve the product and
must not receive traffic.

---

## Admin

Served on a separate host and returned as `404` on the public one.

**Every admin request needs all of:** a session cookie; an `Origin` matching
`ADMIN_FRONTEND_ORIGIN`; an `X-CSRF-Token` header matching the session (mutating
methods); a source address inside `ADMIN_IP_ALLOWLIST` when set; and a role
carrying the required permission. Sessions are bound to the user agent by
default and optionally to the IP.

Destructive operations additionally require re-authentication within
`ADMIN_REAUTH_MINUTES` and a typed confirmation string echoed back exactly.

| Area | Routes |
| --- | --- |
| Auth | `signin`, `signout`, `me`, `csrf`, `reauthenticate`, `change-password` |
| Users | list, detail, `state`, `force-password-change`, `sessions/close` |
| Roles | `roles`, `permissions`, `administrators`, `administrators/{id}/roles` |
| Support | tickets, reply, internal notes |
| Pricing | instruments, `refresh`, anomalies, anomaly review |
| Providers | catalogue, impact, config drafts with apply/reject |
| Telegram | sources CRUD |
| Jobs | jobs, DLQ, retry, cancel |
| Settings | feature flags, operational settings |
| Audit | `GET /api/admin/audit` |

The last active super administrator cannot be demoted or disabled.

---

## Rate limits

Shared across workers through Redis; per-process when Redis is unavailable.
Every `429` carries `Retry-After`.

| Bucket | Limit | Window |
| --- | --- | --- |
| Sign-in failures | 5 | 15 min per IP + identifier |
| Sign-up | 8 | 1 hour per IP |
| Password recovery | 5 | 15 min per IP + email |
| Password reset attempts | 10 | 15 min |
| Push subscribe | 20 | 1 min |
| Notification OTP (per user) | 5 | 10 min |
| Notification OTP (per destination) | 3 | 1 hour |
| Support writes | 30 | 1 min |
| Assistant | 15 | 1 min, plus daily user and global caps |

The edge proxy adds its own limits: 1 r/s to `/api/auth/`, 20 r/s to `/api/`,
5 r/s to the admin API.
