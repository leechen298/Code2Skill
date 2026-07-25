function plainJson(value, seen = new Set()) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (Array.isArray(value)) {
    if (seen.has(value)) return "[circular]";
    seen.add(value);
    const result = value.map((item) => plainJson(item, seen));
    seen.delete(value);
    return result;
  }
  if (value && typeof value === "object") {
    if (seen.has(value)) return "[circular]";
    seen.add(value);
    const result = Object.fromEntries(
      Object.entries(value)
        .filter(([key, child]) => key !== "stack" && typeof child !== "function")
        .map(([key, child]) => [key, plainJson(child, seen)]),
    );
    seen.delete(value);
    return result;
  }
  return String(value);
}

export function toMcpResult(value, isError = false) {
  const structuredContent = plainJson(value);
  return Object.freeze({
    structuredContent,
    content: Object.freeze([
      Object.freeze({ type: "text", text: JSON.stringify(structuredContent) }),
    ]),
    isError,
  });
}

export function normalizeToolError(error, operationPolicy = {}) {
  const source = error && typeof error === "object" ? error : {};
  const hasStructuredCode = typeof source.code === "string" && source.code.trim() !== "";
  const isWrite = ["create", "update", "delete"].includes(operationPolicy.sideEffect);
  const unknownWriteOutcome = source.code === "UNKNOWN_DISPATCH_OUTCOME"
    || (isWrite && source.outcomeKnown !== true);
  const dispatchOccurred = source.dispatchOccurred === true || unknownWriteOutcome;
  const code = unknownWriteOutcome
    ? "UNKNOWN_DISPATCH_OUTCOME"
    : hasStructuredCode
      ? source.code
      : "UNEXPECTED_ERROR";
  const sourceMessage = typeof source.message === "string" && source.message.trim() !== ""
    ? source.message
    : null;
  const message = unknownWriteOutcome
    ? `The write outcome is unknown; reconcile it before any retry.${sourceMessage ? ` Source error: ${sourceMessage}` : ""}`
    : sourceMessage ?? "The operation failed without a source-provided message.";
  const rawDetails = plainJson(source.details ?? {});
  const details = rawDetails && typeof rawDetails === "object" && !Array.isArray(rawDetails)
    ? { ...rawDetails, dispatchOccurred, outcomeKnown: !unknownWriteOutcome }
    : { value: rawDetails, dispatchOccurred, outcomeKnown: !unknownWriteOutcome };
  const retryable = unknownWriteOutcome || isWrite
    ? false
    : source.retryable === true || source.automaticRetryAllowed === true;
  return Object.freeze({
    code,
    message,
    details: Object.freeze(details),
    retryable,
  });
}
