"""Operator CLI. The principal's side of the fence.

Everything here widens or inspects. Nothing an agent runs lives in this file -
that separation is the point, and it is why `cicash grant` is a shell
command a human types and `budget_check` is a tool a model calls.

    python3 -m cicash.cli grant --db ac.db --budget 50 --out wallet.json
    python3 -m cicash.cli balance --db ac.db --wallet wallet.json
    python3 -m cicash.cli revoke  --db ac.db --wallet wallet.json
    python3 -m cicash.cli audit   --db ac.db
"""

import argparse
import json
import sys

from .ledger import Ledger, Wallet
from .money import ci, fmt


def _led(a):
    return Ledger.sqlite(a.db) if a.db else Ledger()


def cmd_grant(a):
    led = _led(a)
    p = led.register_principal(a.principal)
    for m in (a.merchants or "").split(","):
        if m:
            led.register_merchant(m)
    rate = None
    if a.rate_count or a.rate_amount:
        rate = {"max_count": a.rate_count,
                "max_amount": ci(a.rate_amount) if a.rate_amount else None,
                "window_s": a.rate_window}
    w = p.grant(
        budget=ci(a.budget),
        per_tx=ci(a.per_tx) if a.per_tx else None,
        rate=rate,
        ttl_s=a.ttl_h * 3600 if a.ttl_h else None,
        payees=[x for x in (a.payees or "").split(",") if x] or None,
        purposes=[x for x in (a.purposes or "").split(",") if x] or None,
        note=a.note,
    )
    blob = json.dumps(w.to_dict(), indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(blob)
        import os
        os.chmod(a.out, 0o600)
        print(f"wrote {a.out}  (mode 600 - this file is a credential)")
        print(f"token {w.token.token_id}   budget {fmt(ci(a.budget))}")
    else:
        print(blob)


def _wallet(a):
    with open(a.wallet) as f:
        return Wallet.from_dict(_led(a), json.load(f))


def cmd_balance(a):
    print(json.dumps(_wallet(a).balance(), indent=2))


def cmd_revoke(a):
    w = _wallet(a) if a.wallet else None
    tid = a.token_id or w.token.token_id
    _led(a).revoke(tid)
    print(f"revoked {tid} and every wallet delegated from it")


def cmd_receipts(a):
    led = _led(a)
    rs = led.statement(a.token_id) if a.token_id else led.receipts
    print(f"{'receipt':<24}{'payee':<16}{'amount':>10}  {'purpose':<14} depth")
    for r in rs:
        print(f"{r.receipt_id:<24}{r.payee:<16}{fmt(r.amount):>10}  "
              f"{r.purpose:<14} {len(r.lineage)-1}")
    print(f"\n{len(rs)} receipts, total {fmt(sum(r.amount for r in rs))}")


def cmd_audit(a):
    led = _led(a)
    try:
        led.audit_verify()
        print(f"✅ receipt chain verifies ({len(led.receipts)} receipts)")
    except Exception as e:
        print(f"⛔ {e}")
        sys.exit(1)


def cmd_profile(a):
    print(json.dumps(_led(a).security_profile(), indent=2))


def cmd_serve(a):
    from .service import build_demo, serve
    led, api = build_demo(a.db)
    serve(api, a.host, a.port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cicash")
    ap.add_argument("--db", default=None, help="sqlite path (omit = in-memory)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grant", help="issue a bounded wallet to an agent")
    g.add_argument("--principal", default="default")
    g.add_argument("--budget", type=float, required=True, help="USD")
    g.add_argument("--per-tx", type=float, default=None)
    g.add_argument("--rate-count", type=int, default=None)
    g.add_argument("--rate-amount", type=float, default=None)
    g.add_argument("--rate-window", type=int, default=60)
    g.add_argument("--ttl-h", type=float, default=None)
    g.add_argument("--payees", default=None, help="comma separated allowlist")
    g.add_argument("--purposes", default=None, help="comma separated allowlist")
    g.add_argument("--merchants", default=None, help="register these payees too")
    g.add_argument("--note", default="")
    g.add_argument("--out", default=None)
    g.set_defaults(fn=cmd_grant)

    b = sub.add_parser("balance"); b.add_argument("--wallet", required=True)
    b.set_defaults(fn=cmd_balance)

    r = sub.add_parser("revoke")
    r.add_argument("--wallet", default=None)
    r.add_argument("--token-id", default=None)
    r.set_defaults(fn=cmd_revoke)

    c = sub.add_parser("receipts"); c.add_argument("--token-id", default=None)
    c.set_defaults(fn=cmd_receipts)

    sub.add_parser("audit").set_defaults(fn=cmd_audit)
    sub.add_parser("profile").set_defaults(fn=cmd_profile)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8402)
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
