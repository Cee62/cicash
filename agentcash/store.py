"""State that must survive a crash, and a critical section that must not tear.

The dangerous moment in this whole system is settlement: one payment debits
every ancestor in the lineage. If two agents under the same parent settle at
the same instant and those debits interleave, the parent's cap silently stops
being a cap. That is the exact class of bug - a wrong answer with no error -
that this project treats as worse than an outage.

So both stores serialise the read-check-write span:
  * MemoryStore -> a reentrant lock
  * SqliteStore -> BEGIN IMMEDIATE, which takes the write lock up front rather
    than discovering the conflict at COMMIT

Read-only paths (balance) take the same section. A balance that raced a
concurrent settle would be a lie the agent then plans against.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from .models import Hold, Receipt


class MemoryStore:
    """Fast, ephemeral. For tests and single-shot agent runs."""

    persistent = False

    def __init__(self):
        self._lock = threading.RLock()
        self.root_keys = {}
        self.merchant_keys = {}
        self.secrets = {}
        self.token_root = {}
        self.revoked = set()
        self.spent = {}
        self.held = {}
        self.events = {}
        self.holds = {}
        self.idem = {}
        self.receipts = []

    @contextmanager
    def tx(self):
        with self._lock:
            yield self

    # -- keys ---------------------------------------------------------------
    def put_root_key(self, root_id, key): self.root_keys[root_id] = key
    def get_root_key(self, root_id): return self.root_keys.get(root_id)
    def put_merchant_key(self, payee, key): self.merchant_keys[payee] = key
    def get_merchant_key(self, payee): return self.merchant_keys.get(payee)

    def put_binding_secret(self, token_id, secret):
        if secret is not None:
            self.secrets[token_id] = secret

    def get_binding_secret(self, token_id): return self.secrets.get(token_id)
    def put_token_root(self, token_id, root_id): self.token_root[token_id] = root_id
    def get_token_root(self, token_id): return self.token_root.get(token_id, "?")

    # -- revocation ---------------------------------------------------------
    def revoke(self, token_id): self.revoked.add(token_id)
    def revoked_among(self, ids): return sorted(set(ids) & self.revoked)

    # -- counters -----------------------------------------------------------
    def counters(self, token_id):
        return self.spent.get(token_id, 0), self.held.get(token_id, 0)

    def add_spent(self, token_id, d): self.spent[token_id] = self.spent.get(token_id, 0) + d
    def add_held(self, token_id, d): self.held[token_id] = self.held.get(token_id, 0) + d

    # -- rate events --------------------------------------------------------
    def add_event(self, token_id, ts, amount, hold_id):
        self.events.setdefault(token_id, []).append(
            {"ts": ts, "amount": amount, "hold_id": hold_id})

    def events_since(self, token_id, since):
        return [e for e in self.events.get(token_id, []) if e["ts"] > since]

    def set_event_amount(self, hold_id, amount):
        for evs in self.events.values():
            for e in evs:
                if e["hold_id"] == hold_id:
                    e["amount"] = amount

    def drop_events(self, hold_id):
        for tid, evs in self.events.items():
            self.events[tid] = [e for e in evs if e["hold_id"] != hold_id]

    def prune_events(self, before):
        for tid, evs in list(self.events.items()):
            self.events[tid] = [e for e in evs if e["ts"] > before]

    # -- holds --------------------------------------------------------------
    def put_hold(self, hold): self.holds[hold.hold_id] = hold
    def get_hold(self, hold_id): return self.holds.get(hold_id)
    def open_holds_before(self, ts):
        return [h for h in self.holds.values() if h.state == "open" and h.expires_at <= ts]

    def set_hold_state(self, hold_id, state):
        if hold_id in self.holds:
            self.holds[hold_id].state = state

    # -- idempotency --------------------------------------------------------
    def idem_get(self, kind, key): return self.idem.get((kind, key))
    def idem_put(self, kind, key, ref): self.idem[(kind, key)] = ref

    # -- receipts -----------------------------------------------------------
    def append_receipt(self, r): self.receipts.append(r)
    def last_receipt_hash(self): return self.receipts[-1].hash if self.receipts else "genesis"
    def all_receipts(self): return list(self.receipts)
    def get_receipt(self, rid): return next((r for r in self.receipts if r.receipt_id == rid), None)

    def receipts_for(self, token_id):
        return [r for r in self.receipts if token_id in r.lineage]


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS principals(root_id TEXT PRIMARY KEY, root_key BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS merchants(payee_id TEXT PRIMARY KEY, key BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS bindings(token_id TEXT PRIMARY KEY, secret TEXT);
CREATE TABLE IF NOT EXISTS token_root(token_id TEXT PRIMARY KEY, root_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS revocations(token_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS counters(
    token_id TEXT PRIMARY KEY, spent INTEGER NOT NULL DEFAULT 0, held INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, token_id TEXT NOT NULL, ts REAL NOT NULL,
    amount INTEGER NOT NULL, hold_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events ON events(token_id, ts);
CREATE INDEX IF NOT EXISTS ix_events_hold ON events(hold_id);
CREATE TABLE IF NOT EXISTS holds(hold_id TEXT PRIMARY KEY, blob TEXT NOT NULL,
    state TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS idem(kind TEXT NOT NULL, k TEXT NOT NULL, ref TEXT NOT NULL,
    PRIMARY KEY(kind, k));
CREATE TABLE IF NOT EXISTS receipts(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id TEXT UNIQUE NOT NULL,
    blob TEXT NOT NULL, hash TEXT NOT NULL);
"""


