# Changelog

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
