---
name: code2skill
description: Convert an existing frontend, backend, or full-stack application feature into evidence-backed Feature Context, composable MCP Tools, and an observed Agent Skill. Use when extracting agent capabilities from routes, pages, components, API clients, controllers, services, schemas, tests, or existing workflows; when replacing a page-level mega-tool with reusable business capabilities; or when auditing and regenerating code-derived MCP and Skill artifacts.
---

# Code2Skill

Turn capabilities trapped in application code into reusable Agent capabilities. Use the coding Agent as the Producer that searches authorized source roots and implements the export; do not build a parallel scanner or autonomous Agent unless repeated evidence shows one is needed. Treat the Agent Host that later consumes the generated Skill and Tools as a separate system with separately declared capabilities.

## Core contract

Model four connected delivery surfaces and compile them into a complete strict export:

1. **Feature Context** explains the business purpose, concepts, field semantics, states, permissions, rules, failures, and original client behavior.
2. **Function Core** implements one self-contained named business function per public capability.
3. **MCP Tools** expose those independently valuable, composable execution capabilities with stable protocol contracts.
4. **Observed Skill** captures the existing product's usage knowledge, conditional composition paths, and recovery guidance without forcing irrelevant calls.

The portable business contract is independent from its execution adapter. The current default delivery profile, `strict-export-v1`, is the `node-stdio` Runtime Profile: a self-contained capability bundle, named Node Function core, stdio MCP Server, Chinese Feature Context/MCP/Skill documentation, MCP setup guidance, evidence draft, deterministic verification, live receipt, approval audit, and integrity manifest. It remains fully supported, but it is not the only possible implementation of the Portable Core. A documentation-only design note is not a completed Code2Skill output.

Apply this invariant:

> MCP Tools provide composable execution capabilities. Skills provide domain knowledge, selection strategy, and default flows. The Agent chooses the composition for the user's goal. Schemas, handlers, servers, or deterministic workflows enforce constraints that must never be skipped.

Read [vnext-architecture.md](references/vnext-architecture.md) first for Producer/Consumer boundaries, Portable Core, progressive goal completion, portability, and the migration contract. Then read [capability-model.md](references/capability-model.md) before deciding capability boundaries. Read every other reference named by the relevant workflow step; do not ask another agent to interpret these instructions.

## Workflow

### 1. Establish scope and repository rules

- Read repository instructions and inspect the worktree before editing.
- Confirm the requested feature through the user's goal, route, screen, API, symbol, or test. If the target is discoverable from the repository, proceed without asking.
- Define every user-authorized source root and the output directory. Default the self-contained candidate to `generated/code2skill/<feature-id>/`. Search only those roots; do not scan the user's machine to guess where a backend might exist.
- Create `source-topology.json` with a stable `sourceId`, evidence role, accessibility, and search summary for each frontend, backend, contract, test, or other authorized root. These roles describe evidence, not required directory or architecture names. Record unavailable roots and missing semantic roles explicitly.
- Read any evaluator or delivery contract supplied by the target repository. Put the source-proven feature surface, route or stable surface identifier, origin allowlist, dry-run environment variable, protocol, transport, and language in `export-profile.json`; never guess or hard-code another project's constants into this Skill. vNext records the real surface in `featureSurface` and does not use `pageRoute`. A legacy package may still contain `PAGE.md/pageRoute`, but never introduce them as vNext authoring inputs or primary artifacts.
- Preserve unrelated changes. Repository-native MCP code may coexist, but the strict export still needs its own executable Function core and MCP entry point.

### 2. Trace the feature end to end

Read [evidence-and-discovery.md](references/evidence-and-discovery.md).

