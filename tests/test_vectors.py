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

    def test_encoder_refuses_floats_rather_than_guessing(self):
        """SPEC 2.1. A rule only one implementation enforces catches nobody.

        This was a real gap: for one release the JavaScript encoder refused a
        float and the Python one did not, so Python could mint
        `expires:1800000000.5` that the JavaScript verifier then rejected with
        no way to trace the refusal back to its cause.
        """
        from cicash.canonical import canonical
        for bad in (1.5, 1800000000.0, float("1e30")):
            with self.assertRaises(ValueError):
                canonical({"x": bad})
        with self.assertRaises(ValueError):
            canonical([1, [2, 2.5]])
        with self.assertRaises(ValueError):
            ser("expires", 1800000000.5)
        # integers of any size are fine
        self.assertEqual(canonical({"x": 1800000000}), '{"x":1800000000}')

    def test_encoder_emits_raw_utf8(self):
        """SPEC 2.2. Python escapes non-ASCII by default; the spec does not."""
        from cicash.canonical import canonical
        self.assertEqual(canonical("\u0e07\u0e1a"), '"\u0e07\u0e1a"')
        self.assertEqual(ser("note", "\u0e07\u0e1a\u0e27\u0e34\u0e08\u0e31\u0e22 caf\u00e9 \U0001f512"),
                         self.v["canonical_unicode_note"])

    def test_tampering_a_vector_receipt_breaks_it(self):
        r = Receipt.from_dict(self.v["receipt_chain"][0])
        r.amount += 1
        self.assertNotEqual(digest(r.body()), r.hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
