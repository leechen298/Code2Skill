# Code2Skill vNext: Stable Artifact Architecture

## Goals

vNext does not aim to generate more files. It aims to make artifacts more reliable: reconstruct the correct business contract from real code, allow an Agent to progressively obtain information and freely compose capabilities around the user's goal, and ensure that writes and other high-risk actions cannot bypass hard constraints.

A stable artifact should satisfy all of the following:

- **Correct contract**: inputs, outputs, dynamic options, conditionally required fields, failure rules, and side effects all have traceable evidence;
- **Complete capabilities**: queries, calculations, validation, attachments, and submission capabilities required to complete a goal are not accidentally omitted;
- **Flexible interaction**: users do not need to provide all information at once; the Agent asks only for what is currently and genuinely missing;
- **Composable**: capabilities can independently satisfy partial goals or be composed ad hoc with other Tools or Skills;
- **Layered validation**: real backend APIs remain authoritative for ordinary business acceptance rules; only non-bypassable identity, confirmation, provenance, transaction, and duplicate-prevention rules are enforced by the runtime;
- **Honest state**: generation, validation, and host-compatibility status are reported per capability; one successful result cannot conceal other unverified capabilities;
- **Portable**: business understanding does not depend on a particular language, framework, directory convention, or Agent brand.

## Four Layers with Clear Boundaries

```text
Authorized real source code and tests
        ↓
Producer: a programming Agent capable of code search, understanding, editing, and testing
        ↓
Portable Core: language-neutral and host-neutral business and capability facts
        ↓
Runtime Profile: turns the Portable Core into an executable Tool service
        ↓
Consumer Host: Agent host that discovers Skills, interacts with users, and calls Tools
```

### Producer

Code2Skill runs in a programming Agent by default because generation requires reading code, tracing invocation chains, and running tests. The specification depends only on those capabilities, not on any product-specific private commands, memory mechanisms, or interaction model.

The Producer may search only source roots explicitly authorized by the user. It may process frontend and backend code in the same repository, multiple local repositories, independent interface-contract repositories, and test repositories. It must not scan the entire machine to “automatically discover the backend.” If a root is inaccessible or a critical implementation is absent, record the search scope and gap instead of guessing.

For a client feature, the Producer first determines the candidate capability surface from backend APIs actually called by the client, then uses authorized backend, protocol, and test code to complete and cross-check the contract and security semantics. Backend internal methods unrelated to that client invocation chain do not automatically become Functions or Tools merely because they were found. For a backend-only feature explicitly specified by the user, its actual public entry point defines the capability surface.

### Portable Core

The Portable Core is the single source of truth for business facts. It answers: what the feature is, which independent capabilities it contains, what information is required to complete user goals, where that information comes from, which rules must be enforced, and how far the existing evidence proves the result.

The Portable Core contains no assumptions about Node, Python, stdio, a particular MCP SDK, or a particular Agent Host. Nor does it require names such as `DTO`, `Controller`, or `Service`.

### Runtime Profile

A Runtime Profile turns the Portable Core into an executable implementation. A Profile may specify language, SDK, transport, packaging, and static-check surfaces, but it must not alter the business contract.

In vNext, the existing `strict-export-v1` is explicitly the **`node-stdio` strict-audit Profile**: a self-contained Node Function core, the official MCP SDK, Zod, stdio transport, literal per-Tool registration, and a copyable runnable package. It remains supported, but is enabled only when the user explicitly requests complete evidence, Host/runtime validation, or finalization. Ordinary generation uses the compact `core-export-v1` runnable package by default.

vNext no longer preserves a page-shaped primary artifact. Business context is written uniformly to `references/feature-context.md`; `export-profile.json.featureSurface` records the real type and stable identifier. It does not generate `PAGE.md` or use `pageRoute`. Legacy packages may continue to be read for compatibility, but these two legacy fields must not be reintroduced into the vNext contract.

Future Runtime Profiles should reuse the same Portable Core and prove through equivalence tests that inputs, outputs, failures, and hard constraints remain consistent, rather than interpreting the business again.

### Consumer Host

The Consumer Host understands user goals, progressively collects information, selects Skills/Tools, holds trusted identity and session state, requests user confirmation, and presents results. Generated artifacts must not assume that the Consumer has the Producer's code-search, file-reading, or development tools.

