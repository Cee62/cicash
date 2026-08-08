"""Caveats = the constraints written onto a budget token.

Serialisation must be byte-stable, because the signature chain is computed over
these exact strings. Sorted keys, no whitespace, no float formatting surprises.

Design rule: caveats are *conjunctive*. Every caveat in the chain must pass.
That is what makes delegation attenuation-only for free — appending
`max_total = 999999` to a token that already carries `max_total = 100` does
nothing, because both are evaluated and the tighter one wins. There is no
syntax in this system that can loosen a constraint. Not "should not". Cannot.
"""

from .canonical import canonical

# --- caveat kinds -----------------------------------------------------------
SUB = "sub"                # marks a delegation boundary; value = new token id
CNF = "cnf"                # proof-of-possession binding; value = sha256(secret)
MAX_TOTAL = "max_total"    # cumulative cap over this token AND its whole subtree
MAX_PER_TX = "max_per_tx"  # cap on a single payment
RATE = "rate"              # {max_count, max_amount, window_s} - the loop killer
EXPIRES = "expires"        # unix ts
PAYEES = "payees"          # allowlist of counterparties
PURPOSE = "purpose"        # allowlist of purpose tags
NOTE = "note"              # non-enforcing, for the audit trail

STATEFUL = (MAX_TOTAL, RATE)   # need the ledger's counters to evaluate
STATELESS = (MAX_PER_TX, EXPIRES, PAYEES, PURPOSE)


def ser(kind: str, value) -> str:
    return kind + ":" + canonical(value)


def de(caveat: str):
    import json
    kind, _, raw = caveat.partition(":")
    return kind, json.loads(raw)


def narrower_or_equal(kind, new, old) -> bool:
    """Is `new` at least as tight as `old`?

    Used only to fail *loudly* at delegation time. Enforcement never relies on
    this - see the module docstring - but silently accepting a widening caveat
    that will be ignored later is a trap for whoever wrote it.
    """
    if kind in (MAX_TOTAL, MAX_PER_TX, EXPIRES):
        return new <= old
    if kind in (PAYEES, PURPOSE):
        return set(new) <= set(old)
    if kind == RATE:
        if new.get("window_s") != old.get("window_s"):
            return True  # different windows are not comparable; conjunction handles it
        for f in ("max_count", "max_amount"):
            a, b = new.get(f), old.get(f)
            if b is not None and (a is None or a > b):
                return False
        return True
    return True
