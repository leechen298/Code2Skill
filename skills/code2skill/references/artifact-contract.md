# `node-stdio` strict export artifact contract

Code2Skill defaults to `strict-export-v1`, the current `node-stdio` Runtime Profile: a self-contained candidate package that another MCP Host, reviewer, or evaluator can inspect and execute without reading the source repository. Its Portable Core is language- and Host-independent; Node, Zod and stdio requirements apply to this Runtime Profile, not to every future adapter.

```text
generated/code2skill/<feature-id>/
├── export-profile.json
├── source-topology.json
├── canonical-contract.json
├── goal-contract.json
├── consumer-requirements.json
├── host-profile.json
├── host-compatibility-report.json
├── verification-matrix.json
├── capability-bundle.json
├── capability-draft.json
├── SKILL.md
├── MCP.zh-CN.md
├── MCP-SETUP.md
├── references/
│   ├── feature-context.md
│   └── capability-contracts.json
├── function-core/
│   ├── capability-bundle.json
│   ├── index.mjs
│   ├── schema-contract.json
│   └── validation-receipt.json
├── mcp-tool/
│   ├── index.mjs
│   ├── runtime.mjs                # bundled official SDK and schema runtime
│   └── schema-contract.json
├── portable-workflow-guard.mjs   # only when vNext declares a hard workflow
├── portable-error-normalizer.mjs # reviewed structured Tool error projection
├── workflow.json                 # legacy bundle-only writes only
├── preflight-report.json
├── approval-audit.json
├── live-verification.json
└── export-manifest.json
```

Do not replace this package with links to runtime code elsewhere. Repository-native code may coexist, but this Runtime Profile must contain an executable Function core and stdio MCP entry point.

`canonical-contract.json` is the portable authority. `capability-bundle.json` is its `node-stdio` execution view, not a separate place to reinterpret the business contract. The capability graph is embedded in the Canonical Contract.

## Generation phases

1. **Discover**: record every authorized root and missing evidence role in `source-topology.json`.
2. **Model**: author `canonical-contract.json`, including goals, the capability graph, and Consumer requirement definitions; obtain a deployment `host-profile.json` before executable code is finalized.
3. **Draft**: derive `goal-contract.json`, `consumer-requirements.json`, Host compatibility, the capability bundle/draft, and initial verification matrix; then build or cross-check the Function core, MCP runtime, Feature Context, Skill, MCP contract, and MCP setup document.
4. **Pre-finalization validation**: run `validate_artifacts.py --pre-finalize`; build and execute Function tests plus the detached `scripts/probe_mcp.py` protocol probe.
5. **Live verification**: exercise appropriate real `tools/call` paths and retain capability-scoped sanitized input/result JSON outside the candidate directory.
6. **Finalization**: run `finalize_export.py` with a vNext report conforming to `assets/verification-report.schema.json` and matching live evidence pairs. The script writes receipts, hashes, capability/workflow status, approval summary, and the manifest.
7. **Final validation**: run `validate_artifacts.py` without `--pre-finalize`.

Never fabricate passed evidence. A capability may claim `runtime-verified` only when its own live evidence exists; unavailable live access leaves that row at `requires-review` and prevents a fully approved package summary. Other independently verified capabilities may retain their proven status.

## Export profile

`export-profile.json` makes target-specific execution policy explicit without baking a particular evaluator into Code2Skill:

```json
{
  "schemaVersion": "v1",
  "profile": "strict-export-v1",
  "protocolVersion": "2025-11-25",
  "transport": "stdio",
  "documentationLanguage": "zh-CN",
  "featureSurface": {
    "kind": "route",
    "identifier": "/knowledge"
  },
  "allowedRuntimeOrigins": ["https://application.example"],
  "dryRunEnvironmentVariable": "CODE2SKILL_DRY_RUN"
}
```

Resolve the feature surface and runtime origin from the target repository's public startup/configuration contract. `featureSurface.kind` is `route`, `backend-api`, `rpc`, `message`, `worker`, or `other`; its `identifier` is the source-proven route, operation family, topic/consumer, worker, or equivalent stable feature identity. vNext does not use `pageRoute`; business background lives at `references/feature-context.md`. When an external harness supplies a different dry-run variable, protocol, language, or allowed origin, record those values and implement exactly them. The Function request origin and `allowedRuntimeOrigins` must agree; do not substitute a placeholder or guess evaluator-specific constants. Legacy packages may retain `pageRoute` only under the legacy validator contract.

