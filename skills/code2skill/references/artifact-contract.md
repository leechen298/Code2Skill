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
├── PAGE.md
├── SKILL.md
├── MCP.zh-CN.md
├── function-core/
│   ├── capability-bundle.json
│   ├── index.mjs
│   └── validation-receipt.json
├── mcp-tool/
│   ├── index.mjs
│   └── runtime.mjs                # bundled official SDK and schema runtime
├── portable-workflow-guard.mjs   # vNext writes only
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
3. **Draft**: derive `goal-contract.json`, `consumer-requirements.json`, Host compatibility, the capability bundle/draft, and initial verification matrix; then build or cross-check the Function core, MCP runtime, and three documents.
4. **Pre-finalization validation**: run `validate_artifacts.py --pre-finalize`; build and execute unit/protocol tests.
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
  "pageRoute": "/knowledge",
  "allowedRuntimeOrigins": ["https://application.example"],
  "dryRunEnvironmentVariable": "CODE2SKILL_DRY_RUN"
}
```

Resolve the feature surface and runtime origin from the target repository's public startup/configuration contract. `featureSurface.kind` is `route`, `backend-api`, `rpc`, `message`, `worker`, or `other`; its `identifier` is the source-proven route, operation family, topic/consumer, worker, or equivalent stable feature identity. When no UI route exists, use `/__code2skill__/features/<feature-id>` for `pageRoute` solely because the current Runtime Profile requires a PAGE document key. Repeat that reserved value in PAGE frontmatter, label the real surface separately, and never treat it as a deployed route or Function request URL. When an external harness supplies a different dry-run variable, protocol, language, or allowed origin, record those values and implement exactly them. The Function request origin and `allowedRuntimeOrigins` must agree; do not substitute a placeholder or guess evaluator-specific constants.

## Capability bundle

`capability-bundle.json` and `function-core/capability-bundle.json` must be equivalent JSON values. In vNext, generate both bundles and `capability-draft.json` with `scripts/derive_artifacts.py` after every Canonical Contract change instead of maintaining them by hand. The legacy path remains bundle-first when no Canonical Contract exists. The projected bundle uses schema version `v1` and includes:

- one server with evidence;
- 1–40 capabilities with unique `capabilityId`, `toolName`, and `functionExport`;
- explicit authentication, semantic inputs, implementation, success rule, side effect, and evidence for every capability;
- explicit handoffs for result fields that feed later Tool inputs.

The bundle must agree deterministically with `canonical-contract.json`. Public inputs, requiredness, value domains, handoffs, failures, required outputs, side effects, operation policy, and hard prerequisites cannot diverge. Dynamic values scoped to identity, tenant, session, version, or freshness remain dynamic; one observed response must not become a fixed enum.

Each capability implementation is either:

- `local`: no network access and `successRule.kind: output`; or
- `http`: one or more exact request steps and `successRule.kind: http_status_and_output`.

For HTTP steps preserve method, fixed allowlisted origin, path/query/header/body/multipart bindings, authentication, success statuses, stop-on-failure behavior, and evidence. Keep fixed query values in the exact URL template; target-specific ad-hoc fields and unsupported binding-source kinds invalidate the closed Operation schema. A multipart Tool accepts safe logical values such as filename, media type, and base64 content; never an arbitrary local filesystem path.

Required output paths are contractual. Reject responses that omit them, contain forbidden error keys, or use a status outside the exact declared `successStatusCodes`. Compare `response.status` explicitly; `response.ok` is too broad when the source contract names exact statuses. Do not return a partial success after a failed intermediate step.

Required output paths are deliberately minimal. Select the smallest source-proven fields that establish a usable success result; do not add every response echo merely because it is present. Validate source-proven fixed discriminators and reject null or empty required values; require a non-empty collection only when executable source evidence proves it. Preserve the application's exact business field and failure-key names. Never invent friendlier aliases.

Preserve the source contract's semantic input grouping. A nested filter, request, pagination, or options object remains one object input when the authoritative API and application treat it as one value. Do not flatten its UI fields into unrelated top-level Tool inputs merely because the screen renders separate controls. Conversely, do not wrap independent source parameters in a new object without evidence.

`successRule.requiredOutputPaths` is evaluated inside the Function result's `data` value. Paths therefore describe business output such as `["options"]`, `["result", "id"]`, or a legitimate business field `["status"]`; they never begin with the envelope key `data`. The MCP `{status, data}` envelope is an adapter contract, not part of these business-output paths.

## Function core

`function-core/index.mjs` exports one named async function per capability. Each Function accepts a direct input object plus an optional runtime context. It validates the exact allowed input keys and semantic types even when called without MCP. HTTP Functions use context-provided `fetch` when supplied, validate allowed origins, execute each request at most once, and stop on network/status/output failure. Local Functions must not fetch.

Each Function returns `{status, data}` where `status` is the observed/local status and `data` is the raw contractual business output. It rejects a missing required path in `data`; it does not add a second MCP-shaped envelope or test `requiredOutputPaths` against the whole Function result.

The Function must reproduce the source's observable request and validation contract, including fixed query terms, query flattening of an authoritative object input, root-body bindings, multipart encoding, exact header values, defaults, enum/range/pattern checks, cross-field dependencies, and response invariants. Do not infer these from field names when executable schemas or tests are available.

The Function core is self-contained. It may import Node built-ins with `node:` specifiers, but it must not depend on npm packages, target-repository modules, or undeclared runtime files. Put schema-library and MCP-SDK dependencies in the MCP adapter, not in the Function core.

The Function core is the sole business execution layer for the generated MCP adapter. The adapter imports these named Functions; it does not reimplement request logic.

## MCP runtime

`mcp-tool/index.mjs` is an executable stdio MCP server for protocol `2025-11-25` and exposes exactly the capability bundle's Tool set. In this `node-stdio` profile, use `@modelcontextprotocol/sdk`, `McpServer`, one explicit literal `server.registerTool("tool_name", ...)` call per capability, Zod schemas, and `StdioServerTransport`. Do not register a bundle in a name-driven loop and do not hand-roll the JSON-RPC transport: the literal SDK registration surface is part of static and protocol verification.

The adapter imports `McpServer`, `StdioServerTransport`, and `z` from `./runtime.mjs`. Build `runtime.mjs` from the official SDK/Zod entry template with a bundler, leaving no third-party bare imports. Keep the adapter unbundled so literal registrations, direct input schemas, annotations, callbacks, and named Function imports remain statically inspectable. Verify the copied candidate starts without access to the source repository or its `node_modules`.

Every `tools/list` entry contains:

- stable `name`, Chinese business `title`, and a detailed Chinese `description`;
- closed `inputSchema` and `outputSchema`, with descriptions on every business field and precise `required` arrays;
- `annotations` covering read-only, destructive, idempotent, and open-world hints.

Use a Chinese title shaped as `领域：动作对象`. Its action half must be specific enough for discovery. The description is at least 110 characters and 60 Chinese characters and explicitly covers purpose, calling conditions, inputs or no-input state, output, handoff/stop behavior, HTTP/local execution, and side effects.

Every `tools/call` accepts direct arguments, not an extra `{input: ...}` wrapper. The adapter invokes the matching named Function and exposes its `{status, data}` as both text `content` and matching `structuredContent`; it does not reimplement the business request or add another `data` layer. Unknown Tool names or malformed JSON-RPC are protocol errors. Schema, business, authorization, upstream, and output failures are Tool execution errors with `isError: true`.

Dry-run must use a literal `process.env.<declared-variable> === "1"` guard before the named Function call and before any network, file, process, upload, or other side effect. It returns a structured envelope containing `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary`; the policy and summary are derived from the declared authentication, side effect, retry policy, step count, methods, target origins, and attachment count. It performs zero external requests.

## Chinese documents

- `PAGE.md`: 800–3600 characters and 300–1800 Chinese characters. Frontmatter records name, Chinese title/description, `surface`, `surface-id`, the profile-matching route key, and `zh-CN`. Explain feature purpose, user goals, surface/information, dynamic dependencies and invalidation, every Tool, Agent boundaries, excluded abilities, and recommended starting points. A route-less feature documents its real API/RPC/message/worker surface without inventing UI. Read-only features explicitly prohibit writes; write features give one “副作用与确认” safety line per write Tool, including trusted confirmation, Guard enforcement, no automatic retry, and unknown-outcome reconciliation.
- `SKILL.md`: Agent Skills-compatible frontmatter plus at least 4000 characters and 1500 Chinese characters. It is guidance, not a forced transcript. Follow [documentation-contract.md](documentation-contract.md).
- `MCP.zh-CN.md`: at least 8000 characters and 2000 Chinese characters. Document transport/protocol, discovery/call envelopes, schemas, annotations, dry-run, errors, handoffs, and every Tool with a full example.

## Evidence and audit chain

- `capability-draft.json` records inputs, provenance, request chain, and missing evidence. It uses `schemaVersion: v1`, repeats the bundle `recordingId`, and contains exactly one input plus provenance item for every public Tool input. Names are qualified as `tools.<toolName>.input.<inputName>`. A handoff source uses `prior_response:<upstreamTool>:/<slash-separated-output-path>`; other public inputs are `provided` unless runtime authentication proves `context`. Every HTTP step is named `<toolName>.<stepId>` and repeats the exact method, URL template, authentication, and input bindings. Only `status: ready` with no missing evidence can be approved.
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
- `host-compatibility-report.json` deterministically marks each capability `enabled`, `requires-host-integration`, `disabled`, or `blocked`.
- `verification-matrix.json` records evidence and status separately for every capability and hard workflow.

Use `scripts/finalize_export.py`; do not hand-author passed audit files.

Package-level summaries must be computed from the capability/workflow matrix. A successful read-only live call cannot approve an uncalled write Tool. An unverified capability may remain honestly usable only at its proven level; it must not inherit `runtime-verified` or `host-verified` from another capability.

## vNext verification-report and live evidence input

`assets/verification-report.schema.json` is the normative vNext `--verification-report` shape. The report `contractId` matches `canonical-contract.json`, and its arrays cover every Canonical Capability and Workflow exactly once. Capability rows contain `behavior`, `runtime`, and `host`; Workflow rows contain `bypass`, `runtime`, and `host`. An unexecuted phase remains present with `not-run`, `requires-review`, or `blocked` and an empty checks array.

Every passed check records the actual command, non-negative exit code, `passed` status, and SHA-256 `evidenceHash` of captured check evidence. A passed Capability or Workflow runtime check additionally records the Canonical `toolName` and the SHA-256 `inputHash` and `resultHash` of the matching live pair. A passed Workflow bypass check sets `zeroExternalWrites: true` and names the applicable Canonical `verificationChecks` through `checkId`. Generic successful commands that are not bound to a Canonical Tool and live input/result cannot establish `runtime-verified`.

Supply `--live-input` and `--live-result` in matching order and repeat the pair as needed. Each vNext entry has `capabilityId` plus `input` or `result`; an input wraps the exact Canonical Tool call, and a result wraps a successful MCP result with contract-valid `structuredContent.data`. A file may contain one entry, an array, or `{ "capabilities": [...] }`. The finalizer hashes the payloads itself and upgrades only the matching Capability. Legacy aggregate reports and one unscoped live pair remain supported only for a single read-only bundle with no Canonical Contract; they cannot approve vNext, multi-Tool, or write packages.

## Constrained write workflow

For vNext, `canonical-contract.json.workflows[]` is the sole hard-workflow authority and every write maps to exactly one entry. The package includes `portable-workflow-guard.mjs` and executable integration, but omits `workflow.json`; maintaining both would create two workflow truths that can drift. A legacy bundle-only write continues to use `workflow.json` schema version `v1` and kind `constrained-write-subgraph` with its stable `entryCondition`, ordered steps, bindings, enforcement owners, and `unknownOutcomePolicy`.

Each step names exactly one capability or runtime owner, a non-empty list of machine-checkable `requires`, and one of `read_only_bounded`, `not_applicable`, or `never` retry. A `never` step has `maxAttempts: 1`. Bind validation output, request identity, upload grants, and confirmation identity with `equal` or `canonical_equal` constraints.

Enforcement rules use the applicable closed vocabulary: `selection_tokens_same_origin`, `attachment_tokens_from_approved_upload`, `request_equal_to_validated_request`, `confirmation_before_side_effect`, `upload_confirmation_before_transfer`, and `create_at_most_once_no_retry`. Owners are `agent_host`, `mcp_runtime`, `mcp_session_runtime`, `target_api`, or `function:<capability-id>`. Do not invent an alternative prose-only workflow schema.

The workflow protects only non-bypassable safety, transaction, or consistency edges. Optional lookup, progressive questioning, independent partial goals, and ordinary handoffs stay in the Goal Contract and capability graph rather than becoming a rigid transcript.

Every hard edge requires an executable guard and a zero-external-write bypass test. If the declared enforcement owner is unavailable in `host-profile.json`, the protected capability is disabled or marked `requires-host-integration`; prose is not a fallback enforcement mechanism.

For the supplied Node reference guard, import `PortableWorkflowGuard`, create an isolated instance at the deployment's protected session/tenant boundary, and invoke the instance methods `dispatchUploadOnce` or `dispatchOnce`. Do not invent named global dispatch wrappers or share one in-memory grant store across unrelated subjects, sessions, or tenants. A durable/signed replacement may be used only when it preserves the same bindings, atomic single-use consumption, pre-dispatch rejection, and unknown-outcome behavior.

## Migration boundary

- Existing `strict-export-v1` layout and Node/stdio execution remain supported as the `node-stdio` Runtime Profile.
- A package declares vNext by including `canonical-contract.json` with `schemaVersion: vNext`; it must contain the Portable Core, Host compatibility, and per-capability verification files. Legacy packages continue under their original validator contract.
- During migration, `capability-bundle.json` may remain the executable view, but its business content must be derived from or checked against the Canonical Contract.
- A legacy package-level approval may be displayed for compatibility only when computed from all detailed states. It cannot override a weaker capability or workflow state.
- Future Runtime Profiles reuse the same Portable Core and prove behavior equivalence; they do not fork the business model.
