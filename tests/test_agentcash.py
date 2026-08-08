import unittest

from agentcash import Ledger, usd, Denied, AuditBroken, ESCALATE, REPLAN, RETRY_AFTER
from agentcash.token import Token


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def setup(budget=usd(50), **kw):
    clk = Clock()
    led = Ledger(clock=clk)
    p = led.register_principal("acme")
    api = led.register_merchant("api.search")
    kw.setdefault("payees", ["api.search"])
    kw.setdefault("purposes", ["research"])
    w = p.grant(budget=budget, **kw)
    return clk, led, p, api, w


class TestHappyPath(unittest.TestCase):
    def test_pay_and_balance(self):
        clk, led, p, api, w = setup()
        self.assertEqual(w.balance()["available"], usd(50))
        r = w.pay(api.quote(usd(2), "research"), idem_key="run1/step1")
        self.assertEqual(r.amount, usd(2))
        self.assertEqual(w.balance()["available"], usd(48))

    def test_settle_less_than_quoted(self):
        clk, led, p, api, w = setup()
        q = api.quote(usd(5), "research")
        h = w.authorize(q, "k1")
        r = w.settle(h, actual=usd(3), idem_key="k2")
        self.assertEqual(r.amount, usd(3))
        self.assertEqual(w.balance()["available"], usd(47))

    def test_settle_more_than_quoted_refused(self):
        clk, led, p, api, w = setup()
        h = w.authorize(api.quote(usd(5), "research"), "k1")
        with self.assertRaises(Denied) as e:
            w.settle(h, actual=usd(6), idem_key="k2")
        self.assertEqual(e.exception.reason, "OVER_QUOTE")

    def test_hold_reserves_funds_then_expires(self):
        clk, led, p, api, w = setup()
        w.authorize(api.quote(usd(10), "research"), "k1")
        self.assertEqual(w.balance()["available"], usd(40))   # held, not spent
        clk.advance(61)
        self.assertEqual(w.balance()["available"], usd(50))   # auto-released


class TestRetriesAreFree(unittest.TestCase):
    def test_same_idem_key_charges_once(self):
        clk, led, p, api, w = setup()
        q = api.quote(usd(4), "research")
        r1 = w.pay(q, idem_key="run1/step7")
        r2 = w.pay(q, idem_key="run1/step7")
        r3 = w.pay(q, idem_key="run1/step7")
        self.assertEqual(r1.receipt_id, r2.receipt_id)
        self.assertEqual(r2.receipt_id, r3.receipt_id)
        self.assertEqual(len(led.receipts), 1)
        self.assertEqual(w.balance()["available"], usd(46))


class TestAttenuationIsEconomic(unittest.TestCase):
    def test_child_spend_debits_parent(self):
        clk, led, p, api, w = setup()
        sub = w.delegate(budget=usd(5), note="summariser")
        sub.pay(api.quote(usd(2), "research"), idem_key="s1")
        self.assertEqual(sub.balance()["available"], usd(3))
        self.assertEqual(w.balance()["available"], usd(48))

    def test_cannot_escape_parent_cap_by_forking_children(self):
        clk, led, p, api, w = setup(budget=usd(10))
        a = w.delegate(budget=usd(10))
        b = w.delegate(budget=usd(10))
        a.pay(api.quote(usd(6), "research"), idem_key="a1")
        with self.assertRaises(Denied) as e:
            b.pay(api.quote(usd(6), "research"), idem_key="b1")
        self.assertEqual(e.exception.reason, "TOTAL_EXHAUSTED")
        self.assertEqual(e.exception.owner, w.token.token_id)

    def test_deep_chain_still_bound(self):
        clk, led, p, api, w = setup(budget=usd(10))
        cur = w
        for _ in range(5):
            cur = cur.delegate(budget=usd(10))
        self.assertEqual(cur.token.depth, 5)
        cur.pay(api.quote(usd(9), "research"), idem_key="d1")
        with self.assertRaises(Denied):
            cur.pay(api.quote(usd(2), "research"), idem_key="d2")

    def test_widening_refused_loudly(self):
        clk, led, p, api, w = setup(budget=usd(50), per_tx=usd(5))
        with self.assertRaises(Denied) as e:
            w.delegate(budget=usd(500))
        self.assertEqual(e.exception.reason, "WIDENING_REFUSED")
        with self.assertRaises(Denied):
            w.delegate(budget=usd(5), payees=["attacker.xyz"])

    def test_widening_would_be_inert_even_if_forced(self):
        """Belt and braces: append a looser caveat directly, bypassing delegate()."""
        clk, led, p, api, w = setup(budget=usd(10))
        from agentcash.caveats import ser, MAX_TOTAL
        from agentcash.ledger import Wallet
        forced = Wallet(led, w.token.attenuate([ser(MAX_TOTAL, usd(9999))]), w.signer)
        with self.assertRaises(Denied) as e:
            forced.pay(api.quote(usd(50), "research"), idem_key="x1")
        self.assertEqual(e.exception.reason, "TOTAL_EXHAUSTED")