- Trace client entry points, routes or other feature surfaces, components, state, validation, visibility conditions, requests, result rendering, and error handling.
- For a client feature, establish the candidate Function/MCP surface from the backend APIs the client actually invokes. One client API does not mechanically equal one Tool, but a backend-only internal method is not a candidate merely because it is discoverable. Include a backend capability outside that client-observed API surface only when the user explicitly expands the feature scope or another authorized entry surface proves it belongs.
- When available, continue through transfer contracts, authorization, application orchestration, business rules, external calls, persistence, and tests. Use that evidence to confirm or qualify the client-observed request/response contract, dynamic values, conditional fields, permissions, side effects, idempotency, and failures. Discover semantic roles from call paths, registrations, validation, serialization, field use, protocols, and assertions. Names such as DTO, Controller, Service, Request, Schema, or Model are optional clues, never required architecture.
- Build `canonical-contract.json` before authoring executable artifacts. It is the language- and Host-independent source of truth for every capability: exact public input shape, nested-object boundary, defaults, output provenance (`static`, `dynamic`, or `unconstrained`), unconditional/conditional/forbidden inputs, cross-field predicates, provenance and freshness, request boundary, accepted statuses, response names, business failures, minimum usable result, side effects, confirmation, retry, and evidence confidence. Every top-level output declares a value domain; a nested output may inherit one from a declared parent. Static domains contain exactly source-proven values and evidence, dynamic domains explicitly declare identity/tenant/session booleans plus freshness, and unconstrained domains contain only their kind. Resolve material rows from executable code, protocols, validation, or tests; do not replace source names with clearer synonyms.
- Preserve contradictions between sources and select an authority only when evidence supports it. The target API is authoritative for ordinary business acceptance and may reject a structurally valid request with a recoverable business error. Do not duplicate every server rule as Function validation or a hard Workflow. Missing proof about authorization, material side effects, idempotency, confirmation, or unknown-outcome handling keeps the affected write capability out of `ready`; missing proof of an ordinary business rule remains an explicit unknown and is handled through the API's structured error path.
- Run the target repository's relevant tests and inspect their assertions. A TypeScript type or UI control alone does not prove runtime serialization, response validation, or cross-field rules.
- Resolve the public runtime origin from the target repository's actual startup contract, environment configuration, or executable test setup. The origin used by generated Functions must match `allowedRuntimeOrigins`; never replace a proven target origin with a convenient placeholder.
- Record each material conclusion in `canonical-contract.json.evidenceCatalog` with `evidenceId`, `sourceId`, portable `locator`, `semanticRole`, and `assertionLevel` (`fact`, `inference`, or `unknown`). Reuse those `evidenceId` values in Feature Context and contract facts instead of inventing a parallel path-only evidence format.
- Bind fact evidence to the exact operation and contract field it proves. The declared side effect, each HTTP step/request binding, every output and success rule, every conditional rule, and every dynamic scope/freshness or reuse policy must cite fact-level evidence with the matching semantic role. A generic entry/API-existence fact, a label, an inference, or evidence borrowed from another operation cannot prove executable request, response, condition, or side-effect semantics. For writes, `evidenceCoverage` is the closed set `sideEffect/backendContract/authorization/validation/idempotency/unknownOutcome`; reads carry only `sideEffect` coverage.
- Treat the client feature as an evidence boundary, not automatically as one capability or one Tool.

### 3. Model context and capabilities before coding

- Write a short Feature Context using [feature-context.md](assets/feature-context.md) as a starting point.
- Model goals inside `canonical-contract.json` around user outcomes rather than the original screen transcript. Classify information as always required, conditionally required, optional, derived, or dynamic; declare where it can come from, when it expires, when it must be refreshed, and the completion predicate for each goal. `derived` and `dynamic` Goal information must come from an exact Capability output or a declared trusted Host requirement, never from user self-report or an unimplemented local derivation. The derivation step projects this into `goal-contract.json`.
- Give every Goal information need a portable type and a complete closed Schema for object/array values. Map it through `supplies[]` to exact `{capabilityId, inputName, mappingKind}` targets; each target input has exactly one mapping across the Goal. Schema/cardinality, acquisition source, mapping kind, and the target input's source strategy must agree. One need that supplies several inputs needs at least one acquisition source compatible with all of them; trusted Host requirement IDs match exactly, and an upstream-only opaque value cannot be replaced by user input. Optional information cannot supply an unconditionally required Capability input. Every required or conditionally required input of a Capability participating in the Goal must be covered.
- Make `requiredWhen` activation executable: every path resolves against the declared information Schema, cannot depend on optional information or itself, and its condition must exactly match the supplied Capability input's `requiredWhen`. The complete acquisition-provider, supplies, and activation graph must be acyclic. Object-form conditional Capability declarations reuse the same condition as their linked need, and an explicit `conditionalNeedsOnlyWhenActive` value is always `true`. An unresolved activation keeps the Goal pending. `reuseWhile` uses only evidenced true-valued claims; generated Goal-state tests mark current acquisition with `{__goalState: true, value, acquiredNow: true}` and cached values with claim-complete `reuseProof`. Do not accept `fresh: true` as a shortcut, and reject values that fail the need Schema.
- Draft candidate capabilities around independent user or Agent goals.
- Merge or split candidates by business meaning, independent value, contract stability, reuse, side effects, and enforceable preconditions.
- Do not derive Tool count from page count, request count, endpoint count, or function count.
- Decide whether lookup data belongs in an input enum, Skill reference, MCP Resource, or MCP Tool. Do not mechanically turn every option list into a Tool.
- Treat client-visible local options or structured field metadata as independent capabilities when a user can ask for them directly, when several downstream calls need them, or when their labels/semantics matter beyond validation. In those cases, prefer a Tool (or a Resource when execution is unnecessary) even if the current implementation is a constant.
- Apply that test to each catalog independently. Do not merge unrelated local catalogs into a generic page-options Tool merely because they share one configuration file, render on one page, or both execute without HTTP. If each catalog can satisfy a different partial user goal or feeds a different downstream input chain, each is a separate capability.
- Stop and report a boundary if only client code exists and a write operation's authorization, financial effect, idempotency, or compensation behavior cannot be proven.
- Put a `capabilityGraph` in the Canonical Contract. It declares independent stopping points, typed handoffs, optional dependencies, and hard prerequisites; it is not a fixed linear flow. Mark source-observed combinations as `observed` and contract-compatible new combinations as `derived composition`.
- Ensure the goal model supports information arriving in different orders. Reuse still-valid values, skip unnecessary lookup calls, ask only for currently missing information, recompute requirements when conditions change, and stop as soon as the requested partial or full goal is complete.

