# Strict export artifact contract

Code2Skill defaults to `strict-export-v1`: a self-contained candidate package that another MCP Host, reviewer, or evaluator can inspect and execute without reading the source repository.

```text
generated/code2skill/<feature-id>/
├── export-profile.json
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
├── workflow.json                 # only when a hard write subgraph exists
├── preflight-report.json
├── approval-audit.json
├── live-verification.json
└── export-manifest.json
```

Do not replace this package with links to runtime code elsewhere. Repository-native code may coexist, but the strict export must contain an executable Function core and stdio MCP entry point.

## Generation phases

1. **Draft**: produce `export-profile.json`, `capability-draft.json`, the mirrored capability bundle, Function core, MCP runtime, and three documents.
2. **Pre-finalization validation**: run `validate_artifacts.py --pre-finalize`; build and execute unit/protocol tests.
3. **Live verification**: exercise at least one real `tools/call` in an appropriate environment and retain sanitized input/result JSON outside the candidate directory.
4. **Finalization**: run `finalize_export.py` with the executed-check report and real live evidence. The script writes receipts, hashes, approval, and the manifest.
5. **Final validation**: run `validate_artifacts.py` without `--pre-finalize`.

Never fabricate passed evidence. If live access is unavailable, leave `live-verification.json` absent or failed, do not approve the package, and report the bundle as generated but not runtime-verified.

## Export profile

`export-profile.json` makes target-specific execution policy explicit without baking a particular evaluator into Code2Skill:

```json
{
  "schemaVersion": "v1",
  "profile": "strict-export-v1",
  "protocolVersion": "2025-11-25",
  "transport": "stdio",
  "documentationLanguage": "zh-CN",
  "pageRoute": "/knowledge",
  "allowedRuntimeOrigins": ["https://application.example"],
  "dryRunEnvironmentVariable": "CODE2SKILL_DRY_RUN"
}
```

Resolve the route and runtime origin from the target repository's public startup/configuration contract. When an external harness supplies a different dry-run variable, route, protocol, language, or allowed origin, record those values in this profile and implement exactly those values. The Function request origin and `allowedRuntimeOrigins` must agree; do not substitute a placeholder or guess evaluator-specific constants.

## Capability bundle

`capability-bundle.json` and `function-core/capability-bundle.json` must be equivalent JSON values. Generate the mirror and `capability-draft.json` with `scripts/derive_artifacts.py` after every bundle change instead of maintaining them by hand. Use schema version `v1` and include:

- one server with evidence;
- 1–40 capabilities with unique `capabilityId`, `toolName`, and `functionExport`;
- explicit authentication, semantic inputs, implementation, success rule, side effect, and evidence for every capability;
- explicit handoffs for result fields that feed later Tool inputs.

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

`mcp-tool/index.mjs` is an executable stdio MCP server for protocol `2025-11-25` and exposes exactly the capability bundle's Tool set. In the Node strict profile, use `@modelcontextprotocol/sdk`, `McpServer`, one explicit literal `server.registerTool("tool_name", ...)` call per capability, Zod schemas, and `StdioServerTransport`. Do not register a bundle in a name-driven loop and do not hand-roll the JSON-RPC transport: the literal SDK registration surface is part of static and protocol verification.

The adapter imports `McpServer`, `StdioServerTransport`, and `z` from `./runtime.mjs`. Build `runtime.mjs` from the official SDK/Zod entry template with a bundler, leaving no third-party bare imports. Keep the adapter unbundled so literal registrations, direct input schemas, annotations, callbacks, and named Function imports remain statically inspectable. Verify the copied candidate starts without access to the source repository or its `node_modules`.

Every `tools/list` entry contains:

- stable `name`, Chinese business `title`, and a detailed Chinese `description`;
- closed `inputSchema` and `outputSchema`, with descriptions on every business field and precise `required` arrays;
- `annotations` covering read-only, destructive, idempotent, and open-world hints.

