"""One encoder, used everywhere something is signed or hashed.

Writing the second implementation is what exposed why this file has to exist.
Two defaults that are individually reasonable make Python and JavaScript
disagree byte-for-byte:

  * `json.dumps` renders an integral float as `1800000000.0`;
    `JSON.stringify` renders it as `1800000000`. Different bytes, different
    signature, and the failure is silent - the token simply stops verifying
    on the other side of the wire for no visible reason.

  * `json.dumps` escapes non-ASCII by default (`"caf\\u00e9"`);
    `JSON.stringify` emits raw UTF-8 (`"café"`). A budget note in Thai would
    have quietly broken cross-language verification.

So: `ensure_ascii=False`, and no float may ever appear inside a signed
structure. Timestamps are integers - seconds for deadlines, milliseconds for
receipts. See SPEC §2.

The rejection below is not belt-and-braces. SPEC §2.1 says an encoder MUST
refuse a non-integer rather than guess, and for one release this file did not:
it happily produced `expires:1800000000.5`, which the JavaScript verifier then
refused with no way to trace the refusal back to its cause. A spec rule that
only one implementation enforces is a rule that catches nobody.
"""

import json


def _reject_floats(obj, path="$"):
    """Walk before dumping. json.dumps has no hook that can refuse a float."""
    if isinstance(obj, bool) or obj is None or isinstance(obj, (str, int)):
        return
    if isinstance(obj, float):
        raise ValueError(
            f"canonical: floats are not allowed in signed structures "
            f"({path} = {obj!r}). Use integer micro-units for amounts, "
            f"integer seconds for deadlines, integer milliseconds for receipts."
        )
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_floats(v, f"{path}.{k}")
        return
    raise TypeError(f"canonical: unsupported type {type(obj).__name__} at {path}")


def canonical(obj) -> str:
    _reject_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def canonical_bytes(obj) -> bytes:
    return canonical(obj).encode("utf-8")
