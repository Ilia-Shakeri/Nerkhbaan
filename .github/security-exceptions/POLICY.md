# CI Security Scan Exceptions

The default is no exceptions. The shared `.trivyignore.yaml` file applies to repository, dependency, and container scans.

An exception change must include all of these fields:

- the exact finding ID;
- the narrowest affected path or package URL;
- a risk statement and compensating control;
- a tracking issue and accountable owner;
- an `expired_at` date no more than 30 days in the future.

Never suppress a real credential. Revoke it, remove it from the repository, and purge affected history and artifacts through the incident process.

Security review is required for every exception. Expired entries must be removed or reviewed again; Trivy stops honoring them after their date.
