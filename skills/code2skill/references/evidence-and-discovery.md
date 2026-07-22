# Evidence and discovery

## Capability surface and evidence priority

For a client feature, first inventory the backend APIs the client actually calls. That observed API set defines the candidate execution surface; Tool boundaries are still chosen by business value rather than one-request-equals-one-Tool. Do not add a backend-internal method, controller action, service function, or persistence operation merely because source search finds it. Add a capability outside the client-observed surface only when the user explicitly expands scope or another authorized public entry surface proves it belongs.

After the surface is established, prefer stronger, closer-to-runtime evidence when resolving each contract fact:

1. executable tests and protocol contracts;
2. executable transfer contracts and validation, including but not limited to OpenAPI, GraphQL, Proto, request/response types, validators, serializers, or runtime parsing;
3. client API adapters and their exact request/response transformation, which prove what the client actually invokes;
4. authorization, application orchestration, transaction, business-rule, external-call, and persistence code, which supplement and qualify the observed API contract;
5. routes, components, labels, and result rendering;
6. comments, prose documentation, and naming;
7. model inference.

Contradictions must remain visible. Do not silently choose a convenient source.

This ranking does not mean every server-side business rule must be duplicated in the generated Function. The real target API remains authoritative for ordinary eligibility and business acceptance. Backend evidence is used to refine the client-visible transfer contract, especially request/response types, nullability, useful errors, and truly non-bypassable identity, idempotency, confirmation, provenance, or unknown-outcome constraints.

Keep backend implementation details subordinate to the client-observed boundary. A hidden cache refresh, cleanup, reissue, persistence step, or other internal side effect does not by itself add a Tool, split a Tool, or override the operation semantics that the public client/API contract exposes. If such an implementation detail could materially change retry safety but no stable public contract proves how Consumers should handle it, record the uncertainty for review instead of inventing a new client capability or Host Guard.

This ranking describes semantic evidence, not required language or architecture layers. A project may express all of these roles in functions, decorators, configuration, protocol files, generated code, message handlers, or dynamic objects without using names such as DTO, Controller, or Service.

## Authorized source topology

Before tracing, create `source-topology.json` from the roots the user or workspace explicitly authorizes. Include every accessible frontend, backend, contract, test, or other relevant root, plus any supplied root that could not be accessed. Do not discover additional repositories by scanning the whole machine.

For every root record:

- a stable `sourceId` used by evidence references;
- its execution-time path and evidence role;
- whether it was accessible;
- which semantic roles were searched and found;
- which expected roles or proofs remain missing.

One repository may contain many roles, and one role may span several repositories. The role label never determines a fixed folder layout.

## Trace checklist

For a client-visible feature, inspect:

- entry route, navigation, feature flag, role gate, and tenant gate;
- page, drawer, modal, table, form, row action, and shared components;
- field labels, option sources, default values, validation, and dependencies;
- visibility/disabled conditions and confirmation behavior;
- state transitions, caching, pagination, sorting, filtering, and retries;
- API client calls, headers, tokens, request IDs, and response transformation;
- the exact set of backend APIs reached from the scoped feature, including conditional branches, and the backend symbols that are outside that call graph;
- server entry points, authentication, authorization, tenancy, validation, application orchestration, business rules, external calls, and persistence;
- tests covering success, failure, boundary, and permission behavior.

Use repository search and symbol-aware tooling already available to the coding Agent. Do not require a custom AST scanner.

## Evidence record

Record enough detail for another reviewer to re-find the fact:

```json
{
  "evidenceId": "ev-client-search-request",
  "sourceId": "client",
  "locator": "src/features/knowledge/search.ts#searchKnowledge",
  "semanticRole": "request-construction",
  "assertionLevel": "fact"
}
```

This is the exact `canonical-contract.json.evidenceCatalog[]` shape, not a parallel discovery-only record. `evidenceId` is stable within the contract. `sourceId` names one authorized topology root. `locator` combines a path relative to that root with a stable symbol or other source-local locator. `semanticRole` explains the responsibility the evidence proves, and `assertionLevel` is `fact`, `inference`, or `unknown`. Line numbers are optional because they drift. Absolute machine paths may help the Producer during execution but do not belong in the portable evidence record.

Material Canonical Contract facts and Feature Context rows cite `evidenceId` values from this catalog. If two roots disagree about a required field, value domain, failure rule, or side effect, preserve both evidence IDs in the conflict and explain why one source is authoritative. An unresolved conflict is not a license to choose the easier implementation.

