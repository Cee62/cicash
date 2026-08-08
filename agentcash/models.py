"""Records that outlive a process."""

import hashlib
import json
from dataclasses import dataclass, asdict, field


def digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class Hold:
    hold_id: str
    root_id: str
    lineage: tuple
    payee: str
    amount: int
    purpose: str
    quote_id: str
    created_at: float
    expires_at: float
    state: str = "open"          # open | settled | released | expired

    def to_dict(self):
        d = asdict(self)
        d["lineage"] = list(self.lineage)
        return d

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["lineage"] = tuple(d["lineage"])
        return Hold(**d)


@dataclass
class Receipt:
    receipt_id: str
    ts: float
    root_id: str
    lineage: tuple
    payee: str
    amount: int
    purpose: str
    quote_id: str
    idem_key: str
    prev_hash: str
    hash: str = ""

    def body(self):
        d = asdict(self)
        d.pop("hash")
        d["lineage"] = list(self.lineage)
        return d

    def seal(self):
        self.hash = digest(self.body())
        return self

    def to_dict(self):
        d = asdict(self)
        d["lineage"] = list(self.lineage)
        return d

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["lineage"] = tuple(d["lineage"])
        return Receipt(**d)