class SqliteStore:
    """Durable. Survives the process, the crash, and the 3am restart."""

    persistent = True

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        self._local = threading.local()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return c

    @contextmanager
    def tx(self):
        c = self._conn()
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            c.execute("BEGIN IMMEDIATE")
        self._local.depth = depth + 1
        try:
            yield self
        except Exception:
            self._local.depth = depth
            if depth == 0:
                c.execute("ROLLBACK")
            raise
        else:
            self._local.depth = depth
            if depth == 0:
                c.execute("COMMIT")

    def _one(self, sql, args=()):
        return self._conn().execute(sql, args).fetchone()

    def _all(self, sql, args=()):
        return self._conn().execute(sql, args).fetchall()

    def _run(self, sql, args=()):
        self._conn().execute(sql, args)

    # -- keys ---------------------------------------------------------------
    def put_root_key(self, root_id, key):
        self._run("INSERT OR REPLACE INTO principals VALUES(?,?)", (root_id, key))

    def get_root_key(self, root_id):
        r = self._one("SELECT root_key FROM principals WHERE root_id=?", (root_id,))
        return r["root_key"] if r else None

    def put_merchant_key(self, payee, key):
        self._run("INSERT OR REPLACE INTO merchants VALUES(?,?)", (payee, key))

    def get_merchant_key(self, payee):
        r = self._one("SELECT key FROM merchants WHERE payee_id=?", (payee,))
        return r["key"] if r else None

    def put_binding_secret(self, token_id, secret):
        if secret is not None:
            self._run("INSERT OR REPLACE INTO bindings VALUES(?,?)", (token_id, secret))

    def get_binding_secret(self, token_id):
        r = self._one("SELECT secret FROM bindings WHERE token_id=?", (token_id,))
        return r["secret"] if r else None

    def put_token_root(self, token_id, root_id):
        self._run("INSERT OR REPLACE INTO token_root VALUES(?,?)", (token_id, root_id))

    def get_token_root(self, token_id):
        r = self._one("SELECT root_id FROM token_root WHERE token_id=?", (token_id,))
        return r["root_id"] if r else "?"

    # -- revocation ---------------------------------------------------------
    def revoke(self, token_id):
        self._run("INSERT OR IGNORE INTO revocations VALUES(?)", (token_id,))

    def revoked_among(self, ids):
        ids = list(ids)
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        return sorted(r["token_id"] for r in
                      self._all(f"SELECT token_id FROM revocations WHERE token_id IN ({q})", ids))

    # -- counters -----------------------------------------------------------
    def counters(self, token_id):
        r = self._one("SELECT spent, held FROM counters WHERE token_id=?", (token_id,))
        return (r["spent"], r["held"]) if r else (0, 0)

    def _bump(self, token_id, col, d):
        self._run("INSERT INTO counters(token_id, spent, held) VALUES(?,0,0) "
                  "ON CONFLICT(token_id) DO NOTHING", (token_id,))
        self._run(f"UPDATE counters SET {col}={col}+? WHERE token_id=?", (d, token_id))

    def add_spent(self, token_id, d): self._bump(token_id, "spent", d)
    def add_held(self, token_id, d): self._bump(token_id, "held", d)

    # -- rate events --------------------------------------------------------
    def add_event(self, token_id, ts, amount, hold_id):
        self._run("INSERT INTO events(token_id, ts, amount, hold_id) VALUES(?,?,?,?)",
                  (token_id, ts, amount, hold_id))

    def events_since(self, token_id, since):
        return [dict(r) for r in self._all(
            "SELECT ts, amount, hold_id FROM events WHERE token_id=? AND ts>?",
            (token_id, since))]

    def set_event_amount(self, hold_id, amount):
        self._run("UPDATE events SET amount=? WHERE hold_id=?", (amount, hold_id))

    def drop_events(self, hold_id):
        self._run("DELETE FROM events WHERE hold_id=?", (hold_id,))

    def prune_events(self, before):
        self._run("DELETE FROM events WHERE ts<=?", (before,))

    # -- holds --------------------------------------------------------------
    def put_hold(self, hold):
        self._run("INSERT OR REPLACE INTO holds VALUES(?,?,?,?)",
                  (hold.hold_id, json.dumps(hold.to_dict()), hold.state, hold.expires_at))

    def get_hold(self, hold_id):
        r = self._one("SELECT blob FROM holds WHERE hold_id=?", (hold_id,))
        return Hold.from_dict(json.loads(r["blob"])) if r else None

    def open_holds_before(self, ts):
        return [Hold.from_dict(json.loads(r["blob"])) for r in self._all(
            "SELECT blob FROM holds WHERE state='open' AND expires_at<=?", (ts,))]

    def set_hold_state(self, hold_id, state):
        h = self.get_hold(hold_id)
        if h:
            h.state = state
            self.put_hold(h)

    # -- idempotency --------------------------------------------------------
    def idem_get(self, kind, key):
        r = self._one("SELECT ref FROM idem WHERE kind=? AND k=?", (kind, key))
        return r["ref"] if r else None

    def idem_put(self, kind, key, ref):
        self._run("INSERT OR REPLACE INTO idem VALUES(?,?,?)", (kind, key, ref))

    # -- receipts -----------------------------------------------------------
    def append_receipt(self, r):
        self._run("INSERT INTO receipts(receipt_id, blob, hash) VALUES(?,?,?)",
                  (r.receipt_id, json.dumps(r.to_dict()), r.hash))

    def last_receipt_hash(self):
        r = self._one("SELECT hash FROM receipts ORDER BY seq DESC LIMIT 1")
        return r["hash"] if r else "genesis"

    def all_receipts(self):
        return [Receipt.from_dict(json.loads(r["blob"]))
                for r in self._all("SELECT blob FROM receipts ORDER BY seq")]

    def get_receipt(self, rid):
        r = self._one("SELECT blob FROM receipts WHERE receipt_id=?", (rid,))
        return Receipt.from_dict(json.loads(r["blob"])) if r else None

    def receipts_for(self, token_id):
        return [r for r in self.all_receipts() if token_id in r.lineage]
