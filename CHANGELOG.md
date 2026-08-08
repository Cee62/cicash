# Changelog

## 0.3.0

Writing a second implementation is what this release is. It turned the format
from "what the Python library happens to do" into something another runtime can
be held to — and it found two real interoperability bugs on the way.

**Added**
- **A complete JavaScript implementation** (`js/`), node:crypto only, no
  dependencies, sharing no code with the Python one. 24 tests: 11 conformance
  against `spec/vectors.json`, 13 behavioural parity on the same invariants.
- **Cross-language interop check** (`tools/interop_check.py`): Python mints a
  wallet, JavaScript verifies it, signs a payment and delegates a tighter child
  entirely offline, then Python settles both and confirms the ancestor debit
  crossed the boundary. Runs in CI.
- **`agentcash/canonical.py`** — one encoder for everything signed or hashed.
- CI across Python 3.9-3.13 and Node 18/20/22, plus a guard that fails the build
  if `spec/vectors.json` drifts from its generator.
- `SECURITY.md`, `CONTRIBUTING.md`, `PUBLISH.md`, MCP registry manifest.

**Changed — BREAKING to the wire format**
- **No floats in signed structures** (SPEC 2.1). Python rendered an integral
  float as `1800000000.0` where JavaScript rendered `1800000000`, so a token
  minted in one silently failed to verify in the other. `expires` and
  `quote.expires_at` are now integer seconds; `receipt.ts` is integer
  milliseconds; encoders reject non-integers rather than guess.
- **Non-ASCII is raw UTF-8, not escaped** (SPEC 2.2). Python escaped by default,
  JavaScript did not. A budget note in Thai would have broken verification
  across the boundary. Vectors now include a non-ASCII case.
- Object keys sort by Unicode code point, stated explicitly.
- `spec/vectors.json` regenerated. Every signature value in it changed.

**Tests**: 54 Python + 24 JavaScript + 1 interop check.

## 0.2.0

Everything v0.1 disclaimed in its "what this is not, yet" section, except L0.

**Added**
- **Ed25519 proof of possession** (`crypto.py`). The ledger stores no private
  material, and **delegation is fully offline** — the child's public key rides
  inside the signature chain, so a verifier needs no prior knowledge of it.
  HMAC remains as a labelled fallback; `Ledger.security_profile()` reports which
  is in use. Nothing silently downgrades.
- **Durable, concurrency-safe storage** (`store.py`). SQLite with
  `BEGIN IMMEDIATE` around the read-check-write span, WAL, thread-local
  connections. Verified by a 16-thread × 10-payment race against one parent cap:
  exactly the cap is spent, never a micro-unit more.
- **HTTP binding** (`service.py`) with a semantic status mapping —
  402 budget · 401 proof · 403 revoked · 429 rate — and a working
  `402 → quote → pay → retry` resource flow.
- **MCP server** (`mcp_server.py`). Any MCP-capable agent gets
  `budget_check` / `budget_quote` / `budget_pay` / `budget_delegate` /
  `budget_receipts`. **The model never receives the key**, only tools.
- **Client SDK** (`client.py`) with the same shape as the local wallet.
  `delegate()` stays local on purpose: an outage must never stop an agent from
  *reducing* someone's authority.
- **Operator CLI** (`cli.py`): grant, balance, revoke, receipts, audit, serve.
- **Wire specification** (`spec/SPEC.md`) and **conformance vectors**
  (`spec/vectors.json`) so other languages can interoperate byte-for-byte.

**Changed**
- `cnf` caveat now carries `{"alg","pub"}` instead of a hash of a shared secret.
- Stateless checks run in a normative order (`expires`, `payees`, `purpose`,
  `max_per_tx`) so a planner hears the most fundamental violation first.
- `Wallet` gained `to_dict()` / `from_dict()` for cross-process handoff.

**Tests**: 26 → 54.

## 0.1.0

Initial design: macaroon-style budget tokens, attenuation-only delegation,
ancestor debit, holds, idempotency, subtree revocation, hash-chained receipts,
planner-actionable denials.
