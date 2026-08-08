"""MCP server - the part that actually puts this in front of agents.

Design decision worth stating: THE AGENT NEVER RECEIVES THE KEY. It receives
tools. The wallet lives in this process; the model sees `budget_check`,
`budget_quote`, `budget_pay` and nothing else. A credential that never enters
a context window cannot leak out of one, which is a much stronger guarantee
than asking a model not to repeat it.

Every denial comes back as structured content with an `action` field
(RETRY_AFTER / REPLAN / ESCALATE) so the model has something to plan with
instead of a wall to bang on.

Run:
    CICASH_WALLET=./wallet.json CICASH_DB=./ac.db \\
        python3 -m cicash.mcp_server

Claude Code / Claude Desktop config:
    {"mcpServers": {"cicash": {
        "command": "python3", "args": ["-m", "cicash.mcp_server"],
        "env": {"CICASH_WALLET": "/abs/wallet.json",
                "CICASH_DB": "/abs/ac.db"}}}}
"""

import json
import os
import sys

from .errors import Denied
from .ledger import Ledger, Wallet
from .money import fmt
from .protocol import Quote

PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "budget_check",
        "description": (
            "How much money you have left, what you may spend it on, and which "
            "limit is currently binding. Call this BEFORE planning work that "
            "costs money, not after being refused."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "budget_quote",
        "description": (
            "Ask a seller what something costs. Returns a signed quote. You "
            "cannot invent a price or a recipient - both must come from here."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "payee": {"type": "string", "description": "seller id, e.g. api.search"},
                "amount": {"type": "number"},
                "purpose": {"type": "string", "description": "must be inside your grant"},
            },
            "required": ["payee", "amount", "purpose"],
            "additionalProperties": False,
        },
    },
    {
        "name": "budget_pay",
        "description": (
            "Pay a quote from budget_quote. Give the same idem_key if you retry "
            "- retrying is free and will never charge twice. If refused, read "
            "`action`: RETRY_AFTER means wait, REPLAN means try something "
            "different, ESCALATE means stop and tell your principal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote": {"type": "object", "description": "the quote object, unmodified"},
                "idem_key": {"type": "string",
                             "description": "stable id for this step, e.g. run42/step7"},
            },
            "required": ["quote", "idem_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "budget_delegate",
        "description": (
            "Carve a smaller, tighter wallet for a sub-agent. It can only ever "
            "be narrower than yours, and everything it spends also comes out of "
            "your budget. Returns a wallet blob to hand to the sub-agent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number"},
                "per_tx": {"type": "number"},
                "purposes": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string", "description": "what this sub-agent is for"},
            },
            "required": ["budget", "note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "budget_receipts",
        "description": "Everything spent under your wallet, with purpose and lineage.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


class Server:
    def __init__(self, wallet: Wallet, merchants=None):
        self.w = wallet
        self.merchants = merchants or {}

    # -- tools --------------------------------------------------------------
    def budget_check(self, _):
        b = self.w.balance()
        return {
            "available": b["available_str"],
            "available_micro": b["available"],
            "max_per_tx": fmt(b["max_per_tx"]),
            "allowed_payees": b["allowed_payees"],
            "allowed_purposes": b["allowed_purposes"],
            "expires_in_s": b["expires_in_s"],
            "rate_limits": b["rate_limits"],
            "revoked": b["revoked"],
            "binding_owner": b["binding_owner"],
        }

    def budget_quote(self, a):
        m = self.merchants.get(a["payee"])
        if m is None:
            return {"error": "unknown payee", "known": sorted(self.merchants)}
        from .money import ci
        return m.quote(ci(a["amount"]), a["purpose"]).to_dict()

    def budget_pay(self, a):
        r = self.w.pay(Quote.from_dict(a["quote"]), idem_key=a["idem_key"])
        return {"paid": fmt(r.amount), "receipt_id": r.receipt_id,
                "payee": r.payee, "purpose": r.purpose,
                "remaining": self.w.balance()["available_str"]}

    def budget_delegate(self, a):
        from .money import ci
        sub = self.w.delegate(
            budget=ci(a["budget"]),
            per_tx=None if a.get("per_tx") is None else ci(a["per_tx"]),
            purposes=a.get("purposes"), note=a["note"])
        return {"wallet": sub.to_dict(),
                "warning": "this blob is a credential; hand it to the sub-agent "
                           "over a private channel, never into a shared transcript"}

    def budget_receipts(self, _):
        return {"receipts": [
            {"id": r.receipt_id, "payee": r.payee, "amount": fmt(r.amount),
             "purpose": r.purpose, "depth": len(r.lineage) - 1}
            for r in self.w.ledger.statement(self.w.token.token_id)]}

    # -- jsonrpc ------------------------------------------------------------
    def call_tool(self, name, args):
        fn = getattr(self, name, None)
        if fn is None or name not in {t["name"] for t in TOOLS}:
            return {"error": f"no such tool: {name}"}, True
        try:
            return fn(args or {}), False
        except Denied as e:
            return e.as_dict(), True

    def dispatch(self, msg):
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            return self._ok(mid, {
                "protocolVersion": params.get("protocolVersion", PROTOCOL),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "cicash", "version": "0.4.2"},
                "instructions": (
                    "You hold a bounded budget, not an account. Check it before "
                    "planning. Prices come from budget_quote, never from you. "
                    "Reuse idem_key when you retry."),
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "tools/list":
            return self._ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            payload, is_error = self.call_tool(params.get("name"),
                                               params.get("arguments"))
            return self._ok(mid, {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                "structuredContent": payload,
                "isError": is_error,
            })
        if method == "ping":
            return self._ok(mid, {})
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}

    @staticmethod
    def _ok(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def build_from_env():
    db = os.environ.get("CICASH_DB")
    led = Ledger.sqlite(db) if db else Ledger()
    path = os.environ.get("CICASH_WALLET")
    if not path:
        raise SystemExit("set CICASH_WALLET=/path/to/wallet.json "
                         "(create one with `python3 -m cicash.cli grant`)")
    with open(path) as f:
        w = Wallet.from_dict(led, json.load(f))
    payees = os.environ.get("CICASH_MERCHANTS", "api.search,api.gpu")
    merchants = {p: led.register_merchant(p) for p in payees.split(",") if p}
    return Server(w, merchants)


def main():                                                     # pragma: no cover
    srv = build_from_env()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = srv.dispatch(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":                                      # pragma: no cover
    main()
