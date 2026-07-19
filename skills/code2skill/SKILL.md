---
name: code2skill
description: Convert an existing frontend, backend, or full-stack application feature into evidence-backed Feature Context, composable MCP Tools, and an observed Agent Skill. Use when extracting agent capabilities from routes, pages, components, API clients, controllers, services, schemas, tests, or existing workflows; when replacing a page-level mega-tool with reusable business capabilities; or when auditing and regenerating code-derived MCP and Skill artifacts.
---

# Code2Skill

Turn capabilities trapped in application code into reusable Agent capabilities. Use the coding Agent as the Producer that searches authorized source roots and implements the export; do not build a parallel scanner or autonomous Agent unless repeated evidence shows one is needed. Treat the Agent Host that later consumes the generated Skill and Tools as a separate system with separately declared capabilities.

## Core contract

Model three connected layers and compile them into a complete strict export:

1. **Feature Context** explains the business purpose, concepts, field semantics, states, permissions, rules, failures, and original client behavior.
2. **MCP Tools** expose independently valuable, composable execution capabilities with stable contracts.
3. **Observed Skill** captures the existing product's usage knowledge, conditional composition paths, and recovery guidance without forcing irrelevant calls.

The portable business contract is independent from its execution adapter. The current default delivery profile, `strict-export-v1`, is the `node-stdio` Runtime Profile: a self-contained capability bundle, named Node Function core, stdio MCP Server, Chinese PAGE/MCP/Skill documentation, evidence draft, deterministic verification, live receipt, approval audit, and integrity manifest. It remains fully supported, but it is not the only possible implementation of the Portable Core. A three-file design note is not a completed Code2Skill output.

Apply this invariant:

> MCP Tools provide composable execution capabilities. Skills provide domain knowledge, selection strategy, and default flows. The Agent chooses the composition for the user's goal. Schemas, handlers, servers, or deterministic workflows enforce constraints that must never be skipped.

Read [vnext-architecture.md](references/vnext-architecture.md) first for Producer/Consumer boundaries, Portable Core, progressive goal completion, portability, and the migration contract. Then read [capability-model.md](references/capability-model.md) before deciding capability boundaries. Read every other reference named by the relevant workflow step; do not ask another agent to interpret these instructions.

## Workflow

### 1. Establish scope and repository rules

- Read repository instructions and inspect the worktree before editing.
- Confirm the requested feature through the user's goal, route, screen, API, symbol, or test. If the target is discoverable from the repository, proceed without asking.
- Define every user-authorized source root and the output directory. Default the self-contained candidate to `generated/code2skill/<feature-id>/`. Search only those roots; do not scan the user's machine to guess where a backend might exist.
- Create `source-topology.json` with a stable `sourceId`, evidence role, accessibility, and search summary for each frontend, backend, contract, test, or other authorized root. These roles describe evidence, not required directory or architecture names. Record unavailable roots and missing semantic roles explicitly.
- Read any evaluator or delivery contract supplied by the target repository. Put the source-proven feature surface, route or stable surface identifier, origin allowlist, dry-run environment variable, protocol, transport, and language in `export-profile.json`; never guess or hard-code another project's constants into this Skill. For a route-less API, RPC, message, worker, or backend feature, set `featureSurface.kind` and `featureSurface.identifier`, and use `/__code2skill__/features/<feature-id>` only as the required `node-stdio` documentation key in `pageRoute`. Do not describe that reserved value as a deployed route or use it as an execution URL.
- Preserve unrelated changes. Repository-native MCP code may coexist, but the strict export still needs its own executable Function core and MCP entry point.

### 2. Trace the feature end to end

Read [evidence-and-discovery.md](references/evidence-and-discovery.md).

