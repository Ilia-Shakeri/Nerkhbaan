# Administrator guide — 2.8.6

The administrator console uses a separate HttpOnly session cookie under
`/api/admin`. Public login does not grant administrator access. Permissions are
checked on every server request; controls also follow the signed-in account's
permissions. System roles are reconciled from the versioned permission catalog.
Custom roles keep their own policy.

## Start and sign in

1. Apply all forward migrations, including `20261011_001_delivery_hardening`.
2. Configure the exact browser origin in `ADMIN_FRONTEND_ORIGIN`. Local default
   is `http://localhost:4174`; `127.0.0.1` is a different origin. Set the proxy
   allowlist, administrator network policy and secure cookies for the target
   environment. Use HTTPS outside local development.
3. Provide the four bootstrap identity fields through protected deployment
   configuration. The bootstrap password must be 14–128 characters with upper
   case, lower case, a digit and a symbol. Bootstrap creates the initial
   super administrator only when none exists. It cannot reset an existing user.
4. Run the API and console. For the console:

   ```powershell
   npm.cmd run dev --workspace=nerkhbaan-admin-web
   ```

5. Sign in; replace the bootstrap password before opening operational pages.
   `My security` also provides ordinary password changes.
6. Enroll MFA from `My security`. Re-authenticate, add the manual setup key to
   a TOTP authenticator, then confirm a current six-digit code. Store the ten
   recovery codes shown once. Neither the secret nor the recovery codes enter
   audit events. Production Compose and `.env.example` default to `ADMIN_MFA_REQUIRED=true`; this requires enrollment for all
   operational pages. Confirm at least one administrator's enrollment before
   enforcing that deployment policy.

The TOTP profile is encrypted with a purpose-specific key derived from the
application signing key. Preserve the signing key in the protected backup
plan. A TOTP code and each recovery code work once. After using a TOTP code at
login or re-authentication, wait for a new code before another sensitive check.
Recovery codes can sign in, re-authenticate, rotate recovery codes and disable
optional MFA when the deployment policy allows it. Required MFA cannot be disabled through the console. Rotating
recovery codes invalidates all previous recovery codes.

### Console on an existing HTTPS host

The default build path is `/`. To serve the console at `https://nerkhbaan.ir/admin/`,
build with `VITE_ADMIN_BASE_PATH=/admin/` and set `ADMIN_FRONTEND_ORIGIN=https://nerkhbaan.ir`.
The origin contains no path. Preserve `/api/admin` for API requests and the administrator
cookie path; use `nerkhbaan.ir` as the cookie domain or leave the domain unset for a host-only cookie.
Production Compose passes the build variable to the administrator image. Rebuild the image
when changing it. The HTTPS proxy must route `/admin/` and its assets to the administrator
frontend while routing `/api/admin/` directly to the API; redirect `/admin` to `/admin/`.
Hash navigation stays inside `/admin/`. This setup uses the existing host certificate and
does not require a separate administrator DNS record.

## Session and mutation contract

- All non-read requests require the exact allowed `Origin`; authenticated
  mutations also require `X-CSRF-Token`. `GET /auth/csrf` returns a stable token
  for the current session, so opening another tab does not break an existing tab.
- `POST /auth/reauthenticate` accepts `password` and optional `mfa_code`.
  Sensitive operations require recent successful re-authentication, then their
  exact typed confirmation. Limits apply to sign-in and sensitive checks.
- Password changes and reset revoke both public and administrator credentials.
  An administrator password change preserves only the verified current
  administrator session. Role policy changes revoke affected administrator
  sessions. Disabling an account closes both session types.
- The final active super administrator cannot lose access. Role assignment,
  account disable and bootstrap share one PostgreSQL transaction lock.
- Session expiry returns 401 and clears the local console profile. Failed
  network signout clears the local profile and reports pending server logout;
  reopening the console retries server logout before restoring a profile.
- 403 means origin, CSRF, permission, password gate, MFA gate or re-authentication
  denied. 409 means a conflicting state/version or protected final administrator.
  422 means invalid input. 429 includes `Retry-After`.

## Console pages

