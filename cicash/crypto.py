"""Proof of possession.

v0.1 bound tokens with a shared secret the ledger stored. That worked, but it
made the ledger a trusted hub and - worse - it meant a delegation could not be
completed without calling home to register the child's secret.

Ed25519 fixes both. The public key travels *inside the token*, inside the
signature chain, so the ledger needs to store nothing and delegation is fully
offline: an agent on a plane, network down, can still carve a bounded wallet
for a sub-agent and that wallet will verify the first time anyone sees it.

The HMAC backend is kept as a fallback for environments without `cryptography`.
It is honestly labelled as hub-trust in `Ledger.security_profile()`; nothing
silently downgrades.
"""

import hashlib
import hmac
import secrets as _secrets

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.exceptions import InvalidSignature
    HAVE_ED25519 = True
except Exception:                                    # pragma: no cover
    HAVE_ED25519 = False

ED25519 = "ed25519"
HMAC_SHA256 = "hmac-sha256"


class Signer:
    """What the agent holds. Never leaves the agent's process."""

    alg = None

    def public(self) -> str:
        raise NotImplementedError

    def sign(self, msg: str) -> str:
        raise NotImplementedError

    def binding(self) -> dict:
        """The `cnf` caveat value - travels inside the token, publicly."""
        return {"alg": self.alg, "pub": self.public()}

    def ledger_secret(self):
        """What (if anything) the ledger must store to verify us.

        Ed25519: None. That is the entire point.
        """
        return None

    def to_dict(self):
        raise NotImplementedError

    @staticmethod
    def from_dict(d):
        if d["alg"] == ED25519:
            return Ed25519Signer(bytes.fromhex(d["sk"]))
        return HmacSigner(d["sk"])


class Ed25519Signer(Signer):
    alg = ED25519

    def __init__(self, sk_bytes=None):
        if not HAVE_ED25519:                          # pragma: no cover
            raise RuntimeError("ed25519 backend unavailable")
        self._sk = (Ed25519PrivateKey.from_private_bytes(sk_bytes)
                    if sk_bytes else Ed25519PrivateKey.generate())

    def public(self) -> str:
        from cryptography.hazmat.primitives import serialization
        return self._sk.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ).hex()

    def sign(self, msg: str) -> str:
        return self._sk.sign(msg.encode()).hex()

    def to_dict(self):
        from cryptography.hazmat.primitives import serialization
        raw = self._sk.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        return {"alg": self.alg, "sk": raw.hex()}


class HmacSigner(Signer):
    alg = HMAC_SHA256

    def __init__(self, secret=None):
        self._secret = secret or _secrets.token_hex(32)

    def public(self) -> str:
        return hashlib.sha256(self._secret.encode()).hexdigest()

    def sign(self, msg: str) -> str:
        return hmac.new(self._secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

    def ledger_secret(self):
        return self._secret

    def to_dict(self):
        return {"alg": self.alg, "sk": self._secret}


def generate(prefer_ed25519=True) -> Signer:
    if prefer_ed25519 and HAVE_ED25519:
        return Ed25519Signer()
    return HmacSigner()


def verify(binding: dict, msg: str, sig: str, ledger_secret=None) -> bool:
    """Verify a proof against the binding carried in the token."""
    alg, pub = binding.get("alg"), binding.get("pub")
    if not sig:
        return False
    if alg == ED25519:
        if not HAVE_ED25519:                          # pragma: no cover
            return False
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(
                bytes.fromhex(sig), msg.encode()
            )
            return True
        except (InvalidSignature, ValueError):
            return False
    if alg == HMAC_SHA256:
        if ledger_secret is None:
            return False
        if hashlib.sha256(ledger_secret.encode()).hexdigest() != pub:
            return False
        expect = hmac.new(ledger_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, sig)
    return False


def profile() -> dict:
    return {
        "default_alg": ED25519 if HAVE_ED25519 else HMAC_SHA256,
        "ed25519_available": HAVE_ED25519,
        "ledger_stores_private_material": not HAVE_ED25519,
        "offline_delegation": HAVE_ED25519,
    }
