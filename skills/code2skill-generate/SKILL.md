---
name: code2skill-generate
description: Generate runnable, installable Functions, MCP tools, and Agent Skills from authorized frontend, backend, or full-stack code, including page features, interfaces, workflows, and fixes to existing generated packages；从已有前端、后端或全栈代码中提取业务功能，生成可运行、可安装的 Function、MCP 和 Agent Skill，适用于页面功能、接口功能、业务流程及已有生成结果的修正。
---

# Code2Skill

Complete Chinese version: [SKILL.zh-CN.md](references/SKILL.zh-CN.md).

Use the user's language for the final response, generated Skills, and user-facing documentation. When no language is explicitly requested, follow the language of the user's current request.

Turn the business capabilities of an existing application into Functions, MCP tools, and Skills that other agents can use. The default goal is a small, reliable runtime package, not an audit archive of the source code.

Use the current coding agent to search, understand, and modify user-authorized code; do not build a separate scanner. The Consumer of the generated package may not be the current agent. Do not assume that it can read the original repository, files on the Producer machine, or session state, except for controlled attachment paths or attachment references explicitly passed to a tool by the Consumer Host.

## Default Generated Result

Unless the user explicitly requests a strict audit, generate only:

```text
generated/code2skill/<feature-id>/
├── SKILL.md                    # Used when there is only one primary goal
├── skills/                     # Replaces the root SKILL.md when there are multiple primary goals
│   ├── <goal-a>/SKILL.md
│   └── <goal-b>/SKILL.md
├── MCP-SETUP.md
├── package.json              # Current node-stdio profile example: package metadata, runtime scripts, and dependencies
├── function-core/
│   └── index.mjs             # Current node-stdio profile example
├── mcp-tool/
│   └── index.mjs             # Current node-stdio profile example
├── portable-agent-result.mjs # Generic result projection helper for node-stdio (readHttpResponse/httpResultFromError are HTTP-only)
├── tests/
│   └── *.test.mjs            # Current node-stdio profile example
└── references/
    └── feature-context.md     # Generated only when business context cannot be kept concise in the Skill
```

The default artifact composition remains the same, while extensions, dependencies, and startup methods follow the runtime profile. `core-export-v1` is implemented by `node-stdio`.

Use either a root `SKILL.md` or `skills/*/SKILL.md`, never both. A page or directory specified by the user is only the search scope: first identify the primary user goals within it that can be completed independently. Generate a root Skill for one goal; for multiple goals, generate an independent Skill for each and share the same set of atomic Functions and MCP tools. Do not split Skills by interface count or use one large Skill to cover unrelated goals.

When multiple goals use `skills/<goal-id>/SKILL.md`, place references under the corresponding Skill's `references/` directory. Do not make an installed Skill depend on files in its parent directory. The root `references/feature-context.md` applies only to a single root Skill.

Do not generate Canonical/Goal Contracts, Capability Graphs, Host Profiles, Verification Matrices, manifests, hash receipts, other audit files, long MCP documentation, or live receipts in the default package. Temporary analysis notes and test output do not belong in the delivered package.

Code is the maintenance source of truth: Functions are the truth of business execution, MCP is the standard adapter layer, and Skills are the agent's usage knowledge. Avoid describing the same fact repeatedly in multiple JSON files or long documents.

## Default Workflow

### 1. Define the Scope

- Start from the page, directory, interface, route, symbol, or functional goal specified by the user.
- Search only source roots explicitly authorized by the user; do not scan the entire machine. When the user has not explicitly limited the scope, follow direct imports and aliases within the same repository to close dependencies. Do not cross repository boundaries or a constraint such as “only these roots.” Record the missing symbol or file for unavailable dependencies; do not prematurely declare the capability missing on that basis.
- Treat the specified scope as a discovery boundary. First list the primary user goals within it that can be independently triggered, guided, and completed; this may produce one or more Skills.
- The unit of a Skill is a primary user goal, not a directory, file, interface, or input field.
- Read the target repository's rules and existing tests first.

### 2. Identify Goal Decision Boundaries