- Trace client entry points, routes, components, state, validation, visibility conditions, requests, result rendering, and error handling.
- When available, continue through transfer contracts, authorization, application orchestration, business rules, external calls, persistence, and tests. Discover these semantic roles from call paths, registrations, validation, serialization, field use, protocols, and assertions. Names such as DTO, Controller, Service, Request, Schema, or Model are optional clues, never required architecture.
- Build `canonical-contract.json` before authoring executable artifacts. It is the language- and Host-independent source of truth for every capability: exact public input shape, nested-object boundary, defaults, static or dynamic value domain, unconditional/conditional/forbidden inputs, cross-field predicates, provenance and freshness, request boundary, accepted statuses, response names, business failures, minimum usable result, side effects, confirmation, retry, and evidence confidence. Resolve material rows from executable code, protocols, validation, or tests; do not replace source names with clearer synonyms.
- Preserve contradictions between sources and select an authority only when evidence supports it. Missing backend proof for authorization, conditional validation, side effects, idempotency, or unknown-outcome handling keeps the affected write capability out of `ready`.
- Run the target repository's relevant tests and inspect their assertions. A TypeScript type or UI control alone does not prove runtime serialization, response validation, or cross-field rules.
- Resolve the public runtime origin from the target repository's actual startup contract, environment configuration, or executable test setup. The origin used by generated Functions must match `allowedRuntimeOrigins`; never replace a proven target origin with a convenient placeholder.
- Record each material conclusion in `canonical-contract.json.evidenceCatalog` with `evidenceId`, `sourceId`, portable `locator`, `semanticRole`, and `assertionLevel` (`fact`, `inference`, or `unknown`). Reuse those `evidenceId` values in Feature Context and contract facts instead of inventing a parallel path-only evidence format.
- Treat the client feature as an evidence boundary, not automatically as one capability or one Tool.

### 3. Model context and capabilities before coding

- Write a short Feature Context using [feature-context.md](assets/feature-context.md) as a starting point.
- Model goals inside `canonical-contract.json` around user outcomes rather than the original screen transcript. Classify information as always required, conditionally required, optional, derived, or dynamic; declare where it can come from, when it expires, when it must be refreshed, and the completion predicate for each goal. The derivation step projects this into `goal-contract.json`.
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
- Put non-bypassable source, ordering, transaction, and safety rules in schemas, handlers, server state, or deterministic workflows—not only in prose.
- Never generate generic escape hatches such as `call_api`, `execute_sql`, `run_service_method`, or one operation switch that dispatches all business actions.
- Mark side effects and require preview/confirmation or dry-run paths for destructive, financial, publishing, or external actions where supported.
- Never accept `confirmed: true`, `userConfirmed: true`, or a similar Tool argument as proof of user consent. Confirmation belongs to the Agent Host or a trusted runtime and must bind the target, payload digest, transient validation token, and side-effect summary. If that integration does not exist, mark the capability as requiring Host integration rather than claiming it is safe.
- Use the Canonical vocabulary for every Tool: `sideEffect` and `operationPolicy.sideEffect` are `read`, `create`, `update`, or `delete`; `operationPolicy.confirmation` is `not-required`, `trusted-confirmation-required`, or `upload-confirmation-required`. Also declare idempotency, automatic retry, and unknown-outcome handling. Express the actual enforcement owner through Consumer requirements and `workflows[].enforcement.owner`, not a second `confirmationOwner` field.
- For a non-idempotent multi-Tool write chain, generate a deterministic workflow/Host integration contract that binds validation, confirmation, and dispatch. If it cannot be implemented and tested, leave the write capability in `requires-review`.
- For vNext, complete `canonical-contract.json` before runtime code, then run `scripts/derive_artifacts.py <candidate>` to mechanically create both capability-bundle copies, `capability-draft.json`, Goal/Consumer views, Host compatibility, and the initial verification matrix. Do not hand-author derived files. A legacy package without a Canonical Contract retains the older bundle-first derivation path. Give every Tool exactly one distinct named async Function export.
- Preserve authoritative input grouping. Keep source-level filter, request, pagination, and option objects intact instead of flattening them from UI controls or inventing new wrappers.
- Preserve exact HTTP method, allowlisted origin, path/query/header/body/multipart binding, authentication, success status, required output paths, and stop-on-failure semantics. Preserve fixed query parameters inside the exact URL template; do not invent non-schema extension fields or unsupported binding-source kinds. Preserve root-body bindings, multipart field names, defaults, enum membership, cross-field provenance rules, and exact response field names. Execute a request step at most once; never automatically retry a network-ambiguous write.
- Compare the observed `response.status` with the exact declared `successStatusCodes`. Do not use `response.ok` or another broad 2xx shortcut when the source contract names specific accepted statuses.
- Use the source's externally observable names verbatim. Do not rename `status` to a more descriptive alias, turn a root request body into `{request: ...}`, omit a fixed query parameter, or model multipart data as ordinary JSON.
- Define `successRule.requiredOutputPaths` relative to the Function result's raw `data`; never prefix those paths with the MCP envelope key `data`. A business output field actually named `status` remains valid.
- Keep `requiredOutputPaths` minimal and contractual: include the smallest fields that prove the result is usable, not every echoed or incidental response field. Copy the source's actual failure keys into `forbiddenOutputKeys`; do not substitute a conventional list.
- Enforce proven response invariants as well as field presence: reject null or empty required values, validate fixed discriminator values, and require non-empty collections only when executable source evidence establishes that invariant.
- Keep `function-core/index.mjs` self-contained apart from `node:` built-ins. Every named Function validates exact direct inputs and returns one `{status, data}` result; npm dependencies and protocol schemas belong to the MCP adapter.
- For uploads, accept sanitized logical inputs such as filename, media type, and base64 content. Do not accept an arbitrary local file path.
- Model attachments as an end-to-end chain: Host-approved attachment reference or bounded content, metadata/hash validation, upload authorization, secure transfer, returned token/URL, and downstream binding. If the Consumer cannot resolve or upload approved attachments, disable the affected path or mark it `requires-host-integration`; never replace the missing chain with an arbitrary path or unproven URL.
- Implement direct MCP arguments, closed schemas, Chinese Tool titles/descriptions, complete annotations, `content` plus matching `structuredContent`, and `isError: true` Tool errors. Implement a literal `process.env.<declared-variable> === "1"` dry-run guard before every external action and named Function call. Return `dryRun`, `validatedInput`, `operationPolicy`, and `operationSummary`; derive policy and request-summary fields from the capability contract rather than executing or guessing them.
- Register every Tool with its literal name in a distinct `server.registerTool("tool_name", ...)` call. Do not generate a loop that dynamically registers bundle entries and do not hand-roll JSON-RPC.
- Make the strict export executable after it is copied away from the source repository. Keep the readable adapter in `mcp-tool/index.mjs`, import `McpServer`, `StdioServerTransport`, and `z` from `./runtime.mjs`, and build `runtime.mjs` by bundling the official MCP SDK and Zod from [mcp-runtime-entry.mjs](assets/mcp-runtime-entry.mjs). Minify the bundled runtime so dependency examples in third-party comments cannot be mistaken for unresolved imports. Do not bundle the adapter itself: its literal registrations, direct Zod schemas, and named `../function-core/index.mjs` imports must remain inspectable.
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
- Reference Feature Context rather than duplicating it throughout the Skill.
- Generate `PAGE.md` as the source-derived feature context visible to the Agent, `SKILL.md` as conditional usage knowledge, and `MCP.zh-CN.md` as the exact executable Tool contract. `PAGE.md` is a compatibility filename, not proof that a UI page exists: for route-less features, state the real `surface` kind and stable identifier, keep the reserved `pageRoute` only for document identity, and describe API/RPC/message/worker behavior rather than inventing screen regions.
- Meet the structural, Chinese-language, per-Tool, handoff, example, output, failure, dry-run, and side-effect requirements in the documentation contract. Do not use filler to reach the length threshold.

