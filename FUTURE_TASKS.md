# Future Tasks

Tracked work that is not yet done. For the full picture — what is complete, what
is partial, and what production readiness still requires — see
[`PROJECT_STATUS.md`](PROJECT_STATUS.md).

## Engineering

- [ ] Extract the shared web/desktop React layer. `apps/desktop` currently
      duplicates `apps/web`'s API client and views (~2,500 lines) and the two
      have already drifted.
- [ ] Route-level API tests. Every endpoint is exercised through units today;
      none through an HTTP client against a real database.
- [ ] Browser end-to-end coverage for sign-in, alert creation and delivery.
- [ ] A real free-market USD/Toman source. Without one, every Toman metal price
      without a direct provider is bridged through USDT and runs percent-level
      high.
- [ ] Direct Iranian silver source. `SILVER_999_TOMAN_GRAM` has one key-gated
      provider; `SILVER_925_TOMAN_GRAM` is formula-only.
- [ ] Confirm PersianToolbox redistribution terms and whether its USD/IRR
      reference can legally and semantically be shown to customers.
- [ ] Create the free Servix account, add visible source attribution, store its
      key outside Git, and enable only the needed chart routes.

## Operator Proof

Evidence that cannot be produced from source control. Keep it out of the
repository: start from `docs/operator-gates.evidence.example.json`, fill a
private copy, then verify it.

- [ ] Provider rights sign-off with contract or approval record.
- [ ] Scheduled live canary proof from the production network.
- [ ] Production secret injection proof.
- [ ] Navasan HTTPS proxy proof, or a signed disabled-route reason.
- [ ] BRSAPI and TSETMC future-domain ownership record.
- [ ] Off-host backup and disposable restore-drill proof.
- [ ] Production deployment and health proof.
- [ ] Authenticated browser smoke proof.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-operator-gates.ps1 -EvidencePath path\to\operator-gates.evidence.json
```

## Completed

- [x] Provider request bounds, retry policy, parser contracts, secret-safe canary.
- [x] Assistant user quota, shared rate limits, provider fallback, chat transaction order.
- [x] Production evidence schema and strict verifier.
- [x] CI parity for Redis and refresh-token concurrency.
- [x] Deployment health gate and web response guards.
- [x] Local API, web, admin, desktop, dependency and static checks.
- [x] Full production audit and remediation — see `PROJECT_STATUS.md`.
- [x] Reachable no-key Iranian BTC/USD fallback with strict payload validation.
- [x] Reachable Iranian NTP sources tested without changing production time.
- [x] Structured JSON request logging and live pricing metrics.
- [x] Servix free-tier history parser and bounded backfill for BTC, USDT, and USD.
