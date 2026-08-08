# Releasing

Everything is published. Cutting a new version is a tag push, and **no
long-lived publishing credential exists anywhere** — not on a laptop, not in
repository secrets, not in a config file.

| | |
|---|---|
| PyPI | https://pypi.org/project/cicash/ — `pip install cicash` |
| npm | https://www.npmjs.com/package/cicash — `npm install cicash` |
| Source | https://github.com/Cee62/cicash |
| Archive | Software Heritage `swh:1:snp:185c0230818abdb4d0532b330adb5ae2c7d845da` |

## Cutting a release

```bash
# 1. bump the version in all five places
#    cicash/__init__.py · pyproject.toml · js/package.json
#    server.json · cicash/mcp_server.py (serverInfo)

# 2. rebuild the single-file build and commit it — CI fails if it is stale
python3 tools/build_single_file.py

# 3. tag
git tag -a vX.Y.Z -m "…" && git push origin vX.Y.Z
```

`.github/workflows/release.yml` does the rest: PyPI, npm, and a GitHub Release
with the wheel, the sdist, and `cicash_single.py` attached.

**It refuses to publish anything unless all of this holds:** both test suites
pass, the cross-language interop check passes, `spec/vectors.json` matches its
generator, the single-file build is byte-reproducible and self-tests clean, and
the tag equals `cicash.__version__`.

## How the credentials work — or rather, don't

Both registries use **OIDC trusted publishing**. GitHub proves the identity of
*this specific workflow in this specific repository*, and the registry mints a
credential that expires in minutes. There is nothing to leak, rotate, or revoke.

| | Configured as |
|---|---|
| PyPI | publisher `Cee62 / cicash / release.yml`, environment `pypi` |
| npm | trusted publisher on the `cicash` package, gated by repo variable `PUBLISH_NPM=true` |

That is the argument this library makes, applied to itself. Releasing a project
about bounded, short-lived, revocable authority on a permanent bearer token
pasted into a config would have been a poor look.

### Verifying a release really used OIDC

npm records provenance attestations for OIDC publishes and nothing for
hand-published ones:

```bash
curl -s https://registry.npmjs.org/cicash |
  python3 -c "import sys,json;d=json.load(sys.stdin);\
print([(v, 'attested' if d['versions'][v]['dist'].get('attestations') else 'by hand') for v in sorted(d['versions'])])"
# 0.4.0 by hand · 0.4.1 by hand · 0.4.2 attested
```

0.4.0 and 0.4.1 were published from a developer machine before trusted
publishing was wired up. Everything from 0.4.2 carries an attestation.

## Two things that cost an afternoon

Both worth knowing before touching the release workflow.

**npm's OIDC needs a recent npm, and the one bundled with Node is not it.**
The npm shipped with Node 22 predates trusted publishing, so it never looks for
the GitHub identity token sitting next to it. The job upgrades npm first.

**`registry-url` on `actions/setup-node` is actively harmful here.** It writes
an `.npmrc` line reading `_authToken=${NODE_AUTH_TOKEN}`. With no `NPM_TOKEN`
secret that resolves to an *empty* token, which is worse than no auth config at
all: npm stops and asks you to log in rather than falling through to OIDC.

Both produced the same unhelpful `ENEEDAUTH`, which is why the first attempt at
an npm release failed. A pipeline leg that has never run is a leg that will fail
the first time it matters.

## Naming history

The project was called `agentcash` until the unit got a name. That turned out to
matter twice: `agentcash` is **taken on npm** by an active package in the same
space (tagged `mcp · x402 · payments · ai`), so the old name was never going to
work there.

Worth being precise about positioning, since that project is adjacent: it is a
**payment rail**. CIcash is an **authority layer** — attenuation-only
delegation, ancestor debit, subtree revocation, purpose-bound receipts.
Complementary, not competing, but only if you say so clearly.