| Page | Available operations |
| --- | --- |
| Operations | DB/Redis state, current snapshot age, missing/stale instruments, refresh heartbeat, actual provider runtime/circuit state, budget usage, backlogs and administrator worker state |
| Users | Search/state filter, paging, details, security events, paged public/admin sessions, close one/all sessions, force password change, enable/disable with reason |
| Access | Administrator list, select a user, replace multiple roles, revoke all roles, close administrator sessions, create/edit/deactivate custom roles and permission sets |
| Support | Search/status/priority/assignee filters, paging, complete conversation and internal notes, reply, status/priority update, assign active support staff or unassign |
| Providers | Runtime configuration draft, before/proposed/impact comparison, pending/applied/rejected history, apply/reject and create a rollback draft |
| Telegram sources | Create/edit source policy, parser/instrument selection, trust/confidence/age/deviation limits, independent-source requirement and parser preview |
| Pricing | Latest quote per instrument, unit/purity, canonical history, raw source quotes, verification records, budget-controlled refresh and anomaly review with quote proof |
| Jobs & DLQ | Status filter, paging, safe errors/details, retry and cancel queued administrator/backfill work, delivery retry/cancel and a separately paged dead-letter queue |
| Settings | Feature defaults, global/instrument/provider/source scopes, stored versions, effective inherited values, edit and reset override |
| Audit | Action/resource/result/actor/date filters, paging, redacted before/after changes and filtered JSON export |
| Alerts | User/state/instrument filters, paging, alert configuration, delivery history and enable/disable with reason |
| Backup evidence | Read-only backup/restore manifest state and age; reports `not_configured` when no evidence file is connected |
| My security | Password change, MFA enrollment/confirmation, recovery code replacement and optional MFA disable |

Support sends pin the ticket ID at submission. Switching tickets clears the
draft and old details; late responses cannot populate the newly selected ticket.
Assignees must be active and possess `admin.support.reply`.

Telegram and dead-letter pages have their own permission gates, including custom roles with no provider/job access. Source lists use `limit`/`offset` paging and return the supported instrument IDs.

Telegram parser names are `strict_explicit` and `strict_hashtag`; parser version
is `strict-explicit-3`. Use the marked channel ID (`-100…`) from the actual chat,
not a username guess. Preview uses the same parser source as the worker, checks
explicit units and never writes a price. The source policy still controls age,
trust and independent verification during ingestion.

Provider drafts record the current configuration version. Apply takes a lock,
checks that version and recomputes impact. A stale draft returns 409; create a
new draft from the current policy. A rollback creates another reviewable draft,
not an immediate unreviewed change. Code-level quarantines remain safety limits.

Anomaly review never promotes a quote by itself. Open anomalies can become
reviewed, dismissed or resolved; reviewed anomalies can become dismissed or
resolved. A note of at least three characters is required. Candidate and prior
quote values, units, times and sources are shown before a decision.

Delivery cancellation uses a status check in the same transaction. Queued or
claimed (`processing`) work can cancel before its transition to `sending`.
`sending` or delivered work cannot be recalled and returns 409. Queued backfill
and administrator jobs can cancel; running work returns 409. Retry preserves
attempt history. Completed work is not reset silently.

## Request examples

Paths below are relative to `/api/admin`. JSON values are synthetic placeholders.
Use the signed-in browser console for ordinary operations; never commit real
passwords, session cookies, MFA keys or recovery codes into examples.

