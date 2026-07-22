# Capability modeling specification

## Definitions

| Concept | Code2Skill definition |
| --- | --- |
| Producer | The coding Agent that searches authorized source roots, builds contracts and generates/tests artifacts. |
| Consumer Host | The later Agent runtime that discovers the Skill, interacts with the user and invokes capabilities. It may not have Producer capabilities. |
| Portable Core | Language-, framework-, Runtime- and Host-independent business facts used by every generated delivery surface. |
| Canonical Contract | The single evidence-backed authority for capability inputs, outputs, rules, value domains, execution boundaries, safety policy and verification targets. |
| Goal Contract | The user's outcome, required/conditional/derived/dynamic information, acquisition options and completion predicate. |
| Capability Graph | The handoffs, optional dependencies, stopping points and hard prerequisites between capabilities. It is not automatically a linear workflow. |
| MCP | The protocol through which an Agent host discovers context and invokes external capabilities. |
| MCP Server | A service exposing one or more Tools, Resources, or Prompts. |
| Feature Context | Evidence-backed business knowledge extracted from code: purpose, concepts, fields, states, rules, permissions, failures, and original behavior. It is knowledge, not a fourth MCP primitive. |
| MCP Tool | An independently discoverable and selectable business capability with a stable input/output contract. It may have required preconditions. |
| MCP Resource | Context the application controls and clients may read, such as a dynamic catalog or feature description. |
| Tool handler | The explicit implementation entry point for one public Tool. It may call multiple internal helpers or APIs. |
| Observed Skill | Usage knowledge reconstructed from an existing application flow and grounded in code evidence. |
| Derived Skill | A new composition of existing Context and Tools that is not proven to exist in the source application. |
| Deterministic workflow | Runtime code that enforces ordering, transactionality, safety, or consistency that must not depend on Agent compliance. |
| Runtime Profile | A concrete implementation and packaging choice for the Portable Core, such as the current `node-stdio` profile. |

## Governing principle

MCP Tools answer **what can execute**. Feature Context answers **what the capability means**. Goal Contract answers **what information and conditions complete the user's goal**. Skills answer **when and how capabilities can be selected and combined**. The Consumer Agent decides the composition for the current goal. Runtime code enforces rules the Agent must not bypass.

The Producer's ability to read code or run commands is not part of the generated capability. Consumer requirements must be declared separately and checked against the actual Host.

For a client feature, the APIs actually invoked by that client define the candidate execution surface. Backend, contract, and test code refine those candidates; they do not automatically enlarge the public Tool set. A backend-only operation enters scope only when the user explicitly requests it or another authorized public entry surface proves it belongs to the same feature.

## Capability boundary test

A candidate is a strong Tool when most answers are yes:

1. Does it express a business action or query an Agent can name independently?
2. Can it satisfy a complete partial user goal?
3. Could more than one Skill reuse it?
4. Can its inputs, outputs, failure modes, and side effects form a stable contract?
5. Can mandatory preconditions be checked at runtime?
6. Would exposing it avoid forcing unrelated work?

Split a candidate when it combines independently useful goals, incompatible side effects, unrelated permissions, or optional phases. Merge candidates when separating them exposes unstable implementation detail, creates meaningless intermediate state, or breaks required transactionality.

Co-location is not a merge reason. Two local option catalogs remain separate when callers can ask for either one independently, their values have different business meaning, or they feed different downstream inputs. Do not create aggregate `get_page_options`, `get_form_options`, or similar page-shaped Tools just because the values share a source module or require zero HTTP requests.

## Non-equivalences

Never assume:

- one page equals one Tool;
- one component equals one Tool;
- one function equals one Tool;
- one endpoint or HTTP request equals one Tool;
- a Tool is invalid because it depends on a prior value;
- a static option list must always be a Tool;
- the original client flow is the only valid Tool composition.

One Tool may call several endpoints. One endpoint may support multiple business Tools. Tool boundaries follow business semantics and safe reuse.

