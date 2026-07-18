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
- “Deployed” means a delivery action succeeded.

Never infer a later state from an earlier one.
