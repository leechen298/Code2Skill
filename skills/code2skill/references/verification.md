# Verification

## Layers

Report each layer separately:

1. **Artifact structure**: Skill and manifest validation passes.
2. **Static correctness**: types, lint, schema validation, and build pass.
3. **Tool behavior**: each Tool succeeds and fails correctly in isolation.
4. **Composition**: partial goals and representative multi-Tool paths work.
5. **Runtime constraints**: invalid provenance, permissions, states, or unsafe inputs are rejected.
6. **Execution equivalence**: MCP uses the authoritative auth, transaction, persistence, and idempotency boundary; cross-channel behavior is consistent.
7. **End to end**: a real MCP client lists and calls the Tools against an appropriate environment.
8. **Delivery**: merge, deployment, and production verification are distinct later states.

Apply these layers per capability and per hard workflow. A package-level summary is derived from those rows; it never upgrades a weaker row.

## Minimum test matrix

For every Tool:

- one valid minimal request;
- optional fields, bounds, pagination, sorting, or filters when applicable;
- malformed and missing required inputs;
- authorization and tenant rejection when applicable;
- upstream failure and stable error mapping;
- output contract validation.

For the capability set:

- one single-Tool partial goal;
- one path that skips irrelevant option-loading calls;
- one multi-Tool reconstruction of the observed product flow;
- one repeated composition such as comparison or pagination;
- one recovery from a stale or invalid server-issued value;
- one attempt to bypass every hard precondition.
- one attempt by the Agent to self-attest confirmation without a Host/runtime grant;
- one ambiguous post-dispatch failure for each non-idempotent Tool, proving no automatic retry.
- one cross-channel or multi-process check proving MCP does not maintain a divergent private copy of mutable application state.
- information supplied in different orders, proving the same completion predicate is reached without repeated questions;
- all required information supplied up front, proving unnecessary lookups and prompts are skipped;
- one `derived composition` distinct from the observed client path, with separate evidence;
- every dynamic value tested for provenance, identity/session scope, expiry, and refresh behavior;
- every conditional requirement tested on both sides of its condition;
- every derived value rejected when fabricated by the caller;
- every attachment-dependent path tested from approved reference/content through upload result and downstream binding;
- a Host profile without confirmation, session, or attachment support, proving capability-specific disablement or `requires-host-integration` rather than silent weakening.
- repeated generation from the same authorized sources, proving stable business identities and semantically equivalent Canonical Contracts after normalization.

## Verification matrix

`verification-matrix.json` contains one row for every capability and every deterministic workflow. Each row records the exact checks and evidence behind its current state:

- `generated`;
- `behavior-verified`;
- `runtime-verified`;
- `host-verified`;
- `requires-review`;
- `blocked`.

Do not copy a successful live receipt across rows. A read-only call proves nothing about an unexecuted calculation, upload, validation, or write capability. If a real write test is unsafe or unavailable, retain `requires-review`; another Tool's success cannot approve it.

Verify `host-compatibility-report.json` from `consumer-requirements.json` and `host-profile.json`. Host compatibility is about facilities, not product names. Missing facilities must produce deterministic per-capability degradation.

## Finalization input report

Create the vNext `--verification-report` as JSON conforming to [`../assets/verification-report.schema.json`](../assets/verification-report.schema.json). It is input evidence, not the generated `verification-matrix.json` and not the legacy human [`verification-report.md`](../assets/verification-report.md).

The report must:

- use `schemaVersion: vNext` and the exact Canonical `contractId`;
- cover every Canonical Capability exactly once with `behavior`, `runtime`, and `host` phases;
- cover every Canonical hard Workflow exactly once with `bypass`, `runtime`, and `host` phases;
- record `not-run`, `requires-review`, or `blocked` explicitly instead of omitting an unverified row;
- include only commands actually executed, with exit code and SHA-256 `evidenceHash` of captured evidence;
- include the Canonical `toolName` and matching live `inputHash` and `resultHash` on every passed runtime check;
- set `zeroExternalWrites: true` on every passed Workflow bypass check and cover its Canonical `verificationChecks` by `checkId`.

The finalizer accepts repeated, ordered `--live-input FILE --live-result FILE` pairs. A vNext input entry is shaped as:

```json
{
  "capabilityId": "<canonical-capability-id>",
  "input": {
    "name": "<canonical_tool_name>",
    "arguments": {}
  }
}
```

Its matching result entry is:

```json
{
  "capabilityId": "<canonical-capability-id>",
  "result": {
    "isError": false,
    "structuredContent": {
      "status": 200,
      "data": {"<required-output>": "<sanitized-value>"}
    }
  }
}
```

One file may contain one entry, an array, or a `capabilities` array. Input and result files must name the same Capability IDs. The Tool name must match the Canonical Tool, and the result must satisfy that Capability's required and forbidden output paths. Repeat pairs only for Capabilities actually exercised; missing live evidence keeps that row below `runtime-verified`. The report's runtime hashes must match these sanitized payloads. A successful command without this binding is behavior/build evidence, not runtime evidence.

The aggregate legacy report and one unscoped live pair are accepted only for one read-only bundle without `canonical-contract.json`. Never use that compatibility path for vNext, multiple Tools, or any write capability.

## Golden baselines

A Golden represents a capability model, not merely passing code. When the model changes—for example from one page-level operation to several reusable Tools—mark old results:

```text
SUPERSEDED
Reason: capability model and Golden benchmark changed
Valid for current specification: false
```

Retain historical evidence for auditability, but do not count it as current proof. Rebuild the Golden around current Tool boundaries, independent contracts, compositions, and runtime constraints.

## Completion language

Use precise status statements:

- “Generated” means files exist.
- “Validated” means deterministic artifact checks pass.
- “Built” means the MCP/Skill packages compile or load.
- “Behavior verified” means relevant Tool and composition tests pass.
- “Runtime verified” means a real client/environment was exercised.
- “Host verified” means the declared Consumer Host facilities were checked and the capability ran with required confirmation/session/attachment/authentication behavior.
- “Requires Host integration” means the business contract may be complete but a required trusted Host facility is absent.
- “Deployed” means a delivery action succeeded.

Never infer a later state from an earlier one.