### 4. Design and implement MCP capabilities

Read [mcp-tool-design.md](references/mcp-tool-design.md).

- Give every public Tool a distinct business name, description, input schema, and output contract.
- Give every Tool a user-facing top-level `title`; add business descriptions to schema properties instead of placing the title only in annotations or exposing bare types.
- Implement one explicit handler or entry function per public Tool. Internal helpers may be shared.
- Preserve application authentication, authorization, tenancy, validation, idempotency, and audit behavior.
- Identify the authoritative execution boundary before choosing an adapter. When MCP runs separately from the application, prefer the application's supported API or an explicitly shared, persistent domain service. Do not bypass middleware or instantiate a second in-memory state machine that can disagree with Web/API behavior.
- Put only proven non-bypassable identity, confirmation, provenance, ordering, transaction, at-most-once, and safety rules in schemas, handlers, server state, or deterministic workflows—not only in prose. Leave ordinary eligibility, availability, and field-level business acceptance authoritative to the target API unless source evidence proves the client must enforce a harder safety boundary.
- Do not create a validation or preflight Tool merely to mirror every backend rule. Generate it when the client actually calls that API and it has independent value, produces a required server-issued handoff, or participates in a proven non-bypassable write constraint.
- Never generate generic escape hatches such as `call_api`, `execute_sql`, `run_service_method`, or one operation switch that dispatches all business actions.
- Mark side effects and require preview/confirmation or dry-run paths for destructive, financial, publishing, or external actions where supported.
- Never accept `confirmed: true`, `userConfirmed: true`, or a similar Tool argument as proof of user consent. Confirmation belongs to the Agent Host or a trusted runtime and must bind the target, payload digest, transient validation token, and side-effect summary. If that integration does not exist, mark the capability as requiring Host integration rather than claiming it is safe.
- Use the Canonical vocabulary for every Tool: `sideEffect` and `operationPolicy.sideEffect` are `read`, `create`, `update`, or `delete`; `operationPolicy.confirmation` is `not-required`, `trusted-confirmation-required`, or `upload-confirmation-required`. Also declare idempotency, automatic retry, and unknown-outcome handling. Express the actual enforcement owner through Consumer requirements and `workflows[].enforcement.owner`, not a second `confirmationOwner` field.
- Classify every write in `runtimeProtection`: use `backend-authoritative` when the target API owns ordinary validation and no extra local ordering is proven; use `deterministic-workflow` only for proven non-bypassable edges; use `unresolved` when frontend evidence proves the API call but backend protection evidence is missing. An unresolved write must remain `requires-review` or `blocked` and must not guess an owner or Workflow.
- For a non-idempotent multi-Tool write chain with proven non-bypassable edges, generate a deterministic workflow/Host integration contract that binds the relevant server-issued values, confirmation, and dispatch. A simple write whose ordinary business validation belongs to the target API does not require a synthetic preflight or universal grant. If the necessary hard boundary cannot be implemented and tested, leave that protected path in `requires-review`.
- Give every hard Workflow an explicit, non-empty `capabilityIds` membership list containing its `entryCapabilityId`; all IDs must be unique known Canonical capabilities. Model every binding as a structured actual source, protected expected source, comparator, and evidence reference. Runtime-context sources name their semantic claim, generic Host requirement, and exact trusted path; protected values are keyed by the exact binding name. Expected values may come only from session-isolated protected runtime state or an immutable constant, never from the same public Tool arguments being checked. Use `dispatchWithPolicy`; the protected Guard stores both the Canonical projection rules and expected values, projects from the exact Function input and trusted runtime context itself, then dispatches that same frozen input. Do not let Function code pass a caller-projected binding object or run an arbitrary verifier callback. Zero-dispatch tests must cover mismatch, expiry, replay, and missing protected state.
- For vNext, complete `canonical-contract.json` before runtime code, then run `scripts/derive_artifacts.py <candidate>` to mechanically create both capability-bundle copies, `capability-draft.json`, Goal/Consumer views, Host compatibility, the initial verification matrix, both Function/MCP Schema projections, and `references/capability-contracts.json`. Do not hand-author derived files. A legacy package without a Canonical Contract retains the older bundle-first derivation path. Give every Tool exactly one distinct named async Function export.
- Preserve authoritative input grouping. Keep source-level filter, request, pagination, and option objects intact instead of flattening them from UI controls or inventing new wrappers.
- Preserve exact HTTP method, allowlisted origin, path/query/header/body/multipart binding, authentication, success status, required output paths, and stop-on-failure semantics. Preserve fixed query parameters inside the exact URL template; do not invent non-schema extension fields or unsupported binding-source kinds. Preserve root-body bindings, multipart field names, defaults, enum membership, cross-field provenance rules, and exact response field names. Execute a request step at most once; never automatically retry a network-ambiguous write.
- Derive `allowedRuntimeOrigins` from actual HTTP implementation steps. Require the exact non-empty allowlist when any HTTP step exists; require an empty list for an all-local package instead of inventing a placeholder origin.
- Resolve every cross-capability `outputPath` against an exactly declared output and validate its nested Schema and cardinality. Keep upstream source strategies, dynamic domains, Goal acquisition, typed handoffs, observed graph edges, attachment consumer bindings, and implementation request bindings mechanically aligned; a prose handoff or consumer input alone is not a usable chain.
- Compare the observed `response.status` with the exact declared `successStatusCodes`. Do not use `response.ok` or another broad 2xx shortcut when the source contract names specific accepted statuses.
- Use the source's externally observable names verbatim. Do not rename `status` to a more descriptive alias, turn a root request body into `{request: ...}`, omit a fixed query parameter, or model multipart data as ordinary JSON.
- Define `successRule.requiredOutputPaths` relative to the Function result's raw `data`; never prefix those paths with the MCP envelope key `data`. A business output field actually named `status` remains valid.
- Keep `requiredOutputPaths` minimal and contractual: include the smallest fields that prove the result is usable, not every echoed or incidental response field. Copy the source's actual failure keys into `forbiddenOutputKeys`; do not substitute a conventional list.
- Enforce proven response invariants as well as field presence: reject null or empty required values, validate fixed discriminator values, and require non-empty collections only when executable source evidence establishes that invariant.
- Use only the standard JSON Schema `format: "uri"` for source-defined URL strings. Reject `format: "url"`; keep opaque tokens, file IDs, and object keys as non-URI strings.
- Keep `function-core/index.mjs` self-contained apart from statically imported, non-effectful `node:` built-ins accepted by the validator and the exact generated `../portable-workflow-guard.mjs` import required by a proven deterministic Workflow. Do not import filesystem, process-spawning, socket/HTTP, dynamic-module, VM, worker, or equivalent effectful Node modules; business I/O goes through the reviewed Canonical dispatch boundary. Every named Function validates exact direct inputs and returns one `{status, data}` result; npm dependencies and protocol schemas belong to the MCP adapter.
- When source evidence proves an attachment-dependent client path, generate the business upload Function and MCP Tool, returned token/URL handoff, downstream binding guidance, and tests. Accept Host-approved attachment references or sanitized bounded content such as filename, media type, size, digest, and base64 content; never accept an arbitrary local file path. An opaque Host grant is metadata, not upload bytes: represent a generic `attachment-resolution` implementation binding before the business upload, never send the grant object itself as file content, and make `attachments.contentBindings` uniquely and exactly cover every input, resolver requirement, final output step, request location, and body/multipart field that receives resolved content. Each exact upload field must cite fact-level request-construction, serialization, or transport-contract evidence shared with the matching implementation binding; a user-entry, generic API-call, or side-effect fact alone cannot prove a multipart/body path.
- Treat attachment receipt as a Consumer Host responsibility. Code2Skill does not implement chat ingress, file receipt/download, or brand-specific adapters. If the Consumer cannot provide or resolve an approved attachment, disable the affected path or mark it `requires-host-integration`; never replace the missing chain with an arbitrary path or unproven URL.
- Preserve failures as structured Tool errors. Distinguish at least input/schema, business, authorization, upstream/network, malformed-output, and unknown-write-outcome classes when evidence permits; retain source error codes, messages, field details, retryability, and outcome certainty instead of collapsing them into an opaque exception string.
- Import the byte-exact normalizer and call `normalizeToolError(error, <literal Canonical operationPolicy>)` with exactly two arguments in every Tool catch. A write Function may set `outcomeKnown: true` only after a response-proven backend rejection or a deterministic pre-dispatch Guard failure; preserve its structured business code but keep `retryable: false` because a corrected request is a new attempt, not automatic replay. Transport errors, timeouts, disconnects, and write errors without that trusted marker normalize to `UNKNOWN_DISPATCH_OUTCOME` with `retryable: false`, regardless of their code or retry hint.
- Implement direct MCP arguments, closed schemas, Chinese Tool titles/descriptions, complete annotations, `content` plus matching `structuredContent`, and `isError: true` Tool errors. Implement a literal `process.env.<declared-variable> === "1"` dry-run guard before every external action and named Function call. Build one local `dryRunResult` containing exactly `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary`, then return it as `structuredContent` plus a JSON text `content` projection; derive policy and request-summary fields from the capability contract rather than executing or guessing them.
- Register every Tool with its literal name in a distinct `server.registerTool("tool_name", ...)` call. Do not generate a loop that dynamically registers bundle entries and do not hand-roll JSON-RPC.
- Each literal Tool callback must invoke exactly its matching Canonical named Function export. Swapped callbacks, duplicated business execution in the adapter, or a registration that never calls its Function are invalid.
- Make the strict export executable after it is copied away from the source repository. Keep the readable adapter in `mcp-tool/index.mjs`, import `McpServer`, `StdioServerTransport`, and `z` from `./runtime.mjs`, and build `runtime.mjs` by bundling the official MCP SDK and Zod from [mcp-runtime-entry.mjs](assets/mcp-runtime-entry.mjs). The vNext runtime is one self-contained file: no relative or dynamic imports and no client-network or process-control primitives. Minify it so dependency examples in third-party comments cannot be mistaken for unresolved imports. Do not bundle the adapter itself: its literal registrations, direct Zod schemas, and named `../function-core/index.mjs` imports must remain inspectable.
- Keep module import/initialization free of network, file, process, upload, and business-dispatch effects. Function helpers only declare behavior; MCP module setup contains literal registrations and the one reviewed stdio `server.connect(new StdioServerTransport())` startup, while every business effect remains behind a Tool callback, dry-run boundary, and matching named Function.
- Use only direct top-level Zod input types (`string`, `number`, `boolean`, `object`, or `array`) plus refinements. Avoid top-level unions or transformed wrappers that obscure the capability bundle's declared input type.
- Give every Tool a discoverable Chinese `领域：动作对象` title and a substantive description of at least 110 characters and 60 Chinese characters. The description must cover purpose, calling condition, inputs or no-input state, output, downstream handoff or independent stop, HTTP/local behavior, and read/write side effects.