Infer transfer types from contracts rather than samples. Prefer executable protocol/request/response schemas, validators, serializers, runtime parsers, and the client's actual request/response adapter. A live payload is a verification vector, not a type declaration: one observed `null` must never narrow a field that source contracts allow to be a string. Keep absence and nullability separate—an optional field is omitted from an object's `required` list, while a nullable value uses the portable union of its non-null type and `null`. When authorized sources still cannot decide a material type, preserve the wider source-compatible Schema and record the uncertainty instead of guessing a narrower type.

Likewise, distinguish an observed acquisition path from API requiredness. For any structurally optional input (`required: false` with no `requiredWhen`) supplied by an observed upstream Tool, require the matching handoff and graph edge to be optional/non-hard even when the information class is derived or dynamic. Record `targetRequiredness.status: proven-optional` only when executable evidence proves omission is allowed. Otherwise record `status: unproven`, bind `normalProvider` exactly to the observed upstream Tool strategy, and cite fact-level request/call or behavior-test evidence from the feature boundary's primary source for that normal acquisition path; supplementary backend evidence and a transport contract alone cannot prove it. Do not mark the downstream field required solely because the current UI always fills it. Let the target API make the final acceptance decision and preserve its structured business error. The generated Skill should say, in business-specific names, “normally obtain this value from the observed provider first; whether omission is accepted is decided by the target API.” The derived verification matrix surfaces the unresolved decision without blocking otherwise valid backend-authoritative execution, and the minimum behavior checks exercise omission through a controlled target-API vector.

## Operation-bound fact evidence

An evidence item proves only the semantic fact and operation to which it is attached. Do not treat “the API exists,” a route entry, a field label, or evidence from a neighboring operation as proof of an executable contract. At minimum:

- read `evidenceCoverage` contains exactly `sideEffect`; write coverage contains exactly `sideEffect`, `backendContract`, `authorization`, `validation`, `idempotency`, and `unknownOutcome`. Every category is fact-level, cites evidence from an authoritative source for that exact operation, and uses a semantic role appropriate to the category; `declaredSideEffect` equals the Capability effect;
- every HTTP step cites fact-level request-construction, serialization, transport-contract, or behavior-test evidence; each exact request binding cites request-construction, serialization, or transport-contract evidence;
- every public output and `successRule` cites fact-level response-consumption, serialization, transport-contract, behavior-test, or failure-test evidence for the actual response;
- every conditional rule cites fact-level validation, business-rule, transport, request-construction, or behavior-test evidence;
- every dynamic scope/freshness policy and Goal `reuseWhile` claim cites fact-level evidence that proves that exact provenance, scope, invalidation, or reuse boundary.

Place the references on the exact Capability, step, binding, output, condition, or policy record they support. Generic capability-level references may aid discovery, but they cannot replace these operation-bound facts or be borrowed to make another operation look complete.

## Frontend-only boundary

Frontend code can strongly support UI purpose, field semantics, option sources, visible conditions, request shape, and observed sequencing. It usually cannot prove server authorization, transactionality, idempotency, financial consequences, tenant isolation, or compensation.

With frontend-only evidence, or whenever an equivalent authoritative execution boundary is unavailable:

- generate Feature Context;
- generate read-only capabilities when their implementation is safe and real;
- generate the source-proven Function/MCP contract while marking unproven safety facts and capability state honestly;
- keep a write at `requires-review` when authorization, material side effects, idempotency, confirmation, or unknown-outcome behavior cannot be established;
- do not claim production-safe mutations or invent hidden business rules;
- state what backend evidence would close each unknown.

Do not block a client-observed API merely because every ordinary server validation branch is not locally available. Preserve the server as the authority and expose its business rejection through a structured Tool error. Conversely, a visible client-side check does not justify inventing a hard runtime Workflow unless source evidence proves bypass would violate a non-bypassable safety, transaction, identity, provenance, or at-most-once rule.

If a dynamic catalog is only observed from one fixture, user, tenant, environment, or timestamp, record it as a sample. Do not promote those values into a stable closed enum without executable evidence that the domain is static.

## Avoid false positives

- A field name does not prove its business meaning.
- A button does not prove the backend capability exists or is authorized.
- A hidden UI action does not prove the API is disabled.
- A request appearing in one path does not prove it is mandatory in every path.
- Similar labels do not prove two actions share a contract.
- A backend method outside the scoped client's actual API call graph does not prove it belongs in the generated capability surface.
