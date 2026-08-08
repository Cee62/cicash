"""The CIcash — the unit of account.

Money is integers. Always.

    1 CIcash = 1,000,000 uCIcash

Amounts are carried as integer micro-units everywhere: in caveats, in quotes,
in receipts, on the wire. Floats never touch a balance, because an agent that
retries ten thousand times must not accumulate drift into a real overdraft, and
because a float renders differently in Python and JavaScript - which broke
cross-language verification silently until it was made impossible (SPEC 2.1).

Naming the unit changes no bytes. Amounts were always bare integers in the wire
format, so `spec/vectors.json` is untouched and every token minted before the
unit had a name still verifies. The display name lives in `UNIT` alone; change
that one constant and every surface follows.

The CIcash is deliberately *not* an investment asset. If the unit appreciates,
agents hoard it and the payment layer dies - that is Gresham's law, and it is
exactly how Bitcoin stopped being cash and became a thing people keep instead.
Boring money is the goal.
"""

MICRO = 1_000_000

UNIT = "CIcash"
SUBUNIT = "uCIcash"


def ci(amount) -> int:
    """Human number -> integer micro-units.  ci(0.0001) == 100"""
    return int(round(float(amount) * MICRO))


def fmt(micro: int) -> str:
    """Integer micro-units -> readable string, without lying about precision."""
    if micro is None:
        return "unbounded"
    sign = "-" if micro < 0 else ""
    m = abs(int(micro))
    whole, frac = divmod(m, MICRO)
    s = f"{sign}{whole:,}"
    if frac:
        s += f".{frac:06d}".rstrip("0")
    return f"{s} {UNIT}"
