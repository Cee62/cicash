// A denial an agent cannot act on is a denial it will retry-loop against.
export const RETRY_AFTER = "RETRY_AFTER", REPLAN = "REPLAN", ESCALATE = "ESCALATE";

export class Denied extends Error {
  constructor(reason, action, detail = "", extra = {}) {
    super(`${reason}: ${detail}`);
    this.name = "Denied";
    Object.assign(this, { reason, action, detail }, extra);
  }
  asObject() {
    const o = { denied: this.reason, action: this.action, detail: this.detail };
    for (const k of ["constraint", "owner", "remaining", "retry_after", "hint"])
      if (this[k] !== undefined && this[k] !== null) o[k] = this[k];
    return o;
  }
}

export class AuditBroken extends Error {}
