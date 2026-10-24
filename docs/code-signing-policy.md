# Code signing policy

Status: **Preparation for a SignPath Foundation application. Not submitted,
accepted or enabled. No Nerkhbaan artifact is claimed to be signed by SignPath.**

## Proposed service

Requested program attribution, conditional on acceptance:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation

The [Foundation conditions](https://signpath.org/terms.html) govern eligibility
and the service's decision. The MIT grant is scoped in [license scope](license-scope.md).
Dependency and brand-asset clearance is still a separate check, not an implied grant.

## Responsibility and approval

The repository owner, [Ilia-Shakeri](https://github.com/Ilia-Shakeri), is the
proposed committer, reviewer and release-signing approver. This records a proposed
service role; it does not alter repository permissions or certify MFA status.
The owner must confirm MFA on repository access and enroll it on the signing
account. Every production signing request requires the owner's manual approval
of the exact source revision and artifact. Automated tests do not approve signing.

Changes from other contributors require review by a maintainer. The workflow,
build configuration and signing configuration receive the same review as code.

## Scope and provenance

Only this project's application executable, NSIS installer and generated
uninstaller built from reviewed source by an approved hosted Windows workflow
are proposed for signing. Final coverage depends on the service's approved
artifact configuration and the installer signing sequence. Upstream runtime
binaries and libraries retain their upstream publishers and licenses; do not
sign unrelated binaries under this project's subscription.

Product name and release version must match Nerkhbaan and the root VERSION.
Record the source commit, workflow run, artifact hashes, certificate identity,
timestamp and verification receipt. Production acceptance requires Windows trust
verification of the exact files, followed by isolated installation/runtime/removal
and actual notification receipt on a consenting device.

SignPath acceptance, an uploaded artifact, an accepted signing request and a
downloaded signed result are distinct states. A failed or pending state never
becomes a successful release by changing a label. Signing keys remain in the
service; account tokens belong in protected CI secrets, never source or logs.

## Privacy and system changes

The application contacts its configured service for authentication, market data,
alerts and support. Optional conversation features can contact configured
external services. It is not an offline-only application. Credentials are stored
using the desktop's encrypted session bridge; notification consent is per session.
Public native notifications contain generic text and open the inbox for details.

Read the [public privacy notice](https://nerkhbaan.ir/privacy) and the in-app
privacy pages before using the service. The privacy notice's documented limits
still apply; this policy does not certify a complete processor/retention register.
Installer disclosure and optional network-behavior controls require review
against the Foundation's conditions before eligibility is claimed.

The NSIS installer supports per-user installation, displays the destination and
provides an uninstaller. User application data is retained on uninstall by default.
No test will replace an existing user installation or change system trust stores.

## Current missing evidence

- Owner confirmation of reachable application contact and repository MFA.
- Cleared bundled dependencies and permission for every brand asset in scope.
- Service application, acceptance and configured signing/approver roles.
- Approved hosted artifact and successful signing of all required files.
- Trusted signed installation and actual native notification/click receipts.

The public web/server release is a separate artifact. A documentation or license
commit does not redeploy the server or turn an unsigned installer into a signed one.