For each goal, the Producer first forms a minimal temporary graph in **working memory**: user goal → known/missing information → query/selection/validation → branches and stopping conditions → pre-write presentation/confirmation → write → result query/reconciliation when present in source. A purely read-only goal has no write node. Do not invent anything without source evidence.

Each node has exactly one primary role: agent judgment/question/selection | user interaction/confirmation | an independently nameable, callable, reusable, or stoppable MCP tool | a deterministic step inside a Function | a result boundary of completed/stopped/unconfirmed. Constraint owners, which may overlap, are: backend authority | Consumer Host policy | a deterministic Guard proven by source to be non-bypassable. A write tool may carry both Host confirmation and a Guard; do not choose only one. See “Design Capabilities” for the Guard evidence threshold. Keep this graph only in working memory; do not generate an intermediate file or include it in the delivered package.

### 3. Determine the Capability Surface from Real Invocation Points

Business invocation points that actually exist in source code define the Function/MCP candidate surface. When a client or Consumer exists, follow its call chain. Without a client, start from a user-specified public API, RPC, Service, message, or task entry point that source code proves callable. Include only logic that affects those entry points:

- Invocation target and operation (HTTP: method/URL/query/header/body/multipart; RPC: service/method/arguments; message/task: destination/key/payload; in-process Service: method and runtime context).
- Response fields, return values, receipts, or task IDs that the caller actually uses.
- Defaults, transformations, dynamic options, conditional inputs, and error handling.
- User goals, primary branches, stopping points, and information presented before submission.
- How attachment upload results bind to later calls.

Do not automatically expose a tool merely because the backend contains an internal method, arbitrary public method, Repository, message consumer, or scheduled task. Do not mechanically turn a page, request, control, or input field into a tool.

Prefer putting hard-coded page menus, copy, and configuration into the Skill or optional Feature Context. Generate a tool for local data only when that data can independently satisfy a user goal, must be reused by multiple capabilities, or must be read at runtime.

### 4. Perform a Bounded Transport-Contract Check

By default, use backend, protocol, or test source only to complete the public transport contract: the structure and nullability of Request/Response types, interface definitions, Service method signatures, and message/task contracts; authentication, identity boundaries, and runtime-context injection points; common response envelopes and public fields such as `code`, `message`, and `data`; explicitly public enums and attachment upload interfaces. Stop when the contract is sufficient for generation. Do not trace Service, persistence, messages, approvals, downstream RPC, the complete side-effect graph, or every business validation by default.

Continue deeper only when public contracts contradict one another; the operation has clear financial, deletion, publication, or other high-risk effects; source code explicitly contains a non-bypassable security credential or ordering constraint; or the user explicitly requests a deep audit.

The real backend invocation point is authoritative for whether an ordinary business call is accepted. Do not copy the entire backend rule set into a Function or predict success from HTTP status or business fields. Pass the backend response or invocation result to the Consumer Agent so it can judge the result, correct the call, ask for missing information, or explain the outcome.

### 5. Design Capabilities

A tool should express a business capability that can be independently named, called, reused, or stopped. Split by business meaning, input/output stability, and side effects—not by source file or HTTP call count.

Positive conditions for an additional tool, any one of which is sufficient: an intermediate result changes a later call, branch, or parameter; the capability can independently complete part of the goal or be reused; the steps before and after it have different permission, side-effect, or confirmation requirements; the intermediate stage may stop or wait for user input; or source proves an asynchronous status query or reconciliation after a write. Negative conditions against splitting: only to make the model reason more often; deterministic implementation such as request assembly, field formatting, or RAG; the next step is always the same regardless of the intermediate result; splitting exposes meaningless intermediate state; or multiple calls form an indivisible transaction.

One tool may call multiple internal APIs, and one API may support multiple business tools. Do not map mechanically by interface count. Split only nodes whose primary role is MCP tool. Do not rename agent judgment/questions, user confirmation, or deterministic Function-internal steps merely to force a split.

