# Production Hardening Report

## Baseline

Captured on 2026-08-02 at 14:26:18 +03:30 before source changes.

### Repository

- Starting branch: `main`
- Starting commit: `702f85f70cbcce6adc5c59aaf4b8f605fd040933`
- Starting tree: `ce7c833cbee2ccda7f7e0fb79509f9a5d53d6b89`
- Starting worktree: clean
- Hardening branch: `production-hardening`
- Tracked tree entries: 702
- Top-level tracked entry counts: `apps` 635, `packages` 54, and 13 root/configuration entries
- Exact tree command: `git ls-tree -r --name-only 702f85f70cbcce6adc5c59aaf4b8f605fd040933`
- A local ignored `.env` file was present. It was not read, copied, logged, or modified.

### Host toolchain

| Tool | Baseline |
| --- | --- |
| Operating system | Windows NT 10.0.26200.0 |
| Python | 3.14.5, CPython MSC v.1944, 64 bit |
| Project virtual environment | Python 3.14.5, zero installed packages |
| Host Python packages | 143 installed packages; application pins were present globally |
| Node.js | 22.23.0 |
| npm | 10.9.8 |
| Lockfile | npm lockfile version 3, 742 package records |
| Docker | CLI unavailable on this host |

The complete dependency input is tracked in `apps/api/requirements.txt` and `package-lock.json`. The baseline `pip freeze` was captured in the task log without adding host-only packages to the repository.

### Baseline commands and exact outcomes

| Command | Outcome |
| --- | --- |
| `python -m compileall app` from `apps/api` | Passed. |
| `python -m unittest discover -s tests -v` from `apps/api` | Passed: 16 tests in 0.124 seconds. |
| `npm.cmd run build:web` | Failed before bundling: Vite/esbuild could not read `../../../..` on this Windows host and could not load `apps/web/vite.config.ts`. |
| `npm.cmd run build:admin` | Failed: TypeScript TS5096 in `tsconfig.node.json`; `allowImportingTsExtensions` was used without `noEmit` or `emitDeclarationOnly`. |
| `npm.cmd run build:desktop` | Failed: TS2339 in `AppContext.tsx` and TS2345 in `DashboardView.tsx`. |
| `npm.cmd install --package-lock-only --ignore-scripts --dry-run` | Passed: lockfile reported up to date. |
| `docker compose config` | Not run because Docker is unavailable. This is an explicit host verification gap. |

Build-generated, untracked `apps/admin-web/vite.config.js` and `vite.config.d.ts` files were removed after the baseline was recorded. No tracked source was changed by baseline commands.

### Confirmed build and release state

- The root `package-lock.json` already exists and is internally consistent.
- `apps/web/Dockerfile` already copies the root lockfile and installs only the web and shared UI workspaces through the repository install script.
- Admin and desktop TypeScript project files exist and now pass their build paths.
- `packages/ui/src/index.ts` now exports the shared package surface.
- Required 192px and 512px owned PWA icon files already exist.
- Pull-request CI now covers builds, service integration, security scans, and image scans.
- The root `verify` task now runs API checks, frontend contract tests, and all builds.
- Node, npm, Python runtime, and development dependency inputs are pinned.
- `.editorconfig` is present.

## Change log

### Notification release blocker

- Added deterministic regression coverage for Telegram confirmation success, missing setup, invalid/expired/replayed codes, throttling, unavailable delivery, and Web Push availability.
- Removed the undefined-variable crash from Telegram confirmation.
- Moved the VAPID availability guard to the basic push preference endpoint. Enabling unavailable push now returns stable code `push_unavailable`; disabling remains allowed.
- Isolated the reasoning-service test module so its local dependency stubs cannot leak into later tests.

This focused fix was committed before enabling the repository-wide lint gate because the confirmed undefined name would otherwise make the new CI workflow red by construction.

### Phase 0: deterministic tooling and release gates

