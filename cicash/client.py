"""Client SDK. Same shape as the local Wallet, so code does not change when
the ledger moves to another machine.

One thing deliberately does NOT go over the wire: `delegate()`. With the
Ed25519 backend, carving a smaller wallet for a sub-agent is pure local
arithmetic over the signature chain. Making it an RPC would add a network
dependency to the one operation that has no reason to need one - and would let
an outage stop an agent from *reducing* someone's authority, which is exactly
backwards.
"""

import json
import urllib.error
import urllib.request

from . import caveats as cv
from . import crypto
from .caveats import ser
from .errors import Denied
from .ledger import _norm_rate
from .protocol import Quote
from .token import Token, new_id, canonical_request


class RemoteError(Exception):
    pass


class RemoteWallet:
    def __init__(self, base_url: str, blob: dict, timeout=15):
        self.base = base_url.rstrip("/")
        self.token = Token.from_dict(blob["token"])
        self.signer = crypto.Signer.from_dict(blob["signer"])
        self.timeout = timeout

    # -- transport ----------------------------------------------------------
    def _call(self, method, path, body=None):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            payload = json.loads(e.read() or b"{}")
            if "denied" in payload:
                raise Denied(
                    payload["denied"], payload.get("action", "ESCALATE"),
                    payload.get("detail", ""), constraint=payload.get("constraint"),
                    owner=payload.get("owner"), remaining=payload.get("remaining"),
                    retry_after=payload.get("retry_after"), hint=payload.get("hint"),
                ) from None
            raise RemoteError(f"{e.code} {payload}") from None

    # -- planning -----------------------------------------------------------
    def balance(self):
        return self._call("POST", "/v1/balance", {"token": self.token.to_dict()})

    def can_afford(self, amount):
        b = self.balance()
        return (not b["revoked"] and b["available"] is not None
                and b["available"] >= amount
                and (b["max_per_tx"] is None or amount <= b["max_per_tx"]))

    def quote(self, payee, amount, purpose, ttl_s=60):
        return Quote.from_dict(self._call("POST", "/v1/quote", {
            "payee": payee, "amount": int(amount),
            "purpose": purpose, "ttl_s": ttl_s}))

    # -- spending -----------------------------------------------------------
    def _pop(self, quote, idem_key):
        return self.signer.sign(canonical_request(
            self.token.token_id, quote.payee, quote.amount, quote.purpose, idem_key))

    def authorize(self, quote, idem_key):
        return self._call("POST", "/v1/authorize", {
            "token": self.token.to_dict(), "pop": self._pop(quote, idem_key),
            "quote": quote.to_dict(), "idem_key": idem_key})

    def settle(self, hold, actual=None, idem_key=None):
        return self._call("POST", "/v1/settle", {
            "hold_id": hold["hold_id"],
            "actual": hold["amount"] if actual is None else int(actual),
            "idem_key": idem_key or hold["hold_id"]})

    def pay(self, quote, idem_key, actual=None):
        h = self.authorize(quote, idem_key + "|a")
        return self.settle(h, actual, idem_key + "|s")

    def receipts(self):
        return self._call("GET", f"/v1/receipts?token_id={self.token.token_id}")["receipts"]

    # -- delegation (local, offline) ----------------------------------------
    def delegate(self, budget=None, per_tx=None, rate=None, expires_at=None,
                 payees=None, purposes=None, note="") -> dict:
        """Returns a wallet blob for the sub-agent. No network call."""
        signer = crypto.generate()
        current = {k: v for (_, k, v) in self.token.scoped()}
        added = []
        for kind, val in (
            (cv.MAX_TOTAL, None if budget is None else int(budget)),
            (cv.MAX_PER_TX, None if per_tx is None else int(per_tx)),
            (cv.RATE, None if rate is None else _norm_rate(rate)),
            (cv.EXPIRES, expires_at),
            (cv.PAYEES, None if payees is None else sorted(payees)),
            (cv.PURPOSE, None if purposes is None else sorted(purposes)),
        ):
            if val is None:
                continue
            if kind in current and not cv.narrower_or_equal(kind, val, current[kind]):
                raise Denied("WIDENING_REFUSED", "ESCALATE",
                             f"{kind}={val} is looser than your own {current[kind]}",
                             constraint=kind,
                             hint="delegation is a ratchet: children are tighter, never looser")
            added.append(ser(kind, val))
        if note:
            added.append(ser(cv.NOTE, note))
        if signer.ledger_secret() is not None:
            raise RemoteError(
                "remote delegation requires the ed25519 backend; the HMAC "
                "fallback would have to register the child's secret with the ledger")
        tok = self.token.delegate(new_id("tok"), signer.binding(), added)
        return {"token": tok.to_dict(), "signer": signer.to_dict()}
