import { createHash, randomUUID } from "node:crypto";

const LOCAL_PATH = /^(?:file:\/\/|\/|[A-Za-z]:[\\/]|\\\\)/;
const OPAQUE_HOST_ATTACHMENT = /^(?:opaque|host-attachment):[A-Za-z0-9._~:@-]+$/;
const SHA256 = /^[a-f0-9]{64}$/;

export class GuardViolation extends Error {
  constructor(code, message) {
    super(message);
    this.name = "GuardViolation";
    this.code = code;
    this.dispatchOccurred = false;
  }
}

export class UnknownDispatchOutcomeError extends Error {
  constructor(cause) {
    super("The write may have been dispatched. Stop and reconcile; do not retry automatically.", { cause });
    this.name = "UnknownDispatchOutcomeError";
    this.code = "UNKNOWN_DISPATCH_OUTCOME";
    this.dispatchOccurred = true;
    this.automaticRetryAllowed = false;
  }
}

function fail(code, message) {
  throw new GuardViolation(code, message);
}

function nonEmptyString(value, name) {
  if (typeof value !== "string" || value.trim() === "") fail("INVALID_BINDING", `${name} must be a non-empty string`);
  return value;
}

function futureExpiry(value, now, name) {
  if (!Number.isFinite(value) || value <= now) fail("EXPIRED_GRANT", `${name} must be a future epoch-millisecond value`);
  return value;
}

