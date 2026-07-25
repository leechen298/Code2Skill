import { createHash, randomUUID } from "node:crypto";

const LOCAL_PATH = /^(?:file:\/\/|\/|[A-Za-z]:[\\/]|\\\\)/;
const OPAQUE_HOST_ATTACHMENT = /^(?:opaque|host-attachment):[A-Za-z0-9._~:@-]+$/;
const SHA256 = /^[a-f0-9]{64}$/;
const RUNTIME_CONTEXT_CLAIMS = Object.freeze({
  subject: Object.freeze({ requirementId: "authentication-injection", path: Object.freeze(["subjectId"]) }),
  session: Object.freeze({ requirementId: "session-state", path: Object.freeze(["sessionId"]) }),
  confirmation: Object.freeze({ requirementId: "trusted-confirmation", path: Object.freeze(["confirmationGrantId"]) }),
  expiry: Object.freeze({ requirementId: "session-state", path: Object.freeze(["expiresAt"]) }),
});

export class GuardViolation extends Error {
  constructor(code, message) {
    super(message);
    this.name = "GuardViolation";
    this.code = code;
    this.dispatchOccurred = false;
    this.outcomeKnown = true;
  }
}

export class UnknownDispatchOutcomeError extends Error {
  constructor(cause) {
    super("The write may have been dispatched. Stop and reconcile; do not retry automatically.", { cause });
    this.name = "UnknownDispatchOutcomeError";
    this.code = "UNKNOWN_DISPATCH_OUTCOME";
    this.dispatchOccurred = true;
    this.outcomeKnown = false;
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

function deepFreeze(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

function valueAtPath(root, path, name) {
  if (!Array.isArray(path)) fail("INVALID_CONFIGURATION", `${name}.path must be an array`);
  const walk = (current, index) => {
    if (index === path.length) return current;
    const segment = path[index];
    if (segment === "*") {
      if (!Array.isArray(current)) fail("INVALID_BINDING", `${name} wildcard must resolve through an array`);
      return current.map((item) => walk(item, index + 1));
    }
    if (typeof segment !== "string" || segment === "") fail("INVALID_CONFIGURATION", `${name}.path contains an invalid segment`);
    if (!current || typeof current !== "object" || !(segment in current)) {
      fail("MISSING_BINDING", `${name} is missing source path ${path.join(".")}`);
    }
    return walk(current[segment], index + 1);
  };
  return walk(root, 0);
}

function projectBinding(source, input, runtimeContext, name) {
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    fail("INVALID_CONFIGURATION", `${name} binding source must be an object`);
  }
  if (source.kind === "capability-input") {
    return valueAtPath(input, [source.inputName, ...(source.path ?? [])], name);
  }
  if (source.kind === "runtime-context") {
    if (typeof source.claim !== "string" || source.claim === "" || typeof source.requirementId !== "string") {
      fail("INVALID_CONFIGURATION", `${name} runtime-context source must declare claim and requirementId`);
    }
    const claimContract = RUNTIME_CONTEXT_CLAIMS[source.claim];
    if (claimContract && (
      source.requirementId !== claimContract.requirementId
      || !sameOrderedValues(source.path ?? [], claimContract.path)
    )) {
      fail("INVALID_CONFIGURATION", `${name} runtime-context source does not match its semantic claim`);
    }
    return valueAtPath(runtimeContext, source.path, name);
  }
  if (source.kind === "constant") {
    return JSON.parse(canonicalJson(source.value));
  }
  if (source.kind === "derived-calculation") {
    const selected = valueAtPath(input, [source.inputName, ...(source.path ?? [])], name);
    if (source.algorithm === "canonical-json-sha256") return canonicalPayloadDigest(selected);
    if (source.algorithm === "ordered-id-list") {
      if (!Array.isArray(selected) || selected.some((item) => typeof item !== "string" || item === "")) {
        fail("INVALID_BINDING", `${name} ordered-id-list must resolve to non-empty string identifiers`);
      }
      return selected;
    }
    fail("INVALID_CONFIGURATION", `${name} uses an unsupported deterministic calculation`);
  }
  fail("INVALID_CONFIGURATION", `${name} uses an unsupported binding source`);
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
  #consumedOperations = new Set();
  #protectedOperations = new Map();

  constructor({ now = () => Date.now(), maxAttachmentSizeBytes = 1_048_576, protectedOperations = [] } = {}) {
    if (typeof now !== "function") fail("INVALID_CONFIGURATION", "now must be a function");
    if (!Number.isSafeInteger(maxAttachmentSizeBytes) || maxAttachmentSizeBytes <= 0) {
      fail("INVALID_CONFIGURATION", "maxAttachmentSizeBytes must be a positive safe integer");
    }
    this.#now = now;
    this.#maxAttachmentSizeBytes = maxAttachmentSizeBytes;
    if (!Array.isArray(protectedOperations)) fail("INVALID_CONFIGURATION", "protectedOperations must be an array");
    for (const operation of protectedOperations) {
      if (!operation || typeof operation !== "object" || Array.isArray(operation)) {
        fail("INVALID_CONFIGURATION", "each protected operation must be an object");
      }
      const workflowId = nonEmptyString(operation.workflowId, "protectedOperations.workflowId");
      const operationKey = nonEmptyString(operation.operationKey, "protectedOperations.operationKey");
      if (!operation.expectedBindings || typeof operation.expectedBindings !== "object" || Array.isArray(operation.expectedBindings)) {
        fail("INVALID_CONFIGURATION", "protected operation expectedBindings must be an object");
      }
      if (!operation.bindingSources || typeof operation.bindingSources !== "object" || Array.isArray(operation.bindingSources)) {
        fail("INVALID_CONFIGURATION", "protected operation bindingSources must be an object");
      }
      const safeExpectedBindings = JSON.parse(canonicalJson(operation.expectedBindings));
      const safeBindingSources = JSON.parse(canonicalJson(operation.bindingSources));
      if (!sameOrderedValues(Object.keys(safeExpectedBindings).sort(), Object.keys(safeBindingSources).sort())) {
        fail("INVALID_CONFIGURATION", "protected operation bindingSources must exactly cover expectedBindings");
      }
      if (typeof operation.singleUse !== "boolean") {
        fail("INVALID_CONFIGURATION", "protected operation singleUse must be boolean");
      }
      if (
        Object.prototype.hasOwnProperty.call(safeExpectedBindings, "singleUse")
        && safeExpectedBindings.singleUse !== operation.singleUse
      ) {
        fail("INVALID_CONFIGURATION", "protected operation singleUse must match its expected binding");
      }
      if (
        Object.prototype.hasOwnProperty.call(safeExpectedBindings, "expiresAt")
        && safeExpectedBindings.expiresAt !== operation.expiresAt
      ) {
        fail("INVALID_CONFIGURATION", "protected operation expiresAt must match its expected binding");
      }
      if (operation.expiresAt !== undefined) futureExpiry(operation.expiresAt, this.#now(), "protectedOperations.expiresAt");
      const key = `${workflowId}:${operationKey}`;
      if (this.#protectedOperations.has(key)) fail("INVALID_CONFIGURATION", "protected operation keys must be unique");
      this.#protectedOperations.set(key, Object.freeze({
        workflowId,
        operationKey,
        bindingSources: Object.freeze(safeBindingSources),
        expectedBindings: Object.freeze(safeExpectedBindings),
        singleUse: operation.singleUse,
        expiresAt: operation.expiresAt,
      }));
    }
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

  /**
   * Generic hard-workflow boundary.
   *
   * Generated code supplies the exact public input, trusted runtime context,
   * and an opaque operation key. Both the Canonical projection rules and the
   * expected bindings live in the Guard's constructor-injected protected
   * operation store. The Guard projects actual values itself and dispatches the
   * same frozen input it inspected, so public Function code cannot substitute a
   * second payload after checking a caller-provided binding object.
   */
  async dispatchWithPolicy({
    workflowId,
    input,
    runtimeContext,
    operationKey,
    ...unsupportedPolicy
  }, dispatch) {
    if (Object.keys(unsupportedPolicy).length > 0) {
      fail("INVALID_POLICY", `unsupported workflow policy fields: ${Object.keys(unsupportedPolicy).sort().join(", ")}`);
    }
    nonEmptyString(workflowId, "workflowId");
    if (!input || typeof input !== "object" || Array.isArray(input)) fail("INVALID_BINDING", "input must be an object");
    if (!runtimeContext || typeof runtimeContext !== "object" || Array.isArray(runtimeContext)) {
      fail("INVALID_BINDING", "runtimeContext must be a protected Host object");
    }
    const protectedKey = `${workflowId}:${nonEmptyString(operationKey, "operationKey")}`;
    const protectedOperation = this.#protectedOperations.get(protectedKey);
    if (!protectedOperation || protectedOperation.workflowId !== workflowId) {
      fail("PROTECTED_OPERATION_NOT_FOUND", "the runtime did not issue this protected operation");
    }
    const expectedBindings = protectedOperation.expectedBindings;
    const bindings = Object.fromEntries(
      Object.entries(protectedOperation.bindingSources).map(([name, source]) => [
        name,
        projectBinding(source, input, runtimeContext, name),
      ]),
    );
    for (const [name, expected] of Object.entries(expectedBindings)) {
      if (!(name in bindings) || canonicalJson(bindings[name]) !== canonicalJson(expected)) {
        fail("BINDING_MISMATCH", `${name} does not match its source-proven value`);
      }
    }
    if (protectedOperation.expiresAt !== undefined) {
      futureExpiry(protectedOperation.expiresAt, this.#now(), "protectedOperations.expiresAt");
    }
    if (typeof dispatch !== "function") fail("INVALID_DISPATCH", "dispatch must be a function");

    let consumedKey;
    if (protectedOperation.singleUse) {
      consumedKey = protectedKey;
      if (this.#consumedOperations.has(consumedKey)) {
        fail("OPERATION_ALREADY_USED", "the protected operation has already been dispatched");
      }
      this.#consumedOperations.add(consumedKey);
    }

    try {
      const safeInput = deepFreeze(JSON.parse(canonicalJson(input)));
      return await dispatch(safeInput);
    } catch (error) {
      // A consumed key intentionally remains consumed because the external
      // outcome is unknown and must be reconciled before another attempt.
      throw new UnknownDispatchOutcomeError(error);
    }
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
      dispatchResult = await dispatch(deepFreeze({
        target,
        attachmentRef: attachment.attachmentRef,
        fileName: attachment.fileName,
        mediaType: attachment.mediaType,
        sizeBytes: attachment.sizeBytes,
        sha256: attachment.sha256,
      }));
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
      const safePayload = deepFreeze(JSON.parse(canonicalJson(bindings.payload)));
      const safeDispatchInput = deepFreeze({
        target: bindings.target,
        payload: safePayload,
        payloadDigest: authorized.payloadDigest,
        attachments: authorized.attachments.map((attachment) => ({
          uploadResultToken: attachment.uploadResultToken,
          sha256: attachment.attachmentSha256,
        })),
      });
      return await dispatch(safeDispatchInput);
    } catch (error) {
      throw new UnknownDispatchOutcomeError(error);
    }
  }
}
