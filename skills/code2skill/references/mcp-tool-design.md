# MCP Tool design

## Public Tool contract

Define for each Tool:

- stable machine name and user-facing business description;
- user-facing top-level `title` and semantic descriptions for schema properties;
- input schema with semantic descriptions, required fields, enums, and bounds;
- output schema or a documented stable result shape;
- context references;
- side-effect class: `none`, `write`, `destructive`, `financial`, or `external`;
- authentication, authorization, and tenant behavior;
- runtime-enforced preconditions and source constraints;
- typed or machine-distinguishable errors;
- code and test evidence.

Expose one explicit handler per Tool. Shared internal helpers are encouraged. A single generic handler that accepts an operation name is not.

For a Node `strict-export-v1` package, use the official MCP SDK's `McpServer`, one literal `registerTool("tool_name", ...)` call per capability, Zod input/output shapes, and `StdioServerTransport`. Do not hide registration in a loop driven by bundle names and do not replace that surface with a hand-written JSON-RPC loop; protocol behavior and the one-registration-per-capability mapping must be mechanically inspectable.

Preserve semantic object boundaries from the authoritative source contract. A source `filters` or `request` object stays a single object Tool input unless evidence proves that its members are independent API inputs. Screen controls are evidence about field meaning, not permission to flatten or regroup the execution contract.

Put `title` at the Tool's top level. Do not hide it only under `annotations`. Use annotations for read-only, destructive, idempotent, and open-world hints; annotations never replace enforcement.

## Execution boundary

Choose how the handler reaches business logic only after locating the authoritative runtime boundary:

- use the application's supported HTTP/RPC API when it owns authentication, tenancy, transactions, audit, or shared state;
- use a shared domain service only when the MCP and application truly share the same authorization context, persistence, and transaction semantics;
- do not import helpers merely to avoid HTTP when that bypasses middleware or changes observable errors;
- do not instantiate a second in-memory repository, idempotency set, token registry, or workflow state machine for MCP.

If direct integration is intentionally different from the original client path, record and test the equivalence. Otherwise preserve method, target allowlist, parameter binding, response validation, and error mapping from the authoritative API.

Keep the generated Function core dependency-free apart from `node:` built-ins. It must validate direct calls and return one `{status, data}` result whose `data` is the raw business output. The MCP adapter owns protocol schemas and error conversion; it must not duplicate HTTP logic or wrap that Function result in another `{status, data}` layer.

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

For HTTP capabilities, treat each declared success status as part of the public contract. Compare the observed `response.status` against that exact set; do not collapse the contract to `response.ok`. Validate the smallest source-proven usable output, including fixed discriminator values or non-empty collections only when the executable source proves those invariants.

The dry-run branch is an inspectable execution boundary. Use the exact variable from `export-profile.json` in a literal `process.env.<declared-variable> === "1"` guard before calling the named Function. Return `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary` derived from the capability and request plan, with no external request.

## Side effects

- Keep read and write operations separate unless atomicity requires a combined contract.
- Prefer preview then confirm for destructive, financial, publishing, and external actions.
- Preserve idempotency and return durable operation identifiers when the source system supports them.
- Never log or embed secrets, session tokens, or sensitive payloads in generated Context or evidence.
- Return the minimum data needed for the Agent's goal.

Every side-effecting Tool must declare this manifest policy:

```json
{
  "operationPolicy": {
    "confirmationOwner": "host",
    "idempotency": "non-idempotent",
    "automaticRetry": "never",
    "unknownOutcome": "Stop and require an operation-status lookup or human reconciliation."
  }
}
```

Allowed confirmation owners are `host`, `runtime`, and `not-required`. A Tool parameter such as `confirmed: true` is Agent self-attestation, not confirmation. Do not expose such a parameter as evidence of consent. Host confirmation for a risky operation should bind at least the target, payload digest, relevant preview/check token, and side-effect summary. If the Host/runtime integration is unavailable, keep the operation in `requires-review` status.

Set automatic retry to `never` for non-idempotent or unknown-idempotency operations. On a timeout, disconnect, or lost response after dispatch, report the outcome as unknown and require reconciliation before another attempt.

For non-idempotent chains such as validate → confirm → create, emit and test a deterministic workflow or Host integration contract. A short-lived confirmation grant should be bound to user/session, target, payload digest, validation token, expiry, and single use. If the runtime cannot enforce that contract, mark the write path `requires-review`.

## Anti-patterns

- one Tool wrapping a complete page flow with many optional sub-operations;
- `call_api`, `execute_sql`, or arbitrary service-method execution;
- Tool count copied from request count or function count;
- prose-only source validation for IDs or tokens;
- Tool descriptions that expose implementation vocabulary but omit business meaning;
- success responses that erase partial failures or ambiguity.
- boolean confirmation parameters that let the Agent approve its own action;
- non-idempotent writes with automatic retries or no unknown-outcome policy.
