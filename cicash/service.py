"""HTTP transport, so agents that are not written in Python can use this too.

The status-code mapping is the design, not decoration. HTTP already has a code
that means "you must pay to proceed" and it has been unused for thirty years
because humans were never the ones being metered. Agents are.

    402 Payment Required  - budget denial. Body carries the quote or the reason.
    401 Unauthorized      - the token or the proof does not verify.
    403 Forbidden         - revoked, or expired. Stop.
    429 Too Many Requests - rate cap, with Retry-After set from the grant.

An agent that already knows HTTP knows how to behave here without being taught
anything new.

Run:  python3 -m cicash.service --demo
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .errors import Denied, AuditBroken, RETRY_AFTER
from .ledger import Ledger
from .money import ci
from .protocol import Quote
from .token import Token

STATUS = {
    "SIGNATURE_INVALID": 401, "POP_INVALID": 401, "BINDING_MISSING": 401,
    "QUOTE_FORGED": 401,
    "REVOKED": 403, "EXPIRED": 403,
    "RATE_LIMITED": 429,
}
DEFAULT_STATUS = 402


class Api:
    """Transport-free request handling, so this is testable without sockets."""

    def __init__(self, ledger: Ledger, merchants=None):
        self.ledger = ledger
        self.merchants = merchants or {}

    def handle(self, method, path, body, query):
        try:
            fn = getattr(self, f"_{method.lower()}_{path.strip('/').replace('/', '_')}", None)
            if fn is None:
                return 404, {"error": "no such endpoint", "path": path}
            return fn(body, query)
        except Denied as e:
            return STATUS.get(e.reason, DEFAULT_STATUS), e.as_dict()
        except AuditBroken as e:
            return 500, {"error": "audit_broken", "detail": str(e)}
        except (KeyError, TypeError, ValueError) as e:
            return 400, {"error": "bad_request", "detail": str(e)}

    # -- meta ---------------------------------------------------------------
    def _get_v1_health(self, b, q):
        return 200, {"ok": True, "service": "cicash"}

    def _get_v1_profile(self, b, q):
        return 200, self.ledger.security_profile()

    # -- wallet -------------------------------------------------------------
    def _post_v1_balance(self, b, q):
        return 200, self.ledger.balance(Token.from_dict(b["token"]))

    def _post_v1_authorize(self, b, q):
        h = self.ledger.authorize(Token.from_dict(b["token"]), b["pop"],
                                  Quote.from_dict(b["quote"]), b["idem_key"])
        return 200, h.to_dict()

    def _post_v1_settle(self, b, q):
        r = self.ledger.settle(b["hold_id"], int(b["actual"]), b["idem_key"])
        return 200, r.to_dict()

    def _post_v1_release(self, b, q):
        self.ledger.release(b["hold_id"])
        return 200, {"released": b["hold_id"]}

    # -- audit --------------------------------------------------------------
    def _get_v1_receipts(self, b, q):
        tid = (q.get("token_id") or [None])[0]
        rs = self.ledger.statement(tid) if tid else self.ledger.receipts
        return 200, {"receipts": [r.to_dict() for r in rs]}

    def _get_v1_audit(self, b, q):
        return 200, {"verified": self.ledger.audit_verify()}

    # -- a merchant, so the demo has something to buy -----------------------
    def _post_v1_quote(self, b, q):
        m = self.merchants.get(b["payee"])
        if m is None:
            return 404, {"error": "unknown payee", "payee": b["payee"]}
        return 200, m.quote(int(b["amount"]), b["purpose"],
                            float(b.get("ttl_s", 60))).to_dict()

    # -- the 402 flow, end to end -------------------------------------------
    def _get_demo_premium(self, b, q):
        """A paywalled resource. No receipt -> 402 with a quote attached."""
        rid = (q.get("receipt") or [None])[0]
        m = self.merchants.get("api.search")
        if not rid:
            return 402, {
                "error": "payment_required",
                "quote": m.quote(ci(0.01), "research", ttl_s=120).to_dict(),
                "hint": "pay this quote, then retry with ?receipt=<receipt_id>",
            }
        r = self.ledger.store.get_receipt(rid)
        if r is None or r.payee != "api.search":
            return 402, {"error": "receipt_not_found_or_wrong_payee"}
        return 200, {"content": "the answer you paid for", "paid": r.amount,
                     "receipt": r.receipt_id}


class _Handler(BaseHTTPRequestHandler):
    api: Api = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _serve(self, method):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except json.JSONDecodeError:
            body = {}
        status, payload = self.api.handle(method, u.path, body, parse_qs(u.query))
        blob = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        if status == 429 and payload.get("retry_after") is not None:
            self.send_header("Retry-After", str(int(payload["retry_after"]) + 1))
        self.end_headers()
        self.wfile.write(blob)

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")


def serve(api: Api, host="127.0.0.1", port=8402, background=False):
    handler = type("H", (_Handler,), {"api": api})
    httpd = ThreadingHTTPServer((host, port), handler)
    if background:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd
    print(f"cicash serving on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return httpd


def build_demo(db=None):
    led = Ledger.sqlite(db) if db else Ledger()
    merchants = {p: led.register_merchant(p) for p in ("api.search", "api.gpu")}
    return led, Api(led, merchants)


if __name__ == "__main__":                                      # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="cicash HTTP service")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8402)
    ap.add_argument("--db", default=None, help="sqlite path (omit for in-memory)")
    ap.add_argument("--demo", action="store_true", help="register demo merchants")
    a = ap.parse_args()
    led, api = build_demo(a.db) if a.demo else (
        Ledger.sqlite(a.db) if a.db else Ledger(), None)
    serve(api or Api(led), a.host, a.port)
