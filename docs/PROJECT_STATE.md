# Project state — read this first

*Written 2026-08-08, at v0.4.2. This file answers "what is going on and what
must I not break", for whoever (or whatever) picks this up next.*

`README.md` says what CIcash is. `OVERVIEW.md` says why. **This file says what
state it is in, which decisions are already settled, and where the trapdoors
are.**

---

## 1. Where everything lives

| | |
|---|---|
| Working copy | `/root/cicash` — a *copy*. Nothing important is only here. |
| Source of truth | https://github.com/Cee62/cicash (`main`) |
| Package | https://pypi.org/project/cicash/ — `pip install cicash` |
| Release | https://github.com/Cee62/cicash/releases/latest |
| Permanent archive | Software Heritage `swh:1:snp:185c0230818abdb4d0532b330adb5ae2c7d845da` |
| npm | https://www.npmjs.com/package/cicash — `npm install cicash` |

Everything on the working copy is pushed. If this machine dies, nothing is lost.

## 2. Status in one paragraph

v0.4.2 is published and installable. Two independent implementations — Python
(`cicash/`, 56 tests) and JavaScript (`js/`, 24 tests) — are held to one
conformance suite (`spec/vectors.json`) and CI proves a wallet minted in one is
spent by the other. There is an MCP server, an HTTP binding, an operator CLI,
and a zero-install single-file build. **There is no settlement layer, no
issuance, and no audit.** Total CIcash in existence: zero, deliberately.

## 3. Things that are deliberate. Do not "fix" them.

Each of these looks like a gap and is not. Changing one without understanding
the reason will make the system worse in a way that does not announce itself.

**There is no supply, no issuance, and no reserve.** `grant()` never checks
whether the principal "has" the money — you can grant a billion twice from
nothing. CIcash is a *unit of bound authority*, not a thing anyone holds. Adding
a supply before there is real backing would produce a number pretending to be
money, which is worse than no number. See SPEC §13, and roadmap item 1.

**`Wallet` has no `set_budget`, `raise_limit`, or `transfer_to`.** The API
surface an agent can reach is intentionally unable to express "give me more".
Every widening operation lives on `Principal`. Do not add a convenience method
that crosses that line.

**The MCP server exposes no tool that widens a budget.** Same rule, enforced by
a test: `test_agent_cannot_reach_a_widening_tool`.

**Stateless checks run in a fixed order** (`expires`, `payees`, `purpose`,
`max_per_tx`) — normative in SPEC §7. "You may not pay this party at all" is a
different signal to a planner than "that is over your per-call cap". Reordering
for tidiness changes behaviour.

**The npm release job is opt-in** (`vars.PUBLISH_NPM == 'true'`). npm is not
wired up. A release that goes red on a step we knowingly cannot do is a badge
nobody reads after the second time.

**No `cooldown`-style features, no retry-suppression.** Retries are supposed to
be free. If a retry costs money, the bug is in the idempotency path, not in the
agent.

## 4. Trapdoors — the ways this breaks silently

The project's operating principle is that **a wrong answer with no error is
worse than a crash.** These are the places that can produce one.

**`spec/vectors.json` is a contract, not an output.** Regenerating it is a
breaking change to *every* implementation in every language. CI fails if it
drifts from `tools/gen_vectors.py`. If a change genuinely requires new vectors,
say so in the PR title.

**No floats in anything signed or hashed** (SPEC §2.1). Python renders an
integral float as `1800000000.0`; JavaScript renders `1800000000`. A token
minted in one silently fails to verify in the other. Both encoders now throw
rather than guess — keep it that way. Timestamps are integers: `expires` and
`quote.expires_at` in seconds, `receipt.ts` in milliseconds.

> Writing this file is what caught the last instance of it: the rule was in the
> spec, enforced in JavaScript, and *not* enforced in Python, so Python could
> mint `expires:1800000000.5` that JavaScript then refused with no traceable
> cause. **A spec rule that only one implementation enforces catches nobody.**
> If you add a rule to SPEC, add it to both encoders and to
> `tests/test_vectors.py` in the same change.

