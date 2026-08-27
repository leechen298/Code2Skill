# Evaluation of Code2Skill Generated Packages

Evaluation date: 2026-07-25

## Conclusion

This evaluation used the same private, multi-goal client source scope to generate three packages with GPT-5.6 Sol (Ultra mode), Kimi K3 (Max reasoning level), and GPT-5.6 Sol (High reasoning level). The evaluation preserves two independent scoring systems:

| Generation model/runtime configuration | Generation date | Generation time | Main-flow completeness | Business-semantic accuracy | Composite reference score |
|---|---|---:|---:|---:|---:|
| GPT-5.6 Sol (Ultra mode) | 2026-07-24 | 47 min 45 sec | **9.6** | **9.0** | **9.4** |
| Kimi K3 (Max reasoning level) | 2026-07-24 | Approx. 93 min | **9.5** | **8.0** | **8.9** |
| GPT-5.6 Sol (High reasoning level) | 2026-07-24 | 20 min 29 sec | **9.0** | **7.5** | **8.4** |

The composite reference score is calculated as `main-flow completeness × 60% + business-semantic accuracy × 40%`, rounded to one decimal place. The 60/40 weighting reflects the current product priority: first ensure that users can complete the main work, while retaining enough weight to constrain source-semantic accuracy. It is not a third independent evaluation system, nor is it an industry standard applicable to every project.

The main-flow score uses the completeness results that were later recalibrated around whether the user can complete the work. The business-semantic score uses an independent, source-first precision review. The two systems answer different questions, so their scores are not expected to be close. The main flows of all three packages reached code-level basic usability, but none has been validated against real business interfaces or a deployment environment.

Both Codex generations used GPT-5.6 Sol (model ID: `gpt-5.6-sol`): Ultra is a runtime mode that coordinates multiple Agents, while High is a reasoning level. Kimi Code used Kimi K3 (model ID: `k3`) with the Max reasoning level. Model names and runtime configurations are recorded separately to avoid misrepresenting Ultra, High, or Max as model names.

## Generation-Time Methodology

Generation time is measured from the start of the generation task until the corresponding Agent reports that generation is complete and passes that run's offline validation. It includes source reading, Function/MCP/Skill implementation, testing, and correction within that task. It excludes subsequent independent scoring in other tasks, directory renaming, installation, MCP registration, deployment, and real-interface validation.

- GPT-5.6 Sol (High reasoning level) and GPT-5.6 Sol (Ultra mode) use runtimes recorded by their respective Codex tasks: 1,229,306 ms and 2,865,158 ms, displayed as 20 min 29 sec and 47 min 45 sec.
- For Kimi K3 (Max reasoning level), only an observed duration of about 93 minutes was retained in the interface, so it is marked as approximate rather than presenting fabricated second-level precision.
- All three generations occurred on 2026-07-24. Duration depends on model configuration, parallel Agents, dependency installation, source scope, and the number of corrections in that run; it must not be used to infer the models' general speed.

## Privacy Boundary

This report may disclose generation tools, models, and runtime configurations because this information helps explain the generation conditions. Business evidence remains anonymized. The report does not retain or disclose:

- organization, product, page, or business-goal names;
- APIs, fields, enums, business rules, or attachment types;
- private source repositories, directories, file names, code snippets, or local paths;
- accounts, sessions, private prompts, or original candidate-package names;
- credentials, runtime addresses, real responses, or private evaluation evidence.

Publishing model names does not constitute a general capability ranking of model providers. This report compares only these three specific packages generated from the same source scope, and it cannot be used to reconstruct the original business domain.

## Public Report Fields

Future evaluations of this kind should disclose the following whenever possible:

- generation tool, model name, and known reasoning/runtime configuration;
- Code2Skill package Profile, number of delivered files, and effective lines of code;
- the two evaluation questions, their scoring dimensions, composite weighting, and deduction rules;
- evidence priority, independent validation method, and actual execution results;
- whether real interfaces were called and whether Host registration and deployment were completed;
- remaining limitations and states that could not be verified.

