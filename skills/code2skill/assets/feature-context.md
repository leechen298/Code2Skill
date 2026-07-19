# Feature Context: <feature name>

## Purpose

<What user problem this feature solves.>

## Actors and permissions

| Actor | Permission or role | Assertion level | Evidence ID | Source ID | Portable locator |
| --- | --- | --- | --- | --- | --- |
| <actor> | <permission> | fact/inference/unknown | `ev-<stable-id>` | `<sourceId>` | `<relative-path>#<symbol>` |

## Domain concepts and field semantics

| Concept or field | Business meaning | Source or allowed values | Assertion level | Evidence ID | Source ID | Portable locator |
| --- | --- | --- | --- | --- | --- | --- |
| <field> | <meaning> | <source> | fact/inference/unknown | `ev-<stable-id>` | `<sourceId>` | `<relative-path>#<symbol>` |

Every evidence ID above must exist exactly once in `canonical-contract.json.evidenceCatalog`. Never use an absolute machine path or a path without its authorized `sourceId` in a multi-root feature.

## States and business rules

- <state, transition, eligibility rule, or dependency>

## Original client behavior

1. <observed step and when it occurs>
2. <optional branch or stopping point>

## Results and failures

- <how to interpret success, empty results, partial results, and errors>

## Related capabilities

- `<tool-name>`: <independent value>

## Unknowns

- <unknown, impact, and evidence needed to resolve it>
