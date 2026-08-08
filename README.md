# agentcash

**A budget you lend to an AI agent — not money you give it.**

Bounded · expiring · revocable · auditable · worthless once stolen.

**Two independent implementations, held to one published conformance suite.**
Python (stdlib only; `cryptography` optional for Ed25519) and JavaScript
(`node:crypto` only, zero dependencies). They share no code.

```bash
python3 demo.py                                  # the whole story in 10 scenes
python3 -m unittest discover -s tests -t .       # 54 tests
cd js && node --test test/                       # 24 tests
python3 tools/interop_check.py                   # python mints it, javascript spends it
bash examples/quickstart.sh                      # a real wallet in 4 commands
```

---

## The thesis

Bitcoin's key model is unlimited, eternal, irrevocable bearer authority in a single
secret. That is safe for a careful sovereign and catastrophic in the hands of
something that leaks its own context, retries in loops, and can be talked into things
by a web page.

So this keeps Bitcoin's L0 philosophy — **commitments that cannot be loosened, receipts
anyone can verify, cost as the anti-spam mechanism** — and inverts its key model
completely.

| | Bitcoin | agentcash |
|---|---|---|
| authority | unlimited, eternal | bounded, expiring |
| delegation | impossible | offline, attenuation-only |
| revocation | impossible | instant, subtree-wide |
| stolen key | total loss | buys nothing |
| retry | double-spend | free |
| denial | — | tells the planner what to do next |

Bitcoin failed as *money* not for technical reasons but because it optimised the wrong
function: it maximised *"nobody can stop or change this"* and got a speculative asset.
Optimise the same axis for agents and you get the same result. The function that
matters here is **bounded, revocable, auditable spending**, which is nearly the
opposite axis.

---

## Six invariants, each with a test that proves it

**1. Delegation is a ratchet.**
Macaroon-style chain: `sigₙ = HMAC(sigₙ₋₁, caveatₙ)`. The current signature is the key
for the next link, so any holder can *append* a constraint offline — and nobody can
*remove* one without the root key. No syntax in this system widens a budget.
→ `test_removing_a_caveat_breaks_signature`, `test_widening_would_be_inert_even_if_forced`

**2. Attenuation is economic, not just syntactic.**
A payment debits **every ancestor**. An agent capped at $50 cannot mint ten $50
children. Rate limits attenuate the same way.
→ `test_cannot_escape_parent_cap_by_forking_children`, `test_deep_chain_still_bound`

**3. A leaked token is worthless.**
Assume the agent leaks everything — logs, tracebacks, screenshots, the next model's
training data. Spending needs a proof bound to *this exact request*, so a captured
token cannot be replayed and a captured proof cannot be re-aimed.
→ `test_leaked_token_without_secret_is_worthless`, `test_wrong_key_cannot_spend_a_valid_token`

**4. The agent never writes the amount or the payee.**
Both come from a quote the *merchant* signed and the ledger re-verifies. Prompt
injection has nowhere to put the number.
→ `test_payee_allowlist_blocks_injected_recipient`, `test_forged_quote_rejected`

**5. Retries are free — including across a crash.**
Agents retry. That is not a bug to be trained out of them.
→ `test_same_idem_key_charges_once`, `test_idempotency_survives_restart`

**6. The cap does not tear under concurrency.**
16 threads × 10 payments against one parent cap: exactly the cap is spent, never a
micro-unit more. A cap that silently stops being a cap is worse than an outage.
→ `test_parent_cap_holds_under_16_threads`

---

## The part that is genuinely AI-native

A human who gets declined asks a person. An agent that gets declined has three moves,
and if the error does not say which one, it loops until the budget is gone:

```python
except Denied as e:
    e.as_dict()
    # {'denied': 'RATE_LIMITED', 'action': 'RETRY_AFTER', 'retry_after': 12.4,
    #  'hint': 'you are looping faster than the grant allows; wait, or stop
    #           and re-read why you are repeating'}
```

`RETRY_AFTER` · `REPLAN` · `ESCALATE`. And `balance()` / `can_afford()` exist so the
agent plans *before* acting rather than discovering its limits by hitting them.

`Wallet` has no `set_budget`, no `raise_limit`, no `transfer_to`. The API surface an
agent can reach is deliberately unable to express *"give me more."*

---

## Use it

### Python

