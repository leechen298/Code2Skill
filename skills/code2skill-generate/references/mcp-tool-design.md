# MCP Tool design

## Portable contract and Runtime Profile

Choose Tool boundaries and business contracts in `canonical-contract.json` before choosing a language, SDK, schema library, or transport. The Canonical Contract is portable; a Runtime Profile is an adapter that must preserve its names, requiredness, value domains, failure behavior, side effects, confirmation policy, and hard preconditions.

The current `strict-export-v1` package is the supported `node-stdio` Runtime Profile. Requirements below that mention Node, Zod, literal `registerTool`, or stdio are requirements of this profile, not universal facts about all future Code2Skill consumers. Another profile must pass behavior-equivalence checks against the same Canonical Contract.

## Public Tool contract

Define for each Tool:

- stable machine name and user-facing business description;
- user-facing top-level `title` and semantic descriptions for schema properties;
- input schema with semantic descriptions, required fields, enums, and bounds;
- output schema or a documented stable result shape;
- context references;
- Canonical `sideEffect`: `read`, `create`, `update`, or `delete`; describe destructive, financial, publishing, or external risk separately in annotations, operation summaries, and hard workflows rather than replacing this closed vocabulary;
- authentication, authorization, and tenant behavior;
- runtime-enforced preconditions and source constraints;
- typed or machine-distinguishable errors;
- code and test evidence.

Generate or deterministically check this public contract from the Canonical Contract. Function, MCP schema, documentation, and tests must not independently reinterpret input requiredness or output meaning.

For a client feature, derive candidate executable behavior from the backend APIs the client actually calls. One API call may contribute to several business Tools and one Tool may coordinate several observed API calls, but server-side internal methods outside that client call graph are not public candidates unless the user explicitly expands scope or another public entry surface proves them.

Expose one explicit handler per Tool. Shared internal helpers are encouraged. A single generic handler that accepts an operation name is not.

For a Node `strict-export-v1` package, use the official MCP SDK's `McpServer`, one literal `registerTool("tool_name", ...)` call per capability, Zod input/output shapes, and `StdioServerTransport`. Do not hide registration in a loop driven by bundle names and do not replace that surface with a hand-written JSON-RPC loop; protocol behavior and the one-registration-per-capability mapping must be mechanically inspectable.

Every vNext Tool callback receives exactly `(input, runtimeContext)` from the MCP runtime and calls exactly its matching Canonical Function with those two values. It may not derive runtime context, identity, confirmation, Guard state, attachment resolution, or dispatch from public input, and it may not perform adapter, network, or file work before the Function boundary. The only pre-Function branch is the exact first-statement dry-run return. Normal execution uses the reviewed shape `try { Function -> direct success projection } catch (error) { normalizeToolError -> direct isError projection }`, importing the byte-exact `portable-error-normalizer.mjs`. This keeps business errors actionable while forcing unknown dispatch outcomes to remain non-retryable.

The catch path calls `normalizeToolError(error, <literal Canonical operationPolicy>)` with exactly those two arguments; omitting the policy or constructing a different adapter policy is invalid. For `create`, `update`, or `delete`, a structured code alone does not prove the write outcome: transport codes such as timeout/reset and every unmarked write failure normalize to `UNKNOWN_DISPATCH_OUTCOME` with `retryable: false`. A generated Function may add trusted `outcomeKnown: true` only for a response-proven backend rejection or deterministic pre-dispatch Guard failure; that preserves the actionable source code/details but remains `retryable: false`. Correcting inputs after guidance is a new attempt, not automatic replay.

Preserve semantic object boundaries from the authoritative source contract. A source `filters` or `request` object stays a single object Tool input unless evidence proves that its members are independent API inputs. Screen controls are evidence about field meaning, not permission to flatten or regroup the execution contract.

Put `title` at the Tool's top level. Do not hide it only under `annotations`. Use annotations for read-only, destructive, idempotent, and open-world hints; annotations never replace enforcement.

## Execution boundary

Choose how the handler reaches business logic only after locating the authoritative runtime boundary:

- use the application's supported HTTP/RPC API when it owns authentication, tenancy, transactions, audit, or shared state;
- use a shared domain service only when the MCP and application truly share the same authorization context, persistence, and transaction semantics;
- do not import helpers merely to avoid HTTP when that bypasses middleware or changes observable errors;
- do not instantiate a second in-memory repository, idempotency set, token registry, or workflow state machine for MCP.

If direct integration is intentionally different from the original client path, record and test the equivalence. Otherwise preserve method, target allowlist, parameter binding, response validation, and error mapping from the authoritative API.

Treat each business-service base URL as deployment configuration, not a public Tool argument. Give independent services separate, semantically named environment bindings. Generated Functions must not default to a source repository's development, staging, or production host; a missing required binding fails before dispatch. Source-observed environment URLs may appear in setup guidance as deployment references, but the Consumer Host explicitly selects the runtime target. A fixed endpoint mandated by a public protocol, or an upload/callback/pre-signed endpoint returned at runtime by an authoritative service, is not a hidden business-service default and may remain source-bound.

The target API remains authoritative for ordinary business validation. The Function validates its public structure, serialization, safe bounds, and proven non-bypassable constraints, then preserves a server business rejection as a structured failure. Do not recreate every server condition in generated code or insert a synthetic preflight merely to avoid receiving a normal business error.

Keep the generated Function core dependency-free apart from statically imported, non-effectful `node:` built-ins accepted by the validator. Filesystem, process-spawning, socket/HTTP, dynamic-module, VM, worker, and equivalent effectful Node modules are not allowed; use the Canonical request or Host boundary for business I/O. The Function must validate direct calls and return one `{status, data}` result whose `data` is the raw business output. The MCP adapter owns protocol schemas and error conversion; it must not duplicate HTTP logic or wrap that Function result in another `{status, data}` layer.

Importing generated business modules must be inert: module initialization and helper definitions may not perform network, file, process, upload, or dispatch work. Literal Tool registration is declarative, and the executable MCP entry point may perform only its reviewed stdio transport startup outside callbacks; every business effect remains behind the matching named Function and dry-run boundary.

Bundle the SDK/Zod runtime as one self-contained `runtime.mjs`. It has no third-party bare, relative, or dynamic imports and, because this profile is stdio-only, contains no client-network or process-control primitives. The readable MCP adapter remains unbundled for literal registration and callback inspection.

## Tool versus other forms

| Situation | Prefer |
| --- | --- |
| Tiny, stable values used only to validate one input | `inputSchema.enum` |
| Explanatory or mostly static knowledge | Skill reference |
| Application-controlled context that should be read dynamically | MCP Resource |
| Independently queried, filtered, explained, dynamic, or reused values | MCP Tool |
| Mandatory ordered/transactional sequence | Deterministic workflow or one transactional Tool |

A local constant should be a Tool (or Resource) when users can independently ask for it, its labels carry business meaning, several downstream capabilities reuse it, or callers should not depend on schema introspection. Examples include available knowledge topics, supported content languages, or a structured application-field catalog. Use a schema enum only when the values are small, stable, and purely validate another input. Record this as a product choice, not an MCP requirement.

## Hard constraints

Examples include IDs issued by prior results, preview tokens, request IDs, pagination cursors, authorization scopes, tenant bindings, monetary confirmation, and state-version checks.

Enforce them through one or more of:

- JSON Schema constraints;
- opaque or signed values;
- handler validation;
- server-side session or persistence;
- authorization and tenant checks;
- idempotency keys;
- a deterministic workflow or transaction.

The Skill should explain the constraint and recovery path, but must not be its only enforcement.

Unknown Tool names and malformed JSON-RPC are protocol errors. Valid Tool calls with schema, business, authorization, or upstream failures are Tool execution errors (for example `isError: true`). Preserve that distinction so clients can recover correctly.

