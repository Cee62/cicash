# Publishing

Everything is built, tested and committed. These are the steps that need **your**
credentials — there is no gh CLI, no PyPI token and no npm token in the machine
this was built on, and all three publish irreversibly under your identity.

```bash
bash tools/publish.sh      # runs every test, builds, then prints the commands
```

## 🔴 Read this before you pick names

| registry | name | status |
|---|---|---|
| PyPI | `agentcash` | **free** (checked: 404) |
| npm | `agentcash` | **TAKEN** — an active package, v0.17.1, keywords `mcp · x402 · payments · ai · claude · model-context-protocol` |
| npm | `agentcash-protocol` | free — what `js/package.json` currently uses |

The npm collision is not just a naming problem, so decide deliberately:

- Someone is already building in this exact space. That is **evidence the
  problem is real**, which is good news for the idea and bad news for the name.
- Taking `agentcash` on PyPI while a different, active `agentcash` exists on npm
  will confuse everyone including you. Consider renaming the project outright
  before the first publish — it costs nothing today and is expensive later.
- Positioning is worth being precise about. That project is tagged `x402`, i.e.
  a **payment rail**. This one is an **authority layer**: attenuation-only
  delegation, ancestor debit, subtree revocation, purpose-bound receipts. Those
  are complementary, not competing — but only if you say so clearly.

If you rename: `pyproject.toml`, `js/package.json`, the `agentcash/` package
directory, and the title in `spec/SPEC.md`. The wire format does not carry the
name anywhere, so vectors and tokens are unaffected.

## 1. PyPI

```bash
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine upload dist/*          # needs your API token
```

## 2. npm

```bash
cd js && npm publish --access public
```

## 3. GitHub

```bash
gh repo create agentcash --public --source=. --remote=origin --push
# or:
git remote add origin git@github.com:<you>/agentcash.git
git branch -M main && git push -u origin main
```

CI (`.github/workflows/ci.yml`) runs on the first push: Python 3.9–3.13, Node
18/20/22, the cross-language interop check, and a guard that fails if
`spec/vectors.json` has drifted from its generator.

## 4. MCP registry

`server.json` is the manifest. Submit per the registry's current process.

## 5. Before any of it

Put your own name on the copyright line in `NOTICE`.

## Announcement copy

Yours to use or ignore. It leads with the mechanism rather than the pitch,
which is what the audience for this responds to.

> **agentcash — a budget you lend to an AI, not money you give it**
>
> Bitcoin's key model is unlimited, eternal, irrevocable bearer authority in one
> secret. That is safe for a careful sovereign and catastrophic in the hands of
> something that leaks its own context and retries in loops.
>
> agentcash inverts it. Budget tokens are macaroon-style chains: any holder can
> attenuate offline, nobody can remove a caveat, spending debits every ancestor,
> and revoking a token kills its whole subtree instantly. A leaked token buys
> nothing without its key. Retries are free. Denials carry
> `RETRY_AFTER` / `REPLAN` / `ESCALATE` so a planner can act instead of looping.
>
> Two independent implementations — Python and JavaScript — agree byte-for-byte
> on a published conformance suite. A wallet minted in Python is spent by
> JavaScript in CI. MCP server, HTTP 402 binding, and a wire spec so any language
> can join.
>
> Not audited. Do not put real money behind it yet.
>
> Spec: `spec/SPEC.md` · Apache-2.0