**Non-ASCII is raw UTF-8, never escaped** (SPEC §2.2). Python's `json.dumps`
escapes by default; the spec takes JavaScript's behaviour. A budget note in Thai
broke cross-language verification before this was pinned.

**A settlement must debit every ancestor in the lineage** (SPEC §7.1). Debit
only the leaf and the caps become decoration — an agent capped at 50 could mint
ten children of 50 each. `test_cannot_escape_parent_cap_by_forking_children`
guards it.

**`dist/cicash_single.py` must be rebuilt and committed when `cicash/` changes.**
`tools/build_single_file.py` is deterministic; the release workflow fails if the
committed file is stale.

**The release tag must equal `cicash.__version__`.** The workflow checks it.

**Concurrency**: the read-check-write span in `settle()` is the critical
section. `SqliteStore` takes `BEGIN IMMEDIATE`; `MemoryStore` takes a lock.
`test_parent_cap_holds_under_16_threads` spends exactly the cap under 16 threads
and is the test that will catch a regression here.

## 5. How to release — no tokens exist, and none should

Both registries are reached through **Trusted Publishing (OIDC)**. There is no
`PYPI_TOKEN` and no `NPM_TOKEN` secret anywhere, and there should never be one:
GitHub proves this specific workflow's identity and each registry mints a
credential that expires in minutes.

- PyPI: publisher `Cee62 / cicash / release.yml / environment: pypi`
- npm: trusted publisher on the `cicash` package, gated by the repository
  variable `PUBLISH_NPM=true`

Verify a trusted-publishing release actually used OIDC rather than a token:
`https://registry.npmjs.org/cicash` shows `dist.attestations` on versions
published with provenance. Versions 0.4.0 and 0.4.1 were published by hand from
a developer machine and carry none.

```bash
# bump cicash/__init__.py, pyproject.toml, js/package.json, server.json
python3 tools/build_single_file.py     # rebuild, then commit it
git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z
```

The pipeline refuses to publish unless: both test suites pass, the interop check
passes, the vectors are not stale, the single-file build is reproducible and
self-tests clean, and the tag matches the source version.

**Pushing from an automated session needs a GitHub token that does not exist by
default.** In this project's history one was pasted into a chat, used, and then
deleted — which is the correct shape (short-lived, scoped, revoked), but the
better path is to commit through the web UI or from a machine that already has
credentials. A token in a transcript is a token that has leaked.

## 6. What is actually missing

In rough order of what would matter most:

1. **Settlement (L0).** Nothing here moves real value. Receipts are the netting
   input; the leg that turns a receipt into a claim on something is unwritten.
   This is also what would give the question "how many CIcash exist" an answer.
2. **A third-party security audit.** The construction is standard (HMAC chain,
   Ed25519, SHA-256) and two implementations agree, but nobody independent has
   looked. Every surface says so and should keep saying so.
3. **Privacy.** The ledger sees every payment. The stated goal — auditable to
   the principal, private to the world — needs blinding that does not exist.
4. **Dispute resolution off the payment path.** Finality for the seller,
   recourse for the principal. The trade Bitcoin never made and cards made
   backwards.
5. A Go implementation against the same vectors.

## 7. Two lessons worth not relearning

**The second implementation is what makes a spec real.** JavaScript took an
afternoon and immediately found two silent cross-language bugs (§4) that the
Python implementation could not have found alone — because *the first
implementation cannot tell you which of its choices were decisions and which
were defaults*. The same argument applies to a third one.

**CI catches what one machine cannot.** The first public run went red on two
things the dev box could never have shown: `node --test <dir>` changed meaning
in Node 22, and `setup-node` can no longer provision the EOL Node 18. A green
local suite is evidence about one environment.

---

## Quick verification

If you are picking this up cold, run these four. They take under a minute and
tell you whether anything has rotted.

```bash
python3 -m unittest discover -s tests -t .   # 56
cd js && node --test test/*.test.mjs         # 24
python3 tools/interop_check.py               # python mints, javascript spends
python3 dist/cicash_single.py                # 11/11 invariants
```