function canonicalJson(value, seen = new Set()) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("INVALID_PAYLOAD", "payload contains a non-finite number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    if (seen.has(value)) fail("INVALID_PAYLOAD", "payload must not contain cycles");
    seen.add(value);
    const result = `[${value.map((item) => canonicalJson(item, seen)).join(",")}]`;
    seen.delete(value);
    return result;
  }
  if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    if (seen.has(value)) fail("INVALID_PAYLOAD", "payload must not contain cycles");
    seen.add(value);
    const result = `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key], seen)}`).join(",")}}`;
    seen.delete(value);
    return result;
  }
  fail("INVALID_PAYLOAD", "payload must contain only JSON values");
}

export function canonicalPayloadDigest(payload) {
  return createHash("sha256").update(canonicalJson(payload)).digest("hex");
}

function rejectLocalPath(value, name) {
  const text = nonEmptyString(value, name);
  if (LOCAL_PATH.test(text)) fail("LOCAL_PATH_FORBIDDEN", `${name} must be an opaque Host-approved reference, not a local path`);
  return text;
}

function hostApprovedAttachmentReference(value) {
  const text = rejectLocalPath(value, "attachmentRef");
  if (!OPAQUE_HOST_ATTACHMENT.test(text)) {
    fail("UNAPPROVED_ATTACHMENT_REFERENCE", "attachmentRef must be an opaque Host-approved reference, not a URL");
  }
  return text;
}

function sameOrderedValues(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

/**
 * Reference guard for a single process/session runtime.
 *
 * A production adapter may replace the in-memory grant store with signed or
 * durable state, but it must preserve every binding and consume-before-dispatch
 * behavior implemented here.
 */
export class PortableWorkflowGuard {
  #now;
  #maxAttachmentSizeBytes;
  #grants = new Map();

  constructor({ now = () => Date.now(), maxAttachmentSizeBytes = 1_048_576 } = {}) {
    if (typeof now !== "function") fail("INVALID_CONFIGURATION", "now must be a function");
    if (!Number.isSafeInteger(maxAttachmentSizeBytes) || maxAttachmentSizeBytes <= 0) {
      fail("INVALID_CONFIGURATION", "maxAttachmentSizeBytes must be a positive safe integer");
    }
    this.#now = now;
    this.#maxAttachmentSizeBytes = maxAttachmentSizeBytes;
  }

  #issue(kind, claims) {
    const grantId = `${kind}:${randomUUID()}`;
    this.#grants.set(grantId, Object.freeze({ grantId, kind, singleUse: true, used: false, ...claims }));
    return Object.freeze({ grantId, kind, expiresAt: claims.expiresAt, singleUse: true });
  }

  #read(grantId, expectedKind) {
    nonEmptyString(grantId, `${expectedKind}GrantId`);
    const grant = this.#grants.get(grantId);
    if (!grant || grant.kind !== expectedKind) fail("INVALID_GRANT", `missing or invalid ${expectedKind} grant`);
    if (grant.used) fail("GRANT_ALREADY_USED", `${expectedKind} grant has already been used`);
    if (grant.expiresAt <= this.#now()) fail("EXPIRED_GRANT", `${expectedKind} grant has expired`);
    return grant;
  }

  issueAttachmentGrant({ subjectId, sessionId, attachmentRef, fileName, mediaType, sizeBytes, sha256, expiresAt }) {
    const now = this.#now();
    const safeFileName = nonEmptyString(fileName, "fileName");
    if (safeFileName === "." || safeFileName === ".." || /[\\/]/.test(safeFileName)) {
      fail("LOCAL_PATH_FORBIDDEN", "fileName must be a base name without directory components");
    }
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 0) fail("INVALID_ATTACHMENT", "sizeBytes must be a non-negative safe integer");
    if (sizeBytes > this.#maxAttachmentSizeBytes) fail("INVALID_ATTACHMENT", "attachment exceeds the configured size limit");
    if (!SHA256.test(sha256)) fail("INVALID_ATTACHMENT", "sha256 must be a lower-case SHA-256 digest");
    return this.#issue("host-attachment", {
      subjectId: nonEmptyString(subjectId, "subjectId"),
      sessionId: nonEmptyString(sessionId, "sessionId"),
      attachmentRef: hostApprovedAttachmentReference(attachmentRef),
      fileName: safeFileName,
      mediaType: nonEmptyString(mediaType, "mediaType"),
      sizeBytes,
      sha256,
      expiresAt: futureExpiry(expiresAt, now, "expiresAt"),
    });
  }

  issueUploadConfirmationGrant({ subjectId, sessionId, target, attachmentGrantId, confirmed, expiresAt }) {
    if (confirmed !== true) fail("CONFIRMATION_REQUIRED", "trusted upload confirmation must be explicit");
    const attachment = this.#read(attachmentGrantId, "host-attachment");
    if (attachment.subjectId !== subjectId || attachment.sessionId !== sessionId) {
      fail("GRANT_BINDING_MISMATCH", "upload confirmation belongs to a different subject or session");
    }
    return this.#issue("upload-confirmation", {
      subjectId,
      sessionId,
      target: nonEmptyString(target, "target"),
      attachmentGrantId,
      attachmentSha256: attachment.sha256,
      expiresAt: futureExpiry(expiresAt, this.#now(), "expiresAt"),
    });
  }

  async dispatchUploadOnce({ subjectId, sessionId, target, attachmentGrantId, confirmationGrantId }, dispatch) {
    if (typeof dispatch !== "function") fail("INVALID_DISPATCH", "dispatch must be a function");
    const attachment = this.#read(attachmentGrantId, "host-attachment");
    const confirmation = this.#read(confirmationGrantId, "upload-confirmation");
    if (
      attachment.subjectId !== subjectId
      || attachment.sessionId !== sessionId
      || confirmation.subjectId !== subjectId
      || confirmation.sessionId !== sessionId
      || confirmation.target !== target
      || confirmation.attachmentGrantId !== attachmentGrantId
      || confirmation.attachmentSha256 !== attachment.sha256
    ) {
      fail("GRANT_BINDING_MISMATCH", "upload bindings do not match the approved attachment and confirmation");
    }

    // Authorization, expiry, metadata, Hash, identity, and confirmation checks
    // have all completed before the first possible external dispatch.
    for (const grant of [attachment, confirmation]) {
      this.#grants.set(grant.grantId, Object.freeze({ ...grant, used: true }));
    }

    let dispatchResult;
    try {
      dispatchResult = await dispatch({
        target,
        attachmentRef: attachment.attachmentRef,
        fileName: attachment.fileName,
        mediaType: attachment.mediaType,
        sizeBytes: attachment.sizeBytes,
        sha256: attachment.sha256,
      });
    } catch (error) {
      throw new UnknownDispatchOutcomeError(error);
    }
    let uploadResultToken;
    try {
      if (!dispatchResult || typeof dispatchResult !== "object") {
        fail("INVALID_UPLOAD_RESULT", "upload result must be an object");
      }
      uploadResultToken = rejectLocalPath(dispatchResult.attachmentToken, "dispatchResult.attachmentToken");
    } catch (error) {
      throw new UnknownDispatchOutcomeError(error);
    }
    const uploadedAttachmentGrant = this.#issue("uploaded-attachment", {
      subjectId,
      sessionId,
      uploadResultToken,
      attachmentSha256: attachment.sha256,
      expiresAt: Math.min(attachment.expiresAt, confirmation.expiresAt),
    });
    return Object.freeze({ uploadedAttachmentGrant });
  }

  issueValidationGrant({ subjectId, sessionId, target, payload, attachmentGrantIds = [], expiresAt }) {
    const now = this.#now();
    const bindings = {
      subjectId: nonEmptyString(subjectId, "subjectId"),
      sessionId: nonEmptyString(sessionId, "sessionId"),
      target: nonEmptyString(target, "target"),
    };
    if (!Array.isArray(attachmentGrantIds)) fail("INVALID_BINDING", "attachmentGrantIds must be an array");
    const attachments = attachmentGrantIds.map((grantId) => this.#read(grantId, "uploaded-attachment"));
    for (const grant of attachments) {
      if (grant.subjectId !== bindings.subjectId || grant.sessionId !== bindings.sessionId) {
        fail("GRANT_BINDING_MISMATCH", "attachment grant belongs to a different subject or session");
      }
    }
    return this.#issue("validation", {
      ...bindings,
      payloadDigest: canonicalPayloadDigest(payload),
      attachmentGrantIds: [...attachmentGrantIds],
      expiresAt: futureExpiry(expiresAt, now, "expiresAt"),
    });
  }

  issueConfirmationGrant({
    subjectId,
    sessionId,
    target,
    payload,
    validationGrantId,
    attachmentGrantIds = [],
    confirmed,
    expiresAt,
  }) {
    if (confirmed !== true) fail("CONFIRMATION_REQUIRED", "trusted confirmation must be explicit");
    const validation = this.#read(validationGrantId, "validation");
    const payloadDigest = canonicalPayloadDigest(payload);
    if (
      validation.subjectId !== subjectId
      || validation.sessionId !== sessionId
      || validation.target !== target
      || validation.payloadDigest !== payloadDigest
      || !sameOrderedValues(validation.attachmentGrantIds, attachmentGrantIds)
    ) {
      fail("GRANT_BINDING_MISMATCH", "confirmation does not match the validation grant bindings");
    }
    return this.#issue("confirmation", {
      subjectId,
      sessionId,
      target,
      payloadDigest,
      validationGrantId,
      attachmentGrantIds: [...attachmentGrantIds],
      expiresAt: futureExpiry(expiresAt, this.#now(), "expiresAt"),
    });
  }

  #authorizeDispatch({
    subjectId,
    sessionId,
    target,
    payload,
    validationGrantId,
    confirmationGrantId,
    attachmentGrantIds = [],
  }) {
    const validation = this.#read(validationGrantId, "validation");
    const confirmation = this.#read(confirmationGrantId, "confirmation");
    if (!Array.isArray(attachmentGrantIds)) fail("INVALID_BINDING", "attachmentGrantIds must be an array");
    const payloadDigest = canonicalPayloadDigest(payload);
    const expected = { subjectId, sessionId, target, payloadDigest };
    for (const [key, value] of Object.entries(expected)) {
      if (validation[key] !== value || confirmation[key] !== value) {
        fail("GRANT_BINDING_MISMATCH", `${key} does not match protected grants`);
      }
    }
    if (confirmation.validationGrantId !== validationGrantId) {
      fail("GRANT_BINDING_MISMATCH", "confirmation is bound to a different validation grant");
    }
    if (
      !sameOrderedValues(validation.attachmentGrantIds, attachmentGrantIds)
      || !sameOrderedValues(confirmation.attachmentGrantIds, attachmentGrantIds)
    ) {
      fail("GRANT_BINDING_MISMATCH", "attachment grants do not match the validated and confirmed set");
    }
    const attachments = attachmentGrantIds.map((grantId) => this.#read(grantId, "uploaded-attachment"));
    for (const attachment of attachments) {
      if (attachment.subjectId !== subjectId || attachment.sessionId !== sessionId) {
        fail("GRANT_BINDING_MISMATCH", "attachment grant belongs to a different subject or session");
      }
    }
    return { validation, confirmation, attachments, payloadDigest };
  }

  async dispatchOnce(bindings, dispatch) {
    if (typeof dispatch !== "function") fail("INVALID_DISPATCH", "dispatch must be a function");

    // Every rejection above this line occurs before any external dispatch.
    const authorized = this.#authorizeDispatch(bindings);

    // Consume every single-use grant before dispatch. A thrown or disconnected
    // request remains consumed because its external outcome is unknown.
    for (const grant of [authorized.validation, authorized.confirmation, ...authorized.attachments]) {
      this.#grants.set(grant.grantId, Object.freeze({ ...grant, used: true }));
    }

    try {
      return await dispatch({
        target: bindings.target,
        payload: bindings.payload,
        payloadDigest: authorized.payloadDigest,
        attachments: authorized.attachments.map((attachment) => ({
          uploadResultToken: attachment.uploadResultToken,
          sha256: attachment.attachmentSha256,
        })),
      });
    } catch (error) {
      throw new UnknownDispatchOutcomeError(error);
    }
  }
}
