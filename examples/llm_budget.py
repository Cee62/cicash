#!/usr/bin/env python3
"""Wrap a real paid API — the Claude API — in a CIcash budget.

This is the use case that works *today*, with no settlement layer and no
network of merchants: **internal budget control**. Your agent already pays for
LLM calls on a corporate card. What it doesn't have is a cap it cannot exceed,
a kill switch that works mid-task, and an audit trail that says which agent
spent what, on whose authority, for what purpose.

The fit is unusually clean because an LLM call has two different costs:

    before the call   you know the input tokens exactly (count_tokens) and the
                      output ceiling (max_tokens) -> the WORST case
    after the call    response.usage tells you what actually happened

That is exactly the shape of a hold. Reserve the worst case, settle the truth.
An agent cannot overspend even on a call whose cost isn't known yet, and the
unused reservation goes straight back into the budget.

Run:
    python3 examples/llm_budget.py              # mock, no API key needed
    ANTHROPIC_API_KEY=... python3 examples/llm_budget.py --live

Swapping the mock for the real client is the two lines marked LIVE below.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cicash import Ledger, ci, fmt, Denied

# USD per million tokens, from the Claude API pricing table.
# Quote at the standard rate; settle at whatever actually applied. Over-quoting
# is free here - the difference is released, not spent.
PRICES = {
    "claude-opus-5":    {"in": 5.00, "out": 25.00},
    "claude-sonnet-5":  {"in": 3.00, "out": 15.00},   # intro $2/$10 through 2026-08-31
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00},
}
CACHE_READ = 0.1     # cached input bills at ~0.1x
CACHE_WRITE = 1.25   # writing a 5-minute cache entry bills at ~1.25x


def cost_ci(model, in_tok=0, out_tok=0, cache_read=0, cache_write=0):
    """Token counts -> integer micro-CIcash. 1 CIcash is pegged to 1 USD here.

    Integer arithmetic end to end: a fractional micro-unit would be a float in
    a balance, and floats are how a retry loop turns into an overdraft.
    """
    p = PRICES[model]
    usd = (in_tok * p["in"]
           + out_tok * p["out"]
           + cache_read * p["in"] * CACHE_READ
           + cache_write * p["in"] * CACHE_WRITE) / 1_000_000
    return ci(usd)


class LlmBudget:
    """A Claude client that cannot spend past its grant.

    Every call is: count -> quote the worst case -> hold -> invoke -> settle
    the truth. The wallet is the only thing standing between a looping agent
    and a five-figure bill, and it is not made of instructions the agent could
    talk itself out of.
    """

    def __init__(self, wallet, merchant, client=None, model="claude-opus-5"):
        self.w = wallet
        self.m = merchant
        self.client = client            # LIVE: anthropic.Anthropic()
        self.model = model

    # -- estimation ---------------------------------------------------------
    def _count_input(self, system, messages):
        if self.client is not None:
            # LIVE: the only correct way to count Claude tokens. Never tiktoken -
            # it is OpenAI's tokenizer and undercounts Claude by 15-20%.
            return self.client.messages.count_tokens(
                model=self.model, system=system, messages=messages
            ).input_tokens
        text = (system or "") + "".join(m["content"] for m in messages)
        return max(1, len(text) // 4)   # mock only; replaced by count_tokens above

    # -- the payment path ---------------------------------------------------
    def ask(self, prompt, *, idem_key, system=None, max_tokens=1024,
            purpose="research", verbose=True):
        messages = [{"role": "user", "content": prompt}]
        in_tok = self._count_input(system, messages)

        # The worst this call can cost: every input token, plus max_tokens of
        # output. The model almost never writes that much - which is the point.
        ceiling = cost_ci(self.model, in_tok=in_tok, out_tok=max_tokens)
        quote = self.m.quote(ceiling, purpose, ttl_s=120)

        if verbose:
            b = self.w.balance()
            print(f"  {in_tok:>6} in · {max_tokens:>5} max out"
                  f"  → quote {fmt(ceiling):>16}   (have {b['available_str']})")

        hold = self.w.authorize(quote, idem_key=idem_key + "|a")

        try:
            if self.client is not None:
                # LIVE: adaptive thinking is on by default on Claude Opus 5;
                # max_tokens caps thinking + text together.
                r = self.client.messages.create(
                    model=self.model, max_tokens=max_tokens,
                    system=system, messages=messages,
                )
                usage, text = r.usage, next(
                    (b.text for b in r.content if b.type == "text"), "")
            else:
                usage, text = _MockUsage(in_tok), "(mock response)"
        except Exception:
            # The call failed, so nothing was consumed. Give the reservation
            # back immediately rather than waiting for the hold to time out.
            self.w.ledger.release(hold.hold_id)
            raise

        actual = cost_ci(
            self.model,
            in_tok=usage.input_tokens,
            out_tok=usage.output_tokens,
            cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        )
        receipt = self.w.settle(hold, actual=actual, idem_key=idem_key + "|s")

        if verbose:
            print(f"  {usage.input_tokens:>6} in · {usage.output_tokens:>5} out"
                  f"  → paid  {fmt(actual):>16}   "
                  f"released {fmt(ceiling - actual)}")
        return text, receipt


class _Clock:
    """Movable clock, so the demo can actually wait out a rate limit."""

    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class _MockUsage:
    """Stands in for response.usage so the example runs with no API key."""

    def __init__(self, in_tok):
        self.input_tokens = in_tok
        self.output_tokens = max(20, in_tok // 3)
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


def main():
    live = "--live" in sys.argv
    client = None
    if live:
        import anthropic
        client = anthropic.Anthropic()

    clock = _Clock()
    led = Ledger(clock=clock)
    acme = led.register_principal("acme-corp")
    anthropic_api = led.register_merchant("api.anthropic")

    # The principal decides what this agent may spend. The agent is never told
    # the budget can change, because it cannot.
    agent = acme.grant(
        budget=ci(0.50),
        per_tx=ci(0.10),
        rate={"max_count": 30, "max_amount": ci(0.25), "window_s": 60},
        ttl_s=3600,
        payees=["api.anthropic"],
        purposes=["research"],
        note="literature review agent, sprint-19",
    )
    llm = LlmBudget(agent, anthropic_api, client=client)

    print(f"\n{'─'*76}\nCIcash around the Claude API "
          f"({'LIVE' if live else 'mock — pass --live with an API key'})\n{'─'*76}")
    print(f"grant: {agent.balance()['available_str']} · "
          f"per-call {fmt(agent.balance()['max_per_tx'])} · "
          f"30 calls/min · purposes {agent.balance()['allowed_purposes']}\n")

    for i, q in enumerate([
        "Summarise the Wyckoff accumulation schematic in three sentences.",
        "What is the difference between a spring and a shakeout?",
        "List three ways a backtest can leak future information.",
    ]):
        print(f"[{i+1}] {q}")
        llm.ask(q, idem_key=f"review/step-{i+1}", max_tokens=512)
        print()

    # ------------------------------------------------------------------
    print(f"{'─'*76}\nThe agent loops. This is where the money would go.\n{'─'*76}")
    wait = None
    for i in range(400):
        try:
            llm.ask("same question again", idem_key=f"loop/{i}",
                    max_tokens=512, verbose=False)
        except Denied as e:
            d = e.as_dict()
            print(f"  ran {i} calls, then: {d['denied']} → {d['action']}")
            for k in ("retry_after", "remaining", "hint"):
                if k in d:
                    v = fmt(d[k]) if k == "remaining" else d[k]
                    print(f"      {k}: {v}")
            wait = d.get("retry_after")
            break
    print(f"  spent so far: {fmt(ci(0.50) - agent.balance()['available'])}"
          f" of the {fmt(ci(0.50))} grant")
    print("  → 400 calls would have cost real money. The rate cap is what stops")
    print("    a loop; a total cap alone just decides how expensive it gets.")

    # The denial said when, so wait exactly that long. This is what an agent
    # that reads `action` does instead of hammering.
    if wait:
        clock.advance(wait + 0.1)

    # ------------------------------------------------------------------
    print(f"\n{'─'*76}\nA sub-agent, on a slice of the same budget\n{'─'*76}")
    sub = agent.delegate(budget=ci(0.05), per_tx=ci(0.02),
                         purposes=["research"], note="sub: summarise one paper")
    LlmBudget(sub, anthropic_api, client=client,
              model="claude-haiku-4-5").ask(
        "Summarise this abstract.", idem_key="sub/1", max_tokens=256)
    print("  note: the sub-agent runs on claude-haiku-4-5 — a cheaper model on")
    print("        the same budget, which is the usual reason to delegate")
    print(f"  sub left   {sub.balance()['available_str']}")
    print(f"  agent left {agent.balance()['available_str']}"
          f"   ← the parent paid for it too")

    # ------------------------------------------------------------------
    print(f"\n{'─'*76}\nWhat finance gets to see\n{'─'*76}")
    rows = {}
    for r in led.receipts:
        who = r.lineage[-1]
        n, spent = rows.get(who, (0, 0))
        rows[who] = (n + 1, spent + r.amount)

    print(f"  {'agent (token)':<26}{'depth':>6}{'calls':>7}{'spent':>18}  purpose")
    for who, (n, spent) in rows.items():
        depth = 0 if who == agent.token.token_id else 1
        print(f"  {who:<26}{depth:>6}{n:>7}{fmt(spent):>18}  research")
    total = sum(r.amount for r in led.receipts)
    print(f"\n  {len(led.receipts)} calls · {fmt(total)} total · "
          f"receipt chain verifies: {led.audit_verify()}")
    print(f"  every one of those {len(led.receipts)} receipts is individually\n"
          f"  addressable, hash-chained, and names its purpose and its ancestry")
    print("\n  Every row names the agent, its ancestry, and the purpose it was\n"
          "  granted for. That is the artefact that makes a human comfortable\n"
          "  leaving an agent running overnight.\n")


if __name__ == "__main__":
    main()
