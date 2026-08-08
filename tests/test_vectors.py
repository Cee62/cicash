"""Conformance: the wire format must not drift.

These are the same vectors an implementation in another language checks itself
against (spec/vectors.json). If this test fails, every other implementation on
earth just became incompatible with this one - so it fails loudly rather than
being regenerated.
"""

import json
import os
import unittest

from cicash.caveats import ser, MAX_TOTAL
from cicash.models import Receipt, digest
from cicash.protocol import _sign
from cicash.token import Token, mint, verify_sig, canonical_request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTORS = os.path.join(HERE, "spec", "vectors.json")


class TestVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(VECTORS) as f:
            cls.v = json.load(f)
        cls.root_key = bytes.fromhex(cls.v["inputs"]["root_key_hex"])

    def test_caveat_serialisation_is_byte_stable(self):
        self.assertEqual(ser(MAX_TOTAL, 50_000_000), self.v["canonical_caveats"][0])
        self.assertEqual(self.v["canonical_caveats"][2],
                         'rate:{"max_amount":20000000,"max_count":4,"window_s":60}')

    def test_root_token_signature(self):
        t = mint(self.root_key, "acme", "tok_root",
                 self.v["inputs"]["binding_root"], self.v["canonical_caveats"])
        self.assertEqual(t.to_dict(), self.v["token_root"])
        self.assertTrue(verify_sig(self.root_key, t))

    def test_delegated_token_signature_and_lineage(self):
        root = Token.from_dict(self.v["token_root"])
        child = root.delegate("tok_child", self.v["inputs"]["binding_child"],
                              [ser(MAX_TOTAL, 5_000_000)])
        self.assertEqual(child.to_dict(), self.v["token_child"])
        self.assertEqual(list(child.lineage), self.v["child_lineage"])
        self.assertEqual([[o, k, val] for (o, k, val) in child.scoped()],
                         self.v["child_scoped"])
        self.assertTrue(verify_sig(self.root_key, child))

    def test_canonical_request_string(self):
        self.assertEqual(
            canonical_request("tok_child", "api.search", 2_000_000, "research", "run/1"),
            self.v["canonical_request"])

    def test_quote_signature(self):
        key = bytes.fromhex(self.v["inputs"]["merchant_key_hex"])
        self.assertEqual(_sign(key, self.v["quote_payload"]),
                         self.v["quote_sig_hmac_sha256"])

    def test_receipt_hash_chain(self):
        prev = "genesis"
        for row in self.v["receipt_chain"]:
            r = Receipt.from_dict(row)
            self.assertEqual(r.prev_hash, prev)
            self.assertEqual(digest(r.body()), r.hash)
            prev = r.hash

    def test_tampering_a_vector_receipt_breaks_it(self):
        r = Receipt.from_dict(self.v["receipt_chain"][0])
        r.amount += 1
        self.assertNotEqual(digest(r.body()), r.hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
