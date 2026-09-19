# Changelog

All notable Nerkhbaan changes live here. Version numbers use Semantic Versioning.

## [2.6.0] - 2026-09-19

### Added

- Public bilingual privacy, terms, cookies, refund and business-detail draft pages.
- Explicit, server-validated registration, support and external chat processing
  permissions with policy-version receipts. No marketing permission is bundled.
- Legal/accessibility risk register and asset provenance inventory.

### Changed

- Display name optional at signup; username used when omitted. No identity document collection.
- Preferences written on user choice, not first render; storage failures tolerated.
- Removed automatic third-party chart script; an explicit external link remains,
  while the first-party dashboard charts stay available.
- Restored chart-library attribution, strengthened focus/placeholder contrast,
  labelled reply fields and busy buttons, corrected password guidance and chat retention copy.
- Login card flip preserved. Removed unsupported blanket privacy/security promises.

### Release gate

- Local candidate only. Do not deploy these draft legal terms until operator
  identity, contact, jurisdiction, processor details and retention are approved.
- Required request fields change signup/support/chat contracts; release clients
  and API together. Old clients receive validation errors, not assumed consent.
- Tests and remaining evidence: `docs/legal-readiness-2026-09-19.md`.

## [2.5.1] - 2026-09-19

### Fixed

- Pre-deployment container canaries found Wallex markets and Nobitex aggregate
  order books exceed 256 KiB (about 461/450 KiB). Their per-provider ceilings
  are now 1 MiB, still bounded by the global ceiling. Added a regression test.
- Canary output explicitly identifies payload-size failures. Stale Bitpin
  exchange timestamps continue to be rejected, not freshened at receipt.

### Validation

- 2.5.0 was tagged and built but not promoted to the live services; 2.5.1 is
  the corrected deployment candidate.

## [2.5.0] - 2026-09-19

### Added

- Public Bitpin BTC/Toman and USDT/Toman fallbacks with exact symbol, exchange
  timestamp, bounded response size and rate budgets.
- Public Wallgold 18K gold and 925 silver quotes, each using its own market
  field. No key required. Receipt time is explicitly labelled because the
  market response does not provide quote timestamps.
- Read-only public-provider canary script and provider research report.

### Fixed

- Removed all Iranian gold karat and ounce-derived formulas. Separate 18K/24K
  instruments cannot be re-enabled for derivation by old database settings.
- Excluded old calculated and ambiguous-purity gold from current snapshots,
  health, chart buckets and change baselines without deleting historical data.
- Disabled the ambiguous PersianToolbox gold route even if an old environment
  flag enables it; the payload has no karat contract. BTC remains available.
- Enabled verified Wallex fallbacks; changed Nobitex's default to its working
  alternate host, including history requests.
- Corrected Nobitex IRT order-book levels from Rial to Toman, including bid/ask.

### Limits

- No healthy keyless direct Iranian 24K endpoint was verified. Missing prices
  stay unavailable; neither 18K nor international gold fills that gap.
- Existing typed Telegram source pipeline remains intact for later onboarding.
- Public endpoint access is not a redistribution-rights signoff. Formal launch
  evidence remains pending; the user authorized a limited deployment with
  backup and health checks, not fabricated gate approvals.

## [2.4.10] - 2026-09-15

### Fixed

- Overrode the database-backup image's five-minute health interval with a
  30-second production check. The backup service can now become healthy inside
  the deployment command's four-minute wait window.

### Tests

- Added a contract that keeps backup health cadence below the deployment wait
  deadline.

## [2.4.9] - 2026-09-15

### Fixed

- Declared the motion runtime in the shared interface package. Clean web image
  builds no longer depend on a package installed only by another workspace.

### Tests

- Added clean production-image build verification after the local release gate.

## [2.4.8] - 2026-09-15

### Fixed

- Added keyboard focus containment, Escape handling, outside-click dismissal,
  focus restoration, and scroll-safe sizing to shared dialogs.
- Replaced misleading empty states with explicit loading, unavailable, error,
  and retry states across chart analysis, alerts, reports, and support.
- Removed unsupported contact details and the non-working support attachment
  control so every visible action now has a real outcome.
- Prevented overlapping password controls, duplicate toast systems, settings
  save races, and optimistic-setting drift after a failed request.
- Made the mobile navigation drawer contain focus and restore it to the menu
  button when closed.

### Changed

- Increased small interaction targets, added clear control names and state, and
  improved forms for keyboard, screen-reader, password-manager, and mobile use.
- Shortened and damped interface springs, limited transitions to the properties
  that change, and retained the existing authentication card rotation.
- Improved dynamic viewport and safe-area behavior in application shells,
  dialogs, authentication-adjacent errors, and admin screens.

### Performance

- Split protected screens into route-level chunks, reducing the main web entry
  bundle from 692.63 kB to 180.57 kB before compression.