class TestTokenIntegrity(unittest.TestCase):
    def test_removing_a_caveat_breaks_signature(self):
        clk, led, p, api, w = setup(budget=usd(10), per_tx=usd(1))
        stripped = Token(
            w.token.root_id, w.token.root_token_id,
            tuple(c for c in w.token.caveats if not c.startswith("max_per_tx")),
            w.token.sig,
        )
        from agentcash.ledger import Wallet
        bad = Wallet(led, stripped, w.signer)
        with self.assertRaises(Denied) as e:
            bad.pay(api.quote(usd(5), "research"), idem_key="t1")
        self.assertEqual(e.exception.reason, "SIGNATURE_INVALID")

    def test_leaked_token_without_secret_is_worthless(self):
        clk, led, p, api, w = setup()
        leaked = Token.from_dict(w.token.to_dict())      # e.g. copied out of a log
        with self.assertRaises(Denied) as e:
            led.authorize(leaked, "deadbeef", api.quote(usd(1), "research"), "atk")
        self.assertEqual(e.exception.reason, "POP_INVALID")
        self.assertEqual(e.exception.action, ESCALATE)

    def test_pop_is_bound_to_the_request(self):
        """A captured proof cannot be replayed against a different payment."""
        clk, led, p, api, w = setup()
        q1 = api.quote(usd(1), "research")
        q2 = api.quote(usd(9), "research")
        pop = w._pop(q1, "k")
        with self.assertRaises(Denied) as e:
            led.authorize(w.token, pop, q2, "k")
        self.assertEqual(e.exception.reason, "POP_INVALID")


class TestInjectionDefence(unittest.TestCase):
    def test_payee_allowlist_blocks_injected_recipient(self):
        clk, led, p, api, w = setup()
        attacker = led.register_merchant("attacker.xyz")
        q = attacker.quote(usd(900), "research")          # agent was talked into this
        with self.assertRaises(Denied) as e:
            w.pay(q, idem_key="inj1")
        self.assertEqual(e.exception.reason, "PAYEE_NOT_ALLOWED")
        self.assertEqual(e.exception.action, REPLAN)

    def test_purpose_allowlist(self):
        clk, led, p, api, w = setup()
        with self.assertRaises(Denied) as e:
            w.pay(api.quote(usd(1), "buy_gift_cards"), idem_key="inj2")
        self.assertEqual(e.exception.reason, "PURPOSE_NOT_ALLOWED")

    def test_agent_cannot_invent_a_price(self):
        clk, led, p, api, w = setup(per_tx=usd(5))
        with self.assertRaises(Denied) as e:
            w.pay(api.quote(usd(20), "research"), idem_key="inj3")
        self.assertEqual(e.exception.reason, "PER_TX_EXCEEDED")

    def test_forged_quote_rejected(self):
        clk, led, p, api, w = setup()
        q = api.quote(usd(1), "research")
        tampered = q.__class__(q.quote_id, q.payee, usd(500), q.purpose,
                               q.expires_at, q.sig)
        with self.assertRaises(Denied) as e:
            w.pay(tampered, idem_key="inj4")
        self.assertEqual(e.exception.reason, "QUOTE_FORGED")

    def test_stale_quote_rejected(self):
        clk, led, p, api, w = setup()
        q = api.quote(usd(1), "research", ttl_s=30)
        clk.advance(31)
        with self.assertRaises(Denied) as e:
            w.pay(q, idem_key="inj5")
        self.assertEqual(e.exception.reason, "QUOTE_EXPIRED")