### 5. Generate the knowledge documents

Read [observed-skill-design.md](references/observed-skill-design.md) and [documentation-contract.md](references/documentation-contract.md).

- Create an Agent Skills-compatible folder with a concise `SKILL.md` and on-demand references.
- Identify the Skill as `observed`: it is reconstructed from an existing product flow and supported by code evidence.
- Explain when each Tool is useful, what inputs must be collected, what calls may be skipped, what dependencies cannot be skipped, common compositions, failure recovery, and result interpretation.
- Guide progressive completion: begin with the user's stated goal and known information, then obtain only the currently missing values from trusted context, read-only Tools, or concise questions. Do not demand every field up front, repeat still-valid questions, or call a lookup Tool when the required value is already proven and fresh.
- Permit partial goals. A user asking for one option list, one detail, or one page of results should not be forced through the full original screen flow.
- Permit temporary composition with other contract-compatible Tools and Skills. Clearly label combinations not observed in the source as `derived composition`; allow flexible read-only composition while keeping all write guards unchanged.
- Reference `references/feature-context.md` rather than duplicating business background throughout the Skill. `SKILL.md`, `MCP.zh-CN.md`, and Feature Context must name `references/capability-contracts.json` as authoritative and carry its current SHA-256 marker. Narrative text explains goals and recovery but must not invert its requiredness, types, domains, sources, freshness, side effects, error paths, attachment bindings, or operation policy.
- Generate `references/feature-context.md` as the source-derived business understanding visible to the Agent, `SKILL.md` as conditional usage knowledge, `MCP.zh-CN.md` as the exact executable Tool contract, and `MCP-SETUP.md` as platform-neutral startup/registration/authentication guidance. vNext does not generate `PAGE.md` and does not assume a page or route exists. Legacy `PAGE.md` may be read for migration, but it is not a vNext output.
- Include the generic Skill installation form `npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y`. State that it installs only the Skill; MCP startup, Host registration, authentication injection, and environment configuration are separate steps documented in `MCP-SETUP.md`.
- Meet the structural, Chinese-language, per-Tool, handoff, example, output, failure, dry-run, and side-effect requirements in the documentation contract. Do not use filler to reach the length threshold.