- Pinned Node.js 22.23.0, npm 10.9.8, Python image 3.12.13, TimescaleDB 2.28.3 on PostgreSQL 16, Redis 7.4, Nginx 1.30.4, and the backup image build.
- Kept one authoritative root npm lockfile and removed two stale nested locks.
- Added a separate Python development dependency file, root verification commands, `.editorconfig`, `.nvmrc`, and explicit shared UI exports.
- Split desktop renderer and Node TypeScript projects and corrected strict renderer type errors.
- Corrected admin TypeScript emit settings and made the admin image use the root lock with workspace-scoped `npm ci`.
- Kept the Iranian registry order Liara, Chabokan, then the public npm registry in web/admin image builds.
- Resized the owned 1024px logo deterministically into true 192px and 512px PWA icons without changing the artwork.
- Added pull-request CI for clean installs, all application builds, Python compile/lint/tests, TimescaleDB and Redis smoke checks, migration checksum/current-state checks, both Compose configurations, four image builds, secret scans, dependency scans, and image scans.
- Added a reviewed, narrow, expiring exception policy for security scan findings. No exception is currently approved.
- Removed dead Python imports exposed by the new lint gate without changing runtime behavior.

### Phase 1: notification channel correctness

- Added a backward-compatible Telegram bot deep-link handshake behind `TELEGRAM_DEEPLINK_ENABLED`.
- The authenticated API creates a 48-character signed, short-lived start token, stores only its SHA-256 digest, and invalidates older pending tokens for the user.
- The webhook requires Telegram's secret-token header, accepts only a private positive numeric chat, verifies the token signature, locks and consumes the challenge once, and persists the verified numeric chat ID.
- Disabling Telegram invalidates every pending deep-link challenge for that user. Existing verified numeric IDs and the legacy username/code flow remain valid.
- Added a compatible `telegram_deeplink_available` preference field so clients never claim the new flow is ready when operator configuration is incomplete.
- Web and desktop settings display the bot link, poll the existing preference endpoint until verification or expiry, and preserve the current theme and legacy fallback.
- Desktop external navigation goes through a narrow IPC operation that accepts only exact `https://t.me/<bot>?start=<48-char-token>` links.
- Documented the bot username, feature flag, bounded link lifetime, signing secret, and independent webhook secret in `.env.example`.

## Migrations

- Added forward-only `20260802_001_alert_price_source_mode.sql`. Existing alert rows receive `ordinary`; the migration uses `ADD COLUMN IF NOT EXISTS`, restores the default and non-null invariant, and adds a bounded mode check without rewriting alert behavior.
- Normalized provider source semantics and provenance use the existing `provider_quotes.metadata` JSONB field. A separate provider-quote column migration is intentionally deferred because no indexed/queryable column is required in this phase; adding duplicate columns would create schema drift without runtime benefit.

### Phase 2: pricing semantics and alert eligibility

- Added explicit, frozen-clock freshness boundaries for cache retention, live eligibility, stale display and expiry. Future timestamps retain their source time within a bounded skew and cannot extend the live window.
- Added normalized source semantic, family, venue, selected-price, original-value, conversion, route, spread and provenance fields while deriving legacy `source_type` and `is_direct` compatibility fields.
- Made source-family independence, successful source persistence and provider-bounded live eligibility mandatory for canonical selection. Duplicate endpoints from one venue do not add consensus weight, and robust median selection requires a tight majority inlier cluster.
- Added live-cache-first traversal, two-source bounded fallback attempts, ranked external attempts, skip traces and bounded `Retry-After` handling without sleeps. Queued or failed source writes stay unavailable for live selection.
- Corrected the Silver 925 fineness conversion, bounded derivation depth, rejected cycles, decayed confidence, retained complete input provenance and capped each derived live window at its weakest input.
- Added explicit alert price source modes: `ordinary` remains the default for existing alerts; `reference` and `derived` require user opt-in. Queued snapshots and notification text include the selected status and source semantic.
- Added per-input status, source semantic and source summary context to formula-alert snapshots, text and push payloads.

