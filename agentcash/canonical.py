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
"""

import json


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def canonical_bytes(obj) -> bytes:
    return canonical(obj).encode("utf-8")
