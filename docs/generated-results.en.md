# Generated Package Structure and Design Principles

By default, Code2Skill generates the runnable content required to complete the main business goals rather than producing a complete source-code audit archive. Internally, the program still uses `core-export-v1` to identify this directory format; ordinary users do not need to understand or provide this name.

## Capability Discovery

Candidate capabilities come from business invocation entry points that actually exist in the source code. For client-side features, discovery primarily follows calls actually triggered by the client/Consumer. When no client exists, discovery starts from the public API, RPC, Service, message, or task entry point specified by the user. Backend internal methods that the page does not call, arbitrary public methods, Repositories, message consumers, or scheduled tasks are not automatically exposed as Tools merely because they were found during search.

Within the authorized scope, source code, protocols, and tests are used by default only to complete:

- transport structures such as public Requests/Responses, interface definitions, Service method signatures, and message/task contracts;
- authentication and identity boundaries;
- dynamic value domains and enums;
- attachment upload interfaces directly used by the client;
- explicit contradictions with the client contract.

Discovery stops once the public contract is sufficient; it does not trace the complete Service, side effects, or internal validation. When source code is unavailable, Code2Skill may generate an honest partial package from proven invocation contracts while explicitly documenting unknowns and runtime boundaries.

Source discovery is not tied to a language or fixed architecture. `DTO`, `Request`, `Response`, `Schema`, function parameters, protocol definitions, and runtime objects may all carry data transport contracts; their names are only discovery clues.

## Goals and Tools

The page, directory, or interface specified by the user is only the search scope. Code2Skill first identifies the main user goals within it that can be completed independently:

- a single goal produces a root `SKILL.md`;
- multiple goals each produce `skills/<goal>/SKILL.md`;
- multiple Skills may share the same set of atomic Function/MCP capabilities;
- each Skill describes only its own invocation chain, and a shared Tool does not automatically become a global prerequisite.

The number of Tools is determined by independent business semantics, invocation value, contract stability, and safe reuse boundaries—not mechanically by the number of pages, interfaces, or functions.

## Generated Directory

The logical components of the default output remain unchanged. Exact file extensions, dependency manifests, and startup methods follow the runtime profile of the target technology stack. The current default `core-export-v1` format is implemented by the `node-stdio` profile:

```text
generated/code2skill/<feature-id>/
├── SKILL.md                  # One main goal
├── skills/                   # Replaces the root SKILL.md for multiple goals
│   ├── <goal-a>/SKILL.md
│   └── <goal-b>/SKILL.md
├── MCP-SETUP.md
├── package.json              # node-stdio profile example
├── function-core/index.mjs   # node-stdio profile example
├── mcp-tool/index.mjs        # node-stdio profile example
├── portable-agent-result.mjs # node-stdio profile helper for generic result projection
│                              # (readHttpResponse/httpResultFromError are HTTP-only)
├── tests/*.test.mjs          # node-stdio profile example
└── references/
    └── feature-context.md    # Generated only when complex business context requires it
```

The root `SKILL.md` and `skills/*/SKILL.md` are mutually exclusive. In a multi-goal package, references required by each Skill must be placed under that Skill's own `references/` directory and must not depend on parent-directory files that will not exist after installation.

The generated directory does not carry duplicate Contracts, evidence directories, Host reports, validation matrices, receipts, or manifests. The `code2skill.profile=core-export-v1` field in `package.json` exists only so the validator can identify the package format.

## Three Output Approaches

The Producer selects one of the following approaches based on the target repository's existing implementation. Code2Skill does not ship framework-specific generators:

- **Approach A: directly runnable thin wrapper.** When the existing capability already has a callable HTTP, RPC, gRPC, SDK, or command client, the Function reuses that client and wraps only parameter mapping, deterministic transformations, authentication integration, and result delivery.
- **Approach B: wrapper inside the original runtime.** When the existing capability depends on dependency injection, transactions, interceptors, thread context, or an in-application Service, generate the thin wrapper and MCP entry point inside the original project's technology stack. Do not move business methods into a new Node package and pretend that the semantics remain equivalent.
- **Approach C: host integration required.** When no safely callable client or runtime context exists, preserve the provable Skill and Tool contracts plus integration instructions, and explicitly mark `requires-host-integration`. Do not generate universal `call_rpc`, `invoke_method`, or `publish_message` Tools, and do not claim deployment is complete.

Asynchronous publication or task enqueueing means only “accepted/enqueued.” Generate a separate status-query capability only when such a query exists in the source. Do not present a publication receipt or task ID as business completion.

## Request Semantics

The Function is responsible for request construction that the source code directly proves:

- trace field origins through “interface/invocation response → page or caller state → final invocation”; do not infer semantics from identical field names;
- when the currently selected result is expanded as a full row or merged into the downstream request through multiple fields, the Function exposes a semantically clear selected-record input, and the Skill's standard example passes that record truthfully; do not simplify it to an ID without evidence;
- fields used for queries and fields used for final writes receive distinct public names, then map internally back to API fields;
- deterministic transformations such as time composition, ISO formatting, array/URL composition, and display-value cleanup belong in the Function;
- a shared capability without direct invocation-chain evidence must not be elevated into a prerequisite for every write operation.

The real backend invocation entry point is the authoritative boundary for ordinary business validation. Function/MCP does not duplicate the complete backend rule set. The Agent asks follow-up questions, corrects, continues, or stops based on the actual response.

When selected-record handoff exists, offline tests must use at least two distinct anonymous records and switch between them once, confirming that all request fields switch with the current selection and that no value from the previous record remains. This test verifies only request construction proven by the source; it must not expand into a matrix of backend business rules.

## Runtime Addresses and Environments

A business API base URL is deployment configuration, not a user business parameter. In other scenarios, the equivalent concept is called “business service integration configuration”:

- use a semantically clear environment variable for each independent service;
- the Consumer Host explicitly selects and injects the actual address;
- the Function does not default to test, staging, or production environments found in source code;
- when a required base URL is missing, stop before the request instead of silently falling back;
- Tool parameters carry only business inputs and must not allow the Agent to specify a request domain at runtime;
- offline tests use `.invalid`, a local Mock, or an injected fake base URL.

Environment addresses found in source may be documented in `MCP-SETUP.md` for deployment operators, but this does not mean that the environment has been configured, connected, or verified. Public third-party endpoints fixed by protocol, and upload, callback, or presigned addresses returned by a backend runtime, are not hidden defaults for the business service.

## Schemas and Responses

Input Schemas describe known parameters to the Agent. By default, they:

- use open objects;
- represent business fields as permissive values with descriptions;
- do not block early because of common number/string, `null`, missing-field, or extra-field variations;
- allow the Function to place only parameters with source-proven destinations into the real request.

By default, no output Schema is declared, preventing strict validation from blocking a real response before it reaches the Agent.

In HTTP scenarios, a `fetch`-based Function returns the following for any HTTP status:

- `httpStatus`;
- the complete `bodyText` without business-level interpretation.

If the underlying client throws a response-bearing exception for 4xx/5xx, Code2Skill also attempts to recover the status and response body as an ordinary Tool result. Code2Skill does not add success, failure, retry, or write-outcome judgments on the Agent's behalf. Only underlying exceptions with no response at all are delivered through MCP `isError` with serializable information.

## Attachment Boundaries

Attachment intake belongs to the Consumer Host. Code2Skill generates only source-proven business upload and downstream binding:

- prefer opaque references such as `attachmentRef` supplied by the Host;
- use a runtime-injected `hostFilePath` only when the Host explicitly guarantees its origin and accessibility;
- Function/MCP handles business STS, presigning, object-storage upload, and business URL binding;
- Code2Skill does not implement chat-message intake, file download, or a generic Host sandbox.

If the source proves only that upload credentials can be obtained, but does not prove that upload and binding can be completed, the goal must be explicitly marked as not closed. It must not accept a user-reported URL and pretend the operation is complete.

## Feature Context

`PAGE.md` is not generated by default. An optional `references/feature-context.md` is generated only when business background, dynamic information, cross-goal shared concepts, or important boundaries cannot be expressed clearly in the Skill/Function.

It provides business-understanding context; it is not a primary artifact, execution contract, or page-specific document.

## Offline Validation

```bash
cd generated/code2skill/<feature-id> && npm install
cd -
python3 skills/code2skill-generate/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

The validator checks:

- the minimum directory structure and dependency declarations;
- JavaScript syntax;
- MCP `initialize + tools/list`;
- deterministic offline tests included in the package.

By default, the validator sanitizes business credentials, does not call real interfaces or arbitrary lifecycle commands declared by the candidate, and does not claim business correctness. Tests must mock external requests. If the package marks `code2skill.requiresHostIntegration` in `package.json`, the validator reports: “Static structure and MCP discovery passed; runtime validation is incomplete.”

`code2skill-generate` does not independently claim main-flow completeness or source-level precision. Use `code2skill-review-flow` when a completeness judgment is required, and use `code2skill-review-source` for high-value or suspicious goals. Both Reviews are read-only and offline by default.

## Repository and Privacy Boundaries

The Code2Skill repository stores only generic specifications, templates, generators, validators, and fictional synthetic tests. The following target-project content may be read only outside this repository, during user-authorized generation or evaluation:

- private source code, interface paths, fields, enums, and business names;
- logs, real responses, runtime addresses, and business constants;
- private evaluators, Goldens, fixtures, source snapshots, and recording evidence;
- tokens, Cookies, secrets, sessions, or other runtime credentials.

Do not copy this content back into the repository to reproduce a real case. Reusable conclusions must first be generalized into cross-project rules, then covered by regression tests using data with no business meaning.