For each capability, define only the minimal contract: a stable operation identity (tool name, title, invocation target, operation identifier, version/routing key); mapping from public inputs to real invocation fields; known parameter names, provenance, purpose, type/order/serialization; response fields, receipts, or task IDs required for downstream handoff and the next decision; binding (HTTP: method/URL/query/header/body/multipart; RPC: service/method/arguments; message/task: destination/key/payload; in-process Service: method and runtime context); read/create/update/delete side effects; and authentication, runtime-context, and attachment requirements. Routing/version/context and result/error/timeout/retry boundaries must be proven by source and reproduced consistently by the Function.

In HTTP scenarios, the business API base URL is deployment configuration, not user business input. In other scenarios, refer to the equivalent concept as “business service connection configuration.” Declare environment variables per independent service, for example `CODE2SKILL_<FEATURE>_<SERVICE>_BASE_URL` in HTTP scenarios. Do not expose a base URL or any connection configuration as a tool parameter, and do not use source test, staging, production, or fixed addresses as defaults. Source-proven environment addresses may appear in `MCP-SETUP.md` as deployment references; the Consumer Host must inject the actual runtime value explicitly. Object-storage, callback, or presigned URLs dynamically returned by an invocation result or backend response are not static base URLs.

Do not infer semantics from field names alone. For same-name fields, trace provenance, assignment, and purpose. When their meanings differ, use public names that reflect the real purpose and map them internally to the actual invocation fields. Perform source binding for every write capability and every “query → selection → later invocation” chain: trace upstream response → caller normalization → each downstream wire representation. When one upstream value enters multiple downstream calls, independently trace “raw value → normalized value → each downstream wire” at every use site. Do not reuse one representation merely because semantics appear similar or a tool is shared. When source rewrites an upstream value, trace the normalization itself and the normalized result at every downstream use; do not treat the raw representation as usable downstream.

When the client expands or merges multiple fields—or an entire row object—from a selected result into a later request, model it as selected-record handoff. If the downstream call reads only a few fields, expose them individually. If it forwards the entire row, use a business-named open object such as `selectedOrder`. The Function must merge in source order and preserve explicit override relationships. Unless evidence proves that passing only an identifier is equivalent, the Skill's standard example must pass the record; whether omitting it is accepted remains for the backend to decide.

MCP must declare an input Schema, but by default it is parameter guidance for the agent, not a business gatekeeper. Use open objects. Prefer `unknown().optional()` with descriptions for known business fields; do not generate enums, formats, ranges, conditional requirements, or strict types by default. Preserve only the minimum transport constraint when a URL, attachment, or other transport structure cannot be formed without a value. Accept additional parameters; do not set `additionalProperties: false` or use strict objects. The Function must assemble invocations only from source-proven bindings and must not block a call with narrower schemas, types, or local rules. Preserve additional parameters for the callback and agent. When no destination for them is proven, do not guess or claim that they were sent.

Do not declare `outputSchema` by default. Tool descriptions and Skills may describe known response fields, but real variations such as HTTP status, `null`, missing fields, numeric strings, and additional fields must reach the agent first. Add an optional, open `outputSchema` that does not block known variants only when the user explicitly requires machine-typed output and the public contract is sufficiently stable.

Ordinary write interfaces are validated by the backend by default. Implement a deterministic Guard only when source explicitly proves a non-bypassable identity, provenance, transaction, one-time credential, or ordering constraint. A page confirmation dialog, ordinary POST, ordinary backend rejection, or shared query does not by itself prove the need for a custom Host Guard.

### 6. Implement Functions and MCP

The Producer chooses an approach based on the target repository's existing implementation. Do not prebuild framework-specific generators inside Code2Skill:

- **Approach A: Directly runnable thin wrapper.** Reuse an existing HTTP, RPC, gRPC, SDK, or command client. Wrap only parameter mapping, deterministic transformations, authentication integration, and result forwarding.
- **Approach B: Wrapper inside the original runtime.** For dependency injection, transactions, interceptors, thread context, or in-process Service scenarios, generate a thin wrapper in the original project's technology stack. Do not move business methods into a new Node package and pretend the semantics are equivalent. If the target runtime is not the currently verifiable `node-stdio` profile—for example an in-process Java or Python Service—this version handles it as Approach C.
- **Approach C: Host integration required.** When no safely callable client or runtime context is available, preserve the Skill, tool contract, and integration instructions, and set `code2skill.requiresHostIntegration` in `package.json`. Do not generate a universal `call_rpc`, `invoke_method`, or `publish_message` tool or claim that the capability is deployed.