For a client feature, the client-observed backend APIs determine the candidate executable surface. Backend, protocol, and test evidence supplement their public inputs, outputs, dynamic values, authorization, side effects, idempotency, and error meaning. A backend-internal operation outside the scoped client call graph is excluded unless the user explicitly expands scope or another authorized public surface proves it belongs.

## Capability bundle

`capability-bundle.json` and `function-core/capability-bundle.json` must be equivalent JSON values. In vNext, generate both bundles and `capability-draft.json` with `scripts/derive_artifacts.py` after every Canonical Contract change instead of maintaining them by hand. The legacy path remains bundle-first when no Canonical Contract exists. The projected bundle uses schema version `v1` and includes:

- one server with evidence;
- 1–40 capabilities with unique `capabilityId`, `toolName`, and `functionExport`;
- explicit authentication, semantic inputs, implementation, success rule, side effect, and evidence for every capability;
- explicit handoffs for result fields that feed later Tool inputs.

The bundle must agree deterministically with `canonical-contract.json`. Public inputs, requiredness, value domains, handoffs, failures, required outputs, side effects, operation policy, and hard prerequisites cannot diverge. Dynamic values scoped to identity, tenant, session, version, or freshness remain dynamic; one observed response must not become a fixed enum.

Derivation also writes byte-equivalent `function-core/schema-contract.json` and `mcp-tool/schema-contract.json`, plus `references/capability-contracts.json`. The first two machine-comparable views contain every Function export/Tool name, closed input Schema, requiredness, source-proven static enums, output envelope/path Schema, all four Tool annotations, conditional rules, constraints, error contract, operation policy, and deterministic Workflow projection. The documentation view additionally binds Feature Context, Skill, and MCP prose to exact feature-surface, input source/freshness, attachment, implementation, policy, and evidence facts. The three documents carry its SHA-256 marker and cannot describe Canonically required inputs as optional or invert write/retry policy. Canonical value Schemas use only the portable subset actually enforced by the Function/finalizer/probe: JSON type, closed object properties/requiredness, array items and size/uniqueness bounds, string pattern/length bounds, numeric bounds, enum, and const. When a string declares `format`, the only supported value is the standard `uri`; a URL output uses `format: "uri"`, while a token/file ID/object key uses no URI format. Conditional rules live in their explicit contract fields; unsupported JSON Schema keywords such as an unimplemented `if/then` must be rejected rather than silently ignored. The detached MCP probe compares the actual `tools/list` surface and successful results with this projection; Function behavior vectors verify the same input, request binding, and output mapping. A copied JSON file alone is not runtime proof.

Each capability implementation is either:

- `local`: no network access, an empty `allowedRuntimeOrigins`, and `successRule.kind: output`; or
- `http`: one or more exact request steps and `successRule.kind: http_status_and_output`.

For HTTP steps preserve method, fixed allowlisted origin, path/query/header/body/multipart bindings, authentication, success statuses, stop-on-failure behavior, and evidence. The allowlist is non-empty exactly when HTTP steps exist; an all-local package must not carry a fake origin. Keep fixed query values in the exact URL template; target-specific ad-hoc fields and unsupported binding-source kinds invalidate the closed Operation schema. A multipart Tool accepts safe logical values such as filename, media type, and bounded content, or a `host_resolved_attachment` binding tied to the generic `attachment-resolution` requirement; never an arbitrary local filesystem path or the opaque grant JSON as file bytes. For opaque grants, the closed `attachments.contentBindings` list must uniquely and exactly cover every implementation binding's input name, resolver requirement, `implementation.outputStepId`, request location, and non-empty target path. Each exact field must cite a shared fact-level `request-construction`, `serialization`, or `transport-contract` record; generic entry, API-call, side-effect, inference, or unknown evidence cannot establish a request target. The portable opaque-grant profile accepts one attachment per Tool invocation; repeat the Tool for multiple attachments so every grant, metadata set, confirmation, and unknown outcome remains independently protected.