- Removed an unused per-instrument price-history request and expensive blur,
  floating, and persistent animation hints from repeated interface elements.
- Removed duplicate animation and toast dependencies from workspace manifests.
- Limited frontend compiler globals to browser build types so optional desktop
  packaging stubs cannot break web or admin type checks.

### Tests

- Added contracts for shared-dialog focus behavior, mobile navigation focus,
  lazy protected routes, chart request discipline, honest contact actions, and
  working support controls.

## [2.4.7] - 2026-09-14

### Fixed

- Removed fixed market values that were presented as live on the startup screen.
- Made authentication scroll safely on short mobile screens and respect device
  safe areas without changing the normal sign-in/sign-up card rotation.
- Removed duplicate password reveal controls and localized their accessible
  labels across authentication and password-reset flows.
- Added inline, focusable authentication errors with safer localized network
  messages and corrected the recovery-flow description.
- Added reduced-motion, reduced-transparency, and increased-contrast behavior.
- Added accessible chart summaries and recent-point tables, keyboard chart-card
  reordering, named icon controls, and explicit toggle/menu state.
- Made admin navigation history-aware and prevented unauthorized hash sections.
- Trapped focus inside dangerous admin confirmations, added Escape handling,
  and restored focus when a dialog closes.

### Changed

- Reduced non-essential startup motion and removed fake chart decoration.
- Increased small operational text and reduced floating button movement.
- Reduced chart height on small screens while retaining the desktop data view.

### Tests

- Added frontend contracts for honest startup data, mobile authentication,
  password controls, motion preferences, chart alternatives, admin history,
  and dangerous-dialog focus behavior.

## [2.4.6] - 2026-09-13

### Fixed

- Git feed pulls now allow up to 60 seconds before forced termination. The
  deadline still bounds blocked routes while tolerating observed Iran-to-GitHub
  latency above 30 seconds.

## [2.4.5] - 2026-09-13

### Fixed

- Relayed market quotes now start a bounded live window when the Iran API
  receives them, while preserving the upstream observation timestamp.
- BTC/USD and USDT/USD freshness windows now cover the five-minute public-feed
  cadence; faster direct providers retain their own shorter provider windows.
- Both the pull service and API reject live relay quotes older than ten minutes.
  This prevents delayed feeds from appearing current.
- Silver derivation can remain live between scheduled feed updates instead of
  losing its USDT/USD input after 30 seconds.

## [2.4.4] - 2026-09-13

### Fixed

- Git feed pulls now have a hard 30-second deadline and an explicit startup
  log, preventing a blocked Git route from hanging the sidecar forever.
- The pull sidecar now uses the verified Shecan resolvers, avoiding a blocked
  GitHub address returned by the default Docker resolver on the Iran host.

## [2.4.3] - 2026-09-13

### Fixed

- Relay records now use a bounded parser version that fits the production
  schema. The longer upstream parser version remains available in metadata.

## [2.4.2] - 2026-09-13

### Fixed

- The internal pull service now sends the trusted public Host while connecting
  over the private Compose network, so the API host guard accepts signed feed
  ingestion without adding an internal hostname to the public allowlist.

## [2.4.1] - 2026-09-13

### Fixed

- Changes to the feed workflow or builder on `main` now publish an immediate
  initial feed instead of waiting for the first scheduled run.

## [2.4.0] - 2026-09-13

### Added

- A scheduled public price feed for XAG/USD, BTC/USD, and USDT/USD using free,
  validated upstream routes outside Iran.
- A locked-down pull service that reads only the single-commit `price-feed`
  branch through reachable Git smart HTTP, validates the feed again, signs it,
  and sends it only to the internal pricing endpoint.
- Exact worker allowlists and safe ranges for the silver route.
- Server-side rejection of stale, future-dated, and unsupported historical
  relay quotes, plus bounded upstream response reads.

### Changed

- The production stack can run the pull service without exposing database,
  Redis, user, or admin access.
- External price-worker documentation now covers both the preferred Git pull
  route and foreign-VPS replacement steps.

## [2.3.3] - 2026-09-13

### Fixed

- Derived prices now inherit the weakest vetted input's live boundary directly.
  Old raw source timestamps no longer shorten a safe derived gold window twice.

## [2.3.2] - 2026-09-13

### Fixed

- Gold 24K and derived 18K freshness now match the Iranian source's five-minute
  cache interval. Cards no longer spend most of each provider cycle stale.

## [2.3.1] - 2026-09-13

### Fixed

- Receive-anchored cached sources now keep the same live, stale, and expiry
  windows after canonical selection. Gold no longer becomes stale as soon as a
  valid five-minute provider payload is accepted.

## [2.3.0] - 2026-09-13

### Added

- A no-key PersianToolbox 24K gold reference route in IRR per gram.
- Strict checks for unit, freshness, time, source list, and positive value.
- A five-minute call interval matching the documented provider cache.

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
