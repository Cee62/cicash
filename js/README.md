# cicash

JavaScript implementation of [CIcash](https://github.com/Cee62/cicash) — a budget
you lend to an AI agent, not money you give it. Bounded, expiring, revocable,
auditable, and worthless once stolen.

`node:crypto` only. No dependencies. Node >= 20.

```bash
npm install cicash
```

```js
import { Ledger, ci, Denied } from "cicash";

const led   = new Ledger();
const acme  = led.registerPrincipal("acme");
const api   = led.registerMerchant("api.search");

const agent = acme.grant({
  budget: ci(50), perTx: ci(5),
  rate: { max_count: 20, window_s: 60 },
  payees: ["api.search"], purposes: ["research"],
});

agent.pay(api.quote(ci(2), "research"), "run1/step3");   // retry-safe: same key, one charge
const sub = agent.delegate({ budget: ci(5) });           // offline, tighter only
acme.revoke(agent);                                      // kills sub too
led.auditVerify();
```

A denial tells a planner what to do next rather than just refusing:

```js
try { agent.pay(quote, "run1/step4"); }
catch (e) {
  if (e instanceof Denied) e.asObject();
  // { denied: 'RATE_LIMITED', action: 'RETRY_AFTER', retry_after: 12.4, hint: '…' }
}
```

`RETRY_AFTER` · `REPLAN` · `ESCALATE`. And `Wallet` has no `setBudget`,
`raiseLimit`, or `transferTo` — the surface an agent can reach cannot express
*"give me more."*

## Interoperability

This implementation shares no code with the Python one. Both are held to
[`spec/vectors.json`](https://github.com/Cee62/cicash/blob/main/spec/vectors.json),
and CI runs a live handshake on every push: Python mints a wallet, this package
verifies it, signs a payment against it, and delegates a tighter child entirely
offline — then Python settles both and checks the ancestor debit crossed the
language boundary.

```bash
npm test          # node --test test/*.test.mjs
```

The glob is not decoration: `node --test <directory>` changed meaning in Node 22
and resolves the directory as a module.

## Not audited

The construction is standard — HMAC chain, Ed25519, SHA-256 — and two
independent implementations agree on the vectors, but no third party has
reviewed it, and nothing here settles real value. Treat it as a working
reference implementation of a design, not as somewhere to put real money today.

Apache-2.0.
