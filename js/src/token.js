// The budget token: a macaroon-style chained MAC.
//
//   sig0 = HMAC(root_key, root_id + "|" + root_token_id)
//   sigN = HMAC(sigN-1, caveatN)
//
// Any holder can append a caveat offline, because the current signature is the
// key for the next link. Nobody can remove one, because that needs the
// previous signature, which needs the root key. Delegation is a ratchet.

import { createHmac, randomBytes } from "node:crypto";
import { ser, de, SUB, CNF } from "./caveats.js";

const mac = (key, msg) => createHmac("sha256", key).update(msg, "utf8").digest();

export const newId = prefix => `${prefix}_${randomBytes(8).toString("hex")}`;

export class Token {
  constructor(rootId, rootTokenId, caveats, sig) {
    this.root_id = rootId;
    this.root_token_id = rootTokenId;
    this.caveats = [...caveats];
    this.sig = sig;
  }

  get lineage() {
    const out = [this.root_token_id];
    for (const c of this.caveats) {
      const [k, v] = de(c);
      if (k === SUB) out.push(v);
    }
    return out;
  }

  get tokenId() { return this.lineage[this.lineage.length - 1]; }
  get depth() { return this.lineage.length - 1; }

  // Which link in the chain owns each caveat. An ancestor's max_total counts
  // its whole subtree; a child's counts only its own.
  scoped() {
    let owner = this.root_token_id;
    const out = [];
    for (const c of this.caveats) {
      const [k, v] = de(c);
      if (k === SUB) owner = v; else out.push([owner, k, v]);
    }
    return out;
  }

  find(kind) { return this.scoped().filter(([, k]) => k === kind).map(([o, , v]) => [o, v]); }

  _extend(added) {
    let s = Buffer.from(this.sig, "hex");
    for (const c of added) s = mac(s, c);
    return new Token(this.root_id, this.root_token_id,
                     [...this.caveats, ...added], s.toString("hex"));
  }

  attenuate(added) { return this._extend(added); }

  delegate(subTokenId, binding, added = []) {
    return this._extend([ser(SUB, subTokenId), ser(CNF, binding), ...added]);
  }

  toJSON() {
    return { root_id: this.root_id, root_token_id: this.root_token_id,
             caveats: this.caveats, sig: this.sig };
  }

  static fromJSON(d) {
    return new Token(d.root_id, d.root_token_id, d.caveats, d.sig);
  }
}

export function mint(rootKey, rootId, rootTokenId, binding, caveats) {
  const s = mac(rootKey, `${rootId}|${rootTokenId}`);
  return new Token(rootId, rootTokenId, [], s.toString("hex"))
    ._extend([ser(CNF, binding), ...caveats]);
}

export function verifySig(rootKey, token) {
  let s = mac(rootKey, `${token.root_id}|${token.root_token_id}`);
  for (const c of token.caveats) s = mac(s, c);
  return s.toString("hex") === token.sig;
}

// Everything the proof commits to. Change any field and the proof dies.
export const canonicalRequest = (tokenId, payee, amount, purpose, idemKey) =>
  `${tokenId}|${payee}|${Math.trunc(amount)}|${purpose}|${idemKey}`;
