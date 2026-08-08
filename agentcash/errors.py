"""Denials must be *actionable for a planner*, not just "403 Forbidden".

This is the AI-native part of the design. A human who gets declined asks a
person. An agent that gets declined has exactly three sane moves:

    RETRY_AFTER        - transient, a wall-clock wait fixes it
    REPLAN             - permanent for *this* request, another request may pass
    ESCALATE           - no request will pass; only the principal can unblock

If the error does not say which one, the agent retry-loops until the budget,
the rate cap, or the user's patience is gone. So every denial carries it.
"""

RETRY_AFTER = "RETRY_AFTER"
REPLAN = "REPLAN"
ESCALATE = "ESCALATE"


class AgentCashError(Exception):
    pass


class Denied(AgentCashError):
    def __init__(
        self,
        reason,
        action,
        detail="",
        constraint=None,
        owner=None,
        remaining=None,
        retry_after=None,
        hint="",
    ):
        self.reason = reason           # machine-readable code
        self.action = action           # RETRY_AFTER | REPLAN | ESCALATE
        self.detail = detail
        self.constraint = constraint   # which caveat blocked, e.g. "max_total"
        self.owner = owner             # which token in the lineage owns it
        self.remaining = remaining     # micro-units still available, if meaningful
        self.retry_after = retry_after # seconds, if action == RETRY_AFTER
        self.hint = hint               # natural-language next step for the planner
        super().__init__(f"{reason}: {detail}")

    def as_dict(self):
        """What the agent should be handed back. Small enough to put in a prompt."""
        d = {
            "denied": self.reason,
            "action": self.action,
            "detail": self.detail,
        }
        for k in ("constraint", "owner", "remaining", "retry_after", "hint"):
            v = getattr(self, k)
            if v not in (None, ""):
                d[k] = v
        return d


class AuditBroken(AgentCashError):
    """The receipt chain does not verify. Someone edited history."""