A Tool error must be machine-distinguishable enough for the Consumer to choose the next step. When source evidence permits, retain a stable category (`input`, `business`, `authorization`, `upstream`, `network`, `output-contract`, or `unknown-outcome`), source error code/message, field details, retryability, and whether a dispatched write outcome is known. Preserve matching structured content and `isError: true`; do not expose only an opaque exception string or incorrectly advise retry after an uncertain write. Every capability declares a structured `errorContract` with `preservesRecoveryContext: true`; this means the Agent can explain, collect missing data, retry only when allowed, or stop safely—not that every error is recoverable. Its code/message/details and optional retryability paths are projected into Function behavior, MCP output, documentation, and tests; documentation uses the complete dot-joined paths rather than only their leaf names.

Static schema checks are only one enforcement option. Dynamic value domains, identity-scoped selections, conditional requiredness, derived values, attachment grants, expiry, and single-use rules may be enforced by the authoritative API, a handler, or a session/workflow boundary depending on source evidence. A value seen in one live response is not a stable enum. Do not promote an ordinary server-owned business rule to a hard Workflow unless bypass would violate a proven safety, identity, transaction, provenance, or at-most-once invariant.

For HTTP capabilities, treat each declared success status as part of the public contract. Compare the observed `response.status` against that exact set; do not collapse the contract to `response.ok`. Validate the smallest source-proven usable output, including fixed discriminator values or non-empty collections only when the executable source proves those invariants.

Use standard JSON Schema formats. A source-defined URL result is a string with `format: "uri"`; `format: "url"` is not valid. Opaque tokens, file IDs, and object keys remain ordinary strings and must not be labelled with a URI format merely because they can later be embedded in a request.

The dry-run branch is an inspectable execution boundary. Use the exact variable from `export-profile.json` in a literal `process.env.<declared-variable> === "1"` guard before calling the named Function. Construct one local `dryRunResult` with exactly `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary`, then return it unchanged as `structuredContent` and as a JSON text `content` block with `isError: false`; the input and full policy must match the Canonical projection. The static validator and protocol probe check that envelope, while a counted dispatcher test proves zero external requests.

## Side effects

- Keep read and write operations separate unless atomicity requires a combined contract.
- Prefer preview then confirm for destructive, financial, publishing, and external actions.
- Preserve idempotency and return durable operation identifiers when the source system supports them.
- Never log or embed secrets, session tokens, or sensitive payloads in generated Context or evidence.
- Return the minimum data needed for the Agent's goal.

Every side-effecting Tool must declare an explicit manifest policy. The following is an example for a source-proven, non-idempotent write that really requires trusted confirmation; it is not a default for ordinary writes:

```json
{
  "operationPolicy": {
    "sideEffect": "create",
    "idempotency": "at-most-once",
    "automaticRetry": "never",
    "confirmation": "trusted-confirmation-required",
    "unknownOutcome": "stop-and-reconcile"
  }
}
```

`operationPolicy.sideEffect` must equal the capability's top-level `sideEffect`. Allowed confirmation requirements are `not-required`, `trusted-confirmation-required`, and `upload-confirmation-required`. The actual enforcement owner is declared separately through Consumer requirements and `workflows[].enforcement.owner`; do not introduce a competing `confirmationOwner` field. A Tool parameter such as `confirmed: true` is Agent self-attestation, not confirmation. Host confirmation for a risky operation should bind at least the target, payload digest, relevant preview/check token, and side-effect summary. If the Host/runtime integration is unavailable, keep the operation in `requires-review` status.

Default a normal client-observed API write to `confirmation: "not-required"` and `runtimeProtection.mode: "backend-authoritative"` when the target API owns ordinary validation and the source proves no additional non-bypassable boundary. A browser dialog, button click, page sequence, authentication header, or generic session alone is interaction evidence, not proof that the Host must issue a confirmation grant, operation key, protected workflow state, expiry record, or single-use token. Generate those values only when an exact source contract proves who issues them, where the trusted runtime obtains them, what they bind, and that they are checked before dispatch. Otherwise retain the UI confirmation as Skill guidance and leave any genuinely unresolved safety question in the review report—never fabricate a Guard to make the package look safer.

Set automatic retry to `never` for non-idempotent or unknown-idempotency operations. On a timeout, disconnect, or lost response after dispatch, report the outcome as unknown and require reconciliation before another attempt.