Required output paths are contractual. Reject responses that omit them, contain forbidden error keys, or use a status outside the exact declared `successStatusCodes`. Compare `response.status` explicitly; `response.ok` is too broad when the source contract names exact statuses. Do not return a partial success after a failed intermediate step. Preserve a backend business rejection as a structured failure rather than trying to reimplement every server rule locally.

Required output paths are deliberately minimal. Select the smallest source-proven fields that establish a usable success result; do not add every response echo merely because it is present. Validate source-proven fixed discriminators and reject null or empty required values; require a non-empty collection only when executable source evidence proves it. Preserve the application's exact business field and failure-key names. Never invent friendlier aliases.

Preserve the source contract's semantic input grouping. A nested filter, request, pagination, or options object remains one object input when the authoritative API and application treat it as one value. Do not flatten its UI fields into unrelated top-level Tool inputs merely because the screen renders separate controls. Conversely, do not wrap independent source parameters in a new object without evidence.

`successRule.requiredOutputPaths` is evaluated inside the Function result's `data` value. Paths therefore describe business output such as `["options"]`, `["result", "id"]`, or a legitimate business field `["status"]`; they never begin with the envelope key `data`. The MCP `{status, data}` envelope is an adapter contract, not part of these business-output paths.

## Function core

`function-core/index.mjs` exports one named async function per capability. Each Function accepts a direct input object plus an optional runtime context. It validates the exact allowed input keys and semantic types even when called without MCP. HTTP Functions use context-provided `fetch` when supplied, validate allowed origins, execute each request at most once, and stop on network/status/output failure. Local Functions must not fetch.

Each successful Function returns `{status, data}` where `status` is the observed/local status and `data` is the raw contractual business output. It rejects a missing required path in `data`; it does not add a second MCP-shaped envelope or test `requiredOutputPaths` against the whole Function result. Failures retain machine-distinguishable input, business, authorization, upstream/network, output-contract, and unknown-outcome categories when evidence permits, plus source code/message, field details, retryability, and outcome certainty instead of an opaque exception string.

The Function must reproduce the source's observable request and validation contract, including fixed query terms, query flattening of an authoritative object input, root-body bindings, multipart encoding, exact header values, defaults, enum/range/pattern checks, cross-field dependencies, and response invariants. Do not infer these from field names when executable schemas or tests are available.

The Function core is self-contained. It may statically import only non-effectful Node built-ins with `node:` specifiers; filesystem, process-spawning, socket/HTTP, dynamic-module, VM, worker, and equivalent effectful modules are rejected because business I/O must remain behind the Canonical dispatch boundary. It must not depend on npm packages, target-repository modules, or undeclared runtime files. Put schema-library and MCP-SDK dependencies in the MCP adapter, not in the Function core.

Importing the Function core must only establish declarations. Module initialization and helper-definition regions cannot perform network, file, process, upload, or dispatch work outside a named Canonical Function.

The Function core is the sole business execution layer for the generated MCP adapter. The adapter imports these named Functions; it does not reimplement request logic.

## MCP runtime

`mcp-tool/index.mjs` is an executable stdio MCP server for protocol `2025-11-25` and exposes exactly the capability bundle's Tool set. In this `node-stdio` profile, use `@modelcontextprotocol/sdk`, `McpServer`, one explicit literal `server.registerTool("tool_name", ...)` call per capability, Zod schemas, and `StdioServerTransport`. Do not register a bundle in a name-driven loop and do not hand-roll the JSON-RPC transport: the literal SDK registration surface is part of static and protocol verification.

The adapter imports `McpServer`, `StdioServerTransport`, and `z` from `./runtime.mjs`. Build `runtime.mjs` from the official SDK/Zod entry template as one self-contained file, leaving no third-party bare, relative, or dynamic imports. A stdio-only runtime contains no client-network or process-control primitives; business I/O remains behind named Canonical Functions. Keep the adapter unbundled so literal registrations, direct input schemas, annotations, callbacks, and named Function imports remain statically inspectable. Verify the copied candidate starts without access to the source repository or its `node_modules`.

Every `tools/list` entry contains:

- stable `name`, Chinese business `title`, and a detailed Chinese `description`;
- closed `inputSchema` and `outputSchema`, with descriptions on every business field and precise `required` arrays;
- `annotations` covering read-only, destructive, idempotent, and open-world hints.

Use a Chinese title shaped as `领域：动作对象`. Its action half must be specific enough for discovery. The description is at least 110 characters and 60 Chinese characters and explicitly covers purpose, calling conditions, inputs or no-input state, output, handoff/stop behavior, HTTP/local execution, and side effects.

Every `tools/call` accepts direct arguments, not an extra `{input: ...}` wrapper. Each literal registration invokes exactly its matching named Function and exposes that Function's `{status, data}` as both text `content` and matching `structuredContent`; it does not swap Functions, reimplement the business request, or add another `data` layer. Unknown Tool names or malformed JSON-RPC are protocol errors. Schema, business, authorization, upstream, and output failures are Tool execution errors with `isError: true`.

Each callback uses the exact reviewed wrapper: first-statement dry-run, then one `try` that calls the matching Function and projects success directly, followed by `catch (error)` calling `normalizeToolError(error, <literal Canonical operationPolicy>)` with exactly two arguments and projecting `isError: true`. The candidate's normalizer must be byte-identical to the reviewed asset and directly imported. A write Function marks `outcomeKnown: true` only for a response-proven rejection or deterministic pre-dispatch failure; transport and unmarked write errors normalize to non-retryable `UNKNOWN_DISPATCH_OUTCOME`, while known rejections preserve their actionable code but still disallow automatic replay. Outside literal registrations, the MCP module may perform only the single reviewed `server.connect(new StdioServerTransport())` startup; module initialization must not perform other network, file, process, upload, or business-dispatch work.

Run the bundled probe from the Skill root to prove the package works after detachment from the source repository:

```bash
python3 <skill-root>/scripts/probe_mcp.py <candidate> \
  --call /path/to/valid-tool-call.json \
  --error-call /path/to/execution-error-tool-call.json \
  --dry-run-call /path/to/dry-run-tool-call.json
```

The probe copies the candidate to a temporary directory, performs `initialize`, checks exact `tools/list`, verifies the unknown-Tool protocol error, checks missing-required-argument failures, executes one supplied success and one handler-level structured execution error per Tool, validates successes against the Canonical output Schema, and runs supplied calls under the declared dry-run variable. Test every capability-specific invalid enum, range, provenance, business, authorization, and output case separately with structured `isError: true` expectations.

Dry-run must use a literal `process.env.<declared-variable> === "1"` guard before the named Function call and before any network, file, process, upload, or other side effect. It constructs one local result containing exactly `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary`, then returns matching `structuredContent` and JSON text `content` with `isError: false`; validated input and the full policy must match the Canonical projection. The static validator and detached probe validate this envelope. A separate behavior test with a counted/mock dispatcher proves that the branch performs zero external requests.

## Chinese documents

- `references/feature-context.md`: at least 800 characters and 250 Chinese characters of source-derived business background covering feature purpose, user goals, real surface and client-observed API boundary, actors, field semantics, dynamic dependencies, original client behavior, rules, results, every Tool, structured failures, unknowns, excluded abilities, and evidence. It does not assume a page or route. For writes, mention confirmation and Guard only when required by the Canonical policy and a declared hard Workflow.
- `SKILL.md`: Agent Skills-compatible frontmatter plus at least 4000 characters and 1500 Chinese characters. It is guidance, not a forced transcript. Follow [documentation-contract.md](documentation-contract.md).
- `MCP.zh-CN.md`: at least 8000 characters and 2000 Chinese characters. Document transport/protocol, discovery/call envelopes, schemas, annotations, dry-run, errors, handoffs, and every Tool with a full success example plus a structured `isError: true` example. Each Tool section writes every declared `errorContract` path as a complete dot-joined backtick path and states default non-retryability when no retryability path exists.
- `MCP-SETUP.md`: platform-neutral Skill installation and MCP startup/registration/authentication/environment/connectivity guidance. It must say that `npx skills add` installs only the Skill and that MCP setup is separate.

## Evidence and audit chain

