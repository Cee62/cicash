#!/usr/bin/env python3
"""Emit deterministic conformance vectors.

A spec nobody can check is a blog post. These vectors let an implementation in
any language prove byte-for-byte agreement on the parts that must not drift:
caveat serialisation, the signature chain, the request string a proof commits
to, and the receipt hash chain.

    python3 tools/gen_vectors.py > spec/vectors.json
"""

import json
import sys

sys.path.insert(0, ".")

from agentcash.caveats import ser, MAX_TOTAL, MAX_PER_TX, RATE, EXPIRES, PAYEES, PURPOSE
from agentcash.models import Receipt, digest
from agentcash.protocol import _sign
from agentcash.token import mint, verify_sig, canonical_request

ROOT_KEY = bytes.fromhex("00" * 32)
MERCHANT_KEY = bytes.fromhex("11" * 32)
BINDING = {"alg": "ed25519",
           "pub": "3b6a27bcceb6a42d62a3a8d02a6f0d73653215771de243a63ac048a18b59da29"}
CHILD_BINDING = {"alg": "ed25519",
                 "pub": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"}


def main():
    caveats = [
        ser(MAX_TOTAL, 50_000_000),
        ser(MAX_PER_TX, 5_000_000),
        ser(RATE, {"max_amount": 20_000_000, "max_count": 4, "window_s": 60}),
        ser(EXPIRES, 1800000000.0),
        ser(PAYEES, ["api.gpu", "api.search"]),
        ser(PURPOSE, ["research"]),
    ]
    root = mint(ROOT_KEY, "acme", "tok_root", BINDING, caveats)
    assert verify_sig(ROOT_KEY, root)

    child = root.delegate("tok_child", CHILD_BINDING, [ser(MAX_TOTAL, 5_000_000)])
    assert verify_sig(ROOT_KEY, child)
    assert child.lineage == ("tok_root", "tok_child")

    quote = {"quote_id": "q_demo", "payee": "api.search", "amount": 2_000_000,
             "purpose": "research", "expires_at": 1700000060.0}

    r1 = Receipt("rcpt_1", 1700000001.0, "acme", ("tok_root",), "api.search",
                 2_000_000, "research", "q_demo", "run/1", "genesis").seal()
    r2 = Receipt("rcpt_2", 1700000002.0, "acme", ("tok_root", "tok_child"),
                 "api.gpu", 1_500_000, "research", "q_two", "run/2", r1.hash).seal()

    out = {
        "version": "0.2.0",
        "canonical_caveats": caveats,
        "token_root": root.to_dict(),
        "token_child": child.to_dict(),
        "child_lineage": list(child.lineage),
        "child_scoped": [[o, k, v] for (o, k, v) in child.scoped()],
        "canonical_request": canonical_request(
            "tok_child", "api.search", 2_000_000, "research", "run/1"),
        "quote_payload": quote,
        "quote_sig_hmac_sha256": _sign(MERCHANT_KEY, quote),
        "receipt_chain": [r1.to_dict(), r2.to_dict()],
        "digest_of_r1_body": digest(r1.body()),
        "inputs": {
            "root_key_hex": ROOT_KEY.hex(),
            "merchant_key_hex": MERCHANT_KEY.hex(),
            "binding_root": BINDING,
            "binding_child": CHILD_BINDING,
        },
    }
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
