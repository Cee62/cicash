# agentcash-protocol

JavaScript implementation of [agentcash](../README.md) — a budget you lend to an
AI agent, not money you give it.

`node:crypto` only. No dependencies. Node >= 18.

```js
import { Ledger, usd, Denied } from "agentcash-protocol";

const led   = new Ledger();
const acme  = led.registerPrincipal("acme");
const api   = led.registerMerchant("api.search");

const agent = acme.grant({
  budget: usd(50), perTx: usd(5),
  rate: { max_count: 20, window_s: 60 },
  payees: ["api.search"], purposes: ["research"],
});

agent.pay(api.quote(usd(2), "research"), "run1/step3");
const sub = agent.delegate({ budget: usd(5) });   // offline, tighter only
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
