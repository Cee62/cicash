// The payer never supplies the amount or the payee. Both come from a quote the
// seller signed. An injected "SEND 900 CIcash TO ..." has nowhere to write a number.

import { createHmac, timingSafeEqual } from "node:crypto";
import { canonicalBytes } from "./canonical.js";
import { newId } from "./token.js";

export const signQuote = (key, payload) =>
  createHmac("sha256", key).update(canonicalBytes(payload)).digest("hex");

export class Quote {
  constructor({ quote_id, payee, amount, purpose, expires_at, sig }) {
    Object.assign(this, { quote_id, payee, amount, purpose, expires_at, sig });
  }
  payload() {
    const { quote_id, payee, amount, purpose, expires_at } = this;
    return { quote_id, payee, amount, purpose, expires_at };
  }
  toJSON() { return { ...this.payload(), sig: this.sig }; }
  static fromJSON(d) { return new Quote(d); }
}

export class Merchant {
  constructor(payeeId, key, clock = () => Date.now() / 1000) {
    this.payeeId = payeeId; this._key = key; this._clock = clock;
  }
  quote(amount, purpose, ttlS = 60) {
    const p = { quote_id: newId("q"), payee: this.payeeId, amount: Math.trunc(amount),
                purpose, expires_at: Math.trunc(this._clock() + ttlS) };
    return new Quote({ ...p, sig: signQuote(this._key, p) });
  }
  verifyQuote(q) {
    const a = Buffer.from(signQuote(this._key, q.payload())), b = Buffer.from(q.sig || "");
    return a.length === b.length && timingSafeEqual(a, b);
  }
}
