// Caveats are conjunctive. Every one in the chain must pass, and no later
// caveat replaces an earlier one - which is what makes delegation
// attenuation-only without needing any extra rule.

import { canonical } from "./canonical.js";

export const SUB = "sub", CNF = "cnf", MAX_TOTAL = "max_total",
  MAX_PER_TX = "max_per_tx", RATE = "rate", EXPIRES = "expires",
  PAYEES = "payees", PURPOSE = "purpose", NOTE = "note";

export const ser = (kind, value) => kind + ":" + canonical(value);

export function de(caveat) {
  const i = caveat.indexOf(":");
  return [caveat.slice(0, i), JSON.parse(caveat.slice(i + 1))];
}

const subset = (a, b) => a.every(x => b.includes(x));

export function narrowerOrEqual(kind, next, prev) {
  if (kind === MAX_TOTAL || kind === MAX_PER_TX || kind === EXPIRES) return next <= prev;
  if (kind === PAYEES || kind === PURPOSE) return subset(next, prev);
  if (kind === RATE) {
    if (next.window_s !== prev.window_s) return true;   // not comparable; conjunction handles it
    for (const f of ["max_count", "max_amount"]) {
      const a = next[f] ?? null, b = prev[f] ?? null;
      if (b !== null && (a === null || a > b)) return false;
    }
  }
  return true;
}
