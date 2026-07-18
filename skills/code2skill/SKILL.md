---
name: code2skill
description: Convert an existing frontend, backend, or full-stack application feature into evidence-backed Feature Context, composable MCP Tools, and an observed Agent Skill. Use when extracting agent capabilities from routes, pages, components, API clients, controllers, services, schemas, tests, or existing workflows; when replacing a page-level mega-tool with reusable business capabilities; or when auditing and regenerating code-derived MCP and Skill artifacts.
---

# Code2Skill

Turn capabilities trapped in application code into reusable Agent capabilities. Use the coding Agent as the repository scanner and implementation engine; do not build a parallel scanner or autonomous Agent unless repeated evidence shows one is needed.

## Core contract

Model three connected layers and compile them into a complete strict export:

1. **Feature Context** explains the business purpose, concepts, field semantics, states, permissions, rules, failures, and original client behavior.
2. **MCP Tools** expose independently valuable, composable execution capabilities with stable contracts.
3. **Observed Skill** captures the existing product's usage knowledge, conditional composition paths, and recovery guidance without forcing irrelevant calls.

The default delivery profile is `strict-export-v1`: a self-contained capability bundle, named Function core, stdio MCP Server, Chinese PAGE/MCP/Skill documentation, evidence draft, deterministic verification, live receipt, approval audit, and integrity manifest. A three-file design note is not a completed Code2Skill output.

Apply this invariant:

> MCP Tools provide composable execution capabilities. Skills provide domain knowledge, selection strategy, and default flows. The Agent chooses the composition for the user's goal. Schemas, handlers, servers, or deterministic workflows enforce constraints that must never be skipped.

Read [capability-model.md](references/capability-model.md) before deciding capability boundaries. Read every other reference named by the relevant workflow step; do not ask another agent to interpret these instructions.

## Workflow

### 1. Establish scope and repository rules

- Read repository instructions and inspect the worktree before editing.
- Confirm the requested feature through the user's goal, route, screen, API, symbol, or test. If the target is discoverable from the repository, proceed without asking.
- Define the source root and the output directory. Default the self-contained candidate to `generated/code2skill/<feature-id>/`.
- Read any evaluator or delivery contract supplied by the target repository. Put target-specific route, origin allowlist, dry-run environment variable, protocol, transport, and language in `export-profile.json`; never guess or hard-code another project's constants into this Skill.
- Preserve unrelated changes. Repository-native MCP code may coexist, but the strict export still needs its own executable Function core and MCP entry point.

### 2. Trace the feature end to end

Read [evidence-and-discovery.md](references/evidence-and-discovery.md).

- Trace client entry points, routes, components, state, validation, visibility conditions, requests, result rendering, and error handling.
- When available, continue through API contracts, controllers, authorization, services, domain models, persistence, and tests.
- Build a source-contract ledger before authoring the bundle. For every proposed Tool, record the exact public input shape, nested-object boundary, defaults, validation predicates, HTTP method and URL, fixed query values, header names and values, body or multipart encoding, accepted status codes, response field names, business-failure keys, and minimum usable success fields. Resolve every ledger row from executable code, schemas, or tests; do not replace source names with clearer synonyms.
- Run the target repository's relevant tests and inspect their assertions. A TypeScript type or UI control alone does not prove runtime serialization, response validation, or cross-field rules.
- Resolve the public runtime origin from the target repository's actual startup contract, environment configuration, or executable test setup. The origin used by generated Functions must match `allowedRuntimeOrigins`; never replace a proven target origin with a convenient placeholder.
- Record each material conclusion as `fact`, `inference`, or `unknown` with file and symbol evidence.
- Treat the client feature as an evidence boundary, not automatically as one capability or one Tool.

### 3. Model context and capabilities before coding

