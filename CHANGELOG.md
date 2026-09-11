# Changelog

All notable Nerkhbaan changes live here. Version numbers use Semantic Versioning.

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