| Method/path | Body or query | Permission |
| --- | --- | --- |
| POST `/auth/signin` | `identifier`, `password`, optional `mfa_code` | Assigned active administrator |
| GET `/auth/me`, `/auth/csrf`, `/auth/mfa` | none | Current administrator session |
| POST `/auth/reauthenticate` | `password`, optional `mfa_code` | Current session, CSRF |
| POST `/auth/change-password` | `current_password`, `new_password` | Current session, CSRF |
| POST `/auth/signout` | none | Current session, CSRF |
| POST `/auth/mfa/enroll` | none | Recent re-authentication |
| POST `/auth/mfa/confirm`, `/auth/mfa/disable`, `/auth/mfa/recovery-codes` | `code` | Recent re-authentication |
| GET `/users` | `search`, `active`, `limit`, `offset` | `admin.users.read` |
| GET `/users/{id}` | none | `admin.users.read` |
| GET `/users/{id}/sessions` | `kind=user|admin`, `limit`, `offset` | `admin.users.read` |
| GET `/users/{id}/security-history` | `limit`, `offset` | `admin.users.read` |
| PATCH `/users/{id}/state` | `is_active`, `reason`, `confirmation` | `admin.users.manage`, recent re-authentication |
| POST `/users/{id}/force-password-change` | `confirmation` | `admin.users.manage`, recent re-authentication |
| POST `/users/{id}/sessions/close` | `confirmation` | `admin.sessions.manage`, recent re-authentication |
| POST `/users/{id}/sessions/{kind}/{session}/close` | `confirmation` | `admin.sessions.manage`, recent re-authentication |
| GET `/roles`, `/permissions`, `/administrators` | none | `admin.roles.read` |
| PUT `/administrators/{id}/roles` | `roles` array (may be empty), `confirmation` | `admin.roles.manage`, recent re-authentication |
| POST `/administrators/{id}/sessions/close` | `confirmation` | `admin.sessions.manage`, recent re-authentication |
| POST `/roles` / PUT `/roles/{id}` | `name`, `description`, `permissions`, `is_active`, `confirmation` | `admin.roles.manage`, recent re-authentication |
| GET `/support/tickets` | `search`, `status`, `priority`, `assigned_admin_id`, `limit`, `offset` | `admin.support.read` |
| GET `/support/tickets/{id}`, `/support/assignees` | none | `admin.support.read` |
| PATCH `/support/tickets/{id}` | optional `status`, `priority`, `assigned_admin_id` (null clears assignment) | `admin.support.manage` |
| POST `/support/tickets/{id}/reply` | `content` | `admin.support.reply` |
| POST `/support/tickets/{id}/internal-notes` | `content` | `admin.support.manage` |
| GET `/providers`, `/providers/{id}/impact` | impact accepts `enabled`, `role` | `admin.providers.read` |
| GET `/providers/drafts` | `status`, `limit`, `offset` | `admin.providers.read` |
| POST `/providers/{id}/drafts` | Any allowed provider fields listed below | `admin.providers.manage` |
| POST `/providers/drafts/{id}/apply` | `confirmation` | `admin.providers.manage`, recent re-authentication |
| POST `/providers/drafts/{id}/reject`, `/providers/drafts/{id}/rollback` | none | `admin.providers.manage` |
| GET `/telegram/sources` | none | `admin.telegram.read` |
| POST `/telegram/sources` | source identity, policy, `confirmation` | `admin.telegram.manage`, recent re-authentication |
| PATCH `/telegram/sources/{id}` | changed policy fields, `confirmation` | `admin.telegram.manage`, recent re-authentication |
| POST `/telegram/sources/{id}/preview` | `text` | `admin.telegram.read` |
| GET `/pricing/instruments` | none | `admin.pricing.read` |
| GET `/pricing/instruments/{id}` | `history_limit` | `admin.pricing.read` |
| GET `/pricing/anomalies` | `status`, `limit`, `offset` | `admin.pricing.read` |
| POST `/pricing/anomalies/{id}/review` | `status`, `note` | `admin.pricing.manage` |
| POST `/pricing/instruments/{id}/refresh` | `reason` | `admin.pricing.manage` |
| GET `/jobs` | `status`, `limit`, `offset` | `admin.jobs.read` |
| GET `/jobs/dlq` | `limit`, `offset` | `admin.dlq.read` |
| POST `/jobs/{id}/retry`, `/jobs/backfill/{id}/retry` | none | `admin.jobs.manage` |
| POST `/jobs/{id}/cancel`, `/jobs/backfill/{id}/cancel` | `confirmation` | `admin.jobs.manage`, recent re-authentication |
| POST `/jobs/delivery/{id}/retry` | none | `admin.dlq.manage` |
| POST `/jobs/delivery/{id}/cancel` | `confirmation` | `admin.dlq.manage`, recent re-authentication |
| GET `/settings`, `/settings/effective` | effective accepts `scope_id` | `admin.settings.read` |
| PATCH `/settings/feature-flags/{key}` | `enabled`; derived enable also needs `confirmation` | `admin.settings.manage` |
| PUT `/settings/operational` | `key`, `scope_id`, `value`, `expected_version`, optional `confirmation` | `admin.settings.manage` |
| POST `/settings/operational/reset` | same identity/current value/version, `confirmation` | `admin.settings.manage`, recent re-authentication |
| GET `/audit`, `/audit/export` | `action`, `resource_type`, `result`, `actor_admin_id`, `since`, `until`; list also takes `limit`, `offset` | `admin.audit.read` |
| GET `/alerts` | `user_id`, `active`, `instrument_id`, `limit`, `offset` | `admin.alerts.read` |
| GET `/alerts/{id}` | none | `admin.alerts.read` |
| PATCH `/alerts/{id}/state` | `is_active`, `reason`, `confirmation` | `admin.alerts.manage`, recent re-authentication |
| GET `/health`, `/dashboard`, `/backups/status` | none | `admin.health.read` |

