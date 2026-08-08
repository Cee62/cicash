# CIcash

JavaScript implementation of [CIcash](../README.md) — a budget you lend to an
AI agent, not money you give it.

`node:crypto` only. No dependencies. Node >= 18.

```js
import { Ledger, ci, Denied } from "CIcash";

const led   = new Ledger();
const acme  = led.registerPrincipal("acme");
const api   = led.registerMerchant("api.search");

const agent = acme.grant({
  budget: ci(50), perTx: ci(5),
  rate: { max_count: 20, window_s: 60 },
  payees: ["api.search"], purposes: ["research"],
});

agent.pay(api.quote(ci(2), "research"), "run1/step3");
const sub = agent.delegate({ budget: ci(5) });   // offline, tighter only
acme.revoke(agent);                               // kills sub too
led.auditVerify();
```

This implementation shares no code with the Python one. Both are held to
[`spec/vectors.json`](../spec/vectors.json), and CI runs a live handshake where
Python mints a wallet and this package spends it.

```bash
node --test test/
```

Apache-2.0.