Preserve source-level value boundaries after choosing the Tool boundary. Multiple visible controls may populate one authoritative object input, while one visible control may feed several requests. Do not infer Tool input shape from DOM layout alone; trace the client request and authoritative API/schema contract.

## Dependency semantics

“Independently selectable” does not mean “dependency-free.” A detail Tool may require an ID issued by a search Tool; a mutation may require a preview token; a continuation may require a server-issued cursor.

Represent such rules twice when useful:

- describe the dependency in Feature Context and the observed Skill;
- enforce it with schema constraints, signed or opaque values, handler validation, server state, authorization, or a deterministic workflow.

Never rely on prose alone for a non-bypassable rule.

Cross-capability data flow is typed, not descriptive. An upstream strategy, dynamic domain, Goal acquisition source, handoff mapping, observed graph edge, and attachment consumer must resolve the same declared output path and compatible target Schema/cardinality. For `direct`, `select-one`, and `append-to-array` mappings, the Canonical Contract is the only source of truth.

Do not classify every backend rejection as a non-bypassable dependency. Ordinary business eligibility, current availability, and server-owned field validation remain authoritative at the target API and return as structured recoverable errors. Use a deterministic Workflow only when source evidence proves that bypassing an identity, confirmation, provenance, transaction, attachment-source, at-most-once, or unknown-outcome edge would be unsafe or inconsistent.

A deterministic Workflow binding has a source-proven actual value and an expected value from protected runtime state or an immutable constant. Comparing a public argument with a second value derived from that same argument is not enforcement. The protected Guard owns the Canonical projection rules, projects from the exact input and trusted runtime context, and dispatches the same frozen input; caller-projected binding objects and arbitrary verifier callbacks are forbidden.

## Information requirement semantics

Do not require the user to provide every input in the first message. For each goal, distinguish:

- always-required information;
- conditionally required or forbidden information;
- optional information;
- derived information that must come from an exact Capability output or declared trusted Host requirement, never user self-report or an unimplemented local calculation;
- dynamic information scoped to a current identity, tenant, session, version, or validity window and acquired through an exact Capability output or declared trusted Host requirement.

Attachment upload results are also source-defined information. Preserve the target API's URL, file ID, object key, opaque token, or object shape and its proven scope/reuse rules. Do not convert every result into a session-bound single-use grant; add such a Guard only when the source contract proves it.

The Agent should reuse still-valid known information, call safe read capabilities when they can fill gaps, and ask only for missing values that cannot be obtained safely. Report trusted-context acquisition separately from user questions. When several compatible capabilities can satisfy one need, expose one alternative set and choose one compatible provider instead of calling every provider. Recompute the missing set when a condition changes or dynamic information expires. A completion predicate, not a fixed transcript, decides when the goal is ready.

A structurally optional Capability input (`required: false` with no `requiredWhen`) can still have an observed normal provider whether its information class is optional, derived, or dynamic. Keep acquisition guidance separate from target requiredness: every matching handoff and observed graph edge stays optional/non-hard; `targetRequiredness.status: proven-optional` needs fact-level executable evidence that omission is allowed; `status: unproven` names one exact `normalProvider` matching an upstream Tool strategy and needs request/call or behavior-test evidence from the feature boundary's primary source. Supplementary backend evidence and a transport contract alone cannot prove the observed normal path. The Skill recommends the provider without making it a hard prerequisite, and the target API remains authoritative for omission acceptance. The unproven decision appears in the review report and adds a controlled omission behavior vector, but it does not create a Host Guard or automatically block an otherwise valid Capability.

Each `informationNeeds[]` entry is also an executable data contract. It declares a portable `type`; object and array values carry a complete closed Schema. Its `supplies[]` entries map that information to exact required Capability inputs through `{capabilityId, inputName, mappingKind}`, with exactly one mapping per target input across the Goal. The Goal's acquisition source, information Schema/cardinality, mapping kind, and target input source strategy must agree. When one need supplies several inputs, at least one advertised source must be compatible with all targets; trusted Host requirement IDs match exactly, upstream-only opaque values cannot fall back to users, and optional information cannot supply an unconditional required input. Every required or conditionally required input of a Capability participating in the Goal must be covered.