The following remain anonymized: business names, source paths, APIs, fields, enums, rules, real responses, credentials, and per-goal business scores. This explains who generated the package, how it was evaluated, and why it received its score without exposing private business information.

## Two Evaluation Systems

### System One: Main-Flow Completeness

This corresponds to the question addressed by `code2skill-review-flow`:

> After receiving user-provided information and runtime-supplied authentication, attachments, and other inputs, can a Consumer Agent with ordinary Tool-calling capability use the generated package to complete the main user goals step by step?

It focuses on whether the work can be completed. If the Agent can ask follow-up questions, correct inputs, or continue based on actual responses, non-blocking expression differences incur only small deductions. Missing required capabilities, inevitably incorrect terminal requests, or erroneous flow blocking receive substantial deductions.

### System Two: Business-Semantic Accuracy

This corresponds to the question addressed by `code2skill-review-source`:

> Do the Function, MCP, and Skill accurately reproduce the interfaces, field origins, deterministic transformations, cross-Tool handoff, and goal branches already proven by the client source code?

It does not ignore deterministic differences merely because the Agent could theoretically correct them. Incorrect field origins, or leaving time and format transformations to ad hoc Agent reasoning, reduce the accuracy score even when an ordinary path may still complete.

Both systems include Function/MCP implementation in their scores. The difference is that the main-flow system asks whether a discrepancy blocks the user, while the semantic system asks whether it deviates from the source.

## Scoring Model

The evaluation first independently identifies the main user goals that are actually reachable from the authorized source. Five main goals were identified in this evaluation and weighted equally. Each goal is scored out of 10 under each system. Each system's total is the arithmetic mean of the five goal scores, rounded to one decimal place. The public report retains only package-level totals and does not publish per-goal business scores.

### Main-Flow Completeness

| Component | Points | What is evaluated |
|---|---:|---|
| Goal understanding and information guidance | 2.0 | Whether the Skill identifies the correct goal, uses dynamic information, and can progressively collect the currently missing inputs |
| Function/MCP capability coverage | 3.0 | Whether required capabilities such as query, calculation, upload, prevalidation, and final write exist and are callable through MCP |
| Data handoff and request correctness | 3.0 | Whether fields come from the correct upstream source, deterministic transformations are implemented in the Function, and the final request uses the correct interface and structure |
| Conditions, confirmation, and completion handling | 2.0 | Whether required conditional branches, attachments, user confirmation, stopping, and response delivery are sufficient for the Agent to complete the work or stop honestly |

Function/MCP capability coverage and request correctness account for **6 points** in total. Therefore, a candidate containing only Skill documentation, but whose Function lacks required capabilities or inevitably constructs an incorrect request, cannot receive a high score.

### Business-Semantic Accuracy

| Component | Points | What is evaluated |
|---|---:|---|
| Interface-to-capability mapping | 2.0 | Whether the Tool uses the correct interface, method, authentication boundary, and business-operation semantics |
| Field origin and request mapping | 3.0 | Whether query values, user selections, page state, and final request fields come from the correct sources |
| Deterministic transformations and data handoff | 2.5 | Whether time, formatting, composition, cleanup, and cross-Tool handoff are implemented stably by the Function |
| Branches and prerequisites | 1.5 | Whether conditionally required inputs, attachments, prevalidation, confirmation, and stop points are bound to the correct goal or branch |
| Package consistency | 1.0 | Whether Skill, MCP Schema, Function, and tests express the same set of provable semantics |

## Deduction Rules

To avoid impression-based scoring, main-flow completeness uses these rules:

- A representative standard path inevitably cannot reach the final request: that goal usually scores no higher than 5.
- A required conditional path reachable in the source lacks a capability: deduct 1.0–2.0 points according to impact.
- A source-explicit transformation is left to ad hoc Agent reasoning, but the Agent can usually recover: deduct 0.2–0.6 points.
- A mandatory entry condition, user confirmation, or stop point is unclear, but the Agent can still recover: deduct 0.2–0.6 points.
- Differences only in wording detail, file naming, or non-executable explanation: no deduction.

Business-semantic accuracy uses these rules:

- Incorrect interface, method, or critical field origin: deduct 0.5–2.0 points according to impact.
- A source-explicit time, format, or composition transformation is not implemented deterministically: deduct 0.3–0.8 points.
- Query semantics and write semantics are confused, or cross-Tool data handoff depends on guessing: deduct 0.5–1.5 points.
- A condition, attachment, confirmation, or prerequisite is bound to the wrong goal: deduct 0.3–1.0 points.
- A non-blocking contradiction exists among the Skill, MCP, Function, or tests: deduct 0.2–0.5 points.

Both systems follow these shared rules: passing package tests does not directly add business points; not calling real interfaces does not mechanically reduce the code-level score, but must be separately marked as “real business behavior not verified.” Backend-internal rules that are invisible to the client are not penalized merely because they cannot be reconstructed.

## Evidence Priority

This evaluation does not use Review reports generated by any of the three candidates, nor does it reuse scores from historical conversations. Evidence is obtained independently in this order:

1. **Authorized client source code**: re-identify visible entry points, main goals, direct interface invocation chains, user inputs, and deterministic client-side transformations.
2. **Function Core**: inspect endpoints, methods, authentication headers, queries and request bodies, field origins, and time/format transformations item by item.
3. **MCP Tool**: confirm that required Functions are exposed, input Schemas are sufficiently permissive, and results are not blocked by a strict output Schema before reaching the Agent.
4. **Skill**: check whether it can progressively collect information, use the correct Tools, and handle conditions and stop points specific to the current goal.
5. **Independent behavior probes**: without reusing assertions from package tests, independently inspect cross-Tool data handoff and final requests with dry runs or mocks.
6. **Package offline tests and structural validation**: after installing dependencies, confirm that the package loads, completes MCP discovery, and runs its included tests.

Backend Service internals are not part of the default capability surface. Only public interfaces invoked by the client, request/response contracts, and transformations explicitly performed by the client enter the score. Backend-internal rules that cannot be proven from the authorized source are not guessed into hard requirements.

## Execution Method

### 1. Reconstruct the Source Baseline

- Identify main goals from actually visible entry points, excluding hidden or unreachable features.
- For each goal, record a standard path: “obtain context → dynamic query → user selection → conditional branch → final write request.”
- Continue tracing components and shared modules directly referenced by the page within the authorized scope until request construction or attachment-upload results close the loop.
- Do not infer semantics from identical field names; trace the actual origin and purpose through “interface response → page state → next request.”

### 2. Inspect the Generated Package

- Starting from the Skill entry point, confirm whether the Agent can progressively obtain every required input.
- Check that the corresponding MCP Tool exists for each step and ultimately calls the correct Function.
- Compare the query/body produced by the Function field by field against the client's final request.
- Check whether deterministic behavior such as time composition, ISO formatting, dynamic-option selection, and attachment URL binding is performed by the Function.
- Check that shared Tools appear only in invocation chains where the current goal actually requires them.

### 3. Independent Executable Validation

The three original generated packages remained unchanged. Each was copied to a temporary directory, had its declared dependencies installed, and then underwent:

- JavaScript syntax checks;
- MCP `initialize` and `tools/list`;
- package offline tests;
- Code2Skill default directory-structure validation;
- independent dry-run request probes written by the evaluator.

Validation results:

| Generation model/runtime configuration | Package tests | Structure and MCP validation | Independent request probes |
|---|---:|---|---|
| GPT-5.6 Sol (Ultra mode) | 21 / 21 | Passed | Passed; found minor confirmation-policy differences |
| Kimi K3 (Max reasoning level) | 24 / 24 | Passed | Passed; found one deterministic time transformation that depends on the Agent |
| GPT-5.6 Sol (High reasoning level) | 15 / 15 | Passed | Passed; confirmed ordinary paths were executable and found a conditional attachment capability gap |

All validation was offline or local protocol validation. It did not call real business interfaces, object storage, real identities, or write capabilities.

## How the Scores Were Derived

### GPT-5.6 Sol (Ultra mode): Main Flow 9.6 / Semantics 9.0 / Composite 9.4

