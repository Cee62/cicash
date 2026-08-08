"""Money is integers. Always.

The unit is the *micro* (µ) = 1e-6 of the settlement unit.
Floats never touch a balance — an agent that retries 10,000 times must not
accumulate float drift into a real overdraft.
"""

MICRO = 1_000_000


def usd(amount) -> int:
    """Human number -> micro-units. usd(0.0001) == 100"""
    return int(round(float(amount) * MICRO))


def fmt(micro: int) -> str:
    """micro-units -> readable string, without lying about precision."""
    if micro is None:
        return "∞"
    sign = "-" if micro < 0 else ""
    m = abs(int(micro))
    whole, frac = divmod(m, MICRO)
    s = f"{sign}${whole:,}"
    if frac:
        s += f".{frac:06d}".rstrip("0")
    return s