Host compatibility is evaluated by capability, not by brand. Declared capabilities include Skill discovery, MCP transport/runtime, authentication injection, trusted confirmation, session state, resolution of approved attachments, and reconciliation of unknown results. The Host supplies only safe attachment references or restricted content; source-proven business uploads are performed by generated Function/MCP Tools. When a required capability is absent, related capabilities should be hidden, disabled, or marked `requires-host-integration`.

## Discover Semantics from Code, Not a Fixed Architecture

Discovery should look for the responsibility performed by code rather than only certain file names. Common semantic roles include:

- user or system entry points;
- request and response data-transfer boundaries;
- input validation, defaults, serialization, and transformation;
- identity, permissions, tenant, and session;
- application orchestration and business rules;
- external APIs, RPC, messaging, or file services;
- persistence and state changes;
- tests, protocols, and runtime behavior.

These responsibilities may appear in any language, function, type, decorator, configuration, protocol file, or runtime code. File names and framework conventions may help locate them, but cannot prove a contract by themselves.

## Multiple Source Roots and Evidence Topology

`source-topology.json` records the roots authorized and actually searched during the current generation. Each root should have a stable `sourceId`, purpose, accessibility status, and search-result summary—for example, client, server, protocol, or tests—but these purposes are evidence roles and do not require a particular directory layout.

Each piece of evidence is relocated using `sourceId + relative path + symbol/localization rationale`. Absolute paths are used only in the current execution environment and do not enter portable artifacts. Inaccessible roots, semantic roles that were searched but not found, and conflicting facts must all be preserved explicitly.

If a write capability lacks authoritative evidence for authentication, major side effects, idempotency, trusted confirmation, or unknown-result handling, it must not enter the executable `ready` state. If only complete local replication evidence for ordinary business validation is missing, do not guess and generate a prerequisite Guard. Keep the real API authoritative and return its business rejection to the Agent as a structured error.

## Canonical Contract: One Set of Business Facts, Multiple Deterministic Artifacts

`canonical-contract.json` is the single authoritative contract shared by Functions, MCP Tools, Skills, Workflows, and tests. It does not require the target project itself to use a particular Schema or type system.

At minimum, it expresses:

- stable identity, purpose, inputs, and outputs of capabilities;
- static value domains, dynamic value domains, or explicitly unconstrained source shapes for outputs;
- always-required, conditionally required, conditionally forbidden, and cross-field rules;
- sources such as user input, trusted host context, upstream Tools, dynamic queries, or derived calculations;
- identity, tenant, session, version, validity period, and refresh conditions;
- precise requests and success conditions across HTTP, RPC, local, or other execution boundaries;
- failure fields, fixed discriminator values, and minimum usable results;
- side effects, confirmation, idempotency, retry, and unknown-result policies;
- `fact`, `inference`, or `unknown` for every critical conclusion, together with evidence references.

Derivers should generate or verify public inputs, Function validation, MCP Schemas, documentation language, and test vectors from this contract. Any inconsistency across two delivery surfaces must fail; it cannot be explained away manually as “roughly the same meaning.”

Executable facts must bind to the current operation: side effects, HTTP steps and field bindings, outputs and success conditions, conditional rules, dynamic ranges/validity, and reuse policies each reference semantically matching fact-level evidence. Entry-point evidence that proves only that an interface exists, an inference, or evidence for another operation cannot move the current capability into `ready`.

Every output with no parent to inherit from explicitly declares `valueDomain`. `static` contains only `kind/values/evidenceRefs`, and each value satisfies the output Schema. `dynamic` explicitly declares the three booleans `identityScoped/tenantScoped/sessionScoped`, freshness, and evidence; it cannot freeze an option observed once. `unconstrained` contains only `kind` and is used when source proves a type but no closed or dynamic catalog semantics. A nested output may inherit its parent's value domain only when its path actually lies under the declared parent output.

Function and MCP deterministically execute only the proven public contract: basic structure, types, bindings, serialization, security boundaries, and the minimum successful result. Ordinary business rejections returned by the backend should remain machine-distinguishable errors. At minimum, distinguish input structure, business, authorization, upstream/network, response contract, and unknown write result; preserve original error codes, field details, retryability, and result certainty when evidence is available.