### 6. Build the strict export

Read [artifact-contract.md](references/artifact-contract.md).

- Start vNext from `assets/source-topology.json`, `assets/canonical-contract.json`, `assets/host-profile.json`, `assets/export-profile.json`, `assets/feature-context.md`, `assets/MCP-SETUP.md`, and the byte-exact `assets/portable-error-normalizer.mjs`; replace every synthetic example and placeholder and copy the normalizer to the candidate root. Copy Feature Context to `references/feature-context.md`, not the package root. Use `assets/verification-report.schema.json` as the finalizer input contract, never `assets/verification-report.md`, which is retained only as a legacy human summary. Goal, Consumer, compatibility, bundle, draft, and verification-matrix files are generated views and intentionally have no hand-authored vNext templates. Legacy exports may still use the documented bundle/draft and `PAGE.md` compatibility path.
- Author the vNext inputs `source-topology.json`, `canonical-contract.json`, and the deployment-supplied `host-profile.json`. Derive `goal-contract.json`, `consumer-requirements.json`, `host-compatibility-report.json`, and `verification-matrix.json`. The capability graph and Consumer requirement definitions live inside the Canonical Contract; do not maintain duplicate authoring sources.
- Treat `host-profile.json` as deployment evidence, not a Producer or brand assumption. Compare it deterministically with `consumer-requirements.json`. Enable, disable, block, or mark `requires-host-integration` per capability when trusted confirmation, session state, approved attachment resolution, authentication injection, transport, or unknown-outcome reconciliation is unavailable. Keep this Host status separate from Canonical `readiness`: source/contract uncertainty remains `requires-review` in the verification state and must never be mislabeled as a missing Host integration. The Host supplies an approved reference or bounded content; the generated business Tool owns the source-proven upload request.
- Run `scripts/derive_artifacts.py <candidate>` after every Canonical Contract change. For vNext it projects `capability-bundle.json`, its Function mirror, `capability-draft.json`, Goal/Consumer views, Host compatibility, and the verification matrix from the completed contract. The draft keeps one qualified `tools.<tool>.input.<name>` input and provenance record per public input plus one qualified `<tool>.<step>` request-chain record per HTTP step. Do not edit those projections or maintain an unrelated page-global input list.
- Generate the complete strict export tree. In vNext, hard workflows live only in `canonical-contract.json`; include `portable-workflow-guard.mjs` and runtime integration only when at least one proven non-bypassable workflow exists. Do not impose a universal Workflow or preflight grant on ordinary writes. `workflow.json` is omitted to avoid a second source of truth. Legacy bundle-only exports keep their existing constrained `workflow.json` contract.
- Keep the capability set identical across both bundle copies, named Function exports, MCP `tools/list`, Tool call dispatch, Skill, MCP documentation, and Feature Context capability references.
- Derive or deterministically cross-check Function validation, MCP schemas and registrations, Skill claims, workflow guards, and test vectors against the Canonical Contract. Runtime Profile details may add transport and packaging behavior but must not change business names, requiredness, value domains, failures, or safety policy.
- Keep all evidence references source-derived. `capability-draft.json` may be `ready` only when material evidence is complete; otherwise stop before approval.