class TestRunawayLoop(unittest.TestCase):
    def test_rate_cap_stops_the_loop_and_says_when_to_retry(self):
        clk, led, p, api, w = setup(rate={"max_count": 3, "max_amount": None, "window_s": 60})
        for i in range(3):
            w.pay(api.quote(usd(1), "research"), idem_key=f"loop{i}")
        with self.assertRaises(Denied) as e:
            w.pay(api.quote(usd(1), "research"), idem_key="loop3")
        self.assertEqual(e.exception.reason, "RATE_LIMITED")
        self.assertEqual(e.exception.action, RETRY_AFTER)
        self.assertGreater(e.exception.retry_after, 0)
        clk.advance(e.exception.retry_after + 0.1)
        w.pay(api.quote(usd(1), "research"), idem_key="loop4")

    def test_amount_rate_cap(self):
        clk, led, p, api, w = setup(rate={"max_count": None, "max_amount": usd(5), "window_s": 60})
        w.pay(api.quote(usd(4), "research"), idem_key="r1")
        with self.assertRaises(Denied) as e:
            w.pay(api.quote(usd(2), "research"), idem_key="r2")
        self.assertEqual(e.exception.reason, "RATE_LIMITED")


class TestRevocation(unittest.TestCase):
    def test_revoking_parent_kills_descendants_instantly(self):
        clk, led, p, api, w = setup()
        a = w.delegate(budget=usd(10))
        b = a.delegate(budget=usd(5))
        b.pay(api.quote(usd(1), "research"), idem_key="ok1")
        p.revoke(w)
        for wallet in (w, a, b):
            with self.assertRaises(Denied) as e:
                wallet.pay(api.quote(usd(1), "research"), idem_key="after" + wallet.token.token_id)
            self.assertEqual(e.exception.reason, "REVOKED")
            self.assertEqual(e.exception.action, ESCALATE)
        self.assertTrue(b.balance()["revoked"])

    def test_expiry(self):
        clk, led, p, api, w = setup(ttl_s=3600)
        clk.advance(3601)
        with self.assertRaises(Denied) as e:
            w.pay(api.quote(usd(1), "research"), idem_key="exp1")
        self.assertEqual(e.exception.reason, "EXPIRED")


class TestAudit(unittest.TestCase):
    def test_chain_verifies_and_detects_tampering(self):
        clk, led, p, api, w = setup()
        sub = w.delegate(budget=usd(10), note="sub")
        w.pay(api.quote(usd(1), "research"), idem_key="a1")
        sub.pay(api.quote(usd(2), "research"), idem_key="a2")
        self.assertTrue(led.audit_verify())

        self.assertEqual(len(led.statement(sub.token.token_id)), 1)
        self.assertEqual(len(led.statement(w.token.token_id)), 2)

        led.receipts[0].amount = usd(999)
        with self.assertRaises(AuditBroken):
            led.audit_verify()

    def test_receipt_binds_purpose_and_lineage(self):
        clk, led, p, api, w = setup()
        sub = w.delegate(budget=usd(10))
        r = sub.pay(api.quote(usd(2), "research"), idem_key="p1")
        self.assertEqual(r.purpose, "research")
        self.assertEqual(r.root_id, "acme")
        self.assertEqual(r.lineage, (w.token.token_id, sub.token.token_id))


class TestPlannerErgonomics(unittest.TestCase):
    def test_denial_tells_the_agent_what_to_do(self):
        clk, led, p, api, w = setup(budget=usd(3))
        with self.assertRaises(Denied) as e:
            w.pay(api.quote(usd(10), "research"), idem_key="e1")
        d = e.exception.as_dict()
        self.assertIn("action", d)
        self.assertIn("hint", d)
        self.assertEqual(d["remaining"], usd(3))

    def test_can_afford_before_acting(self):
        clk, led, p, api, w = setup(budget=usd(3), per_tx=usd(2))
        self.assertTrue(w.can_afford(usd(2)))
        self.assertFalse(w.can_afford(usd(3)))   # blocked by per-tx, not total


if __name__ == "__main__":
    unittest.main(verbosity=2)