- `capability-draft.json` records inputs, provenance, request chain, and missing evidence. It uses `schemaVersion: v1`, repeats the bundle `recordingId`, and contains exactly one input plus provenance item for every public Tool input. Names are qualified as `tools.<toolName>.input.<inputName>`. A handoff source uses `prior_response:<upstreamTool>:/<slash-separated-output-path>`; other public inputs are `provided` unless runtime authentication proves `context`. A Host-resolved attachment request mapping also records `sourceKind: host-resolved-attachment` and `requirementId: attachment-resolution`. Every HTTP step is named `<toolName>.<stepId>` and repeats the exact method, URL template, authentication, and input bindings. Only `status: ready` with no missing evidence can be approved.
- `validation-receipt.json` binds the draft and bundle hashes.
- `preflight-report.json` binds generated hashes and the commands actually run.
- `approval-audit.json` may approve only a passed preflight.
- `live-verification.json` hashes a real successful input and result. It is not a placeholder.
- `export-manifest.json` covers every candidate file except itself with SHA-256 and `sanitized: true`.
- `source-topology.json` proves which roots were authorized, accessible, and searched. Evidence references use stable `sourceId` values and source-relative locators.
- `canonical-contract.json` records portable business facts, evidence confidence, constraints, the capability graph, and unresolved conflicts.
- `goal-contract.json` records full and partial goals, information requirements, acquisition options, freshness, and completion predicates.
- `consumer-requirements.json` states Host facilities needed by each capability and workflow.
- `host-profile.json` states the actual deployment Host facilities without relying on a brand name.
- `host-compatibility-report.json` deterministically marks each capability `enabled`, `requires-host-integration`, `disabled`, or terminally `blocked`, and reports Canonical readiness separately; `requires-review` remains a verification/contract state and is never translated into a Host integration gap.
- `verification-matrix.json` records evidence and status separately for every capability and hard workflow.

Use `scripts/finalize_export.py`; do not hand-author passed audit files.

Package-level summaries must be computed from the capability/workflow matrix. A successful read-only live call cannot approve an uncalled write Tool. An unverified capability may remain honestly usable only at its proven level; it must not inherit `runtime-verified` or `host-verified` from another capability.

## vNext verification-report and live evidence input

`assets/verification-report.schema.json` is the normative vNext `--verification-report` shape. The report `contractId` matches `canonical-contract.json`, and its arrays cover every Canonical Capability and Workflow exactly once. Capability rows contain `behavior`, `runtime`, and `host`; Workflow rows contain `bypass`, `runtime`, and `host`. An unexecuted phase remains present with `not-run`, `requires-review`, or `blocked` and an empty checks array.

Every passed check records the actual command, non-negative exit code, `passed` status, and SHA-256 `evidenceHash` of captured check evidence. A passed Capability or Workflow runtime check additionally records the Canonical `toolName` and the SHA-256 `inputHash` and `resultHash` of the matching live pair. A passed Workflow bypass check sets `zeroExternalWrites: true` and names the applicable Canonical `verificationChecks` through `checkId`. Generic successful commands that are not bound to a Canonical Tool and live input/result cannot establish `runtime-verified`.

The finalizer augments each Capability with mechanically derived minimum checks and requires every applicable `checkId` in a passed phase; manually declared checks only add to that floor. For a Host-approved attachment, the passed `attachment-resolution-runtime-vector` carries `attachmentProof` for each Canonical target triple (`stepId`, request `location`, `path`) and the required resolver/dispatch/content/size/digest assertions. `traceEvidenceHash` is the canonical JSON SHA-256 of that proof without the hash field, and the enclosing check's `evidenceHash` must equal it. `hostVerified` is true only when the Host phase passed and the Capability compatibility assessment is `enabled`; a Workflow's explicit `capabilityIds` must all be enabled.

Supply `--live-input` and `--live-result` in matching order and repeat the pair as needed. Each vNext entry has `capabilityId` plus `input` or `result`; an input wraps the exact Canonical Tool call, and a result wraps a successful MCP result with contract-valid `structuredContent.data`. A file may contain one entry, an array, or `{ "capabilities": [...] }`. The finalizer hashes the payloads itself and upgrades only the matching Capability. Legacy aggregate reports and one unscoped live pair remain supported only for a single read-only bundle with no Canonical Contract; they cannot approve vNext, multi-Tool, or write packages.