### 7. Verify behavior, not just structure

Read [verification.md](references/verification.md).

- Run the repository's relevant static checks, build, unit tests, and MCP protocol tests.
- Test every Tool independently with valid and invalid inputs.
- Use the Canonical-derived minimum verification checks rather than a hand-picked smoke list. Derivation always requires valid input/output, invalid-input rejection, and structured error recovery, then adds checks for HTTP bindings/status, dynamic values, conditional branches, attachments, writes, backend-authoritative rejection, Goal information ordering/minimal questioning, and derived composition as applicable. Declared custom checks may only add to this set; a passed phase missing any required `checkId` must fail finalization.
- For every write, test both sides of outcome certainty: a response-proven backend rejection marked `outcomeKnown: true` preserves its actionable code with no automatic retry, while a timeout/connection error or any unmarked write failure becomes non-retryable `UNKNOWN_DISPATCH_OUTCOME` and requires reconciliation.
- Test representative partial and multi-Tool compositions.
- Test progressive collection with information supplied in different orders and with all information supplied up front. Prove that the Skill neither repeats questions nor calls irrelevant Tools.
- Test representative `derived composition` paths separately from observed paths.
- Test runtime rejection of fabricated IDs, invalid source tokens, unauthorized access, unsafe parameters, and skipped hard preconditions.
- Validate the generated artifact bundle:

```bash
python3 <skill-root>/scripts/validate_artifacts.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --pre-finalize
```

- Repeat `--source-map sourceId=/absolute/authorized/root` for every available root declared by `source-topology.json`. Use the legacy `--source-root` base only when every portable root is intentionally relative to one already authorized workspace. Never widen that base merely to reach unrelated repositories.

- Run Function unit vectors for every capability, including input/conditional/request-binding/status/network/output failures. The deterministic derivation writes identical `function-core/schema-contract.json` and `mcp-tool/schema-contract.json`; generated implementations and tests must consume or verify those projections rather than retyping a second contract. Use the bundled detached MCP probe for initialize, `tools/list`, unknown-Tool protocol errors, one successful call per Tool, every required-argument failure, and one dry-run call per write Tool with zero external effects:

```bash
python3 <skill-root>/scripts/probe_mcp.py <candidate> \
  --call /path/to/valid-tool-call.json \
  --error-call /path/to/execution-error-tool-call.json \
  --dry-run-call /path/to/dry-run-tool-call.json
```

- The detached probe compares the complete runtime `inputSchema`, `outputSchema`, and all four Tool annotations exactly with the Canonical projection; validates each successful result against its output Schema; checks an invalid argument case for every Tool (missing required input or an extra field for zero-input/optional-only Tools); and requires one handler-level structured `isError: true` execution-error case per Tool. Test every capability-specific invalid enum, range, conditional rule, provenance, business, authorization, request binding, and output case separately. The probe validates the dry-run envelope, while a Function/Guard test with an observed dispatcher proves zero external actions.
- Function vectors must assert the exact URL, query serialization, lower-cased header contract, root or nested body shape, multipart field metadata, accepted status, returned field names, defaults, invalid extra keys, invalid enums/ranges/patterns, cross-field dependencies, response failure keys, and required-output rejection. A test that only proves “a request happened” is insufficient.
- `probe_mcp.py` copies the candidate to a detached temporary directory before starting it, so no source-repository `node_modules` exists on its ancestor path. This proves `mcp-tool/runtime.mjs` is actually self-contained.
- Execute a real MCP call for every capability claimed as `runtime-verified`; at minimum exercise one appropriate capability to establish package-level runtime reachability. Save sanitized inputs and results outside the candidate directory. Do not fabricate a successful live receipt or apply one Tool's receipt to another.
- Record verification per capability and per declared hard workflow in `verification-matrix.json`. Distinguish `generated`, `behavior-verified`, `runtime-verified`, `host-verified`, `requires-review`, and `blocked`; one successful Tool call never approves another Tool or workflow.
- Write a vNext JSON verification report conforming to `assets/verification-report.schema.json`. It must match the Canonical `contractId`, cover every Capability and every declared hard Workflow exactly once, record Capability `behavior/runtime/host` phases and Workflow `bypass/runtime/host` phases, and include only commands actually executed. A package with no hard Workflow has no synthetic Workflow rows. Every passed check records its exit code and evidence SHA-256. Every passed runtime check also binds the Canonical `toolName` and matching live `inputHash/resultHash`; every passed bypass check sets `zeroExternalWrites: true` and covers the Canonical workflow check IDs. Use `not-run`, `requires-review`, or `blocked` rather than omitting an unverified row.
- For every Host-approved attachment `contentBinding`, a passed runtime phase includes an executed `attachment-resolution-runtime-vector` proof bound to the exact Canonical `stepId`, request `location`, and `path`. It proves one resolver call and one business dispatch on success, zero dispatch on resolution failure, no raw-grant forwarding, resolved-content binding, and size/digest verification. Compute `traceEvidenceHash` from the canonical JSON of the proof without that field and require the check's `evidenceHash` to equal the same digest.

Then finalize:

```bash
python3 <skill-root>/scripts/finalize_export.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --verification-report /path/to/executed-checks.json \
  --live-input /path/to/first-capability-input.json \
  --live-result /path/to/first-capability-result.json \
  --live-input /path/to/second-capability-input.json \
  --live-result /path/to/second-capability-result.json
```

