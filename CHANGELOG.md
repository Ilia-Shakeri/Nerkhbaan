# Changelog

All notable Nerkhbaan changes live here. Version numbers use Semantic Versioning.

## [2.2.1] - 2026-09-13

### Fixed

- Provider source history now binds an optional provider filter with an explicit
  PostgreSQL type, so unfiltered source-history requests work on an empty real
  database instead of returning HTTP 503.

## [2.2.0] - 2026-09-13

### Added

- A 14-stage HTTP integration smoke against real PostgreSQL and Redis in CI.
- Route proof for anonymous authentication boundaries, duplicate signup,
  session listing, invalid alert delivery, legacy and instrument history,
  authenticated source history, unknown resources, and refresh-token reuse.

### Changed

- Project status and roadmap now separate the 2026-08-20 audit baseline from
  completed integration, browser, observability, replica, and production work.
- The release-version gate now verifies every workspace entry in the lockfile,
  preventing a package manifest and lockfile version drift.

## [2.1.1] - 2026-09-12

### Fixed

- PersianToolbox payloads inside the provider's documented five-minute cache
  window are accepted without replacing their original source timestamp.
- A documented cached response receives only the instrument's normal short live
  window from receipt. Payloads older than the explicit provider limit remain
  rejected, and the original observation time remains visible and persisted.
- The freshness test module now supplies its own isolated test secret instead
  of depending on suite execution order.

## [2.1.0] - 2026-09-12

### Added

- A no-key PersianToolbox BTC/USD fallback with strict timestamp, freshness,
  source, symbol, and unit validation.
- Authenticated Servix history backfill for BTC/USD, USDT/USD, and USD/Toman,
  including strict symbol/unit parsing and header-only key transport.
- A Servix USDT/USD fallback route, disabled until an operator supplies a key,
  enables attribution, and turns on the route.
- A disabled PersianToolbox USD/IRR reference route for later operator review;
  it is not treated as a free-market USD/Toman quote.
- A production clock-synchronization runbook using reachable Iranian NTP
  sources and a no-change query gate before any clock correction.

### Changed

- Servix documentation now records its permanent 50-request daily free tier.
- Servix route budgets share at most 48 daily calls across the three registered
  instruments, leaving quota room for operator checks.
- Release metadata is consistent across every package after the 2.0.10 API-only
  version drift.

## [2.0.10] - 2026-09-12

### Added

- Authenticated external price-worker ingress for BTC/USD and USDT/USD, including HMAC request verification and Redis replay protection.
- A systemd worker package that imports one year of free CoinGecko history once and posts live crypto updates every minute.
- An operator runbook for installation, secret rotation, migration to a replacement VPS, verification, and rollback.

## [2.0.9] - 2026-09-12

### Added

- CoinGecko free historical market-chart routes for BTC/USD and USDT/USD backfill.

## [2.0.8] - 2026-09-12

### Fixed

- Backfill jobs now defer once when a live quote is unavailable instead of retrying the same history work until the queue fills.

## [2.0.7] - 2026-09-12

### Fixed

- Canonical reads now accept negative percentage changes, so valid falling-market rows no longer disappear from aggregate prices or flood error logs.
- History requests for instruments with no enabled history route no longer create deferred backfill jobs.

## [2.0.6] - 2026-09-11

### Fixed

- Quarantined three live-proven broken fallback routes so they no longer spend refresh budget or create repeated failures.
- Registry safety defaults now remain effective when an older operational database row still says a provider is enabled.

## [2.0.5] - 2026-09-11

### Fixed

- A reachable fallback provider now uses its bounded normal provider budget instead of stopping after the small reserved fallback allowance.

## [2.0.4] - 2026-09-11

### Fixed

- An expired canonical quote no longer marks a fresh provider quote as suspicious only because the old market level differs.

## [2.0.3] - 2026-09-11

### Fixed

- Empty price charts no longer render a made-up point from the current quote.
- Chart loading, no-history, and request-failure states now explain the state and provide a retry action.

## [2.0.2] - 2026-09-11

### Fixed

- Frontend image builds now use the locked local npm cache when every configured registry is unavailable.

## [2.0.1] - 2026-09-11

### Fixed

- A malformed canonical-history row no longer removes valid prices from the aggregate API response.
- Price refresh health now reports `healthy`, `degraded`, or `failed` with safe result counts.

### Added

- Storage-read failure metric for canonical aggregate reads.

## [2.0.0] - 2026-09-11

### Added

- One release version for API, web, admin, desktop, and shared UI packages.
- Release version in public health responses for safe deployment checks.
- Automated release-version consistency check.

### Changed

- Set the first tracked project release to `2.0.0`.

## Version policy

- Patch: bug fix with no public API break (`2.0.1`).
- Minor: backward-compatible feature (`2.1.0`).
- Major: breaking public API or product contract (`3.0.0`).
- Every release changes `VERSION`, package manifests, API release module, this file, and release documentation in the same commit.
