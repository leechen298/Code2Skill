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

## Offline default and opt-in live verification

The first-round Producer pipeline (`scripts/run_pipeline.py`) runs in two verification modes. The default `verify` stage is strictly offline and executes only fixed, repository-maintained steps: strict artifact validation, the detached MCP probe in `--offline` mode (a protocol test: initialize, exact `tools/list`, schema parity, protocol errors, dry-run envelope from a detached copy with a scrubbed credential-free environment — not a network-isolation proof), and deterministic Function/Goal/mock-dispatcher vectors derived from the Canonical Contract by `scripts/run_vectors.py`. The pipeline never executes candidate-declared commands. A capability that cannot be proven offline keeps its runtime phase `not-run` or `requires-review`; the pipeline never probes a live target opportunistically to fill that gap, and a write capability is never called live as a side effect of acceptance.

Live verification is a separate opt-in `runtime-verify` stage that performs real `tools/call` invocations through the repository-fixed live caller. Enabling it (`--enable-runtime-verify`), and every per-capability write authorization (`--authorize-write`), applies to a single invocation only and is never persisted; a later plain run never re-executes live calls. Whenever the inputs behind existing live evidence change, that evidence and every conclusion built on it are voided before `finalize` runs. Live inputs and results persist in the Producer verification directory in the explicit caller-sanitized shape the finalizer expects, and are hashed only after persistence; the pipeline does not generically redact business data, so enabling live verification is the operator's statement that the environment's inputs and results may be persisted. Host verification is not executed by the pipeline in this round; it remains a separately reported state in the verification matrix.

## Minimum test matrix

The matrix is not selected manually. Derive the minimum `verificationChecks` for each Capability from the Canonical Contract: every Capability gets valid input/output, invalid-input rejection, and structured error recovery; HTTP, dynamic-domain, conditional, attachment, write, backend-authoritative, Goal, and derived-composition facts add their applicable checks. Canonical custom checks may append to this set but cannot remove it. Finalization rejects a `passed` phase that omits any required `checkId`; an unpassed phase retains the missing IDs and remains below approval.

For every Tool:

- one valid minimal request;
- optional fields, bounds, pagination, sorting, or filters when applicable;
- malformed and missing required inputs;
- authorization and tenant rejection when applicable;
- upstream failure and stable error mapping;
- backend business rejection with structured category/code/message/field details when available, proving the Agent can correct information without treating MCP as broken;
- for an optional upstream-provided input whose `targetRequiredness.status` is `unproven`, one controlled omission vector proving the Function does not promote the value to a local hard requirement and preserves the target API's structured acceptance or rejection decision;
- for writes, a response-proven rejection marked with trusted `outcomeKnown: true`, preserving its actionable code but remaining non-retryable, plus a timeout/reset/disconnect or unmarked failure that becomes non-retryable `UNKNOWN_DISPATCH_OUTCOME`;
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
- every Tool listed by the detached MCP runtime compared exactly with the Canonical-derived input/output Schema and four annotations, plus a Schema-valid success, one rejected invalid-argument case even for zero-input Tools, matching text projection, handler-level structured execution error, and applicable dry-run;
- a Host profile without confirmation, session, or attachment support, proving capability-specific disablement or `requires-host-integration` rather than silent weakening.
- repeated generation from the same authorized sources, proving stable business identities and semantically equivalent Canonical Contracts after normalization.
- a client-feature fixture with extra backend-internal methods, proving only the client's real API surface contributes candidate Function/MCP capabilities;
- a simple write whose target API owns ordinary business validation, proving no synthetic preflight, validation grant, or hard Workflow is generated and the business error remains recoverable;
- a genuinely protected write, proving its declared hard Guard rejects bypass with zero external writes;
- an attachment fixture, proving the Host supplies the approved attachment while the generated business upload and downstream binding remain platform-neutral. For every Canonical `contentBinding` target, a passed `attachment-resolution-runtime-vector` records `attachmentProof` bound to the exact `stepId`, request `location`, and `path`: exactly one resolver call and one business dispatch on success, zero dispatch when resolution fails, no raw-grant forwarding, resolved content in the declared request field, and verified size plus digest. Compute `traceEvidenceHash` as the canonical JSON SHA-256 of the proof without that field; the enclosing check's `evidenceHash` must equal the same digest;
- at least two additional synthetic features with different languages, contract names, and repository topologies, proving the implementation is not specialized for one project or one business flow.