## Constrained write workflow

For vNext, `canonical-contract.json.workflows[]` is the sole hard-workflow authority. Each Workflow declares a non-empty, duplicate-free `capabilityIds` list of known Canonical capabilities and includes its `entryCapabilityId`; Host compatibility and verification use that exact membership rather than guessing from prose or steps. A write maps to an entry only when source evidence proves a non-bypassable identity, confirmation, provenance, transaction, attachment-source, at-most-once, or unknown-outcome constraint. When such an entry exists, the package includes `portable-workflow-guard.mjs` and executable integration, but omits `workflow.json`; maintaining both would create two workflow truths that can drift. A simple write whose ordinary business validation remains authoritative at the target API has no synthetic Workflow, preflight, or validation grant. A legacy bundle-only write continues to use `workflow.json` under its legacy contract.

Each Workflow names the generated executable owner, the exact source-proven bindings, its unknown-outcome policy, and executable zero-dispatch bypass checks. Every binding is structured as an actual source, a protected expected source, a deterministic comparator, and evidence. A runtime-context source declares its semantic claim, generic Host requirement, and exact trusted-context path; known `subject`, `session`, `confirmation`, and `expiry` claims cannot be relabelled or exchanged. Protected operation values are keyed by the exact binding name. Expected values may come only from session-isolated protected runtime state or an immutable constant—not from the same public Tool arguments being checked. Do not add validation grants, upload grants, identity/session fields, expiry, single-use, or a fixed enforcement vocabulary unless evidence for that feature proves those exact mechanics. Conversely, every declared hard binding must appear in executable enforcement and tests rather than only in prose.

The workflow protects only non-bypassable safety, transaction, or consistency edges. Optional lookup, progressive questioning, independent partial goals, and ordinary handoffs stay in the Goal Contract and capability graph rather than becoming a rigid transcript.

Every hard edge requires an executable guard and a zero-external-write bypass test. If the declared enforcement owner is unavailable in `host-profile.json`, the protected capability is disabled or marked `requires-host-integration`; prose is not a fallback enforcement mechanism.

For the supplied Node reference guard, import `PortableWorkflowGuard` and use `dispatchWithPolicy` for a source-specific hard boundary. A session-isolated protected operation stores the Canonical actual-source definitions, expected values, expiry, and operation key. The Function passes the exact public input and trusted runtime context; the Guard performs projection/comparison itself and gives the same deeply frozen input to dispatch. The Guard does not execute an arbitrary verifier callback, so dispatch is the first extensible code path that may produce an external side effect. The additional upload/validation grant helpers are only a complex synthetic example and must not be copied into a feature that does not prove those mechanics. Isolate state at the scope declared by that Workflow, and require atomic consumption only when the source contract actually proves single-use or at-most-once behavior.

## Migration boundary

- Existing Node/stdio execution remains supported as the `node-stdio` Runtime Profile. vNext replaces root `PAGE.md` with `references/feature-context.md`, removes `pageRoute`, and adds `MCP-SETUP.md`; legacy layouts remain readable only through the legacy compatibility path.
- vNext also includes the byte-exact `portable-error-normalizer.mjs`. Every direct MCP callback accepts `(input, runtimeContext)`, runs the dry-run guard first, calls only its matching Function inside a strict try block, projects success unchanged, and invokes `normalizeToolError(error, <literal Canonical operationPolicy>)` with exactly two arguments before returning the Canonical `code/message/details/retryable` shape with `isError: true`. Callback code cannot construct trusted context or execute adapter side effects; only a trusted response/pre-dispatch `outcomeKnown: true` marker preserves a known write rejection, while transport and other unmarked write failures are non-retryable unknown outcomes.
- A package declares vNext by including `canonical-contract.json` with `schemaVersion: vNext`; it must contain the Portable Core, Host compatibility, and per-capability verification files. Legacy packages continue under their original validator contract.
- During migration, `capability-bundle.json` may remain the executable view, but its business content must be derived from or checked against the Canonical Contract.
- A legacy package-level approval may be displayed for compatibility only when computed from all detailed states. It cannot override a weaker capability or workflow state.
- Future Runtime Profiles reuse the same Portable Core and prove behavior equivalence; they do not fork the business model.