`requiredWhen` conditions resolve paths against the declared information Schemas and exactly match the condition of every Capability input they supply. They may not depend on optional information, themselves, unknown fields, or a cycle in the combined acquisition-provider, supplies, and activation graph. Object-form conditional Capability declarations use the same condition as their linked need, and explicit `conditionalNeedsOnlyWhenActive` is always true. If activation cannot yet be resolved, the Goal remains pending and first acquires the dependency; it must not guess that the conditional item is active or inactive.

`reuseWhile` contains only executable true-valued claims such as `sameSubject`, `sameTenant`, `sameSession`, `samePayloadDigest`, `sameVersion`, `notEdited`, `notExpired`, or `notConsumed`, plus fact-level evidence. Generated Goal-state vectors mark a value obtained in the current acquisition with `{__goalState: true, value, acquiredNow: true}`. A cached value uses the same wrapper with a claim-by-claim `reuseProof`; every true Canonical claim must be proven. A bare `fresh: true` flag is not a substitute for that proof. Values that fail their information Schema or reuse proof remain invalid or missing rather than satisfying the completion predicate.

## Capability graph semantics

Model observed handoffs and dependencies in the Canonical Contract's `capabilityGraph`. A graph edge can describe a reusable handoff, an optional acquisition path, or a hard runtime prerequisite. Only the last category belongs in a deterministic workflow.

Compositions proven in source are `observed`. A new but contract-compatible combination is a `derived composition`; it requires separate verification and must not be described as source behavior. Flexible read-only composition is allowed when authorization and contracts permit it. A derived write composition still needs every original runtime guard.

Dynamic catalogs are not static enums. A set observed for one user, tenant, environment, or time is only a sample unless source evidence proves a stable closed domain.

## Write protection classification

Every write declares one `runtimeProtection.mode`:

- `backend-authoritative`: the client-observed target API owns ordinary business validation; no synthetic preflight or local Workflow is generated.
- `deterministic-workflow`: source evidence proves identity, confirmation, provenance, transaction, single-use, or at-most-once edges that must be guarded before dispatch.
- `unresolved`: the frontend proves a write API exists, but the backend owner, authorization, idempotency, confirmation, or unknown-outcome boundary is not available. This mode is never `ready`, does not guess an owner, and has no Workflow.

Only `deterministic-workflow` capabilities map to `canonical-contract.json.workflows[]` and require a generated Guard.

A deterministic classification also carries closed `runtimeProtection.hardWorkflowEvidence` for three independently reviewable facts: `protectedValueIssuance`, `protectedValueBinding`, and `preDispatchEnforcement`. Each category cites fact-level, operation-bound evidence with a matching semantic role and must be attached respectively to this capability's protected input producer, actual dispatch binding, and current Workflow/constraint enforcement point; a transport contract from a neighboring operation cannot be reused. UI confirmation, a generic POST request, authentication middleware, or non-idempotency alone cannot satisfy these categories. If any category is missing, use `backend-authoritative` for an ordinary API-owned write or `unresolved` when the protection owner itself remains unknown; do not emit a partial Guard.

## Origin and confidence

Mark every workflow as `observed` or `derived`. Mark every material claim as:

- `fact`: directly supported by source, tests, schema, or runtime evidence;
- `inference`: reasonable but not explicitly proven;
- `unknown`: required information is absent or contradictory.

Only observed workflows qualify as source-derived Golden baselines. Derived Skills require separate validation.

## Error semantics

Keep errors useful for progressive recovery. A Consumer should be able to distinguish malformed Tool input, correctable business rejection, authorization/tenancy failure, upstream/network failure, malformed upstream output, and an unknown write outcome. Preserve source error codes, messages, field details, retryability, and outcome certainty when they are available. Do not convert every failure into one prose string, and do not let a business rejection imply that the Skill or MCP transport itself is broken.