- Write a short Feature Context using [feature-context.md](assets/feature-context.md) as a starting point.
- Draft candidate capabilities around independent user or Agent goals.
- Merge or split candidates by business meaning, independent value, contract stability, reuse, side effects, and enforceable preconditions.
- Do not derive Tool count from page count, request count, endpoint count, or function count.
- Decide whether lookup data belongs in an input enum, Skill reference, MCP Resource, or MCP Tool. Do not mechanically turn every option list into a Tool.
- Treat client-visible local options or structured field metadata as independent capabilities when a user can ask for them directly, when several downstream calls need them, or when their labels/semantics matter beyond validation. In those cases, prefer a Tool (or a Resource when execution is unnecessary) even if the current implementation is a constant.
- Apply that test to each catalog independently. Do not merge unrelated local catalogs into a generic page-options Tool merely because they share one configuration file, render on one page, or both execute without HTTP. If each catalog can satisfy a different partial user goal or feeds a different downstream input chain, each is a separate capability.
- Stop and report a boundary if only client code exists and a write operation's authorization, financial effect, idempotency, or compensation behavior cannot be proven.

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
- Declare confirmation ownership, idempotency, automatic retry, and unknown-outcome handling for every side-effecting Tool in `operationPolicy`.
- For a non-idempotent multi-Tool write chain, generate a deterministic workflow/Host integration contract that binds validation, confirmation, and dispatch. If it cannot be implemented and tested, leave the write capability in `requires-review`.
- Write `capability-bundle.json` before runtime code. Then run `scripts/derive_artifacts.py <candidate>` to mechanically create `function-core/capability-bundle.json` and `capability-draft.json`; do not hand-author either derived file. Give every Tool exactly one distinct named async Function export.
- Preserve authoritative input grouping. Keep source-level filter, request, pagination, and option objects intact instead of flattening them from UI controls or inventing new wrappers.
- Preserve exact HTTP method, allowlisted origin, path/query/header/body/multipart binding, authentication, success status, required output paths, and stop-on-failure semantics. Preserve fixed query parameters inside the exact URL template; do not invent non-schema extension fields or unsupported binding-source kinds. Preserve root-body bindings, multipart field names, defaults, enum membership, cross-field provenance rules, and exact response field names. Execute a request step at most once; never automatically retry a network-ambiguous write.
- Compare the observed `response.status` with the exact declared `successStatusCodes`. Do not use `response.ok` or another broad 2xx shortcut when the source contract names specific accepted statuses.
- Use the source's externally observable names verbatim. Do not rename `status` to a more descriptive alias, turn a root request body into `{request: ...}`, omit a fixed query parameter, or model multipart data as ordinary JSON.
- Define `successRule.requiredOutputPaths` relative to the Function result's raw `data`; never prefix those paths with the MCP envelope key `data`. A business output field actually named `status` remains valid.
- Keep `requiredOutputPaths` minimal and contractual: include the smallest fields that prove the result is usable, not every echoed or incidental response field. Copy the source's actual failure keys into `forbiddenOutputKeys`; do not substitute a conventional list.
- Enforce proven response invariants as well as field presence: reject null or empty required values, validate fixed discriminator values, and require non-empty collections only when executable source evidence establishes that invariant.
- Keep `function-core/index.mjs` self-contained apart from `node:` built-ins. Every named Function validates exact direct inputs and returns one `{status, data}` result; npm dependencies and protocol schemas belong to the MCP adapter.
- For uploads, accept sanitized logical inputs such as filename, media type, and base64 content. Do not accept an arbitrary local file path.
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
- Permit partial goals. A user asking for one option list, one detail, or one page of results should not be forced through the full original screen flow.
- Reference Feature Context rather than duplicating it throughout the Skill.
- Generate `PAGE.md` as the source-derived feature context visible to the Agent, `SKILL.md` as conditional usage knowledge, and `MCP.zh-CN.md` as the exact executable Tool contract.
- Meet the structural, Chinese-language, per-Tool, handoff, example, output, failure, dry-run, and side-effect requirements in the documentation contract. Do not use filler to reach the length threshold.

### 6. Build the strict export

Read [artifact-contract.md](references/artifact-contract.md).

- Start from `assets/export-profile.json`, `assets/capability-bundle.json`, `assets/capability-draft.json`, and `assets/PAGE.md`; replace every example and placeholder.
- Run `scripts/derive_artifacts.py <candidate>` after every bundle change. It derives `capability-draft.json` mechanically from the completed bundle: one qualified `tools.<tool>.input.<name>` input and provenance record per public input; canonical prior-response details; and one qualified `<tool>.<step>` request-chain record per HTTP step. Do not maintain an unrelated page-global input list.
- Generate the complete strict export tree. A read-only bundle omits `workflow.json`; a bundle with any write capability includes a constrained workflow that names actual enforcement owners.
- Keep the capability set identical across both bundle copies, named Function exports, MCP `tools/list`, Tool call dispatch, PAGE, Skill, and MCP documentation.
- Keep all evidence references source-derived. `capability-draft.json` may be `ready` only when material evidence is complete; otherwise stop before approval.

### 7. Verify behavior, not just structure

Read [verification.md](references/verification.md).

- Run the repository's relevant static checks, build, unit tests, and MCP protocol tests.
- Test every Tool independently with valid and invalid inputs.
- Test representative partial and multi-Tool compositions.
- Test runtime rejection of fabricated IDs, invalid source tokens, unauthorized access, unsafe parameters, and skipped hard preconditions.
- Validate the generated artifact bundle:

```bash
python3 <skill-root>/scripts/validate_artifacts.py \
  generated/code2skill/<feature-id> \
  --source-root . \
  --pre-finalize
```

- Run Function unit vectors for every capability, including status/network/output failures. Run an MCP stdio protocol probe for initialize, `tools/list`, valid calls, invalid arguments, unknown Tools, and dry-run with zero external effects.
- Function vectors must assert the exact URL, query serialization, lower-cased header contract, root or nested body shape, multipart field metadata, accepted status, returned field names, defaults, invalid extra keys, invalid enums/ranges/patterns, cross-field dependencies, response failure keys, and required-output rejection. A test that only proves “a request happened” is insufficient.
- Run the MCP probe from a temporary copy of the candidate with no source-repository `node_modules` on its ancestor path. This proves `mcp-tool/runtime.mjs` is actually self-contained.
- Execute at least one real MCP call in an appropriate environment. Save sanitized input and result outside the candidate directory. Do not fabricate a successful live receipt.
- Write a JSON verification report containing only commands actually executed. Then finalize:

```bash
python3 <skill-root>/scripts/finalize_export.py \
  generated/code2skill/<feature-id> \
  --verification-report /path/to/executed-checks.json \
  --live-input /path/to/sanitized-live-input.json \
  --live-result /path/to/sanitized-live-result.json
```

- Run the target repository's evaluator when one exists, then re-run `validate_artifacts.py` without `--pre-finalize`.
- If an old Golden encoded a different capability model, retain it only as superseded audit history and rebuild the current baseline.

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

## Resource map

- [capability-model.md](references/capability-model.md): definitions and boundary decisions.
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