### 6. Build the strict export

Read [artifact-contract.md](references/artifact-contract.md).

- Start vNext from `assets/source-topology.json`, `assets/canonical-contract.json`, `assets/host-profile.json`, `assets/export-profile.json`, and `assets/PAGE.md`; replace every synthetic example and placeholder. Use `assets/verification-report.schema.json` as the finalizer input contract, never `assets/verification-report.md`, which is retained only as a legacy human summary. `assets/goal-contract.json` and `assets/consumer-requirements.json` illustrate derived shapes, not independent authoring sources. Legacy exports may still use the bundle/draft templates directly.
- Author the vNext inputs `source-topology.json`, `canonical-contract.json`, and the deployment-supplied `host-profile.json`. Derive `goal-contract.json`, `consumer-requirements.json`, `host-compatibility-report.json`, and `verification-matrix.json`. The capability graph and Consumer requirement definitions live inside the Canonical Contract; do not maintain duplicate authoring sources.
- Treat `host-profile.json` as deployment evidence, not a Producer or brand assumption. Compare it deterministically with `consumer-requirements.json`. Enable, disable, block, or mark `requires-host-integration` per capability when trusted confirmation, session state, attachment resolution, secure upload, authentication injection, transport, or unknown-outcome reconciliation is unavailable.
- Run `scripts/derive_artifacts.py <candidate>` after every Canonical Contract change. For vNext it projects `capability-bundle.json`, its Function mirror, `capability-draft.json`, Goal/Consumer views, Host compatibility, and the verification matrix from the completed contract. The draft keeps one qualified `tools.<tool>.input.<name>` input and provenance record per public input plus one qualified `<tool>.<step>` request-chain record per HTTP step. Do not edit those projections or maintain an unrelated page-global input list.
- Generate the complete strict export tree. In vNext, hard workflows live only in `canonical-contract.json`; every write includes `portable-workflow-guard.mjs` and runtime integration, and `workflow.json` is omitted to avoid a second source of truth. Legacy bundle-only exports keep their existing constrained `workflow.json` contract.
- Keep the capability set identical across both bundle copies, named Function exports, MCP `tools/list`, Tool call dispatch, PAGE, Skill, and MCP documentation.
- Derive or deterministically cross-check Function validation, MCP schemas and registrations, Skill claims, workflow guards, and test vectors against the Canonical Contract. Runtime Profile details may add transport and packaging behavior but must not change business names, requiredness, value domains, failures, or safety policy.
- Keep all evidence references source-derived. `capability-draft.json` may be `ready` only when material evidence is complete; otherwise stop before approval.

