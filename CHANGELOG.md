# Changelog

All notable Nerkhbaan changes live here. Version numbers use Semantic Versioning.

## [Unreleased]

## [2.8.15] - 2026-10-28

- Deployed and accepted the exact source with all 15 source jobs, four strict-scanned runtime images, preserved ten-migration ledger, live native/reference rates, account flows and browser asset checks. Preserve the initial failed HTTPS receipt and the separately reviewed successful continuation. [Release and off-VPS backup evidence](docs/pricing-release-2.8.15-fa.md).
- Revalidate the USD last-change reference within its existing 60-second receipt window and 180-second source-age cap; do not rewrite its source timestamp or renew it from a cache read.

- Separate explicitly scoped same-instrument quality validation from permission to publish derived valuations. Keep source clocks, anomaly thresholds, independent verification, revocation and full derivation gates intact. Reject cross-instrument comparisons under a quality-only grant.
- Bind quality checks to current source evidence and expiry in the rights manifest, at both calculation and SQL decision storage. Hide calculated diagnostics after revocation; do not grant resale, relay or external processing.
- Retain the failed 2.8.14 real-source canary: seven routes refreshed, USD did not; native updates were blocked by the broader derivation-only comparison check. No 2.8.14 application deployment occurred.

## [2.8.14] - 2026-10-28

- Isolate slow pricing refreshes with one owned task per instrument and a bounded cycle wait. Preserve distributed leases, source budgets, source clocks and alert eligibility; cancel and await owned tasks on shutdown or Redis loss.
- Keep price refresh start cadence between six and ten seconds at the default interval, including cycle work, so a slow source cannot consume another instrument's entire twenty-second live window.
- Read the documented Nobitex multi-market book for USDT, selecting only its own timestamp and Rial-valued levels. Preserve strict freshness, payload bounds and attribution.
- Classify non-JSON HTTP error pages by their actual status. Honour HTML 429 cooldowns, retry bounded 503 responses, and reject HTML 200 responses as invalid data.
- Preserve an off-host full database snapshot and verify an isolated Timescale restore. Application deployment and live-rate acceptance need their own final evidence; see the dated pricing repair record.

## [2.8.13] - 2026-10-24

- Deployed the exact tagged application with ten migrations and 17 protected identities retained. Guard-only recovery binds the original failed retirement receipts and uses concurrent strict pair probes inside the unchanged 30-second deadline; migrations are not rerun. See [the final administrator release record](docs/admin-release-2.8.13-fa.md).

- Add administrator-managed Kavenegar SMS and Asterisk ARI connections with a separate encryption key, write-only credentials, independent configuration versions, permission checks, CSRF, recent re-authentication and typed confirmations.
- Add critical-call policy, quiet hours, cooldowns, daily caps, consented test recipients, dry-run previews and paged masked history. Real sending remains disabled until a configured provider and an explicit test confirmation exist. Provider acceptance is not device receipt or an answered call.
- Connect SMS phone verification and critical VoIP alerts to the durable worker. Recheck consent, current settings, source rights, fresh prices and persistent conditions at dispatch. Paid unknown outcomes are not retried automatically. Complete mixed paid/nonpaid alert aggregates in either completion order.
- Improve all fifteen administrator routes, role-limited reads, MFA failure handling, mobile navigation and sensitive-form duplicate/uncertain-result protection. Preserve configuration drafts when paginating history and discard stale responses.
- Add an explicit fail-closed nine-to-ten migration plan with isolated restore, exact schema/data preservation and old/new image compatibility evidence. Existing recovery plans cannot authorize this transition.
- Document SMS/PBX setup inside the console and in the Persian administrator guide. Email alarms are outside the current scope; authentication mail remains supported. Final source, hosted runtime and target receipts must identify this exact release.
- Replace the vulnerable certifi trust bundle with hash-verified 2026.10.23 and build/test the feed with Go 1.26.10, which includes the crypto/x509 security correction. Preserve failed candidate CI 39594722700; do not suppress its findings or reuse its images.
- Update the four Nginx recipes to 1.30.6 and Vite to the compatible 6.4.4 security patch. Keep failed CI 40023578757 as failed evidence; all security scans remain mandatory and include unfixed HIGH/CRITICAL findings. Protected ingress services require their own scoped rollout and are not recreated by the application wrapper.

