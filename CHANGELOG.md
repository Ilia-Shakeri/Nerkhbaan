# Changelog

All notable Nerkhbaan changes live here. Version numbers use Semantic Versioning.

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