Paginated lists return `items`, `total`, `limit`, `offset`. `/jobs` returns
`admin_jobs`, `backfill_jobs`, `delivery_jobs` and totals per collection. The
three job lists share the selected offset. Audit export returns up to 500
filtered records and a `truncated` flag; narrow the date range when truncated.
All exposed errors and audit data redact credential patterns and personal fields.

Allowed provider draft fields: `enabled`, `role`, `priority`, `trust_score`,
`minimum_interval_seconds`, `operational_ttl_seconds`, `requests_per_minute`,
`requests_per_hour`, `requests_per_day`, `reserved_anomaly_requests`,
`reserved_fallback_requests`. Credential values are never writable through a
provider draft; configured status is computed from the shared settings object.

Operational keys: `comparison_visible`, `derived_fallback_enabled`,
`backfill_enabled`, `telegram_source_enabled`, `anomaly_threshold_percent`,
`canonical_expiry_seconds`, `provider_budget_requests_per_hour`. Provider budget
scopes name a provider; Telegram scopes name a stored source; other scopes name
an instrument. All accept `global`. Scope-specific values override global values;
removing a row restores inherited defaults. `expected_version=0` creates a new
override; subsequent edits must provide the current stored version. Canonical
expiry is 30–172800 whole seconds, anomaly threshold is 0.1–25 percent and hourly
budget is 0–100000 whole requests. Boolean keys require actual JSON booleans.
Administrator frontend visibility remains a deployment control and is read-only.

### Typed confirmations

```text
ENABLE USER {id} / DISABLE USER {id}
FORCE PASSWORD CHANGE {id}
CLOSE USER SESSIONS {id}
CLOSE ADMIN SESSIONS {id}
CLOSE USER SESSION {session_id} / CLOSE ADMIN SESSION {session_id}
SET ADMIN ROLES {id}
CREATE ROLE {name} / UPDATE ROLE {id}
APPLY PROVIDER {provider_id}
CREATE TELEGRAM SOURCE {channel_id}
UPDATE TELEGRAM SOURCE {source_id}
CANCEL ADMIN JOB {id} / CANCEL BACKFILL {id} / CANCEL DELIVERY {id}
CHANGE SETTING {key}:{scope_id}
RESET SETTING {key}:{scope_id}
ENABLE DERIVED FALLBACK
ENABLE ALERT {id} / DISABLE ALERT {id}
```

## Backup status wiring

`ADMIN_BACKUP_STATUS_FILE` must name an absolute path to a small JSON manifest.
Mount only that file read-only in the API container. The API returns only
`last_backup_at`, `last_restore_at`, `backup_status`, `restore_status`, `verified`,
`size_bytes` and computed ages. It never exposes backup paths or permits restore.
The restore drill can write this evidence file using `BACKUP_STATUS_FILE` after
the Timescale restore and fingerprint comparison pass. Local or CI evidence
must not be relabeled as live-host verification.

## Validation and delivery gate

```powershell
Push-Location apps/api
python -m unittest discover -s tests -p 'test_admin*.py'
python -m pyflakes app/admin
Pop-Location
npm.cmd run build --workspace=nerkhbaan-admin-web
npm.cmd run typecheck --workspace=@nerkhbaan/ui
npm.cmd run test:e2e -- tests/e2e/admin-console.spec.ts
```

The administrator suite tests CSRF stability, real HTTP session/MFA checks,
one-use recovery, password/role revocation, final-super-admin protection,
assignment/unassignment, SQL filtering/latest quote selection, draft conflicts,
setting versions/reset, safe errors and worker recovery. The browser suite uses
synthetic responses for ticket races, permissions, paging, logout and required
MFA. Run the full project gates from the release runbook as well. SQLite tests
do not prove PostgreSQL locking under two replicas, live provider correctness,
Docker deployment or live backup recovery; those target-host gates remain part
of the delivery procedure.