For non-idempotent chains with proven non-bypassable edges, such as a server-issued validation grant → trusted confirmation → create, emit and test a deterministic workflow or Host integration contract. A short-lived confirmation grant should be bound to user/session, target, payload digest, validation token when one truly exists, expiry, and single use. A simple API write that relies on ordinary backend validation does not need a fabricated validation grant. If a required hard boundary cannot be enforced, mark the protected write path `requires-review`.

Each hard binding declares an actual source, a protected expected source, `json-equals`, and evidence. Expected values come only from protected session/runtime state or an immutable constant, never from a public Tool argument or the same `bindings` object. The protected Guard stores both actual-source projections and expected values. The Function passes only the exact input, trusted runtime context, workflow ID, and opaque operation key; the Guard projects, compares, freezes, and dispatches that same input. It rejects caller-supplied binding fields and never runs an arbitrary verifier callback before dispatch.

## Attachments

When the observed client/API path proves attachments are part of the business feature, generate the business upload capability and model the chain beyond a string URL input: a Host-approved attachment reference or bounded content, upload authorization, transfer, returned token/URL/file ID/object, and downstream binding. The provider output path, target input source strategy, typed handoff, observed graph edge, attachment consumer binding, and actual implementation request binding must agree mechanically.

An STS credential, presigned-request helper, upload authorization, or storage token alone is not the business upload capability and must not be exposed as if the chain were complete. The generated Function/MCP boundary owns every source-proven step needed to turn approved attachment content into the business result consumed downstream. Do not expose raw storage credentials to the model when they are only an internal implementation detail. If the authorized sources do not contain enough evidence to implement that transfer, keep only the affected attachment path below approval and state the missing upload contract; unrelated capabilities remain usable.

Never accept an arbitrary local filesystem path. A public input may accept a Host-approved opaque reference, or bounded logical values such as sanitized filename, media type, size, digest, and content. Runtime enforcement must prove that downstream attachment values came from the approved upload path when the business rule requires it.

The external Consumer Host is responsible for receiving or otherwise providing the approved attachment. Code2Skill does not implement message ingress, file download, or brand-specific adapters. Declare attachment provision/resolution and any Host-owned secure-content boundary in `consumer-requirements.json`. An opaque grant is only a protected reference plus metadata; the implementation must resolve it through the generic `attachment-resolution` facility and bind the resolved content or stream to the source-proven body/multipart field. It must never upload the grant JSON as file content. Record every exact field in the closed `attachments.contentBindings` list and require unique, complete agreement with the implementation's final output step. If the actual `host-profile.json` lacks the required facility, `host-compatibility-report.json` must disable or mark attachment-dependent capabilities `requires-host-integration` while leaving unrelated capabilities available.

## Consumer capability requirements

Do not branch behavior by Host brand. Describe the required facilities: Skill discovery, MCP transport/runtime, authentication injection, trusted confirmation, session state, approved attachment resolution, and unknown-outcome reconciliation. Determine availability by comparing `consumer-requirements.json` with the deployment's `host-profile.json`. Attachment upload is a generated business Tool responsibility when the client-observed API proves it; the Host only supplies an approved reference or bounded content.

Host incompatibility is capability-specific. Missing trusted confirmation disables protected final writes; missing session state disables workflows that depend on bound one-time grants; missing attachment support disables attachment-dependent paths. Never weaken the business contract to make an incompatible Host appear supported.

## Anti-patterns

- one Tool wrapping a complete page flow with many optional sub-operations;
- `call_api`, `execute_sql`, or arbitrary service-method execution;
- Tool count copied from request count or function count;
- prose-only source validation for IDs or tokens;
- Tool descriptions that expose implementation vocabulary but omit business meaning;
- success responses that erase partial failures or ambiguity.
- boolean confirmation parameters that let the Agent approve its own action;
- non-idempotent writes with automatic retries or no unknown-outcome policy.
- server-internal methods exposed only because they were found outside the scoped client's real API call graph;
- universal preflight, validation grants, or hard Workflows generated for ordinary backend-owned business validation;
- opaque error strings that prevent an Agent from distinguishing a correctable business rejection from an authorization, network, output-contract, or unknown-outcome failure.