### 7. Verify behavior, not just structure

Read [verification.md](references/verification.md).

- Run the repository's relevant static checks, build, unit tests, and MCP protocol tests.
- Test every Tool independently with valid and invalid inputs.
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

- Run Function unit vectors for every capability, including status/network/output failures. Run an MCP stdio protocol probe for initialize, `tools/list`, valid calls, invalid arguments, unknown Tools, and dry-run with zero external effects.
- Function vectors must assert the exact URL, query serialization, lower-cased header contract, root or nested body shape, multipart field metadata, accepted status, returned field names, defaults, invalid extra keys, invalid enums/ranges/patterns, cross-field dependencies, response failure keys, and required-output rejection. A test that only proves “a request happened” is insufficient.
- Run the MCP probe from a temporary copy of the candidate with no source-repository `node_modules` on its ancestor path. This proves `mcp-tool/runtime.mjs` is actually self-contained.
- Execute a real MCP call for every capability claimed as `runtime-verified`; at minimum exercise one appropriate capability to establish package-level runtime reachability. Save sanitized inputs and results outside the candidate directory. Do not fabricate a successful live receipt or apply one Tool's receipt to another.
- Record verification per capability and per hard workflow in `verification-matrix.json`. Distinguish `generated`, `behavior-verified`, `runtime-verified`, `host-verified`, `requires-review`, and `blocked`; one successful Tool call never approves another Tool or workflow.
- Write a vNext JSON verification report conforming to `assets/verification-report.schema.json`. It must match the Canonical `contractId`, cover every Capability and Workflow exactly once, record Capability `behavior/runtime/host` phases and Workflow `bypass/runtime/host` phases, and include only commands actually executed. Every passed check records its exit code and evidence SHA-256. Every passed runtime check also binds the Canonical `toolName` and matching live `inputHash/resultHash`; every passed bypass check sets `zeroExternalWrites: true` and covers the Canonical workflow check IDs. Use `not-run`, `requires-review`, or `blocked` rather than omitting an unverified row. Then finalize:

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

## Resource map

- [capability-model.md](references/capability-model.md): definitions and boundary decisions.
- [vnext-architecture.md](references/vnext-architecture.md): Producer/Consumer separation, Portable Core, progressive goals, portability, and migration boundaries.
- [evidence-and-discovery.md](references/evidence-and-discovery.md): tracing and evidence classification.
- [mcp-tool-design.md](references/mcp-tool-design.md): Tool, Resource, schema, and runtime rules.
- [observed-skill-design.md](references/observed-skill-design.md): generated Skill structure and composition guidance.
- [documentation-contract.md](references/documentation-contract.md): Chinese PAGE, Skill, and MCP documentation bar.
- [artifact-contract.md](references/artifact-contract.md): self-contained strict export, runtime, audit, and integrity contract.
- [verification.md](references/verification.md): verification matrix and superseded baselines.
- `assets/`: templates to copy into generated output.
- `scripts/validate_artifacts.py`: deterministic pre-finalization and final package validation.
- `scripts/derive_artifacts.py`: deterministic bundle mirroring and capability-draft derivation.
- `scripts/finalize_export.py`: evidence-gated receipts, approval, live hashes, and integrity manifest.