## [2.8.12] - 2026-10-19

- Add session-only Windows notices with explicit main-window consent, bounded generic text, current-account and source-rights leases, strict IPC records and a fixed inbox action. Keep unpackaged builds disabled; real installed-device and signing acceptance remain pending.
- Revoke notices on logout, account or rights changes, expired leases, navigation and window teardown. Share one price connection across views and notices. Accept unseen lower notice IDs that commit after newer IDs without replaying baseline inbox rows.
- Serialize email challenge issuance, confirmation and disablement under the same user lock. Invalidate older challenges and commit preferences with consumption; keep failed sends from reviving old codes.
- Keep transient push targets retryable when another target has expired; permanent failure requires all targets to be gone. Continue fanout after bounded transport failures and retain any successful target without retrying that successful job.
- Freeze the durable-history fixture permission clock alongside its backfill clock. Keep expired and future grants blocked; retain the first failed hosted run without extending any production permission.
- October 19 notification checks passed 114 real-PostgreSQL backend cases, 44 focused local backend cases, 117 frontend cases, 24 affected mocked browser cases and three renderer builds. Suites overlap. Actual SMTP receipt, installed Windows notice delivery and publisher signing remain separate.

## [2.8.11] - 2026-10-18

- Align the generated API route index with the release and include its exact header in the release consistency gate. Preserve both failed candidate tags and their hosted receipts; publish the final tag only after all hosted checks pass.
- Keep the bounded current-price read, full source permissions and cache fallback unchanged. Candidate 2.8.10 passed backend unit tests but failed the subsequent generated-document check.

## [2.8.10] - 2026-10-18

- Update the existing latest-price parameter test for the explicitly typed instrument definition and correlated ordered scan. Keep the parameter, source restrictions and no-untyped-null checks.
- Preserve tag 2.8.9 and its failed hosted unit-test receipt. Real PostgreSQL permissions and budget tests passed, but the legacy SQL-text assertion failed. This corrective release needs its own full source checks, canonical runtime images and live acceptance.

## [2.8.9] - 2026-10-18

- Bound current-quote database reads in a read-only transaction. Preserve stricter database timeouts, keep settings local to the read, and let verified Redis snapshots serve through the existing failure path when the database exceeds its budget.
- Read necessary root-source candidates in newest-first order before the unchanged full recursive permission checks. Historical, retired, daily-only and calculated-gold restrictions remain in force before current-row selection; older eligible observations retain their original clocks.
- Passed 21 isolated real-PostgreSQL cases for local budgets, lock and query cancellation, permission equivalence, purity, older eligible rows, pool reset and permitted-cache fallback. A separate read-only target preview returned 11 instrument contracts in 2.014409 seconds through the existing cache path after its database read exceeded the budget; candidate HTTP acceptance remains separate.
- Retain the failed 2.8.8 postdeployment inventory timeouts as failures. The corrective release requires its own source, hosted checks, runtime images and live acceptance.

- [Deployment guard]: Hash the fully resolved Compose model through private stdin. Add an explicit evidence-bound resume for the interrupted 2.8.8 rollout; retain the original failed receipt, application tag and runtime images, and verify the existing ninth migration without running it again.

## [2.8.8] - 2026-10-18