- Supply `--live-input` and `--live-result` in matching order and repeat the pair for each Capability with live evidence; a file may instead contain a `capabilities` array. Every entry names `capabilityId`; the input wraps the exact Canonical Tool call under `input`, and the result wraps a successful contract-valid MCP result under `result`. A Capability without its own pair cannot become `runtime-verified`. The aggregate legacy report plus one live pair is allowed only for a single read-only bundle without `canonical-contract.json`.
- The finalizer must match every passed runtime check's Canonical `toolName`, `inputHash`, and `resultHash` to that Capability's live pair. If final validation fails, it restores the pre-finalization audit files so an invalid receipt, matrix, approval, or manifest cannot remain looking complete.

- Run the target repository's evaluator when one exists, then re-run `validate_artifacts.py` without `--pre-finalize`.
- If an old Golden encoded a different capability model, retain it only as superseded audit history and rebuild the current baseline.
- Test Host degradation deterministically: missing confirmation disables protected final writes, missing session state disables one-time bound write chains, and missing attachment support disables attachment-dependent goals without removing unrelated read capabilities.
- Set `hostVerified: true` only when that Capability's Host phase passed and its compatibility assessment is `enabled`; a Workflow additionally requires every Capability named by its Canonical `capabilityIds` to be enabled. A write always requires Host verification for approval. Do not translate Canonical `requires-review` into a Host integration status.

### 8. Report with boundaries

Lead with what is actually usable. Separate:

- capability model and artifact completion;
- static checks and tests;
- build/protocol verification;
- runtime or end-to-end verification;
- deployment status;
- inferences, unknowns, and remaining safety risks.

Never collapse “generated,” “builds,” “verified against a live system,” and “deployed” into one status.

## Non-negotiable checks

- No page-level mega-tool when independently valuable capabilities exist inside the feature.
- No one-request-equals-one-Tool rule.
- No important business claim without evidence classification.
- No write capability inferred from client code alone and presented as production-safe.
- No hard constraint enforced only by Skill prose.
- No Tool input that lets the Agent self-attest user confirmation.
- No non-idempotent operation with automatic retry or an undefined unknown-outcome policy.
- No MCP adapter that bypasses the authoritative auth/transaction/state boundary or creates a private duplicate of mutable application state.
- No observed Skill that merely explains how to call one oversized Tool.
- No fixed Tool count treated as a general formula; counts are feature-specific Golden results.
- No passed preflight, approval, live verification, or manifest produced from invented evidence.
- No target evaluator's private cases, Golden answers, fixtures, source code, or product-specific constants copied into the Code2Skill package.
- No language, framework, filename, directory layout, DTO/Controller/Service convention, Runtime Profile, or Agent brand treated as a prerequisite for business-contract discovery.
- No whole-machine search for an undeclared backend or contract repository.
- No dynamic catalog frozen into a static enum from one observed user, tenant, session, or test run.
- No package-level success used to conceal an unverified or blocked capability/workflow.
- No generated Skill that requires all user inputs up front or turns the original page sequence into the only legal composition.
- No backend-internal method added to a client feature's public capability surface without a client-observed API call or explicit scope expansion.
- No ordinary backend business rule duplicated as a universal preflight or hard Workflow merely to make the generated package appear complete.
- No opaque error string that prevents the Consumer Agent from distinguishing a correctable business rejection from authorization, network, malformed-output, or unknown-write-outcome failure.
- No generated package that claims Skill installation also starts, registers, authenticates, or verifies its MCP server.

## Resource map

- [capability-model.md](references/capability-model.md): definitions and boundary decisions.
- [vnext-architecture.md](references/vnext-architecture.md): Producer/Consumer separation, Portable Core, progressive goals, portability, and migration boundaries.
- [evidence-and-discovery.md](references/evidence-and-discovery.md): tracing and evidence classification.
- [mcp-tool-design.md](references/mcp-tool-design.md): Tool, Resource, schema, and runtime rules.
- [observed-skill-design.md](references/observed-skill-design.md): generated Skill structure and composition guidance.
- [documentation-contract.md](references/documentation-contract.md): Chinese Feature Context, Skill, MCP, and MCP setup documentation bar.
- [artifact-contract.md](references/artifact-contract.md): self-contained strict export, runtime, audit, and integrity contract.
- [verification.md](references/verification.md): verification matrix and superseded baselines.
- `assets/`: templates to copy into generated output.
- `scripts/validate_artifacts.py`: deterministic pre-finalization and final package validation.
- `scripts/derive_artifacts.py`: deterministic bundle mirroring and capability-draft derivation.
- `scripts/finalize_export.py`: evidence-gated receipts, approval, live hashes, and integrity manifest.
- `scripts/probe_mcp.py`: detached stdio MCP initialize/list/call/dry-run protocol probe.
