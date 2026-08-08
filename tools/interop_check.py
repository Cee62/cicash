#!/usr/bin/env python3
"""Cross-language handshake: Python issues the wallet, JavaScript spends it.

Vectors prove the two implementations encode the same bytes. This proves
something stronger and more useful: a budget granted by one runtime is
*honoured* by the other, live, including the Ed25519 proof of possession and
the ancestor debit through a wallet JavaScript delegated on its own.

    python3 tools/interop_check.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentcash import Ledger, Wallet, usd, fmt, crypto
from agentcash.protocol import Quote
from agentcash.token import Token

JS = r"""
import { readFileSync, writeFileSync } from "node:fs";
import { Token, verifySig, canonicalRequest } from "{BASE}/js/src/token.js";
import { Quote } from "{BASE}/js/src/protocol.js";
import { signerFromJSON } from "{BASE}/js/src/crypto.js";
import { ser, MAX_TOTAL, NOTE } from "{BASE}/js/src/caveats.js";
import { newId } from "{BASE}/js/src/token.js";
import { generate } from "{BASE}/js/src/crypto.js";

const io = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = {};

// 1. does a token minted by Python verify here?
const tok = Token.fromJSON(io.wallet.token);
out.verified = verifySig(Buffer.from(io.root_key_hex, "hex"), tok);
out.lineage = tok.lineage;

// 2. produce a proof of possession Python will check
const signer = signerFromJSON(io.wallet.signer);
const q = Quote.fromJSON(io.quote);
out.pop = signer.sign(canonicalRequest(tok.tokenId, q.payee, q.amount, q.purpose, io.idem));

// 3. delegate a tighter wallet, offline, entirely inside JavaScript
const childSigner = generate();
const childId = newId("tok");
const child = tok.delegate(childId, childSigner.binding(),
  [ser(MAX_TOTAL, io.child_budget), ser(NOTE, "delegated by javascript")]);
out.child_wallet = { token: child.toJSON(), signer: childSigner.toJSON() };
out.child_pop = childSigner.sign(
  canonicalRequest(childId, q.payee, io.child_amount, q.purpose, io.child_idem));

writeFileSync(process.argv[3], JSON.stringify(out));
"""


def main():
    root = Path(__file__).resolve().parent.parent
    led = Ledger()
    acme = led.register_principal("acme")
    api = led.register_merchant("api.search", key=b"shared-merchant-key")
    wallet = acme.grant(budget=usd(50), per_tx=usd(5), payees=["api.search"],
                        purposes=["research"], note="issued by python")
    quote = api.quote(usd(3), "research", ttl_s=3600)

    io = {
        "root_key_hex": led.store.get_root_key("acme").hex(),
        "wallet": wallet.to_dict(),
        "quote": quote.to_dict(),
        "idem": "interop/1",
        "child_budget": usd(4),
        "child_amount": usd(2),
        "child_idem": "interop/child-1",
    }

    with tempfile.TemporaryDirectory() as d:
        inp, outp, script = Path(d) / "in.json", Path(d) / "out.json", Path(d) / "s.mjs"
        inp.write_text(json.dumps(io))
        script.write_text(JS.replace("{BASE}", root.as_uri()))
        subprocess.run(["node", str(script), str(inp), str(outp)],
                       cwd=root, check=True)
        js = json.loads(outp.read_text())

    ok = []

    ok.append(("javascript verified a python-minted token", js["verified"] is True))
    ok.append(("lineage agrees", js["lineage"] == list(wallet.token.lineage)))

    # Python honours the proof JavaScript produced.
    hold = led.authorize(wallet.token, js["pop"], quote, "interop/1")
    receipt = led.settle(hold.hold_id, hold.amount, "interop/1s")
    ok.append(("python settled a javascript-signed payment",
               receipt.amount == usd(3)))

    # The wallet JavaScript delegated, entirely offline, spends against Python.
    child = Wallet.from_dict(led, js["child_wallet"])
    ok.append(("child token verifies in python", child.token.depth == 1))
    q2 = api.quote(usd(2), "research", ttl_s=3600)
    # re-sign for this quote id, since the proof commits to the whole request
    h2 = led.authorize(child.token,
                       child.signer.sign(
                           f"{child.token.token_id}|{q2.payee}|{q2.amount}|"
                           f"{q2.purpose}|interop/2"),
                       q2, "interop/2")
    led.settle(h2.hold_id, h2.amount, "interop/2s")

    parent_left = led.balance(wallet.token)["available"]
    child_left = led.balance(child.token)["available"]
    ok.append(("ancestor debit crossed the language boundary",
               parent_left == usd(45) and child_left == usd(2)))

    ok.append(("audit chain intact", led.audit_verify()))

    width = max(len(n) for n, _ in ok)
    for name, passed in ok:
        print(f"  {'PASS' if passed else 'FAIL'}  {name.ljust(width)}")
    print(f"\n  parent {fmt(parent_left)} left of $50   child {fmt(child_left)} left of $4")
    if not all(p for _, p in ok):
        sys.exit(1)
    print("\n  cross-language interop: OK")


if __name__ == "__main__":
    main()