- Added three separately named Iranian reference contracts after approval of published/calculated values: the publisher's 24K gram reference and same-source BTC/Toman or USDT/Toman divided by USD/Toman. Gold purity stays unconfirmed; the ratios do not claim global exchange prices or stablecoin peg measurements.
- Preserved source last-change time, original receipt, parent prices, daily Jalali dates and missing days. Delayed references are visibly marked and become unavailable after 24 hours; ordinary quote and alert age limits remain unchanged.
- Added a separate durable reference table through the ninth forward migration. Bounded, idempotent imports cannot replace newer observations with older clocks. Collection, storage, display, history and calculation permissions are checked independently.
- Added a read-only reference API and dashboard panel with source credit, day-precision history, rights-revision protection and durable-history recovery. Existing native contracts and archived prices retain their identities.
- Corrected Nerkhsanj's documented clock label to last rate change. Fresh HTTP headers do not refresh old source values. Actual upstream update latency remains an operational limitation, with dated receipts retained separately from test fixtures.
- Added a guarded, evidence-bound deployment plan for the pinned ninth migration. Old replicas keep serving during the explicitly checked migration-only readiness transition; replacement health and final HTTPS readiness remain strict. This path requires an actual restore and old/new image compatibility proof before any live mutation.
- Final local API discovery passed 1,021 tests with zero skips on owned PostgreSQL/Redis plus unit, SQLite and mocked cases. Frontend contracts passed 79, six focused mocked browser cases passed, and all three renderer builds passed. Each real PostgreSQL/Timescale reference suite passed 46 cases. These suites overlap; hosted and live acceptance have separate final-commit receipts.

## [2.8.7] - 2026-10-17

- Retired Servix from active collection, key requirements and operational overrides. Kept old records and permitted historical output; retired quotes cannot mask current prices.
- Added attributed Iranian Nerkhsanj current and daily/intraday routes, GTA Silver 925 quotes, and Wallgold published 18K/925 quotes plus hourly/daily 925 archives. Registration covers eight instruments; complete fresh operational coverage remains unproved. No 24K purity substitution, USDT peg or manufactured currency cross was introduced.
- Shared bounded Nerkhsanj HTTP snapshots across replicas with one request per URL per minute and the original receive clock. Budget pressure defers history work without consuming error attempts. Remote quote expiry never extends instrument freshness.
- Kept UTC/Gregorian and Tehran/Jalali daily metadata separate through real database aggregation, API responses and charts. Publication clocks remain distinct from unknown trade times and stay attached to the selected currency.
- Added an explicit market/reference choice to both alert forms. Ordinary alerts keep their default eligibility; edits retain the saved mode instead of silently changing the price basis.
- Hardened Nobitex single-market order books and closed hourly candles; protected source units, OHLC consistency and pagination fixtures. The historical endpoint still returns 403 from the target, so its routes stay disabled while permitted Nerkhsanj archives remain available.
- Includes the post-2.8.6 daily silver archive and owned-database fixture corrections. Existing release tags stay immutable. Final source checks and operational limits are recorded in the Iranian replacement report; live rollout and step-three receipt remain pending.
- Local validation passed 937 backend cases with zero skips, 78 frontend contracts, ten focused mocked browser cases and three renderer builds. Real PostgreSQL/Timescale history and UUID-isolated Redis concurrency checks passed; the latter now run in hosted integration. Failed earlier fixtures remain retained separately. Final-commit hosted checks and target acceptance keep their own evidence.

## [2.8.6] - 2026-10-17

### Fixed

- Enforced reviewed provider permissions at collection, persistence/replay, cache reads/writes, history aggregation, administrator output, notification dispatch and WebSocket delivery. Historical evidence remains stored; missing or revoked permission withholds its outputs. Derived quotes require bounded, complete parent provenance, including candidate and previous dependencies.
- Cleared browser price, chart, analysis and notification state when source permissions change; delayed responses and unacknowledged WebSocket revisions cannot restore withdrawn data. Show credits for actual current and historical sources.
- Added a strict independent Gold API BTC/USD parser and disabled Servix BTC/Toman and USDT/Toman price/history routes, preserving source times and Rial conversion. No USDT dollar peg or physical silver history is invented.
- Replaced restricted standalone producer paths with reviewed own-application sources. Public redistribution and external analysis are separate permissions. Production deployment refuses disabled rights enforcement.

