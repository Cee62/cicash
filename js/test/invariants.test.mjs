// Behavioural parity: the same six invariants the Python suite proves.
// Written against the spec, not ported from the other implementation.

import { test } from "node:test";
import assert from "node:assert/strict";
import { Ledger, Wallet, ci, Denied, crypto } from "../src/index.js";

function clockAt(t0 = 1_000_000) {
  const c = () => c.t;
  c.t = t0;
  c.advance = s => { c.t += s; };
  return c;
}

function setup(opts = {}) {
  const clock = clockAt();
  const led = new Ledger({ clock });
  const p = led.registerPrincipal("acme");
  const api = led.registerMerchant("api.search");
  const w = p.grant({
    budget: ci(50), payees: ["api.search"], purposes: ["research"], ...opts,
  });
  return { clock, led, p, api, w };
}

test("happy path and balance", () => {
  const { api, w } = setup();
  assert.equal(w.balance().available, ci(50));
  const r = w.pay(api.quote(ci(2), "research"), "run1/step1");
  assert.equal(r.amount, ci(2));
  assert.equal(w.balance().available, ci(48));
});

test("retries are free", () => {
  const { led, api, w } = setup();
  const q = api.quote(ci(4), "research");
  const a = w.pay(q, "run1/step7");
  const b = w.pay(q, "run1/step7");
  assert.equal(a.receipt_id, b.receipt_id);
  assert.equal(led.receipts.length, 1);
  assert.equal(w.balance().available, ci(46));
});

test("a child cannot escape the parent cap by forking siblings", () => {
  const { api, w } = setup({ budget: ci(10) });
  const a = w.delegate({ budget: ci(10) });
  const b = w.delegate({ budget: ci(10) });
  a.pay(api.quote(ci(6), "research"), "a1");
  assert.throws(() => b.pay(api.quote(ci(6), "research"), "b1"), e => {
    assert.equal(e.reason, "TOTAL_EXHAUSTED");
    assert.equal(e.owner, w.token.tokenId);
    return true;
  });
});

test("delegation is a ratchet", () => {
  const { w } = setup({ perTx: ci(5) });
  assert.throws(() => w.delegate({ budget: ci(500) }), /WIDENING_REFUSED/);
  assert.throws(() => w.delegate({ budget: ci(5), payees: ["attacker.xyz"] }),
    /WIDENING_REFUSED/);
});

test("a widening caveat forced past delegate() is still inert", () => {
  const { led, api, w } = setup({ budget: ci(10) });
  const forced = new Wallet(led,
    w.token.attenuate(['max_total:' + ci(9999)]), w.signer);
  assert.throws(() => forced.pay(api.quote(ci(50), "research"), "x1"),
    /TOTAL_EXHAUSTED/);
});

test("a leaked token without its key buys nothing", () => {
  const { led, api, w } = setup();
  assert.throws(() => led.authorize(w.token, "deadbeef",
    api.quote(ci(1), "research"), "atk"), e => {
    assert.equal(e.reason, "POP_INVALID");
    assert.equal(e.action, "ESCALATE");
    return true;
  });
});

test("a captured proof cannot be re-aimed at another payment", () => {
  const { led, api, w } = setup();
  const q1 = api.quote(ci(1), "research");
  const q2 = api.quote(ci(9), "research");
  assert.throws(() => led.authorize(w.token, w._pop(q1, "k"), q2, "k"),
    /POP_INVALID/);
});

test("injected payee is refused with a REPLAN action", () => {
  const { led, api, w } = setup();
  const attacker = led.registerMerchant("attacker.xyz");
  assert.throws(() => w.pay(attacker.quote(ci(900), "research"), "inj1"), e => {
    assert.equal(e.reason, "PAYEE_NOT_ALLOWED");
    assert.equal(e.action, "REPLAN");
    assert.ok(e.hint.length > 0);
    return true;
  });
});

test("rate cap stops a loop and says when to retry", () => {
  const { clock, api, w } = setup({ rate: { max_count: 3, window_s: 60 } });
  for (let i = 0; i < 3; i++) w.pay(api.quote(ci(1), "research"), "loop" + i);
  let retryAfter = null;
  assert.throws(() => w.pay(api.quote(ci(1), "research"), "loop3"), e => {
    assert.equal(e.reason, "RATE_LIMITED");
    assert.equal(e.action, "RETRY_AFTER");
    retryAfter = e.retry_after;
    return true;
  });
  assert.ok(retryAfter > 0);
  clock.advance(retryAfter + 0.1);
  w.pay(api.quote(ci(1), "research"), "loop4");
});

test("revoking a parent kills the whole subtree", () => {
  const { p, api, w } = setup();
  const a = w.delegate({ budget: ci(10) });
  const b = a.delegate({ budget: ci(5) });
  b.pay(api.quote(ci(1), "research"), "ok1");
  p.revoke(w);
  for (const wallet of [w, a, b]) {
    assert.throws(() => wallet.pay(api.quote(ci(1), "research"),
      "post" + wallet.token.tokenId), /REVOKED/);
  }
  assert.equal(b.balance().revoked, true);
});

test("holds reserve funds and expire", () => {
  const { clock, api, w } = setup();
  w.authorize(api.quote(ci(10), "research"), "k1");
  assert.equal(w.balance().available, ci(40));
  clock.advance(61);
  assert.equal(w.balance().available, ci(50));
});

test("receipt chain verifies and detects tampering", () => {
  const { led, api, w } = setup();
  const sub = w.delegate({ budget: ci(10) });
  w.pay(api.quote(ci(1), "research"), "a1");
  sub.pay(api.quote(ci(2), "research"), "a2");
  assert.ok(led.auditVerify());
  assert.equal(led.statement(sub.token.tokenId).length, 1);
  assert.equal(led.statement(w.token.tokenId).length, 2);
  led.receipts[0].amount = ci(999);
  assert.throws(() => led.auditVerify(), /receipt chain breaks/);
});

test("wallet exposes no way to widen its own budget", () => {
  const { w } = setup();
  for (const forbidden of ["setBudget", "raiseLimit", "transferTo", "topUp"]) {
    assert.equal(typeof w[forbidden], "undefined");
  }
});
