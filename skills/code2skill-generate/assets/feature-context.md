# Feature Context: <feature name>

> This is the vNext business-context template. During generation, copy it to `references/feature-context.md`, replace every placeholder with source facts, and remove this note.

<!-- code2skill-capability-contract-sha256:<sha256-after-derivation> -->

Requiredness, types, dynamic value domains, provenance, validity periods, side effects, errors, and runtime policies are defined by the Canonical-derived `references/capability-contracts.json`. This document explains business meaning and cites evidence; it does not create a second, conflicting contract.

## Feature Positioning

<Explain the user problem this business feature solves, its actual `featureSurface.kind`, and its stable identifier. Do not assume it must be a page or route.>

## Typical User Goals

- <An independently completable full or partial goal>

## Capability Sources and Scope

- APIs actually called by the client: <List the real request families and invocation conditions that form the candidate Function/MCP capability surface.>
- Supplementary backend/protocol/test evidence: <Explain which parameters, dynamic values, permissions, side effects, idempotency, or failure rules they verify.>
- Explicit exclusions: <List backend-internal capabilities that the client does not call and that the user did not include by expanding the scope.>

<For backend-only, RPC, message, worker, or another type of feature, describe the actual public entry point instead. Do not fabricate a client API.>

## Actors and Permissions

| Actor | Permission or role | Assertion level | Evidence ID | Source ID | Portable locator |
| --- | --- | --- | --- | --- | --- |
| <actor> | <permission> | fact/inference/unknown | `ev-<stable-id>` | `<sourceId>` | `<relative-path>#<symbol>` |

## Business Concepts and Field Semantics

| Concept or field | Business meaning | Provenance or value domain | Requiredness/condition | Assertion level | Evidence ID |
| --- | --- | --- | --- | --- | --- |
| <field> | <meaning> | <source> | <required/conditional/optional/derived/dynamic> | fact/inference/unknown | `ev-<stable-id>` |

## Dynamic Dependencies and Invalidation Rules

- <Describe value identity, tenant, session, version, time range, refresh, and invalidation conditions.>

## State and Business Rules

- <States, transitions, conditional requirements, or prohibitions.>
- Ordinary business validation: <Explain that the real backend API is authoritative and how the agent should supply more information after a rejection.>
- Hard constraints: <List only identity, confirmation, provenance, transaction, duplicate-prevention, or unknown-result constraints proven by the Canonical Contract and enforced at runtime; explicitly state none when there are none.>

## Original Client Behavior

1. <Observed entry point, client API call, and condition under which it occurs.>
2. <Optional branch, error handling, or a stopping point for a partial goal.>

<When this feature has no client, explicitly state “No client behavior was found” and record the actual public entry point under “Capability Sources and Scope.”>

## Results and Failures

- Success, empty results, and partial results: <Explain the return semantics.>
- Input/structural errors: <How to correct them.>
- Business rejection: <Original error code/message/field details and reasonable guidance.>
- Permission, upstream/network, and response-contract errors: <Whether to retry and when to stop.>
- Unknown write result: <How to stop and reconcile without automatically retrying.>

## Related Capabilities

- `<tool-name>`: <Independent value, read/write classification, primary input provenance, output, and optional handoff.>

## Unknowns

- <Unknown item, impact, required evidence, or capability not generated in this run.>

## Evidence Index

| Evidence ID | Source ID | Semantic role | Assertion level | Portable locator |
| --- | --- | --- | --- | --- |
| `ev-<stable-id>` | `<sourceId>` | <semantic-role> | fact/inference/unknown | `<relative-path>#<symbol>` |

Every evidence ID must appear exactly once in `canonical-contract.json.evidenceCatalog`. Do not write absolute machine paths.