### Acceptance

- Local final-source validation passed 673 backend cases with zero skips using owned PostgreSQL/Redis plus unit, SQLite and mocked cases; 72 frontend cases, 28 standalone channel-worker cases, three renderer builds and 11 Go cases also passed. A real local proxy fixture passed eight permission/TLS-routing checks. Initial failed adapter-fixture receipts remain separate. Hosted checks, target canaries and actual notification receipt are distinct acceptance gates.
- Version 2.8.5 and its published tag remain immutable. This corrective release requires separate final-commit hosted checks and target evidence. The target remains 2.8.1 until the chosen full replacement scope passes; source rights, account quota, network reachability and fresh data are independent gates.

## [2.8.5] - 2026-10-17

### Fixed

- Made deployment mount identity independent of Docker inspection array order while retaining every mount field and strict rejection of actual mount/configuration changes. Read-only target inspection reproduced the false difference. Required operator evidence and every other deployment gate remain intact.
- Preserved release 2.8.4 and its successful 15-job hosted run; this corrective release needs its own final-commit validation and target evidence.

## [2.8.4] - 2026-10-17

### Changed

- Added keyless Iranian Wallex hourly history for USDT/Toman and BTC/Toman, with bounded seven-day requests, closed-candle checks, preserved gaps and complete-range validation before persistence. Stored samples are hourly closing observations, not original OHLC bars. Internal boundaries preserve candles for ranges starting between hours.
- Added four disabled Servix price/daily-history routes for gold/silver ounces and 18K/24K grams. Exact weight/purity declarations and a key are required; registration does not establish verified coverage. The seven catalogue budgets total 42 requests/day before operator overrides; effective account budgets still require review.
- Corrected TALA price endpoints and explicit symbol, status, unit and timezone validation. Required confirmed RIAL/TOMAN units and Unix source time for Navasan. Source contracts and parser provenance reflect these requirements.
- Added a read-only key/contract plan that reveals credential presence only, reports runtime budgets as unknown and identifies the two uncovered physical-silver history instruments. No new provider was activated and no live server was changed. See the step-two source report for actual public-response evidence, test scope and remaining keys.

### Validation

- All 518 backend tests passed with zero skips, including owned PostgreSQL 17.11/Redis 7.4.11 cases and unit, SQLite/mocked fixtures. Static name/import checks passed. A separate replay of two captured actual public Wallex responses preserved and read back 24 hourly closing observations per pair in owned PostgreSQL. No authenticated provider response, full source archive or live deployment is claimed.

## [2.8.3] - 2026-10-17

### Changed

- Started step two with strict Servix current-price contract handling: explicit quote currency and source time, official array/single-object shapes, duplicate-symbol rejection and matching parser provenance. Fourteen contract cases and the complete local 464-case backend suite pass with zero skips. These fixtures do not prove authenticated prices, source rights or operational coverage; provider activation is unchanged.
- Recorded the October 16 Iranian-source canaries and current documentation, including separate direct-gold/cash-dollar and history acceptance gates.

## [2.8.2] - 2026-10-16

### Fixed