```python
from agentcash import Ledger, usd

led   = Ledger.sqlite("ac.db")
acme  = led.register_principal("acme-corp")
api   = led.register_merchant("api.search")

agent = acme.grant(
    budget   = usd(50),
    per_tx   = usd(5),
    rate     = {"max_count": 20, "max_amount": usd(10), "window_s": 60},
    ttl_s    = 24 * 3600,
    payees   = ["api.search"],
    purposes = ["research"],
)

receipt = agent.pay(api.quote(usd(2), "research"), idem_key="run1/step3")
sub     = agent.delegate(budget=usd(5), note="sub: summarise")   # offline, tighter only
acme.revoke(agent)                                               # kills sub too
led.audit_verify()
```

### Any MCP agent

The model gets tools; the key stays in the server process. A credential that never
enters a context window cannot leak out of one.

```json
{"mcpServers": {"agentcash": {
  "command": "python3", "args": ["-m", "agentcash.mcp_server"],
  "env": {"AGENTCASH_DB": "/abs/ac.db", "AGENTCASH_WALLET": "/abs/wallet.json"}}}}
```

Tools: `budget_check` · `budget_quote` · `budget_pay` · `budget_delegate` ·
`budget_receipts`. There is deliberately no tool that widens a budget.

### Any language, over HTTP

```bash
python3 -m agentcash.cli --db ac.db serve      # 127.0.0.1:8402
```

`402` budget · `401` proof · `403` revoked · `429` rate (with `Retry-After`).
HTTP has had a code meaning *"you must pay to proceed"* for thirty years and it went
unused because humans were never the ones being metered. Agents are.

### Operator CLI

```bash
agentcash --db ac.db grant --budget 50 --per-tx 5 --payees api.search --out wallet.json
agentcash --db ac.db balance --wallet wallet.json
agentcash --db ac.db revoke  --wallet wallet.json
agentcash --db ac.db audit
```

---

## Interoperability

Neither package is the standard — [`spec/SPEC.md`](spec/SPEC.md) is, and
[`spec/vectors.json`](spec/vectors.json) pins caveat serialisation, both signature
chains, lineage derivation, the request string, quote signing, and the receipt chain.
Reproduce the vectors in any language and you interoperate.

`tools/interop_check.py` proves the stronger claim: **Python mints a wallet,
JavaScript verifies it, signs a payment against it, and delegates a tighter child
wallet entirely offline — then Python settles both and confirms the ancestor debit
crossed the language boundary.** CI runs it on every push, alongside a guard that
fails the build if the vectors drift from their generator.

Writing the second implementation is also what hardened the format. It found two
bugs that fail *silently* — a token that simply stops verifying on the other side
of the wire, with nothing to point at:

- Python renders an integral float as `1800000000.0`; JavaScript renders
  `1800000000`. **No float may appear in a signed structure**, and encoders now
  reject one rather than guess (SPEC §2.1).
- Python escapes non-ASCII by default, JavaScript does not. A budget note in Thai
  would have broken cross-language verification. **Raw UTF-8 is normative**
  (SPEC §2.2), and the vectors carry a non-ASCII case.

That is the argument for a second implementation in general: the first one cannot
tell you which of its choices were decisions and which were defaults.

---

## What this is still not

Stated plainly, because a payment library that oversells itself is worse than none:

- **No L0.** Nothing settles to a real asset. Receipts are the netting input; the
  settlement leg is not written.
- **No privacy layer.** The ledger sees every payment. *Auditable to the principal,
  private to the world* needs blinding this does not have.
- **No dispute layer.** The design calls for finality to the seller with recourse
  handled off the payment path. Not built.
- **Trusts its clock.** Expiry and rate windows are only as good as `time.time()`.
- **Not audited.** The cryptographic construction is standard (HMAC chain, Ed25519,
  SHA-256), but no third party has reviewed this. Treat v0.2 as a working reference
  implementation of a design, not as something to put real money behind today.

## Next

1. Netting + settlement to a stable unit
2. Blinded receipts
3. Dispute layer off the payment path — finality for the seller, recourse for the
   principal, which is the trade Bitcoin never made and cards made backwards
4. A Go implementation against the same vectors — the JavaScript one took an
   afternoon and paid for itself twice over

---

## Publishing

See [PUBLISH.md](PUBLISH.md). One thing to know before you pick names: **`agentcash`
is already taken on npm** by an active package in this same space (v0.17.1, tagged
`mcp · x402 · payments · ai`). The JavaScript package here is therefore
`agentcash-protocol`. That collision is worth a deliberate decision rather than a
default — the reasoning is in PUBLISH.md.

---

Apache-2.0. See [CHANGELOG.md](CHANGELOG.md) for what changed in 0.3, including two
breaking wire-format fixes.
