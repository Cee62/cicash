#!/usr/bin/env python3
"""Build a single self-contained .py an agent can fetch and run with no install.

Distribution for agents has a different shape than distribution for people. A
person runs `pip install` and reads a README. An agent lands in a sandbox with
no network policy it controls, no package manager it is allowed to invoke, and
one shot at proving the thing works. So the unit of distribution is: **one file,
one command, prints its own proof.**

The package is embedded as a base64 zip rather than concatenated source. Naive
concatenation breaks on the `import * as cv` style namespacing this codebase
uses, and it breaks silently - which is the failure mode this project treats as
worse than a crash. A zip is byte-exact by construction, and the loader checks
its own digest before trusting it.

    python3 tools/build_single_file.py
"""

import base64
import hashlib
import io
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "cicash"
OUT = ROOT / "dist" / "cicash_single.py"

HEADER = '''#!/usr/bin/env python3
"""CIcash {version} - the whole library in one file. No install, no dependencies.

    curl -sL <url> -o cicash_single.py && python3 cicash_single.py

Running it executes a self-test that proves the invariants rather than
asserting them. Importing it gives you the full API:

    from cicash_single import Ledger, ci, Denied

A budget you lend to an AI agent, not money you give it: bounded, expiring,
revocable, auditable, and worthless once stolen.

Spec + conformance vectors: spec/SPEC.md in the source repository.
Apache-2.0. Ed25519 is used when `cryptography` is present; otherwise the
HMAC fallback is used and `Ledger.security_profile()` says so plainly.
"""

import base64
import hashlib
import os
import sys
import tempfile

_SHA256 = "{sha}"
_ZIP = (
{payload}
)


def _install():
    blob = base64.b64decode("".join(_ZIP))
    if hashlib.sha256(blob).hexdigest() != _SHA256:
        raise RuntimeError("cicash_single: embedded payload failed its digest check")
    d = os.path.join(tempfile.gettempdir(), "cicash_" + _SHA256[:16])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "cicash.zip")
    if not os.path.exists(p):
        tmp = p + ".part"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, p)
    if p not in sys.path:
        sys.path.insert(0, p)


_install()

from cicash import *                    # noqa: E402,F401,F403
from cicash import __version__          # noqa: E402
'''

SELFTEST = '''

def _selftest():
    """Prove the invariants. An agent that runs this knows what it has."""
    from cicash import Ledger, Wallet, ci, fmt, Denied, crypto

    clock = type("C", (), {"t": 1_000_000.0})()
    now = lambda: clock.t

    led = Ledger(clock=now)
    acme = led.register_principal("acme")
    api = led.register_merchant("api.search")
    other = led.register_merchant("attacker.xyz")
    w = acme.grant(budget=ci(50), per_tx=ci(5),
                   rate={"max_count": 3, "window_s": 60},
                   payees=["api.search"], purposes=["research"])

    checks = []

    def check(name, fn):
        try:
            checks.append((name, bool(fn())))
        except Exception as e:                       # a failure is a result too
            checks.append((name, f"ERROR {e!r}"))

    r = w.pay(api.quote(ci(2), "research"), idem_key="s/1")
    check("a payment settles and the balance moves",
          lambda: r.amount == ci(2) and w.balance()["available"] == ci(48))

    check("retrying the same idem_key charges once",
          lambda: w.pay(api.quote(ci(2), "research"), idem_key="s/1").receipt_id
                  == r.receipt_id and w.balance()["available"] == ci(48))

    sub = w.delegate(budget=ci(5), note="sub-agent")
    sub.pay(api.quote(ci(1), "research"), idem_key="s/2")
    check("a child's spend debits its parent too",
          lambda: sub.balance()["available"] == ci(4)
                  and w.balance()["available"] == ci(47))

    def widen():
        try:
            sub.delegate(budget=ci(500))
            return False
        except Denied as e:
            return e.reason == "WIDENING_REFUSED"
    check("delegation is a ratchet, never looser", widen)

    def inject():
        try:
            w.pay(other.quote(ci(900), "research"), idem_key="s/3")
            return False
        except Denied as e:
            return e.reason == "PAYEE_NOT_ALLOWED" and e.action == "REPLAN"
    check("an injected payee is refused, with an action", inject)

    def leaked():
        try:
            led.authorize(w.token, "deadbeef", api.quote(ci(1), "research"), "s/4")
            return False
        except Denied as e:
            return e.reason == "POP_INVALID"
    check("a token without its key buys nothing", leaked)

    def looped():
        try:
            for i in range(6):
                w.pay(api.quote(ci(1), "research"), idem_key="loop/%d" % i)
            return False
        except Denied as e:
            return e.reason == "RATE_LIMITED" and e.retry_after > 0
    check("a runaway loop is stopped, and told when to retry", looped)

    acme.revoke(w)

    def revoked():
        try:
            sub.pay(api.quote(ci(1), "research"), idem_key="s/5")
            return False
        except Denied as e:
            return e.reason == "REVOKED"
    check("revoking the parent kills the whole subtree", revoked)

    check("the receipt chain verifies", led.audit_verify)

    led.receipts[0].amount = ci(9999)

    def tamper():
        try:
            led.audit_verify()
            return False
        except Exception:
            return True
    check("an edited receipt is detected", tamper)

    check("the wallet exposes no way to widen itself",
          lambda: not any(hasattr(w, n) for n in
                          ("set_budget", "raise_limit", "transfer_to", "top_up")))

    width = max(len(n) for n, _ in checks)
    ok = True
    print("CIcash %s  self-test" % __version__)
    print("crypto: %s" % crypto.profile()["default_alg"])
    print()
    for name, res in checks:
        good = res is True
        ok = ok and good
        print("  %s  %s%s" % ("PASS" if good else "FAIL", name.ljust(width),
                              "" if good else "   <- %s" % res))
    print()
    print("  %d/%d invariants hold" % (sum(1 for _, r in checks if r is True), len(checks)))
    return ok


if __name__ == "__main__":
    sys.exit(0 if _selftest() else 1)
'''


def main():
    buf = io.BytesIO()
    # Deterministic: sorted names, fixed timestamps, so the same source always
    # produces the same file and the same digest.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(PKG.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            info = zipfile.ZipInfo(str(p.relative_to(ROOT)), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    blob = buf.getvalue()
    sha = hashlib.sha256(blob).hexdigest()
    b64 = base64.b64encode(blob).decode()

    lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]
    payload = "\n".join('    "%s"' % ln for ln in lines)

    sys.path.insert(0, str(ROOT))
    from cicash import __version__

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        HEADER.format(version=__version__, sha=sha, payload=payload) + SELFTEST)
    OUT.chmod(0o755)
    print("%s  %s  %.1f KB  sha256:%s" % (
        OUT.relative_to(ROOT), __version__, OUT.stat().st_size / 1024, sha[:16]))


if __name__ == "__main__":
    main()