- Revoked an entire user refresh family under the owner lock when an administrator closes any rotated member. Unified normal and crash-recovery logout, preserved incomplete logout across reloads and tabs, serialized credential operations and retained encrypted native revocation credentials until a successful retry.
- Charged every managed provider attempt against its shared budget, applied public quote visibility and current instrument policy to health, rejected currency relabeling and forwarded fresh version-two feed siblings after dropping expired quotes. Version-one feeds and invalid routes remain strict.
- Stored immutable alert conditions, destinations and occurrence times. Kept current account/channel consent checks, withdrew delivery consent on deletion, safely handled legacy records, serialized the active-alert cap and completed multi-channel occurrences under a shared event lock, including administrator cancellation.
- Replaced lossy persistence-stream trimming with atomic capacity checks. Quarantined malformed records with every original byte retained in PostgreSQL before atomic acknowledgement/removal; transient database failures keep the original queued record.
- Shared SMTP transport across account and alert mail, including verified implicit TLS on port 465. Rejected malformed worker headers before hashing and retained replay claims for the full accepted timestamp window. Bounded conversation replies/history to 4000 characters and continued fallback after invalid provider response types.
- Restored notification bodies and collapsed-navigation names. Added explicit support errors, retry and refresh with stale-response guards, plus bounded/cancellable admin reads without automatically retrying writes.
- Replaced unscoped production recreation with reviewed application-only overlap, exact image/container/config/network checks, a private environment binding, strict HTTPS readiness and a pre-write schema compatibility gate. Existing data, monitoring and shared-ingress containers are protected.

### Validation

- 450 backend tests passed with zero skips, including owned PostgreSQL 17.11 and Redis 7.4.11 cases; the suite also contains unit, SQLite and mocked checks.
- 65 frontend tests, 26 Edge cases, 10 Go feed checks, 14 deployment CLI fixtures and 31 infrastructure/helper checks passed. Browser coverage includes one real disposable HTTP/PostgreSQL flow and 25 mocked HTTP flows. The deployment checks use fake containers and HTTPS responses.
- Web, admin and desktop renderer builds passed. Applied SQL and dependency versions remain unchanged. New real alert/queue regression modules are included in hosted integration configuration.
- Hosted [run 38972610806](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38972610806) passed all 15 jobs at release commit `1af7521a2c1c6edf4a41c9db293ad7c021ee8587`, tagged `v2.8.2`. This includes image scans and a disposable Timescale/PostgreSQL restore. The preceding run failed because the bare Go test container lacked Git; the corrected job installs that test dependency and retains the real Git integration case.
- This is source and disposable-environment validation. No live deployment, production-data restore, trusted publisher signature or real notification receipt is claimed for 2.8.2. Earlier 2.8.1 target evidence retains its original date and scope.

## [2.8.1] - 2026-10-11

### Fixed

- Added an immutable eighth migration and matching ORM check for the durable notification sending state; the previous seven migration files remain unchanged.
- Parsed valid empty Nobitex history responses and paginated capped history downloads instead of silently completing a truncated range.
- Isolated independent public feed sources and added a validated XAU fallback without bypassing source time, unit, anomaly or independence checks.
- Preserved the vetted relay freshness anchor across stored quote reads without extending source eligibility or operator policy windows.
- Coalesced unfinished WebSocket snapshot reads and batched instrument policies per response, removing the repeated database work exposed by actual cold connection and sustained-load checks.
- Bounded automatic chart backfill with an owner-checked Redis guard and batched provider settings; repeated GETs no longer create an unrestricted queue of nearly identical ranges. Manual enqueue and fresh policy checks stay intact.
- Removed completed public price-payload caching, read current quotes after chart inputs, reevaluated expiry when serving each caller and sent `Cache-Control: no-store` for current prices.
- Shared unfinished history reads and used streaming first/last aggregates only when the actual database exposes the Timescale aggregates; ordinary PostgreSQL retains the original query. Both backends passed real OHLC, count, range and direct-gold equivalence checks.
- Enabled executable metadata/signing and made the Windows release command fail when a publisher signature is unavailable; the explicit unsigned test package stays separate.

### Added

- Real PostgreSQL delivery-state upgrade regressions, a trusted publisher/timestamp signature verifier and installed Windows runtime/logout checks.
- Bounded duration/rate load workers with JSON evidence, HTTP status counts, response validation and latency percentiles.

### Acceptance