For asynchronous publication or task enqueueing, state only “accepted” or “enqueued.” Generate a separate status capability only when status-query source exists. Do not present a receipt or task ID as business completion.

General rules: each tool has a same-named independent Function export; Function Core exports a Zod Schema; public field names express business meaning and map internally to real fields; authentication, invocation construction, and deterministic transformations must be owned by the Function (date/time, formatting, defaults, renaming, arrays/URLs, ordering, serialization, and context); concatenation, formatting, and normalization must not be pushed to the agent or evaded through open Schema or backend authority; construct the wire representation of the same value independently at different call sites; MCP uses SDK/Zod (the current `node-stdio` profile example); every tool provides a name, `title`, `description`, open `inputSchema`, and annotations; omit `outputSchema` by default; after a result is obtained, use `toAgentResult` to pass it to the agent unchanged; only project low-level exceptions that produced no response through `toAgentError`; dry-run sends no network traffic or writes; module initialization must not make business requests; inject business service connection configuration through the environment (the API base URL in HTTP scenarios), return a configuration error before invocation when it is missing, and never fall back to test, staging, or production.

#### HTTP-Specific Rules

A `fetch`-based implementation returns `httpStatus` and complete `bodyText` for every HTTP status. When an HTTP client throws for 4xx or 5xx, recover its status and response as an ordinary tool result. Only low-level exceptions that produced no response go through `toAgentError`. Do not derive success, failure, unknown-result, or retry conclusions from a response envelope or business `code`. Under the `node-stdio` profile, copy `portable-agent-result.mjs`; HTTP targets use its `readHttpResponse` and `httpResultFromError`.

The Consumer Agent decides when to call a tool, how to complete parameters, whether to ask the user first, how to interpret a response, and whether to call another tool, based on the user's goal and actual result. Functions and MCP must not hard-code a universal retry or write policy.

Attachments are supplied by the Consumer Host. Prefer opaque references such as `attachmentRef`. Use `hostFilePath` only when the Host explicitly guarantees provenance and accessibility; this is a deployment trust prerequisite. When the prerequisite is not met, mark the attachment capability unmet. When source proves an upload chain, generate the upload Function/tool and downstream binding. The Skill must prohibit the agent from guessing or constructing local paths. When only STS or presigned credentials are obtainable but uploading is impossible, clearly mark the goal incomplete; do not pretend a URL already exists.

### 7. Write Skills

Each Skill serves one primary user goal and independently describes its invocation chain. Shared tools are reusable atomic capabilities, not a mandatory process shared across Skills. Center the Skill on the user goal and source-proven invocation point, not a retelling of page clicks. It should explain:

- Which invocation triggers the Skill (HTTP, RPC service/method, message destination, task entry point, in-process Service, and so on).
- What each tool does and when to call or skip it.
- Which information is known, missing, conditionally required, dynamically obtained, or optional.
- How to ask incrementally instead of demanding a complete form from the user at once.
- Common combinations, partial goals, stopping conditions, and result presentation.
- How actual responses are presented to the agent, and how the agent may continue calling tools, ask for more information, or explain the result directly.
- Source-proven write effects, risks, and user choices. Whether confirmation is required is decided by the Consumer Agent or Host policy, not forced in generic Functions or MCP.

For a goal with multiple decision nodes, the Skill must explain known, missing, and safely obtainable information; which result changes the next step; when to skip, stop, ask, or select; effects presented before a write; agent/Host policy and hard constraints. An ambiguous response goes to the agent and must not be automatically converted to success or failure. A Skill is not a fixed step-by-step script. When information is already complete, it should not ask meaningless questions or repeat queries.

Describe available capabilities and the usual order from the direct source call chain for the current Skill's goal. A query or precheck reused across several goals is merely a shared tool. Without evidence from the current goal's call chain, do not make it a prerequisite for this Skill. The agent may skip unneeded capabilities, temporarily compose tools, adjust calls based on responses, or communicate with the user first.

