function jsonSafe(value, seen = new Set()) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (typeof value === "undefined") return null;
  if (typeof value === "bigint" || typeof value === "symbol") {
    return String(value);
  }
  if (value instanceof Error) {
    if (seen.has(value)) return "[circular]";
    seen.add(value);
    const properties = Object.fromEntries(
      Object.entries(value)
        .filter(([key, child]) => key !== "stack" && child !== undefined && typeof child !== "function")
        .map(([key, child]) => [key, jsonSafe(child, seen)]),
    );
    const result = {
      ...properties,
      name: value.name,
      message: value.message,
    };
    if (value.code !== undefined && !Object.hasOwn(result, "code")) {
      result.code = jsonSafe(value.code, seen);
    }
    if (value.cause !== undefined && !Object.hasOwn(result, "cause")) {
      result.cause = jsonSafe(value.cause, seen);
    }
    seen.delete(value);
    return result;
  }
  if (Array.isArray(value)) {
    if (seen.has(value)) return "[circular]";
    seen.add(value);
    const result = value.map((item) => (
      item === undefined || typeof item === "function" || typeof item === "symbol"
        ? null
        : jsonSafe(item, seen)
    ));
    seen.delete(value);
    return result;
  }
  if (value && typeof value === "object") {
    if (seen.has(value)) return "[circular]";
    seen.add(value);
    const result = Object.fromEntries(
      Object.entries(value)
        .filter(([, child]) => child !== undefined && typeof child !== "function")
        .map(([key, child]) => [key, jsonSafe(child, seen)]),
    );
    seen.delete(value);
    return result;
  }
  return String(value);
}

function asStructuredContent(value) {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : { value };
}

function result(value, isError) {
  const serialized = jsonSafe(value);
  const structuredContent = asStructuredContent(serialized);
  return {
    content: [{ type: "text", text: JSON.stringify(structuredContent) }],
    structuredContent,
    isError,
  };
}

export async function readHttpResponse(response) {
  return {
    httpStatus: response.status,
    bodyText: await response.text(),
  };
}

export function httpResultFromError(error) {
  const response = error && typeof error === "object" ? error.response : null;
  if (!response || typeof response !== "object" || response.status === undefined) {
    return null;
  }
  return {
    httpStatus: response.status,
    body: response.data,
  };
}

export function toAgentResult(value) {
  return result(value, false);
}

export function toAgentError(error) {
  return result(error, true);
}
