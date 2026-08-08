# Changelog

## 0.4.2

Documentation, and the release that proves the pipeline needs no secrets.

- `docs/PROJECT_STATE.md` records how each registry is reached and which
  credentials exist (none, once trusted publishing is configured on both).
- CHANGELOG entry for 0.4.1, which shipped without one.

The code is unchanged from 0.4.1. A release pipeline that has never run its
npm leg is a pipeline that will fail the first time it matters, so this
version exists to run it — the same reason every claim in this project has a
test rather than a paragraph.

## 0.4.1

**The two implementations disagreed about how to render an amount.** Python
gave `47 CIcash` where JavaScript gave `$47` — the rename to CIcash had missed
a literal `$` in the JavaScript formatter.

Display-only, but not cosmetic: `available_str` is part of the balance object
an agent reads, so this was two implementations disagreeing about an API field.
No existing test could see it, because the conformance vectors cover the wire
format and rendering is not on the wire. It was found by installing the
freshly-published npm package and running it.

**Fixed**
- `js/src/ledger.js` renders through a `UNIT` constant, matching `money.py`.
- `tools/interop_check.py` now compares eight rendered amounts across the
  language boundary, so a display divergence cannot ship again. CI runs it.
- The Python canonical encoder now enforces the no-floats rule (SPEC §2.1) that
  it wrote into the spec but only JavaScript was checking. A rule enforced by
  one implementation catches nobody.

**Added**
- `examples/llm_budget.py` — CIcash wrapped around the Claude API. The use case
  that works today with no settlement layer: `count_tokens` plus `max_tokens`
  give the worst-case cost before a call, `response.usage` gives the truth
  after it, and that gap is exactly what a hold is for.
- `docs/PROJECT_STATE.md` — what is deliberate and must not be "fixed", and
  where the trapdoors that fail silently are.

## 0.4.0

**The unit of account has a name: the CIcash.** Until now the money in this
system was anonymous — "micro-units of the settlement unit" — which quietly
implied dollars in every example and committed to nothing.

- `usd()` is now `ci()`; `fmt()` renders `50 CIcash` rather than `$50`.
- The package, the CLI, the npm module and the environment variables are all
  `cicash` / `CICASH_*`. The project was `agentcash`, which was **taken on npm**
  by an active package in the same space; `cicash` is free on both registries.
- **The wire format did not change.** Amounts were always bare integers, so
  `spec/vectors.json` is byte-identical, every previously minted token still
  verifies, and the two implementations still agree. Naming the unit fixes what
  the integer *means*, which every party to a payment had to agree on anyway.
- SPEC §1 is now "Unit of account", and states that the name is not carried on
  the wire — a deployment may denominate in something else without invalidating
  a vector.

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
- **`cicash/canonical.py`** — one encoder for everything signed or hashed.
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
