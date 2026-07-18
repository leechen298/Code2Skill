# Evidence and discovery

## Evidence priority

Prefer stronger, closer-to-runtime evidence:

1. executable tests and protocol contracts;
2. OpenAPI, GraphQL, Proto, DTO, or validation schemas;
3. authorization, controller, service, transaction, and domain code;
4. client API adapters, state, validation, and control-flow code;
5. routes, components, labels, and result rendering;
6. comments, prose documentation, and naming;
7. model inference.

Contradictions must remain visible. Do not silently choose a convenient source.

## Trace checklist

For a client-visible feature, inspect:

- entry route, navigation, feature flag, role gate, and tenant gate;
- page, drawer, modal, table, form, row action, and shared components;
- field labels, option sources, default values, validation, and dependencies;
- visibility/disabled conditions and confirmation behavior;
- state transitions, caching, pagination, sorting, filtering, and retries;
- API client calls, headers, tokens, request IDs, and response transformation;
- backend routes, authentication, authorization, tenancy, validation, services, and persistence;
- tests covering success, failure, boundary, and permission behavior.

Use repository search and symbol-aware tooling already available to the coding Agent. Do not require a custom AST scanner.

## Evidence record

Record enough detail for another reviewer to re-find the fact:

```json
{
  "path": "src/features/knowledge/search.ts",
  "symbol": "searchKnowledge",
  "reason": "Builds the knowledge search request and maps pagination",
  "classification": "fact"
}
```

Use repository-relative paths. Line numbers are optional because they drift; stable symbols and reasons are preferred.

## Frontend-only boundary

Frontend code can strongly support UI purpose, field semantics, option sources, visible conditions, request shape, and observed sequencing. It usually cannot prove server authorization, transactionality, idempotency, financial consequences, tenant isolation, or compensation.

With frontend-only evidence:

- generate Feature Context;
- generate read-only capabilities when their implementation is safe and real;
- draft write contracts as `requires-review` when necessary;
- do not claim production-safe mutations or invent hidden business rules;
- state what backend evidence would close each unknown.

## Avoid false positives

- A field name does not prove its business meaning.
- A button does not prove the backend capability exists or is authorized.
- A hidden UI action does not prove the API is disabled.
- A request appearing in one path does not prove it is mandatory in every path.
- Similar labels do not prove two actions share a contract.
