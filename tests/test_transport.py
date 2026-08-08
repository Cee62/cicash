"""The transports must not weaken anything the core guarantees."""

import json
import unittest

from cicash import Ledger, ci, Denied, crypto
from cicash.client import RemoteWallet
from cicash.mcp_server import Server, TOOLS
from cicash.service import Api, build_demo, serve


class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led, cls.api = build_demo()
        cls.httpd = serve(cls.api, port=8499, background=True)
        cls.base = "http://127.0.0.1:8499"
        acme = cls.led.register_principal("acme")
        cls.w = acme.grant(budget=ci(20), per_tx=ci(5),
                           payees=["api.search"], purposes=["research"])

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def rw(self):
        return RemoteWallet(self.base, self.w.to_dict())

    def test_remote_pay_matches_local_semantics(self):
        w = self.rw()
        before = w.balance()["available"]
        q = w.quote("api.search", ci(2), "research")
        r = w.pay(q, idem_key="http/1")
        self.assertEqual(r["amount"], ci(2))
        self.assertEqual(w.balance()["available"], before - ci(2))

    def test_retry_over_http_is_free(self):
        w = self.rw()
        q = w.quote("api.search", ci(1), "research")
        a = w.pay(q, idem_key="http/retry")
        b = w.pay(q, idem_key="http/retry")
        self.assertEqual(a["receipt_id"], b["receipt_id"])

    def test_denial_crosses_the_wire_with_its_action(self):
        w = self.rw()
        q = w.quote("api.gpu", ci(1), "research")     # payee not on allowlist
        with self.assertRaises(Denied) as e:
            w.pay(q, idem_key="http/deny")
        self.assertEqual(e.exception.reason, "PAYEE_NOT_ALLOWED")
        self.assertEqual(e.exception.action, "REPLAN")
        self.assertTrue(e.exception.hint)

    def test_status_codes_are_semantic(self):
        st, body = self.api.handle("POST", "/v1/authorize", {
            "token": self.w.token.to_dict(), "pop": "00", "idem_key": "x",
            "quote": self.api.merchants["api.search"].quote(ci(1), "research").to_dict(),
        }, {})
        self.assertEqual(st, 401)                      # bad proof -> unauthorized
        self.assertEqual(body["denied"], "POP_INVALID")

        big = self.api.merchants["api.search"].quote(ci(99), "research")
        st2, body2 = self.api.handle("POST", "/v1/authorize", {
            "token": self.w.token.to_dict(),
            "pop": self.w._pop(big, "y"), "quote": big.to_dict(), "idem_key": "y",
        }, {})
        self.assertEqual(st2, 402)                     # over budget -> payment required
        self.assertEqual(body2["denied"], "PER_TX_EXCEEDED")

    def test_402_resource_flow(self):
        st, body = self.api.handle("GET", "/demo/premium", {}, {})
        self.assertEqual(st, 402)
        q = body["quote"]
        w = self.rw()
        from cicash.protocol import Quote
        r = w.pay(Quote.from_dict(q), idem_key="402/flow")
        st2, body2 = self.api.handle("GET", "/demo/premium", {},
                                     {"receipt": [r["receipt_id"]]})
        self.assertEqual(st2, 200)
        self.assertIn("content", body2)

    @unittest.skipUnless(crypto.HAVE_ED25519, "needs ed25519")
    def test_remote_delegation_is_offline_and_still_bound(self):
        w = self.rw()
        blob = w.delegate(budget=ci(2), note="sub")   # no network call
        sub = RemoteWallet(self.base, blob)
        q = sub.quote("api.search", ci(1), "research")
        sub.pay(q, idem_key="sub/1")
        self.assertEqual(sub.balance()["available"], ci(1))
        with self.assertRaises(Denied):
            w.delegate(budget=ci(999))


class TestMcp(unittest.TestCase):
    def setUp(self):
        self.led, api = build_demo()
        acme = self.led.register_principal("acme")
        self.w = acme.grant(budget=ci(10), per_tx=ci(3),
                            payees=["api.search"], purposes=["research"])
        self.srv = Server(self.w, api.merchants)

    def rpc(self, method, params=None, mid=1):
        return self.srv.dispatch({"jsonrpc": "2.0", "id": mid,
                                  "method": method, "params": params or {}})

    def test_handshake_and_tool_list(self):
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18"})
        self.assertIn("serverInfo", r["result"])
        self.assertIsNone(self.rpc("notifications/initialized"))
        names = {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}
        self.assertEqual(names, {t["name"] for t in TOOLS})

    def test_tools_have_schemas_a_model_can_follow(self):
        for t in TOOLS:
            self.assertTrue(t["description"].strip())
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("additionalProperties", t["inputSchema"])

    def test_check_quote_pay_round_trip(self):
        chk = self.rpc("tools/call", {"name": "budget_check"})["result"]
        self.assertFalse(chk["isError"])
        self.assertEqual(chk["structuredContent"]["available"], "10 CIcash")

        q = self.rpc("tools/call", {"name": "budget_quote", "arguments": {
            "payee": "api.search", "amount": 2, "purpose": "research"}})
        quote = q["result"]["structuredContent"]

        pay = self.rpc("tools/call", {"name": "budget_pay", "arguments": {
            "quote": quote, "idem_key": "mcp/1"}})["result"]
        self.assertFalse(pay["isError"])
        self.assertEqual(pay["structuredContent"]["remaining"], "8 CIcash")

    def test_denial_is_structured_not_a_wall(self):
        q = self.rpc("tools/call", {"name": "budget_quote", "arguments": {
            "payee": "api.gpu", "amount": 1, "purpose": "research"}})
        res = self.rpc("tools/call", {"name": "budget_pay", "arguments": {
            "quote": q["result"]["structuredContent"], "idem_key": "mcp/2"}})["result"]
        self.assertTrue(res["isError"])
        sc = res["structuredContent"]
        self.assertEqual(sc["denied"], "PAYEE_NOT_ALLOWED")
        self.assertIn(sc["action"], ("REPLAN", "ESCALATE", "RETRY_AFTER"))
        self.assertTrue(sc["hint"])

    def test_agent_cannot_reach_a_widening_tool(self):
        names = {t["name"] for t in TOOLS}
        self.assertFalse(names & {"budget_set", "budget_raise", "budget_transfer"})
        bad, is_err = self.srv.call_tool("dispatch", {})
        self.assertTrue(is_err)

    def test_delegate_tool_returns_a_tighter_wallet(self):
        res = self.rpc("tools/call", {"name": "budget_delegate", "arguments": {
            "budget": 2, "note": "sub: summarise"}})["result"]
        blob = res["structuredContent"]["wallet"]
        from cicash import Wallet
        sub = Wallet.from_dict(self.led, blob)
        self.assertEqual(sub.balance()["available"], ci(2))
        self.assertIn("credential", res["structuredContent"]["warning"])

    def test_unknown_method(self):
        r = self.rpc("tools/nope")
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