Application commit `ce22c1d` passed all 15 hosted jobs and the exact target image passed 182 native
checks, seven real PostgreSQL checks and three real Timescale history checks. The owned stage
passed a clean 1800.258-second soak: 27,000 HTTP 200 responses, 14.998 rps, 323.249 ms p95
and 200 stable filtered WebSockets. Separate API/Redis fault windows passed all-client recovery
in 3.746/4.495 seconds. The earlier fixture-publisher failure remains a failed receipt; the corrected
fault-only run links the original clean proof. Owned stage storage was removed after capture.
Native Windows push, trusted signing and continuous all-source coverage remain blocked.
An actual unsigned installation is never reported as signed. See the delivery matrix for limits.

## [2.8.0] - 2026-10-11

### Fixed

- Kept instrument currency, weight, purity and original source time through prices, charts and alerts.
- Hardened canonical worker selection, independent anomaly verification, stale-primary fallback and Telegram validation.
- Made history/backfill durable, resumable and gap-aware; accepted valid zero volume.
- Selected only currently runnable history instruments before claiming database jobs; preserved blocked old rows and resumed them when source policy or live availability recovers.
- Hardened user/admin session lifecycle, password reset/rotation, CSRF, roles, worker jobs and delivery cancellation.
- Connected admin policy edits to effective runtime behavior and expanded operational screens and permission checks.
- Corrected browser push/logout, conversation/ticket races, desktop origin, links, chart CSP and asset paths.
- Loaded stream snapshots only after connection capacity and Redis availability checks; rejected connections cannot cause eager database/cache reads.
- Preserved migration TLS options, bounded migration lock waits and rejected unknown newer schema versions.
- Corrected relay upstream TLS, Docker service DNS, staging subnet isolation, source timestamp feed contracts and Windows install failures.
- Updated vulnerable HTTP/multipart dependencies and replaced the previous token package with pinned PyJWT and required-claim validation.
- Isolated historical backfills from current snapshots, repaired legacy XAG fallback defaults and preserved explicit operator overrides.
- Updated container OS packages and Go to remove image scan findings; kept strict HIGH/CRITICAL gates for API, clients, Telegram, feed, relay and edge.
- Generated disposable TLS certificates on the CI runner and resolved backend names in nginx syntax fixtures.
- Excluded `/admin` and `/admin/` from the public service worker navigation fallback once the updated worker activates.
- Used IPv4 loopback for the admin container health probe and allowed a ten-second startup period.
- Re-resolved web/admin API upstreams through Docker DNS without waiting for a backend hostname at configuration parsing; late backend start and address replacement pass in isolated runtime checks.
- Removed the unused default IPv6 configuration helper from all four custom Nginx images; its Alpine package-manifest lookup could delay startup by two minutes on the target network. Explicit listeners and other entrypoint helpers remain intact.
- Allowed the release history repair to exceed Timescale's compressed-DML tuple limit within its release transaction; kept the migration runner's 300-second timeout and all six previously applied migration checksums.

### Added

- Admin TOTP/recovery flow, provider/Telegram policy controls and read-only backup status.
- Portable infrastructure behavior tests and migration safety regression tests.
- Go/sidecar CI gates, Timescale restore flow with data/chunk/policy comparisons and timestamp-based freshness alerts.
- Generated complete API schema/route index, delivery acceptance matrix and verified source archive with file hashes.
- Hashed Python runtime/development locks, exact-package vulnerability gates and guarded PostgreSQL browser fixtures.
- Restore target ownership checks and streaming fingerprints that preserve existing databases and large histories.
- Configurable admin asset base for a secure path deployment when a separate admin hostname is unavailable.

### Validation boundary

Hosted [CI run 38136644783](https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/38136644783)
passed all 15 jobs for `a53842359ff147fe8946131f007dbcade7074adc`, including seven strict
HIGH/CRITICAL image scans and real Timescale/Redis, migration/restore and browser checks.

The target's verified 47-table restore passed the seventh migration with the `b9f5538` API image
on Timescale 2.28.3 / PostgreSQL 16.14. Three hypertables, 37 chunks and four users remained.
User and price fingerprints matched after excluding only the intended historical-backfill flag.