## Verification log

### Phase 0 local verification

| Command | Outcome |
| --- | --- |
| `npm.cmd install --package-lock-only --ignore-scripts --no-audit --no-fund` | Passed; root lockfile up to date. |
| `npm.cmd ci --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/` | Passed from a cleared workspace: 688 packages installed in 7 minutes. The explicit final fallback was needed because a host-global legacy mirror reset connections; repository files contain no reference to that mirror. |
| `npm.cmd ls --package-lock-only --depth=0` | Passed. |
| `npm.cmd run build:web` | Passed; 3,979 modules transformed and PWA service worker generated. |
| `npm.cmd run build:admin` | Passed. |
| `npm.cmd run build:desktop` | Passed; 4,611 modules transformed. |
| `python -m compileall -q apps/api/app apps/api/tests apps/api/scripts` | Passed. |
| `python -m pyflakes app tests scripts` from `apps/api` | Passed after the confirmed notification crash fix and dead-import cleanup. |
| `python -m unittest discover -s tests -v` before deep-link test implementation | Passed: 25 tests. |
| `npm.cmd run verify` after the first notification, deep-link, and Phase 2 slices | Passed: compile, pyflakes, 51 tests, web build, admin build, and desktop build. |
| `python -m unittest apps.api.tests.test_telegram_deeplink apps.api.tests.test_notifications` | Passed: 20 tests, including availability, one-use, expiry, tamper, replay, disable, and legacy compatibility cases. |
| `python -m unittest discover -s tests -v` from `apps/api` after Phase 2 self-correction | Passed: 116 tests; one PostgreSQL concurrency test skipped because `TEST_DATABASE_URL` is not set. No external provider calls were made. |
| `python -m compileall app` and `python -m pyflakes app tests scripts` from `apps/api` after Phase 2 self-correction | Passed. |
| `node --check apps/desktop/electron/main.cjs` and `node --check apps/desktop/electron/preload.js` | Passed. |
| `npm.cmd run build:web` after deep-link UI wiring | Passed; 3,979 modules transformed and PWA service worker generated. |
| `npm.cmd run build:desktop` after deep-link UI and IPC wiring | Passed; 4,611 modules transformed. |
| YAML parse of CI and both Compose files | Passed. |
| PWA dimension check | Passed: `icon-192.png` is 192x192 and `icon-512.png` is 512x512. |
| `git diff --check` | Passed; only host line-ending notices were printed. |

### Final local verification, 2026-08-09

| Command | Outcome |
| --- | --- |
| `npm.cmd run verify` | Passed: API compile and lint, 144 API tests, 4 frontend contract tests, and web, admin, and desktop production builds. One PostgreSQL concurrency test was skipped because `TEST_DATABASE_URL` is not set locally. |
| `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-operator-gates.ps1` | Passed with generated fresh production-shaped evidence. |
| `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-operator-gates.ps1 -EvidencePath docs/operator-gates.evidence.example.json` | Failed as required; the pending example cannot satisfy a production gate. |
| CI workflow YAML parse | Passed. |

The PostgreSQL race test now runs against the CI PostgreSQL service. Production provider canaries, restore proof, deployment health, and authenticated browser smoke proof remain operator gates and are not represented as local success.

Docker is absent on this host. CI defines, but local work does not claim, image builds, Compose evaluation, service integration, or vulnerability scan results.

## Feature flags and rollback

- Telegram deep-link verification defaults off. Roll back by setting `TELEGRAM_DEEPLINK_ENABLED=false`; verified numeric chat IDs and the legacy flow remain available.
- New source chains and policy changes will remain disabled or in shadow mode until promoted.

## Remaining risks and intentionally deferred work

- Docker image, Compose, PostgreSQL/Timescale, Redis, browser, and live process verification require a host with Docker.
- No external provider will be called by automated tests.
- The host-global npm configuration points at an unreliable legacy mirror. Repository and image install paths do not reference it; local verification used the documented public registry only as the final fallback.