When the standard path contains “query result → select one → downstream operation,” guide the agent to preserve and pass the selected record supported by the Function. Reuse it directly while the information is still fresh; do not repeat the query.

Preserve the actual values of booleans, enums, or status fields that decide the next step. When a field is missing, `null`, or structurally unrecognizable, do not silently convert it to `false`, success, or failure. Pass the actual result to the agent so it can judge from context or tell the user that the outcome cannot be confirmed.

Put short background knowledge directly in `SKILL.md`. Generate `references/feature-context.md` only when that knowledge would materially interfere with the usage instructions. Do not maintain the same knowledge twice.

Use `assets/core-MCP-SETUP.md` and `assets/core-feature-context.md` as the English templates. For Chinese user-facing output, use `assets/core-MCP-SETUP.zh-CN.md` and `assets/core-feature-context.zh-CN.md` instead. Keep `MCP-SETUP.md` concise. Explain only: `npx skills add` installs the Skill only; under the `node-stdio` profile, use `npm ci` when a lockfile exists and `npm install` otherwise; register a local MCP server through runtime-neutral stdio `command/args/cwd/env` launch parameters, and use Streamable HTTP only for an independently deployed remote service; how business connection configuration (the base URL in HTTP scenarios), authentication, and dry-run environment variables are injected; mark `requires-host-integration` when runtime context, dependencies, or a safe entry point are unavailable; how to stop when the base URL is missing; and report installation, registration, connectivity, validation, and deployment as separate layers. Do not present host conventions such as `mcpServers` as protocol requirements. Do not copy strict-export-vNext templates into the default package.

### 8. Offline Validation

Do not call live business interfaces by default. Always perform generic checks for directory structure, Skills, MCP discovery, and safety boundaries. Known verifiable runtime profiles handle language-specific builds and tests. The current `core-export-v1` can automatically perform runtime validation only for the `node-stdio` profile; handle wrappers in other original runtimes as Approach C. At minimum:

1. Function smoke tests: cover source-visible invocation construction (HTTP: method/URL/query/header/body/multipart; RPC: service/method/arguments; message/task: destination/key/payload; in-process Service: method and runtime context). Use type variants, `null`, or additional parameters to prove calls are not rejected prematurely by Schema. For selected-record handoff, switch calls between two different anonymous records and verify that no values from the previous record remain.
2. MCP smoke tests: `initialize`, `tools/list`, and representative `tools/call`; prove that calls work without `outputSchema`; sample HTTP 4xx/5xx, non-JSON, long bodies, and low-level exceptions, as well as exception and receipt forwarding for RPC, message, and task scenarios.
3. Write-capability dry-run: verify that dry-run sends no network traffic or writes; never call a write interface for real.
4. Runtime configuration: for HTTP use `.invalid`, mock, or fake base URLs to validate URL construction; for RPC, Service, message, and task scenarios, inject a fake client, Broker handle, or runtime context. Prove zero external calls when required configuration is missing and no fallback environment default exists.
5. Package tests: the `node-stdio` profile example uses `npm test`, then runs the compact validator:

```bash
python3 <skill-root>/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

`package.json` must contain `code2skill.profile=core-export-v1`. Under the `node-stdio` profile, the validator performs syntax checks, starts MCP to complete `initialize + tools/list`, and runs in-package tests with `node --test` after sanitizing credentials. It does not parse source templates or install dependencies. Use `npm ci` when a lockfile exists and `npm install` otherwise. A result produced with `--skip-tests` for structural diagnosis must not be described as verified runnable. When there is no known verifiable profile, report “automatic runtime validation not completed” after generic checks; do not fabricate a pass. Tests must mock external requests and honor dry-run.

Keep test code in the package; do not retain logs or receipts. Tests prove only that the package can load, register, assemble invocations, construct Guards, and forward responses. They do not prove business rules, live responses, end-to-end behavior, or actual agent behavior. `code2skill-review-flow` reviews Skill invocation chains, stopping points, and non-global prerequisites. Live-interface validation requires explicit authorization and is disabled by default; write interfaces are never called automatically. Capabilities that cannot be proven offline must be marked `requires-host-integration`, without fabricated evidence.

Organize generated-package tests by goal: one normal representative path for each complex goal; cross-tool handoff tests showing upstream results entering downstream calls; bypass counterexamples proving zero external writes for runtime hard boundaries. Use anonymous, cross-domain synthetic cases. Anonymization must preserve real method/path/query/body/service/method/destination/key field names. Cross-tool tests start from anonymous upstream responses, switch calls between two different anonymous records, and verify that downstream wire data retains no old values. Assert exact wire output for deterministic transformations. Derive expected values from source; do not merely hand-fill the final correct parameters.

### 9. Delivery Report

Report only the states the user needs: generated capabilities, whether offline tests passed, whether a live environment was called, installation/registration/deployment status, and specific limitations. For a package marked `requires-host-integration`, report: “Static structure and MCP discovery passed; runtime validation is incomplete.” Do not conflate “files generated,” “MCP starts,” “live business behavior verified,” and “deployed.”

`code2skill-generate` does not itself claim that the main workflow is complete or that source semantics are exact. Use `code2skill-review-flow` for an independent judgment of whether primary goals and representative standard paths are closed. Use `code2skill-review-source` for deeper checks of field provenance, deterministic transformations, and critical dependencies.

## Advanced Validation (Explicit Opt-in)

The internal `strict-export-v1` format remains supported for compatibility but is no longer executed by default. Enable it only when the user explicitly requests any of the following: a complete evidence chain, Canonical/Goal Contracts, Host compatibility, a per-capability verification matrix, live receipts, finalization, a complete manifest, an external evaluator, or a compliance/high-risk audit.

The current `strict-export-v1` compatibility contract still emits `zh-CN` Agent-facing documentation. State this boundary before enabling strict mode for a non-Chinese request. Do not present the English default templates as proof that strict output is bilingual.

Do not upgrade to strict mode merely because the user says “stable,” “usable,” or “complete.” Before upgrading, explain that it expands source scope, artifacts, and elapsed time.

Strict mode continues to use:

- [vnext-architecture.md](references/vnext-architecture.md)
- [capability-model.md](references/capability-model.md)
- [evidence-and-discovery.md](references/evidence-and-discovery.md)
- [mcp-tool-design.md](references/mcp-tool-design.md)
- [observed-skill-design.md](references/observed-skill-design.md)
- [documentation-contract.md](references/documentation-contract.md)
- [artifact-contract.md](references/artifact-contract.md)
- [verification.md](references/verification.md)
- `scripts/run_pipeline.py`

Existing strict packages and validators remain compatible. Do not mix core and strict files in one directory. When upgrading from core to strict, use a new working directory and add the evidence required by strict mode. Do not present core offline validation as a completed audit.

## Non-negotiable Defaults

- Do not generate a page-level mega-tool or mechanically create one tool per interface.
- Keep input Schemas open with only the minimum transport structure MCP requires. Do not block the agent early with business types. Do not declare output Schemas by default.
- Do not reuse semantics merely because fields share a name. Public names express business meaning; map internally to real invocation fields.
- Do not freeze a dynamic catalog into enums from one sample.
- Do not upgrade ordinary backend business rules into a fabricated hard Workflow.
- Do not turn a shared capability into an unproven global prerequisite.
- Do not generate an arbitrary `call_api` escape hatch or a local upload path constructed by the agent. An attachment path whose provenance and accessibility are explicitly guaranteed by the Host may be accepted as business upload input.
- Do not rewrite invocation results, HTTP responses, low-level exceptions, or critical decision fields into Code2Skill's own business conclusions.
- In HTTP scenarios, do not expose the business API base URL as a tool parameter; in other scenarios, do not expose business service connection configuration as a tool parameter. Never hard-code test, staging, or production defaults. The Consumer Host injects configuration explicitly per service.
- Do not use generated code or its own green tests to prove that the main workflow is complete or source semantics are correct. Delegate those conclusions to the independent review Skills.
- Do not access live business environments during default validation.
- Do not claim that installing a Skill means MCP is registered, authenticated, validated, or deployed.