Side effects and confirmation use a closed vocabulary: Capability and `operationPolicy.sideEffect` use `read/create/update/delete`; `operationPolicy.confirmation` uses `not-required/trusted-confirmation-required/upload-confirmation-required`. The actual enforcement owner is expressed through Consumer requirements and `workflows[].enforcement.owner`; parallel fields such as `confirmationOwner` are no longer maintained.

When generation is repeated against the same source set and evidence boundary, stable business identities, field semantics, capability boundaries, constraints, and Goals should remain consistent. File order, temporary absolute paths, drifting line numbers, or one-run samples must not change the core contract. If semantics genuinely change, produce a reviewable contract diff rather than silently generating a different interpretation.

## Goal Contract: Collect Information Around Goals

Goal definitions in the Canonical Contract describe the user's intended goals and their completion conditions, then deterministically project to `goal-contract.json`. They do not freeze the original page click order as the only flow.

Each information item should be marked:

- `required`: needed in all cases;
- `requiredWhen`: needed only when the condition holds;
- `optional`: the goal can still complete without it;
- `derived`: may come only from an explicit Capability output or a declared trusted Host requirement; it cannot be self-reported by the user or represented as “local derivation” with no executable contract;
- `dynamic`: must be dynamically obtained through an explicit Capability output or declared trusted Host requirement under the current identity and validity period; it cannot be self-reported by the user or frozen from one response into a fixed enumeration.

The Skill should guide the Consumer to:

1. identify the goal and information the user has already provided;
2. calculate missing items under current conditions;
3. prefer still-valid trusted context and upstream results;
4. call a read-only Tool first when it can obtain the value safely;
5. ask only for information that cannot be obtained automatically and is currently required;
6. recalculate missing items when conditions change or dynamic data expires;
7. enter confirmation or submission only after the completion predicate is satisfied.

When multiple compatible providers exist for the same missing information, Goal state should present them to the Consumer as `one-compatible-provider` choices instead of calling all of them by default. Values available only from trusted Host context should also be reported separately from “ask the user.” If the user supplies everything at once, skip redundant questions; if the user needs only partial results, stop after the partial goal completes.

Each information need declares a type and executable Schema and maps precisely through `supplies` to the inputs of participating Goal Capabilities. Each goal input is supplied by exactly one need within the same Goal. Source, Schema/cardinality, and mapping kind must be compatible. When one need supplies multiple inputs, at least one common source compatible with all targets must exist, and trusted Host requirement IDs must match exactly. An optional need cannot supply an unconditionally required input. `requiredWhen` paths must resolve from these Schemas and be equivalent to the target Capability input condition. The complete dependency graph formed by acquisition providers, supplies, and activation must be acyclic. An object-form conditional Capability reuses the same condition as its associated need, and explicit `conditionalNeedsOnlyWhenActive` may only be `true`. Goal state remains pending while the condition is unresolved. `reuseWhile` accepts only evidence-backed executable true claims: a value just obtained is marked `acquiredNow`, while cached values must each provide `reuseProof`; bare `fresh: true` cannot bypass this requirement.

## Capability Graph and Dynamic Composition

The Canonical Contract's `capabilityGraph` describes available handoffs, optional dependencies, and hard prerequisites among capabilities. It is not a fixed flowchart, and it does not maintain a separate capability-graph file that can drift.

Each capability should declare:

- which user goals it can satisfy independently;
- which inputs it needs and which reusable outputs it produces;
- which outputs can be handed to which downstream inputs;
- when it can be skipped and when execution should stop;
- whether it has side effects;
- which prerequisites are recommendations and which must be runtime-enforced.

The Agent may compose different MCP Tools or Skills ad hoc for the current goal. Compositions observed in source are marked `observed`; contract-compatible new compositions absent from source are marked `derived composition`. Read-only derived compositions may execute when the contract and permissions allow; compositions involving writes still require the same hard constraints and separate validation.

Page controls are not Tool boundaries, and the original page order is not the only valid composition. Tools should be separated by independent business value and safe reuse boundaries.

## Hard Workflows Protect Only Non-Bypassable Subgraphs

Deterministic Workflows are used only for parts with evidence that they cannot be freely adjusted without violating security, transaction, or consistency requirements, for example:

- the server issues an unforgeable validation credential, and source proves that it must exactly match the final request;
- a dynamic selected value must come from a still-valid query under the current identity;
- an upload result must come from an approved attachment;
- trusted confirmation must bind the minimum source-proven fields; session, request digest, validation credential, validity period, or one-time-use semantics are added only when they exist in the real contract;
- a non-idempotent write is dispatched at most once;
- when the result becomes uncertain after dispatch, stop and reconcile instead of retrying automatically.

In vNext, `canonical-contract.json.workflows[]` contains only these proven hard constraints. It must explicitly cover members with non-empty `capabilityIds`, include `entryCapabilityId`, point to the actual enforcement owner, and have runtime guards and bypass tests. Do not hand-write a separate `workflow.json` and create two sources of truth. Each binding specifies the actual source, protected expected source, comparison method, and evidence; the expected value cannot come from the same public Tool parameter. A generic Guard does not execute arbitrary verifier callbacks, preventing hidden network or file side effects before the Guard consumes the operation. A simple write capability without hard constraints may call the real API directly; ordinary business validation failures recover through structured errors, without generating a generic preflight, validation grant, or Workflow. Legacy bundle-only packages continue to use the existing `workflow.json`. If a truly non-bypassable condition can only be written in Skill documentation, the related write path remains `requires-review`.

Every write capability is explicitly classified through `runtimeProtection.mode`: `backend-authoritative` means the real target API owns ordinary validation; `deterministic-workflow` means a proven hard edge must execute before dispatch; `unresolved` means the client invocation is proven but the backend protection boundary is missing. `unresolved` may only be `requires-review` or `blocked`; do not guess the owner, Workflow, or production safety.

## Attachments Are a Complete Capability Chain, Not a URL Field

The attachment model should cover: the Host supplies a user-approved attachment reference or restricted content; the generated business capability obtains upload authorization according to the source contract, performs the upload, obtains a result token, URL, file ID, object key, or object, and binds that result to a downstream request. Upload output, downstream input provenance, typed handoff, observed graph edge, consumer binding, and actual request field must agree. The user must not be allowed to enter a plausible-looking result and impersonate the upload chain. If the input is an opaque authorized reference from the Host, it is only a reference and metadata; the generated implementation must first resolve it into controlled content or a stream through the generic `attachment-resolution` capability, then bind it to the source-proven body/multipart field. It must not upload the authorization object JSON as a file. `attachments.contentBindings` must record this fact item by item as input, resolver requirement, final request step, location, and path, and match every post-resolution binding under `implementation.outputStepId` uniquely and field by field. Every real body/multipart target field must be proven by fact-level request-construction, serialization, or transport-contract evidence and share that evidence with the executable binding; proof only of entry, interface existence, or side effects is insufficient to prove an exact field.

Public Tools may accept only:

- Host-approved attachment references; or
- restricted content plus metadata required by source or deployment boundaries, such as file name, media type, size, and Hash.

The Agent must never be allowed to provide an arbitrary local file path. Code2Skill does not implement messaging channels, file intake/download, or host-specific adapters; those are responsibilities of the external runtime environment. If the Consumer cannot provide an approved attachment, the related goal should be marked `requires-host-integration` or `blocked`, rather than accepting an unproven URL and pretending the chain is complete.

## Skill Installation and MCP Connection Are Separate Stages

Generated Skills should be installable into Consumers that support Agent Skills with `npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y`. This command installs only Skill knowledge files; it does not start or register MCP, and it does not provide authentication or environment variables.

Every vNext package must generate a platform-neutral `MCP-SETUP.md` that separately documents the MCP startup command, command/args/cwd required for Host registration, required environment variables, the authentication-injection boundary, and `tools/list/tools/call` connectivity validation. Installation, MCP connectivity, Host compatibility, and real business validation must be reported separately.

## Host Requirements and Safe Degradation

The Canonical Contract declares the host capabilities required by each capability and deterministically projects them to `consumer-requirements.json`. `host-profile.json` is supplied by the actual host or deployer. `host-compatibility-report.json` compares the two deterministically and reports by capability and goal. This status describes only Host reachability; Canonical `readiness: requires-review` remains expressed by the verification matrix and must not be disguised as `requires-host-integration`:

- `enabled`: the host provides execution and safety guarantees;
- `requires-host-integration`: the business contract is complete, but host bridging is missing;
- `disabled`: the capability should not be exposed in this host;
- `blocked`: source or runtime evidence itself is insufficient.

For example, when trusted confirmation is unavailable, read-only capabilities may remain while final writes that depend on confirmation are disabled. When session state is unavailable, disable non-idempotent flows that bind one-time credentials. When attachment bridging is unavailable, disable attachment-dependent paths. Degradation should be precise to capabilities and goals; the entire Skill need not fail uniformly.

## Per-Capability and Per-Workflow Validation

`verification-matrix.json` records evidence for every capability and hard Workflow instead of replacing all validation with one package-level success state. At minimum, statuses distinguish:

- `generated`: the artifact exists and can be parsed;
- `behavior-verified`: input, output, failure, and composition tests pass;
- `runtime-verified`: a real MCP client/runtime has been invoked;
- `host-verified`: compatibility validation passed under the declared Host Profile;
- `requires-review`: contract or safety proof is insufficient and requires human review or an additional environment;
- `blocked`: a known condition is unmet and the capability is currently unavailable.

One successful invocation of a read-only Tool cannot approve other Tools. When a real write cannot be executed safely, the write capability may remain `requires-review`, but another capability's `runtime-verified` must not override it. Finalization should allow honestly partial usable packages while refusing to mark unverified capabilities as approved.

Validation should also cover different information arrival orders, skipping redundant calls when information is complete, derived composition, expired/wrong-identity/wrong-session/duplicate credentials, bypasses for every hard constraint, attachment chains, unknown write results, and host-capability degradation.

Finalization input reports use `assets/verification-report.schema.json`: each Capability records behavior/runtime/host, and each Workflow records bypass/runtime/host. A passed runtime check must bind the Canonical Tool name and Hashes matching the live input/result. A passed bypass check must prove zero external writes. Live input/result pairs are supplied by Capability ID and may be repeated, but one successful command or one read-only Tool's live result cannot substitute for evidence on other rows.

The minimum validation `checkId` for each Capability is mechanically derived from the contract; handwritten checks may only be appended. A passed phase that omits any applicable check fails. Attachment runtime proof binds precisely to the Canonical `stepId/location/path` and requires the trace digest to agree with the check evidence digest. `hostVerified` is true only when the Host phase passed and compatibility is `enabled`; write capabilities always require this Host validation, and Canonical `requires-review` cannot be rewritten as a host gap.

## Migration Boundary for strict-export-v1

vNext uses incremental migration so currently usable outputs do not suddenly become invalid:

1. The Node/stdio behavior of `strict-export-v1` remains supported and is explicitly named the `node-stdio` Runtime Profile. The vNext documentation tree becomes `references/feature-context.md`, `SKILL.md`, `MCP.zh-CN.md`, and `MCP-SETUP.md`.
2. After Portable Core files are added, the existing `capability-bundle.json` may serve as the Canonical Contract's execution view, but no longer carries every responsibility for Goals, source topology, host requirements, and per-capability validation.
3. Legacy packages remain valid under legacy validators. When `canonical-contract.json` exists and its `schemaVersion` is `vNext`, the package declares vNext and must include the new contracts and pass the new consistency checks.
4. vNext Functions, MCP, documentation, and tests are derived from or checked against the Canonical Contract. A Runtime Profile adds only execution details; it cannot change field names, requiredness, value domains, or security policies.
5. Package-level `approved` gradually migrates to capability-level and Workflow-level statuses. A summary status may still be generated during migration, but it must be computed from all detailed statuses and cannot override them in reverse.
6. Adding a Runtime Profile requires new equivalence validation; do not copy and fork the Portable Core.

## Repository Contamination Boundary

Real project cases are used to validate Code2Skill only outside the repository. The Code2Skill repository may contain only generic specifications, generic implementations, and fictional synthetic tests. It must not copy real-project code, interface paths, field names, enums, business names, logs, secrets, private evaluators, Goldens, or fixtures.

Lessons from real cases must first be abstracted into cross-project rules and then validated with synthetic examples carrying no business meaning. Contamination scanning is a mandatory gate before finalization.