- All main goals, required Tools, and final write requests close the loop.
- Conditional attachment capabilities and downstream binding are complete.
- Query-use and final-write semantics are separated, while deterministic time and field transformations are performed by the Function.
- The main-flow score loses points only because a small number of confirmation policies depend on the Consumer Agent/Host; the semantic score applies stricter deductions for edge branches and differences from source expression.

### Kimi K3 (Max reasoning level): Main Flow 9.5 / Semantics 8.0 / Composite 8.9

- Main goals and attachment paths close the loop, and user-confirmation instructions are clear.
- Function/MCP request construction is generally correct, and dynamic values can be handed off into the final request.
- A small number of deterministic transformations and entry checks still depend on the Agent. They usually do not block the main flow, but receive explicit deductions under the source-semantic system.

### GPT-5.6 Sol (High reasoning level): Main Flow 9.0 / Semantics 7.5 / Composite 8.4

- Ordinary standard paths without attachments are complete; queries, calculations, prevalidation, and write requests can execute.
- Identically named fields in the final request, dynamic selection, and common time transformations are handled correctly.
- When the source dynamically requires an attachment, the package has no business upload Function/MCP and can only accept an externally uploaded URL. As a result, some conditional paths cannot be completed by the generated package alone.
- Conditional inputs, confirmation, and some exact semantics depend on the Host or Agent, so semantic accuracy is notably lower than main-flow completeness.

## Package Size

The table below measures the generated packages themselves, not the amount of source code actually read by the Producer. Line counts exclude `package-lock.json` and `node_modules`:

| Generation model/runtime configuration | Delivered files | Effective text/code lines | Directory size |
|---|---:|---:|---:|
| GPT-5.6 Sol (Ultra mode) | 16 | 2,880 | 176 KB |
| Kimi K3 (Max reasoning level) | 15 | 1,859 | 164 KB |
| GPT-5.6 Sol (High reasoning level) | 13 | 1,168 | 120 KB |

The final package cannot reliably prove which source files or how many lines of code the Producer actually read. Shared source code also cannot be simply apportioned among individual Skills. If this metric is needed in the future, an anonymous package-level access summary should be recorded during generation; it must not be reverse-engineered from the generated result.

## Status Boundary

This report proves that:

- the generated package structure can load;
- MCP Tools are discoverable;
- offline request construction can execute;
- main user goals reconstructed from source are basically closed at the code level.

This report does not prove that:

- real authentication and permissions work;
- dynamic production data matches offline samples;
- real business interfaces accept the requests;
- write operations have been submitted, approved, or taken effect;
- the Consumer Host has correctly registered MCP or provided attachments.

Therefore, **a main-flow score above 9 means basic code-level usability, not production readiness**. The semantic score measures consistency with visible source code and cannot replace real-interface validation. Before deployment, users must still configure the environment and spot-check high-value paths using their own business knowledge. Real-interface validation requires explicit authorization, and write interfaces must never be called automatically.

## Product Conclusion

This evaluation supports the current product direction:

- Generate compact, runnable Functions, MCPs, and independent Skills by default.
- Prioritize enabling users to complete representative main flows without restoring large Contract, matrix, or audit directories.
- Put source-explicit request construction and deterministic transformations in the Function; leave interaction, follow-up questions, and response interpretation to the Agent.
- Treat green package tests only as technical assurance; use an independent Review or real-environment sampling when needed.
- The current core generation flow can enter a stable phase. Future work should fix high-value gaps found in new real cases rather than continue speculative architectural expansion.

## Limitations

- Only one anonymized, multi-goal source scope was evaluated; it cannot represent every language, architecture, or business type.
- The total scores include evaluator judgment. They are suitable for comparing packages from the same batch and should not be used as hard thresholds across projects.
- The composite reference score's 60/40 weighting reflects Code2Skill's current product priorities. Other projects may retain the two raw scores and use different weights.
- Without real-interface and deployment evidence, the generated results cannot be claimed to be end-to-end usable.
- To protect private information, the repository does not provide the original source code, generated packages, field-level evidence, private prompts, or business-identity mappings.
