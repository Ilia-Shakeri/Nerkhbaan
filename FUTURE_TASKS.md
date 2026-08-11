# Future Tasks

## Repository Work

- [x] Provider request bounds, retry policy, parser contracts, and secret-safe canary.
- [x] Smart Assistant user quota, shared rate limits, fallback, and chat transaction order.
- [x] Production evidence schema and strict verifier.
- [x] CI parity for Redis and refresh-token concurrency.
- [x] Deployment health gate and web response guards.
- [x] Local API, web, admin, desktop, dependency, and static checks.

## Operator Proof

- [ ] Provider rights sign-off with contract or approval record.
- [ ] Scheduled live canary proof from the production network.
- [ ] Production secret-manager activation proof.
- [ ] Navasan HTTPS proxy proof, or a signed disabled-route reason.
- [ ] BRSAPI and TSETMC future-domain ownership record.
- [ ] Disposable production-like restore drill proof.
- [ ] Production deployment and health proof.
- [ ] Authenticated browser smoke proof.

Keep proof out of source control. Start from `docs/operator-gates.evidence.example.json`, fill a private file, then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-operator-gates.ps1 -EvidencePath path\to\operator-gates.evidence.json
```
