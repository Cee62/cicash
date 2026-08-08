"""The budget token: a macaroon-style chained MAC.

    sig_0 = HMAC(root_key, "root_id|root_token_id")
    sig_n = HMAC(sig_{n-1}, caveat_n)

Two properties fall straight out of that construction, and they are the whole
reason this shape was chosen over a JWT:

1. ANYONE HOLDING THE TOKEN CAN ATTENUATE IT, OFFLINE, WITH NO ISSUER CALL.
   The current signature *is* the key for the next link. An agent can carve a
   smaller budget for a sub-agent mid-task, on a plane, with the network down.

2. NOBODY CAN REMOVE A CAVEAT.
   Un-appending requires sig_{n-1}, which requires the root key. Delegation is
   a one-way ratchet: tighter, never looser.

This is the inversion of Bitcoin's key model. A Bitcoin key is unlimited,
eternal, and irrevocable authority in a single bearer secret. That model is
what makes Bitcoin safe for a careful sovereign and catastrophic in the hands
of something that leaks its own context. Here the bearer secret is bounded,
expiring, revocable, and by itself worthless (see CNF below).
"""

import hmac
import hashlib
import secrets as _secrets
from dataclasses import dataclass
from typing import Tuple

from .caveats import ser, de, SUB, CNF


def _mac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{_secrets.token_hex(8)}"




@dataclass(frozen=True)
class Token:
    root_id: str                 # the principal (who is ultimately liable)
    root_token_id: str           # id of the first grant in this chain
    caveats: Tuple[str, ...]
    sig: str

    # -- structure ----------------------------------------------------------
    @property
    def lineage(self) -> Tuple[str, ...]:
        """Every token id from the root grant down to this one.

        Derived from the SUB caveats, never from a self-declared field: a
        forged lineage would have to survive the signature chain, and it can't.
        """
        out = [self.root_token_id]
        for c in self.caveats:
            k, v = de(c)
            if k == SUB:
                out.append(v)
        return tuple(out)

    @property
    def token_id(self) -> str:
        return self.lineage[-1]

    @property
    def depth(self) -> int:
        return len(self.lineage) - 1

    def scoped(self):
        """[(owner_token_id, kind, value)] - which link in the chain owns each caveat.

        Matters because a `max_total` written by the principal must be counted
        against the *entire subtree's* spending, while one written by a
        sub-agent counts only its own. Without this the ancestor's cap would be
        trivially escaped by delegating.
        """
        owner = self.root_token_id
        out = []
        for c in self.caveats:
            k, v = de(c)
            if k == SUB:
                owner = v
            else:
                out.append((owner, k, v))
        return out

    def find(self, kind):
        return [(o, v) for (o, k, v) in self.scoped() if k == kind]

    # -- crypto -------------------------------------------------------------
    def _extend(self, added) -> "Token":
        s = bytes.fromhex(self.sig)
        for c in added:
            s = _mac(s, c)
        return Token(self.root_id, self.root_token_id, self.caveats + tuple(added), s.hex())

    def attenuate(self, added_caveats) -> "Token":
        """Append caveats without touching the issuer. Offline. Tighter only."""
        return self._extend(list(added_caveats))

    def delegate(self, sub_token_id: str, binding: dict, added_caveats) -> "Token":
        """`binding` is the child's PUBLIC key material. Nothing secret goes in.

        Because it rides inside the signature chain, a verifier needs no prior
        knowledge of the child - which is what makes offline delegation safe.
        """
        chain = [ser(SUB, sub_token_id), ser(CNF, binding)] + list(added_caveats)
        return self._extend(chain)

    # -- wire ---------------------------------------------------------------
    def to_dict(self):
        return {
            "root_id": self.root_id,
            "root_token_id": self.root_token_id,
            "caveats": list(self.caveats),
            "sig": self.sig,
        }

    @staticmethod
    def from_dict(d):
        return Token(d["root_id"], d["root_token_id"], tuple(d["caveats"]), d["sig"])


def mint(root_key: bytes, root_id: str, root_token_id: str,
         binding: dict, caveats) -> Token:
    s = _mac(root_key, f"{root_id}|{root_token_id}")
    t = Token(root_id, root_token_id, tuple(), s.hex())
    return t._extend([ser(CNF, binding)] + list(caveats))


def verify_sig(root_key: bytes, token: Token) -> bool:
    s = _mac(root_key, f"{token.root_id}|{token.root_token_id}")
    for c in token.caveats:
        s = _mac(s, c)
    return hmac.compare_digest(s.hex(), token.sig)


# -- proof of possession -----------------------------------------------------
def canonical_request(token_id, payee, amount, purpose, idem_key) -> str:
    """Everything the proof commits to. Change any field and the proof dies."""
    return f"{token_id}|{payee}|{int(amount)}|{purpose}|{idem_key}"