Release 2.8.0 is running on the existing target as of 2026-10-11. HTTPS readiness, two-replica
failover, real admin security/read routes and the public-worker/admin browser flow passed.
See [delivery readiness](docs/delivery-readiness.md) for proof scope and the
[server handoff](docs/production-handoff-fa.md) for live URLs and safe commands.
Provider rights, uncovered-source canaries, actual notification receipt, signed installation
and a long load/soak run still require their own external evidence.

## [2.7.5] - 2026-09-30

### Fixed
- Browser checks now start the web workspace on the port expected by the test
  runner instead of silently falling back to Vite's default port.
- Integration checks now expose the API package root to direct test scripts.
- Compose validation now supplies the required worker secret with a CI-only value.

### Changed
- Pinned checkout, Node.js setup and Python setup actions to current supported
  immutable releases.
- Updated Vite, Electron and transitive Node packages to patched compatible
  releases; the HIGH/CRITICAL npm audit gate is now clean.

### Validation
- Release identity, frontend contracts and browser test discovery pass locally.
- Full hosted CI and image scans remain the release gate for this candidate.

## [2.7.4] - 2026-09-19

### Fixed
- Shared edge Nginx now re-resolves API and web container addresses after a
  rolling replacement, preventing stale-upstream 502 responses.
- Kept the external-chart script and frame policy in the tracked shared-edge
  configuration so a future configuration refresh does not block the chart.

## [2.7.3] - 2026-09-19

### Fixed
- Replaced the protected-branch-incompatible forced price-feed publication with
  a normal fast-forward update from the existing validated feed branch.
- Silver charts now open on the 30-day range so sparse but valid persisted
  observations render as a useful trend instead of an empty single-point line.

## [2.7.2] - 2026-09-19

### Fixed
- Updated the Iran-side feed validator to accept exactly one validated silver
  route from either Gold API Free or XAUS. Duplicate silver routes remain blocked.

## [2.7.1] - 2026-09-19

### Fixed
- Vendored the two small CC0 cryptocurrency marks so production image builds do
  not depend on downloading a newly added package from the Iran host.

## [2.7.0] - 2026-09-19

### Added
- Consent-gated TradingView Advanced Chart. No third-party chart request occurs
  until the visitor presses the clear load button.
- Keyless XAUS XAG/USD fallback for the public relay, with strict freshness,
  timestamp and safe-range validation.
- Licensed CC0 Bitcoin and Tether icons, plus clearer gold and silver marks.

### Changed
- Removed the in-chart Lightweight Charts attribution mark while retaining the
  required public TradingView notice and link in the site footer.
- Rebuilt the footer and legal pages in the existing gold/charcoal visual system.
- Unified shared button shape, focus, press and restrained hover feedback.
- Collapsed sidebar now uses an animated expand control instead of the brand logo.
- Chart cards reorder only after hold-and-drag; visible up/down controls removed.
- Policy receipt advanced to `2026-09-19.2` for the optional external chart.

### Fixed
- Silver feed can continue through a second free source when the original XAG
  endpoint fails, preventing the chart from remaining permanently empty.
- Footer now stays at the bottom on short pages without covering page content.

## [2.6.1] - 2026-09-19

### Changed
- Published owner-supplied identity: Ilia Shakeri / ایلیا شاکری, Tehran, Iran,
  and public privacy/support email iliashkr@gmail.com in both languages.
- Clarified current Iran-only target market and free service; subscriptions and
  worldwide expansion are future plans, not active services.
- Added an account-free email link on every legal page. No invented postal address,
  registration, licensing, retention guarantee or legal compliance certification.
- Revised policy receipt version to `2026-09-19.1` on client and server together.
- Fixed Persian refresh-cookie lifetime from 31 to 30 days; chat retention unchanged.
- Owner approved a limited deployment with backup and health checks despite
  outstanding rights, retention and restore evidence. Normal gates remain intact.

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