## Verification matrix

Before recording runtime reachability, run the repository-provided detached protocol probe:

```bash
python3 <skill-root>/scripts/probe_mcp.py <candidate> \
  --call /path/to/valid-tool-call.json \
  --error-call /path/to/execution-error-tool-call.json \
  --dry-run-call /path/to/dry-run-tool-call.json
```

It verifies MCP initialize, exact Tool discovery, the unknown-Tool protocol error, supplied Schema-valid successful calls, one structured handler execution error per Tool, the exact dry-run envelope, and independence from source-repository `node_modules`. Missing-argument protocol checks remain distinct from handler-level business/authorization/upstream failures. The probe does not by itself prove zero dispatch; record a separate Function/Guard check with a counted dispatcher. A successful detached probe is build/protocol evidence; it becomes capability runtime evidence only when the supplied non-dry-run call actually reaches the authorized target and its capability-scoped live input/result hashes are retained.

`verification-matrix.json` contains one row for every capability and every declared deterministic workflow. A package with no hard Workflow has no synthetic Workflow row. Each row records the exact checks and evidence behind its current state:

- `generated`;
- `behavior-verified`;
- `runtime-verified`;
- `host-verified`;
- `requires-review`;
- `blocked`.

The matrix must also retain deterministic, human-readable `reviewItems` derived from Canonical `missingEvidence`, unproven input `targetRequiredness`, unresolved conflicts, and Host compatibility restrictions. Each item has a stable `issueRef` back to the exact Canonical or compatibility field; copied input/provider, detail, claim, requirement ID, and compatibility status are mechanical projections of that field. `currentDisposition` is copied from Canonical readiness or Host compatibility, while `recommendedAction` uses a closed generic action (`provide-evidence-and-run-controlled-test`, `resolve-conflict-and-run-controlled-test`, or `configure-host-requirement`) rather than guessed project advice. Do not hand-author another warning list. Finalization re-derives these items while updating verification state, and `approval-audit.json` carries each Capability's exact matrix `reasons` and `issueRefs`. A Capability with no concrete uncertainty has empty arrays. Unproven ordinary target requiredness may remain usable while its controlled-test question stays visible; missing safety evidence can still require review. A fabricated type, upload chain, or Guard is a generation defect and cannot be made acceptable merely by adding a warning.

Do not copy a successful live receipt across rows. A read-only call proves nothing about an unexecuted calculation, upload, validation, or write capability. If a real write test is unsafe or unavailable, retain `requires-review`; another Tool's success cannot approve it.

Verify `host-compatibility-report.json` from `consumer-requirements.json` and `host-profile.json`. Host compatibility is about facilities, not product names. Missing facilities must produce deterministic per-capability degradation.

Do not mark a Capability `hostVerified` merely because its Host check command passed: its compatibility assessment must also be `enabled`. A Workflow additionally requires every Capability named by its Canonical `capabilityIds` to be enabled. Writes require Host verification for approval; a read with no Host requirements may pass the Host gate without claiming `hostVerified`. Keep Canonical `requires-review` separate from Host integration status.

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

“Skill installed” means only that a Skill discovery mechanism copied or linked the knowledge package. It does not mean the MCP process is registered, reachable, authenticated, runtime verified, Host verified, or deployed. Report those states separately according to `MCP-SETUP.md` and the verification matrix.

Never infer a later state from an earlier one.
