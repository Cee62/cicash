"""Tests for the properties v0.1 could not claim: durability, offline
delegation, and a debit that does not tear under concurrency."""

import os
import shutil
import tempfile
import threading
import unittest

from agentcash import Ledger, SqliteStore, Wallet, usd, Denied, crypto


class TestDurability(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "ac.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _open(self):
        return Ledger.sqlite(self.path)

    def test_state_survives_process_restart(self):
        led = self._open()
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search", key=b"fixed-merchant-key")
        w = acme.grant(budget=usd(50), payees=["api.search"], purposes=["research"])
        w.pay(api.quote(usd(12), "research"), idem_key="k1")
        blob = w.to_dict()
        self.assertEqual(w.balance()["available"], usd(38))

        del led                                   # process dies here
        led2 = self._open()                       # ...and comes back
        api2 = led2.register_merchant("api.search", key=b"fixed-merchant-key")
        w2 = Wallet.from_dict(led2, blob)
        self.assertEqual(w2.balance()["available"], usd(38))

        w2.pay(api2.quote(usd(8), "research"), idem_key="k2")
        self.assertEqual(w2.balance()["available"], usd(30))
        self.assertTrue(led2.audit_verify())
        self.assertEqual(len(led2.receipts), 2)

    def test_idempotency_survives_restart(self):
        """The worst retry is the one that crosses a crash."""
        led = self._open()
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search", key=b"k")
        w = acme.grant(budget=usd(50), payees=["api.search"], purposes=["research"])
        q = api.quote(usd(5), "research", ttl_s=10_000)
        r1 = w.pay(q, idem_key="run/step-1")
        blob = w.to_dict()

        del led
        led2 = self._open()
        led2.register_merchant("api.search", key=b"k")
        w2 = Wallet.from_dict(led2, blob)
        r2 = w2.pay(q, idem_key="run/step-1")
        self.assertEqual(r1.receipt_id, r2.receipt_id)
        self.assertEqual(len(led2.receipts), 1)
        self.assertEqual(w2.balance()["available"], usd(45))

    def test_receipt_chain_persists_and_still_detects_tampering(self):
        led = self._open()
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search", key=b"k")
        w = acme.grant(budget=usd(50), payees=["api.search"], purposes=["research"])
        for i in range(3):
            w.pay(api.quote(usd(1), "research"), idem_key=f"k{i}")
        self.assertTrue(self._open().audit_verify())

        import sqlite3
        c = sqlite3.connect(self.path)
        c.execute("UPDATE receipts SET blob=replace(blob,'\"amount\": 1000000',"
                  "'\"amount\": 999000000') WHERE seq=2")
        c.commit()
        c.close()
        with self.assertRaises(Exception):
            self._open().audit_verify()


class TestOfflineDelegation(unittest.TestCase):
    @unittest.skipUnless(crypto.HAVE_ED25519, "ed25519 backend unavailable")
    def test_child_verifies_with_no_prior_registration(self):
        """The ledger has never seen this sub-agent's key before it spends.

        With ed25519 the child's public key rides inside the signature chain,
        so an agent with a dead uplink can still safely sub-contract.
        """
        led = Ledger()
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search")
        w = acme.grant(budget=usd(50), payees=["api.search"], purposes=["research"])
        sub = w.delegate(budget=usd(5))

        self.assertIsNone(led.store.get_binding_secret(sub.token.token_id))
        sub.pay(api.quote(usd(2), "research"), idem_key="s1")
        self.assertEqual(sub.balance()["available"], usd(3))
        self.assertEqual(w.balance()["available"], usd(48))

    @unittest.skipUnless(crypto.HAVE_ED25519, "ed25519 backend unavailable")
    def test_ledger_stores_no_private_material(self):
        led = Ledger()
        self.assertTrue(led.security_profile()["offline_delegation"])
        self.assertFalse(led.security_profile()["ledger_stores_private_material"])

    def test_hmac_fallback_still_works(self):
        led = Ledger()
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search")
        w = acme.grant(budget=usd(50), payees=["api.search"], purposes=["research"],
                       signer=crypto.HmacSigner())
        w.pay(api.quote(usd(1), "research"), idem_key="h1")
        self.assertEqual(w.balance()["available"], usd(49))

    @unittest.skipUnless(crypto.HAVE_ED25519, "ed25519 backend unavailable")
    def test_wrong_key_cannot_spend_a_valid_token(self):
        led = Ledger()
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search")
        w = acme.grant(budget=usd(50), payees=["api.search"], purposes=["research"])
        imposter = Wallet(led, w.token, crypto.generate())
        with self.assertRaises(Denied) as e:
            imposter.pay(api.quote(usd(1), "research"), idem_key="i1")
        self.assertEqual(e.exception.reason, "POP_INVALID")


class TestConcurrentDebit(unittest.TestCase):
    """The dangerous moment: many children settling against one parent cap.

    If the read-check-write span tears, the cap silently stops being a cap -
    a wrong answer with no error, which this project treats as worse than a
    crash. So we hammer it.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_parent_cap_holds_under_16_threads(self):
        path = os.path.join(self.dir, "race.db")
        led = Ledger.sqlite(path)
        acme = led.register_principal("acme")
        api = led.register_merchant("api.search", key=b"k")
        parent = acme.grant(budget=usd(100), payees=["api.search"],
                            purposes=["research"])
        kids = [parent.delegate(budget=usd(100)) for _ in range(16)]

        ok, denied = [], []
        lock = threading.Lock()

        def spend(i, kid):
            w = Wallet.from_dict(Ledger.sqlite(path), kid.to_dict())
            m = w.ledger.register_merchant("api.search", key=b"k")
            for j in range(10):
                try:
                    r = w.pay(m.quote(usd(1), "research", ttl_s=600),
                              idem_key=f"t{i}/{j}")
                    with lock:
                        ok.append(r.amount)
                except Denied:
                    with lock:
                        denied.append(1)

        threads = [threading.Thread(target=spend, args=(i, k))
                   for i, k in enumerate(kids)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(ok)
        self.assertEqual(total, usd(100), "parent cap leaked under concurrency")
        self.assertEqual(len(ok) + len(denied), 160)
        self.assertEqual(Ledger.sqlite(path).balance(parent.token)["available"], 0)
        self.assertTrue(Ledger.sqlite(path).audit_verify())


if __name__ == "__main__":
    unittest.main(verbosity=2)
