# Invocation- and Language-Neutral Generation: Upgrade Plan

## Goal

Upgrade Code2Skill from "primarily generating capabilities from frontend HTTP calls" to "generating capabilities from real business invocation entry points found in source code." Users still invoke the same `code2skill-generate` and do not need separate commands for Dubbo, gRPC, Java, Python, or other technologies.

This iteration only strengthens generation rules, artifact selection, and validation criteria. Code2Skill will not develop generic RPC or messaging clients, maintain a framework catalog, or reimplement the original system's business logic.

## Core definition

The business capability remains in the original system. The generated Function is a thin adapter:

```text
Agent
→ MCP Tool
→ generated Function adapter
→ existing HTTP / RPC / SDK / Service / message or task entry point
```

The Function reliably maps the Agent's business-semantic inputs to the original invocation entry point and returns the original result or error to the Agent. It does not copy the business implementation.

Prefer the target project's existing language, dependencies, and invocation mechanism:

- When the generated package can call an existing entry point directly, generate a runnable thin wrapper.
- When the capability must be called inside the original application process, generate a same-language wrapper and MCP entry point suitable for integration into the original project.
- When runtime context, dependencies, or a safe entry point are missing, explicitly mark the capability as requiring integration; do not pass off documentation as a runnable Function.

MCP stdio or Streamable HTTP is the protocol from the Agent to the Tool. It does not mean that the Tool must also use HTTP to reach the business system.

## Development boundaries

- Keep the invocation form: `Use $code2skill-generate to generate capabilities related to <business goal> from <code scope>.`
- Select the invocation mechanism and implementation language automatically from source code; do not add commands such as `dubbo-generate` or `grpc-generate`.
- Do not enumerate rules by language or framework. Identify invocation semantics, not product names.
- Do not automatically expose arbitrary public methods, repositories, message consumers, or scheduled jobs as Tools.
- Do not scan registries, brokers, databases, or an entire machine for capabilities.
- By default, do not connect to real services, start real business applications, publish messages, or execute jobs.
- Do not add heavyweight contracts, capability graphs, audit reports, or new default delivery documents.
- Preserve the existing principles of goal decisions, Tool splitting, open schemas, source binding, deterministic transformations, and Agent leadership.
- In this iteration, keep `strict-export-v1` compatible but do not expand it into a multi-language execution platform.

## Phase 1: Discover capabilities through real invocation entry points

Update `code2skill-generate` and both Review Skills.

Use this discovery order consistently:

1. Start from the business goal, code scope, entry symbol, or caller specified by the user.
2. When a client or Consumer exists, prefer tracing the real invocation chain from it.
3. When no client exists, start only from a public business entry point that the user specified and the source code proves callable.
4. Trace input sources, client or Consumer normalization, deterministic transformations, return values, side effects, and stop boundaries.
5. Stop when the contract is sufficient for generation; do not traverse every implementation and downstream dependency by default.

Use neutral concepts for the invocation contract held in working memory:

- invocation target and operation;
- parameters, message payload, or task payload and their sources;
- who supplies runtime context such as identity, tenant, and transaction;
- synchronous return, error, publication receipt, task ID, or status query;
- read/write side effects, idempotency, and unknown-outcome boundaries;
- how the runtime integrates with the original capability.

HTTP method/URL/query/header/body, RPC service/method/arguments, and messaging destination/key/payload are only technology-specific representations of this contract in different projects.

## Phase 2: Let the Producer select the thinnest implementation

The Producer selects one of the following approaches from the target repository's existing implementation. Code2Skill does not ship framework-specific generators.

### Approach A: Direct out-of-process invocation

When the original capability already has an invocable HTTP, RPC, gRPC, SDK, or command client, the Function reuses that client and wraps only parameter mapping, deterministic transformations, authentication integration, and result propagation.

### Approach B: Wrapper inside the original runtime

When the original capability depends on dependency injection, transactions, interceptors, thread context, or an in-application Service, generate a thin wrapper and MCP entry point in the original project's technology stack. Do not move the business method into a new Node package and pretend it is semantically equivalent.

### Approach C: Host integration required

If no safely invocable client or runtime context is available, preserve the provable Skill and Tool contract plus integration instructions, and clearly state that the capability is not yet runnable. Do not generate a universal `call_rpc`, `invoke_method`, or `publish_message` Tool, and do not claim that deployment is complete.

Regardless of the approach:

- Design Tools around business decision boundaries, not as a mechanical mapping of interfaces or methods.
- Do not require the Agent to assemble protocol wire representations manually.
- Return original-system results and errors to the Agent as faithfully as possible; do not impose a guessed, uniform definition of business success.
- For asynchronous publication or job enqueueing, report only "accepted" or "enqueued"; generate a separate status-query capability only when the source provides one.
- Deployment supplies runtime configuration. Do not expose it as user business input or hard-code test, staging, or production values.

## Phase 3: Relax language assumptions in artifacts and validation

Keep the logical composition of default artifacts unchanged: Function, MCP, Skill, tests, and installation instructions. File extensions, dependency manifests, and startup commands may follow the target technology stack.

Update the following consistently:

- In `SKILL.md`, treat `fetch`, HTTP status, and API base URL as HTTP-specific rules rather than definitions of every Function.
- In `MCP-SETUP.md`, document the actual runtime language, dependencies, startup command, runtime configuration, and unmet requirements.
- Keep directory, Skill, MCP discovery, and safety-boundary checks in the validator, while delegating language-specific builds and tests to controlled, known profiles.
- When no corresponding profile exists, run the target project's existing offline tests or explicitly mark automated runtime validation as incomplete; never fabricate a pass.
- Upgrade Review from "compare the final HTTP request" to "compare the final business invocation," while continuing to verify parameter sources, order, transformations, context, and result boundaries.

## Phase 4: Anonymous validation and representative regeneration

Add a small number of anonymous tests organized by invocation semantics; do not build a framework combination matrix:

1. Synchronous request-response: existing HTTP behavior must not regress.
2. Synchronous method invocation: use anonymous interfaces, DTOs, and Consumers to verify service/method identity, parameter order, deterministic transformations, and error propagation.
3. In-application Service: verify that the Producer selects an original-runtime wrapper instead of copying the business implementation.
4. Asynchronous submission: verify that a publication receipt or task ID is not presented as business completion.
5. No usable runtime boundary: the output must say that integration is required and must not generate a falsely runnable capability.

Then regenerate from two representative code scopes:

- one existing HTTP/frontend case, to confirm that the previous capability and artifact size have not materially regressed;
- one non-HTTP invocation case, preferably in a different language, to confirm that the same command can generate a reasonable thin wrapper or an honest integration boundary.

All tests are offline by default and must not call real business APIs, RPC services, brokers, jobs, or databases.

## Acceptance criteria

- Users continue to use one `code2skill-generate` and need not understand framework-specific commands.
- The Generator no longer equates a Function with JavaScript `fetch`.
- The Producer can discover business capabilities from real Consumers, SDKs, public Services, or task entry points.
- Generated code reuses original-system capabilities, does not copy business implementations, and does not bulk-expose internal methods as Tools.
- Runnable artifacts provide genuinely executable thin wrappers; non-runnable artifacts accurately describe missing integration requirements.
- The main flow, tests, and artifact size of an existing representative HTTP case show no material regression.
- At least one anonymous non-HTTP case passes offline generation and Review.
- The README, generated-artifact documentation, three Skills, templates, and related tests express the same boundaries.
- The full test suite and `git diff --check` pass, with no real business invocation.

## Stop conditions

Stop this iteration once the acceptance criteria above are met. Do not continue pursuing:

- exhaustive coverage of every language, RPC framework, messaging framework, and job framework;
- generic invocation middleware inside Code2Skill;
- automatic solutions for registries, service governance, transactions, identity, or deployment platforms;
- dedicated commands and templates for every technology stack;
- proof that generated artifacts can be deployed directly in every project.

Continue iterating only on general gaps that recur in real use. Problems specific to one framework or one project should first remain with the generating Agent and the user rather than becoming default Code2Skill complexity.

## Suggested modification scope

- `skills/code2skill-generate/SKILL.md`
- `skills/code2skill-review-flow/SKILL.md`
- `skills/code2skill-review-source/SKILL.md`
- `skills/code2skill-generate/assets/core-feature-context.md`
- `skills/code2skill-generate/assets/core-MCP-SETUP.md`
- `skills/code2skill-generate/scripts/validate_core_export.py` (only profile or language-neutral adjustments that are necessary)
- `README.md`
- `docs/generated-results.md`
- anonymous tests and fixtures

During development, preserve the user's existing uncommitted work. Do not modify articles or images, and do not commit or push unless the user requests it separately.