Use a Chinese title shaped as `领域：动作对象`. Its action half must be specific enough for discovery. The description is at least 110 characters and 60 Chinese characters and explicitly covers purpose, calling conditions, inputs or no-input state, output, handoff/stop behavior, HTTP/local execution, and side effects.

Every `tools/call` accepts direct arguments, not an extra `{input: ...}` wrapper. The adapter invokes the matching named Function and exposes its `{status, data}` as both text `content` and matching `structuredContent`; it does not reimplement the business request or add another `data` layer. Unknown Tool names or malformed JSON-RPC are protocol errors. Schema, business, authorization, upstream, and output failures are Tool execution errors with `isError: true`.

Dry-run must use a literal `process.env.<declared-variable> === "1"` guard before the named Function call and before any network, file, process, upload, or other side effect. It returns a structured envelope containing `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary`; the policy and summary are derived from the declared authentication, side effect, retry policy, step count, methods, target origins, and attachment count. It performs zero external requests.

## Chinese documents

- `PAGE.md`: 800–3600 characters and 300–1800 Chinese characters. Frontmatter records name, Chinese title/description, exact route, and `zh-CN`. Explain page purpose, user goals, regions/information, dynamic dependencies and invalidation, every Tool, Agent boundaries, excluded abilities, and recommended starting points. Read-only pages explicitly prohibit writes; write pages give one safety block per write Tool.
- `SKILL.md`: Agent Skills-compatible frontmatter plus at least 4000 characters and 1500 Chinese characters. It is guidance, not a forced transcript. Follow [documentation-contract.md](documentation-contract.md).
- `MCP.zh-CN.md`: at least 8000 characters and 2000 Chinese characters. Document transport/protocol, discovery/call envelopes, schemas, annotations, dry-run, errors, handoffs, and every Tool with a full example.

## Evidence and audit chain

- `capability-draft.json` records inputs, provenance, request chain, and missing evidence. It uses `schemaVersion: v1`, repeats the bundle `recordingId`, and contains exactly one input plus provenance item for every public Tool input. Names are qualified as `tools.<toolName>.input.<inputName>`. A handoff source uses `prior_response:<upstreamTool>:/<slash-separated-output-path>`; other public inputs are `provided` unless runtime authentication proves `context`. Every HTTP step is named `<toolName>.<stepId>` and repeats the exact method, URL template, authentication, and input bindings. Only `status: ready` with no missing evidence can be approved.
- `validation-receipt.json` binds the draft and bundle hashes.
- `preflight-report.json` binds generated hashes and the commands actually run.
- `approval-audit.json` may approve only a passed preflight.
- `live-verification.json` hashes a real successful input and result. It is not a placeholder.
- `export-manifest.json` covers every candidate file except itself with SHA-256 and `sanitized: true`.

Use `scripts/finalize_export.py`; do not hand-author passed audit files.

## Constrained write workflow

When any capability has side effect `create`, `update`, or `delete`, `workflow.json` uses schema version `v1` and kind `constrained-write-subgraph`. It declares a stable `entryCondition`, ordered steps, bindings, enforcement owners, and `unknownOutcomePolicy`.

Each step names exactly one capability or runtime owner, a non-empty list of machine-checkable `requires`, and one of `read_only_bounded`, `not_applicable`, or `never` retry. A `never` step has `maxAttempts: 1`. Bind validation output, request identity, upload grants, and confirmation identity with `equal` or `canonical_equal` constraints.

Enforcement rules use the applicable closed vocabulary: `selection_tokens_same_origin`, `attachment_tokens_from_approved_upload`, `request_equal_to_validated_request`, `confirmation_before_side_effect`, `upload_confirmation_before_transfer`, and `create_at_most_once_no_retry`. Owners are `agent_host`, `mcp_runtime`, `mcp_session_runtime`, `target_api`, or `function:<capability-id>`. Do not invent an alternative prose-only workflow schema.
