# CIcash wire specification v0.3

Status: **draft**. Everything below is checkable against `spec/vectors.json`.

This document exists so the Python package is not the standard — the format is.
An implementation in any language that reproduces the vectors interoperates.

---

## 1. Unit of account

The unit is the **CIcash**. Amounts are **integers of micro-units**,
1 CIcash = 1,000,000 micro-units. Floats MUST NOT appear in any amount field:
an agent that retries ten thousand times must not accumulate drift into a real
overdraft, and a float does not survive the language boundary (§2.1).

The unit's *name* is not carried anywhere in the wire format — amounts are bare
integers — so a deployment may denominate in something else without changing a
single byte or invalidating a vector. What the name fixes is the meaning of the
integer, which every party to a payment must already agree on.

The CIcash is deliberately not an investment asset. If the unit appreciates,
agents hoard it and the payment layer dies. That is Gresham's law, and it is how
Bitcoin stopped being cash and became a thing people keep instead.

## 2. Canonical encoding

Wherever this spec says *canonical JSON*: UTF-8, object keys sorted by **Unicode
code point**, separators `","` and `":"` with no whitespace, no trailing
newline. All signatures and hashes are computed over canonical JSON.

Two further rules are normative, and both exist because a second implementation
found them the hard way. Each produces a **silent** failure — the token simply
stops verifying on the other side of the wire, with nothing to point at:

**2.1 No floats.** A number inside any signed or hashed structure MUST be an
integer. Python renders an integral float as `1800000000.0`; JavaScript renders
`1800000000`. An encoder MUST reject a non-integer rather than guess.
Consequently: `expires` is integer unix **seconds**, `quote.expires_at` is
integer unix **seconds**, `receipt.ts` is integer unix **milliseconds**, and all
amounts are integer micro-units.

**2.2 Raw UTF-8, not escaped.** Non-ASCII characters MUST be emitted literally.
Python's `json.dumps` escapes them by default (`"caf\u00e9"`) and JavaScript's
`JSON.stringify` does not (`"café"`); this spec takes the JavaScript behaviour,
so implementations built on Python MUST pass `ensure_ascii=False`. A budget note
in Thai or an emoji in a purpose tag verifies identically in both.

## 3. Caveats

A caveat is a constraint written onto a token. Serialised form:

```
<kind> ":" canonical_json(<value>)
```

| kind | value | meaning |
|---|---|---|
| `sub` | string | delegation boundary; value is the child token id |
| `cnf` | `{"alg","pub"}` | key the holder must prove possession of |
| `max_total` | integer µ | cumulative cap over this token **and its whole subtree** |
| `max_per_tx` | integer µ | cap on one payment |
| `rate` | `{"max_count","max_amount","window_s"}` | sliding-window cap; nulls allowed |
| `expires` | integer (unix s) | hard stop |
| `payees` | array of string | counterparty allowlist |
| `purpose` | array of string | purpose-tag allowlist |
| `note` | string | non-enforcing, carried into the audit trail |

**Caveats are conjunctive.** A verifier MUST evaluate every caveat in the chain
and MUST NOT treat a later caveat as replacing an earlier one. This is what
makes delegation attenuation-only without any additional rule: appending
`max_total = 999999` to a token that already carries `max_total = 100` changes
nothing.

`alg` is `ed25519` (RECOMMENDED) or `hmac-sha256` (fallback; makes the verifier
a trusted hub, see §7). `pub` is lowercase hex: the raw 32-byte public key for
ed25519, or `sha256(secret)` for the fallback.

## 4. Token

```json
{"root_id": "...", "root_token_id": "...", "caveats": ["..."], "sig": "hex"}
```

### 4.1 Signature chain

```
sig₀ = HMAC-SHA256(root_key, root_id || "|" || root_token_id)
sigₙ = HMAC-SHA256(sigₙ₋₁, caveatₙ)          # caveat bytes, UTF-8
sig  = hex(sig_last)
```

The issuer MUST append a `cnf` caveat first, before any constraint.

Two properties follow from the construction and MUST be preserved:

- **Anyone holding the token can append a caveat offline.** `sigₙ₋₁` is the key
  for link *n*, and the holder has it.
- **Nobody can remove a caveat.** Un-appending needs `sigₙ₋₁`, which needs the
  root key.

### 4.2 Delegation

Append, in order: `sub:<child_id>`, `cnf:<child binding>`, then the child's
constraints. With `alg = ed25519` the child's public key travels inside the
chain, so a verifier needs **no prior knowledge of the child** and delegation
requires no network.

### 4.3 Lineage and scope

`lineage` = `[root_token_id]` followed by every `sub` value **in order**. A
verifier MUST derive it from the caveats and MUST NOT trust any self-declared
lineage field.

Each non-`sub` caveat is *owned* by the most recent `sub` value before it, or by
`root_token_id` if none precedes it. Ownership decides whose counters a stateful
caveat reads (§6).

## 5. Quote

The payer never supplies the amount or the payee. Both come from a quote the
seller signed:

```json
{"quote_id","payee","amount","purpose","expires_at","sig"}
```

`sig = hex(HMAC-SHA256(merchant_key, canonical_json(payload)))` where *payload*
is the object without `sig`. `amount` is integer micro-units and `expires_at` is
integer unix seconds — see §2.1.

Verifiers MUST reject a quote whose signature fails, whose `expires_at` has
passed, or whose `payee` is unknown. Settlement MAY be lower than `amount` and
MUST NOT be higher.

## 6. Proof of possession

The presenter signs exactly this string:

```
<token_id> "|" <payee> "|" <amount> "|" <purpose> "|" <idem_key>
```

`amount` is the decimal integer µ with no padding. For ed25519 the proof is
hex(Ed25519(sk, utf8(request))); for the fallback, hex(HMAC-SHA256(secret, …)).

Because the whole request is inside the signed string, a captured proof cannot
be re-aimed at a different payment, and a token copied out of a log without the
key buys nothing.

## 7. Evaluation

A verifier MUST perform these in order and stop at the first failure:

1. **Signature** — recompute §4.1 from the root key.
2. **Revocation** — if *any* id in `lineage` is revoked, reject. Revocation is
   therefore subtree-wide and instant.
3. **Proof of possession** — against the `cnf` owned by the leaf token id.
4. **Quote** — §5.
5. **Stateless caveats**, in this order: `expires`, `payees`, `purpose`,
   `max_per_tx`. Order is normative: *"you may not pay this party at all"* is a
   different signal to a planner than *"that is over your per-call cap"*, and
   when both are true the agent should hear the first.
6. **Stateful caveats** — `max_total` then `rate`, each read against the
   counters of the caveat's **owner**, not the leaf.

### 7.1 Ancestor debit — normative

A settlement of *A* µ MUST debit the counters of **every id in `lineage`**.

Without this, attenuation is only syntax: a token capped at 50 could mint ten
children of 50 each. Implementations that debit only the leaf are non-conformant
and MUST NOT claim this spec.

### 7.2 Holds

`authorize` places a hold of the quoted amount against every ancestor and MUST
count toward `max_total` and `rate` while open. `settle(actual ≤ held)` converts
it; the remainder is released. Holds expire; an expired hold MUST release.

### 7.3 Idempotency

Every mutating call carries an `idem_key`. A repeat MUST return the original
result without a second effect — including across a process restart. Agents
retry; a system that charges twice for a retried tool call is broken by design.

## 8. Receipts

```json
{"receipt_id","ts","root_id","lineage","payee","amount","purpose",
 "quote_id","idem_key","prev_hash","hash"}
```

`hash = sha256(canonical_json(record without "hash"))`, `prev_hash` is the
previous receipt's `hash`, or `"genesis"`. Verification recomputes the chain.

This is the *purpose-bound receipt*: who authorised, which agent in the chain,
for what, under which quote — the artefact that makes a human willing to let a
program spend.

## 9. Errors

Denials are machine-actionable. Every denial carries `action`, and an agent
that cannot see it will retry-loop until the budget is gone.

| action | meaning |
|---|---|
| `RETRY_AFTER` | transient; `retry_after` seconds fixes it |
| `REPLAN` | permanent for this request; another request may pass |
| `ESCALATE` | no request will pass; only the principal can unblock |

| reason | action | HTTP |
|---|---|---|
| `SIGNATURE_INVALID`, `POP_INVALID`, `BINDING_MISSING`, `QUOTE_FORGED` | ESCALATE | 401 |
| `REVOKED`, `EXPIRED` | ESCALATE | 403 |
| `RATE_LIMITED` | RETRY_AFTER | 429 + `Retry-After` |
| `PAYEE_NOT_ALLOWED`, `PURPOSE_NOT_ALLOWED`, `PER_TX_EXCEEDED`, `QUOTE_EXPIRED`, `UNKNOWN_PAYEE`, `OVER_QUOTE`, `HOLD_NOT_OPEN` | REPLAN | 402 |
| `TOTAL_EXHAUSTED` | REPLAN if any budget remains, else ESCALATE | 402 |
| `WIDENING_REFUSED` | ESCALATE | 400 |

`402 Payment Required` has been unused for thirty years because humans were
never the ones being metered. Agents are.

## 10. HTTP binding

| method | path | body |
|---|---|---|
| POST | `/v1/balance` | `{token}` |
| POST | `/v1/authorize` | `{token, pop, quote, idem_key}` |
| POST | `/v1/settle` | `{hold_id, actual, idem_key}` |
| POST | `/v1/release` | `{hold_id}` |
| GET | `/v1/receipts?token_id=` | — |
| GET | `/v1/audit` | — |
| GET | `/v1/profile` | — |

A paywalled resource SHOULD answer an unpaid request with `402` and a quote in
the body, and accept the resulting receipt id on retry.

## 11. Agent binding (MCP)

A conforming MCP server exposes `budget_check`, `budget_quote`, `budget_pay`,
`budget_delegate`, `budget_receipts` — and **MUST NOT** expose any tool that
widens a budget. The key stays in the server process; the model receives tools,
never credentials. A credential that never enters a context window cannot leak
out of one.

## 12. Conformance

`spec/vectors.json` pins caveat serialisation (including a non-ASCII case),
both signature chains, lineage and scope derivation, the request string, quote
signing, and the receipt chain. Reproduce it and you interoperate.

Two implementations are held to it today — `cicash/` (Python) and `js/`
(JavaScript, node:crypto only) — and they share no code. `tools/interop_check.py`
goes further: Python mints a wallet, JavaScript verifies it, signs a payment
against it, and delegates a tighter child wallet offline; Python then settles
both and checks the ancestor debit crossed the language boundary. CI runs it on
every push.

Regenerate with `python3 tools/gen_vectors.py`. Changing a vector is a
**breaking change** to every implementation, and should be treated as one.

## 13. Out of scope for v0.2

Settlement to a real asset · netting · privacy (the ledger sees every payment;
the goal of *auditable to the principal, private to the world* needs blinding
this does not have) · dispute resolution · clock trust.
