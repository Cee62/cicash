// Ed25519 proof of possession, on node:crypto only. No dependencies.
//
// The public key travels inside the token's signature chain, so a verifier
// needs no prior knowledge of a delegated wallet and delegation works offline.

import { createHmac, createHash, createPrivateKey, createPublicKey,
         sign as nodeSign, verify as nodeVerify, generateKeyPairSync,
         randomBytes, timingSafeEqual } from "node:crypto";

export const ED25519 = "ed25519", HMAC_SHA256 = "hmac-sha256";

// RFC 8410 DER wrappers, so raw 32-byte keys round-trip through node:crypto.
const SPKI  = Buffer.from("302a300506032b6570032100", "hex");
const PKCS8 = Buffer.from("302e020100300506032b657004220420", "hex");
const pubFromRaw  = raw => createPublicKey({
  key: Buffer.concat([SPKI, raw]), format: "der", type: "spki" });
const privFromRaw = raw => createPrivateKey({
  key: Buffer.concat([PKCS8, raw]), format: "der", type: "pkcs8" });

export class Ed25519Signer {
  static alg = ED25519;
  constructor(rawSk) {
    if (!rawSk) {
      const { privateKey } = generateKeyPairSync("ed25519");
      rawSk = privateKey.export({ format: "der", type: "pkcs8" }).subarray(PKCS8.length);
    }
    this.alg = ED25519;
    this._raw = Buffer.from(rawSk);
    this._sk = privFromRaw(this._raw);
  }
  public() {
    return this._sk.export({ format: "jwk" }).x
      ? Buffer.from(this._sk.export({ format: "jwk" }).x, "base64url").toString("hex")
      : null;
  }
  sign(msg) { return nodeSign(null, Buffer.from(msg, "utf8"), this._sk).toString("hex"); }
  binding() { return { alg: this.alg, pub: this.public() }; }
  ledgerSecret() { return null; }
  toJSON() { return { alg: this.alg, sk: this._raw.toString("hex") }; }
}

export class HmacSigner {
  constructor(secret) {
    this.alg = HMAC_SHA256;
    this._secret = secret || randomBytes(32).toString("hex");
  }
  public() { return createHash("sha256").update(this._secret).digest("hex"); }
  sign(msg) { return createHmac("sha256", this._secret).update(msg, "utf8").digest("hex"); }
  binding() { return { alg: this.alg, pub: this.public() }; }
  ledgerSecret() { return this._secret; }
  toJSON() { return { alg: this.alg, sk: this._secret }; }
}

export const signerFromJSON = d =>
  d.alg === ED25519 ? new Ed25519Signer(Buffer.from(d.sk, "hex")) : new HmacSigner(d.sk);

export const generate = (preferEd = true) =>
  preferEd ? new Ed25519Signer() : new HmacSigner();

export function verify(binding, msg, sig, ledgerSecret = null) {
  if (!sig) return false;
  try {
    if (binding.alg === ED25519) {
      return nodeVerify(null, Buffer.from(msg, "utf8"),
        pubFromRaw(Buffer.from(binding.pub, "hex")), Buffer.from(sig, "hex"));
    }
    if (binding.alg === HMAC_SHA256) {
      if (ledgerSecret === null) return false;
      if (createHash("sha256").update(ledgerSecret).digest("hex") !== binding.pub) return false;
      const a = Buffer.from(createHmac("sha256", ledgerSecret).update(msg, "utf8").digest("hex"));
      const b = Buffer.from(sig);
      return a.length === b.length && timingSafeEqual(a, b);
    }
  } catch { return false; }
  return false;
}

export const profile = () => ({
  default_alg: ED25519, ed25519_available: true,
  ledger_stores_private_material: false, offline_delegation: true,
});
