# Security

## Status

**v0.3 is a reference implementation, not an audited product.** The construction
is standard — HMAC-SHA256 chain, Ed25519, SHA-256 — and two independent
implementations agree on the vectors, but no third party has reviewed it. Do not
put real money behind it yet.

## Reporting

Open a **private** security advisory on the repository (Security → Advisories →
Report a vulnerability). Please do not open a public issue for anything that
lets a token spend more than its grant allows.

Include: what you can spend that you should not be able to, the smallest
reproduction you have, and which implementation (`cicash/` or `js/`).

## What counts as a vulnerability

Anything that breaks one of the invariants the tests claim:

- spending past a cap, at any delegation depth (`max_total` must debit **every**
  ancestor)
- a delegation that ends up **wider** than its parent
- a token that spends without a valid proof of possession
- a revoked token, or any descendant of one, that still spends
- an idempotency key that charges twice
- a receipt chain that verifies after being edited
- the two implementations disagreeing on `spec/vectors.json`

## Known limitations — not vulnerabilities, but read them

- **The ledger trusts its clock.** Expiry and rate windows are only as good as
  system time. A host with a badly wrong clock can extend a grant.
- **The HMAC fallback makes the ledger a trusted hub.** It stores the shared
  secret. `Ledger.security_profile()` reports this; it never downgrades silently.
- **No privacy layer.** The ledger sees every payment.
- **A wallet blob is a credential.** `wallet.json` is written mode 600 by the
  CLI. Anything that reads it can spend the budget until it is revoked.
- **No settlement layer.** Nothing here moves real value.
