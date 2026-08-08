# Contributing

## The bar

This project treats **a wrong answer with no error** as worse than a crash. A
cap that silently stops being a cap is the failure mode everything here is
designed against. Patches are judged against that first.

## Before you open a PR

```bash
python3 -m unittest discover -s tests -t .   # 54 tests
cd js && node --test test/                   # 24 tests
python3 tools/interop_check.py               # python issues, javascript spends
```

## Changing the wire format

`spec/vectors.json` is generated, and CI fails if it drifts from the generator.
Regenerating it is a **breaking change to every implementation** — it means
every other language binding stops interoperating. If a PR needs to change a
vector, say so in the title and explain why in the body.

New behaviour that is not in `spec/SPEC.md` is not a feature yet. Spec first.

## Adding an implementation in another language

This is the most valuable contribution available. The bar is:

1. reproduce every value in `spec/vectors.json`
2. implement §7 evaluation **in order**, including 7.1 ancestor debit
3. expose no API that can widen a budget

Two things bite every implementer, both documented in `agentcash/canonical.py`:
integral floats rendering differently across languages, and non-ASCII escaping.
Both are settled in SPEC §2 — read it before writing the encoder.

## Style

Comments explain *why*, especially where the obvious implementation is wrong.
If a line exists because of a bug that was hard to find, say so where it lives.
