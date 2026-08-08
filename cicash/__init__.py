"""cicash - a budget you lend to an AI, not money you give it.

    Design it as money the agent OWNS  -> you get Bitcoin's failure mode:
                                          an unbounded, irrevocable bearer key
                                          in the hands of something that leaks
                                          its own context.

    Design it as a budget the agent BORROWS -> bounded, expiring, revocable,
                                               auditable, and worthless once
                                               stolen.

This library is the second one.
"""

from .money import ci, fmt, MICRO
from .errors import Denied, AuditBroken, RETRY_AFTER, REPLAN, ESCALATE
from .token import Token
from .protocol import Merchant, Quote
from .ledger import Ledger, Principal, Wallet
from .models import Hold, Receipt
from .store import MemoryStore, SqliteStore
from . import crypto

__all__ = [
    "ci", "fmt", "MICRO",
    "Denied", "AuditBroken", "RETRY_AFTER", "REPLAN", "ESCALATE",
    "Token", "Merchant", "Quote",
    "Ledger", "Principal", "Wallet", "Hold", "Receipt",
    "MemoryStore", "SqliteStore", "crypto",
]
__version__ = "0.4.1"
