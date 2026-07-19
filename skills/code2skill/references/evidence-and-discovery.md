# Evidence and discovery

## Evidence priority

Prefer stronger, closer-to-runtime evidence:

1. executable tests and protocol contracts;
2. executable transfer contracts and validation, including but not limited to OpenAPI, GraphQL, Proto, request/response types, validators, serializers, or runtime parsing;
3. authorization, application orchestration, transaction, business-rule, external-call, and persistence code;
4. client API adapters, state, validation, and control-flow code;
5. routes, components, labels, and result rendering;
6. comments, prose documentation, and naming;
7. model inference.

Contradictions must remain visible. Do not silently choose a convenient source.

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

## Frontend-only boundary

Frontend code can strongly support UI purpose, field semantics, option sources, visible conditions, request shape, and observed sequencing. It usually cannot prove server authorization, transactionality, idempotency, financial consequences, tenant isolation, or compensation.

With frontend-only evidence, or whenever an equivalent authoritative execution boundary is unavailable:

- generate Feature Context;
- generate read-only capabilities when their implementation is safe and real;
- draft write contracts as `requires-review` when necessary;
- do not claim production-safe mutations or invent hidden business rules;
- state what backend evidence would close each unknown.

If a dynamic catalog is only observed from one fixture, user, tenant, environment, or timestamp, record it as a sample. Do not promote those values into a stable closed enum without executable evidence that the domain is static.

## Avoid false positives

- A field name does not prove its business meaning.
- A button does not prove the backend capability exists or is authorized.
- A hidden UI action does not prove the API is disabled.
- A request appearing in one path does not prove it is mandatory in every path.
- Similar labels do not prove two actions share a contract.
