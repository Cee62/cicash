// One encoder, used everywhere something is signed or hashed.
//
// This file is why writing a second implementation was worth the afternoon.
// Two individually-reasonable defaults make Python and JavaScript disagree
// byte-for-byte, and the failure is silent - the token just stops verifying
// on the other side of the wire:
//
//   * Python renders an integral float as `1800000000.0`; JS renders
//     `1800000000`. So no float may appear inside a signed structure at all,
//     and this encoder throws rather than guess.
//   * Python escapes non-ASCII by default; JS emits raw UTF-8. The spec picks
//     raw UTF-8, so a budget note in Thai verifies in both.
//
// See SPEC section 2.

const cmp = (a, b) => {
  const A = Array.from(a), B = Array.from(b);
  for (let i = 0; i < Math.min(A.length, B.length); i++) {
    const x = A[i].codePointAt(0), y = B[i].codePointAt(0);
    if (x !== y) return x - y;
  }
  return A.length - B.length;
};

export function canonical(v) {
  if (v === null) return "null";
  switch (typeof v) {
    case "boolean": return v ? "true" : "false";
    case "string":  return JSON.stringify(v);
    case "number":
      if (!Number.isFinite(v)) throw new Error("canonical: NaN/Infinity");
      if (!Number.isInteger(v))
        throw new Error(`canonical: floats are not allowed in signed structures (${v})`);
      return String(v);
    case "object":
      if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
      return "{" + Object.keys(v).sort(cmp)
        .map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
    default:
      throw new Error(`canonical: unsupported type ${typeof v}`);
  }
}

export const canonicalBytes = v => Buffer.from(canonical(v), "utf8");
