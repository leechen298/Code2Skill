---
name: code2skill-review-flow
description: Review representative Code2Skill main flows for closure / 轻量审核 Code2Skill 代表性主流程是否闭环。
---

# Code2Skill Main Flow Review

The complete Chinese version is available at [references/SKILL.zh-CN.md](references/SKILL.zh-CN.md).

Follow the user's language for the final reply, review conclusions, and all user-facing content.

Review whether an existing Code2Skill-generated package can help an Agent complete the main user goals along representative standard paths. This Skill answers only whether the main flows are basically usable; it does not prove field by field that the generated package fully matches the source code.

This Skill is read-only, offline, and source-first by default. It may be used by an independent Agent or invoked separately after `code2skill-generate` completes. It does not generate Contracts, evidence matrices, review reports, or other deliverable files.

## Inputs and Boundaries

Before starting, determine:

- the path of the generated package to review;
- the source roots and page, directory, interface, or feature scope explicitly authorized by the user;
- whether only some main goals should be reviewed;
- whether the user has also authorized fixes; remain read-only when no such authorization is explicit.

Review only the default output of `code2skill-generate`. When encountering an advanced-validation format, a legacy version, or an unrecognized directory, explain that this process does not apply instead of forcing the directory through it.

Search only the authorized source roots. When a client or Consumer exists, focus on business invocations actually triggered by the client/Consumer. When no client exists, start from the public API, RPC, Service, message, or task entry point specified by the user. Trace only the code required to prove a representative standard path; do not descend into backend Services, databases, downstream messaging, approvals, or complete business validation.

By default, do not:

- call real business interfaces or write interfaces;
- install, register, or deploy MCP for the review;
- scan the entire machine for unauthorized source code;
- modify the generated package, source code, or tests;
- write temporary goal lists or path derivations into the repository.

When the user explicitly authorizes fixes, blocking issues may be corrected and focused offline tests may be added. Authorization to fix does not authorize calls to real interfaces.

## Keep the Review Independent

Prefer an Agent or new session that did not participate in generation. This Skill accepts only the source scope, generated-package path, and user goals; it does not treat the Producer's goal list, conclusions, or green tests as facts.

When only the same Agent is available, perform a cold review:

1. Treat the goals claimed by the generated package and the test expectations as unverified hypotheses.
2. First identify the main user goals independently from the source entry points.
3. Form the minimum standard paths in working memory.
4. Then read the generated package and compare it.
5. Only afterward inspect or run the existing tests.

## Review Process

### 1. Independently Identify Main Goals from Source

From the page, directory, interface, or feature entry point specified by the user, identify the main user goals that can be completed independently. A main goal represents a user-visible terminal outcome, not every input field, API, file, or page branch.

At this stage, do not read the detailed implementation of the generated package and do not treat its existing Skill list as the complete goal set. First form a temporary goal list, then lightly inspect the generated package's `package.json`, directory structure, and each Skill's frontmatter/title to compare:

- whether each source-derived goal has a corresponding Skill or equivalent independent entry point;
- whether multiple independent goals were incorrectly merged;
- whether one goal was mechanically split by interface;
- whether the generated package claims goals with no source basis.

### 2. Build Only One Representative Standard Path per Goal

For each main goal, record only the following in working memory:

```text
Goal entry point
→ Key information required to complete the goal
→ Required Function/MCP
→ Upstream-to-downstream Tool handoff
→ Terminal business invocation, stop condition, or interpretable result
```

At minimum, distinguish information originating from user input, prior responses, page or client state, Host input, and genuinely unknown values. Inspect deterministic transformations or critical imports only when they affect whether the terminal business invocation can be formed.

By default, verify only one representative standard path for each goal. Expand hidden entry points, edit modes, optional branches, and all condition combinations only when the user explicitly specifies them or when they are mandatory conditions of that standard path.

For a complex write goal, verify one additional real critical decision branch beyond the representative standard path—not every branch.

### 3. Compare Against the Generated Package

Compare only the minimum scope:

1. Whether the Skill provides an independent entry point and required guidance for the current goal.
2. Whether Function/MCP has the capabilities required to complete the standard path and clearly declares the business service base required from the Host (the API base URL in HTTP scenarios; the corresponding client, Broker connection, or runtime context in RPC/Service/message/task scenarios).
3. Whether prior responses, user input, and Host input can be handed to the correct downstream Tool.
   If the client's standard path passes the entire currently selected row or multiple accompanying fields into a downstream invocation, confirm that the upstream result can be preserved and that the Skill guides the Agent to use the selected-record input exposed by Function/MCP, instead of showing only an ID-only path whose equivalence has not been proven.
4. Whether mandatory conditions, attachments, or confirmations are missing or incorrectly applied to another goal.
5. Whether the Agent can construct the terminal business invocation (also called the terminal request in HTTP scenarios) and continue communicating or stop based on the actual response.
6. Whether an intermediate result, stop point, or pre-write prerequisite that changes the next step is missing.
7. Whether Agent follow-up questions, user confirmation, page order, or ordinary business validation were incorrectly generated as a Tool or global Workflow. Do not fabricate ordinary business validation or page order as a deterministic Guard, consistent with the rules above that a shared Tool is not a global prerequisite and page order is not an unskippable Workflow.
8. Whether an asynchronous status-query or result-reconciliation capability claimed by the generated package has source evidence: a generated capability with no source basis is fabricated, while a source-backed capability that is absent is an omission.
9. Whether a simple read-only query goal was over-split into multiple Tools or Skills.

A shared Tool is a reusable atomic capability; it does not automatically become a global prerequisite for every goal. Page presentation order also does not automatically become an unskippable runtime Workflow.

Business service integration configuration—the API base URL in HTTP scenarios, or the corresponding client, runtime context, or Broker connection in RPC/Service/message/task scenarios—is Host deployment configuration, not a user business input. If every standard path is unable to invoke the service because a required integration configuration was not declared, treat this as a main-flow gap. If the concern is only portability caused by a default test, staging, or production domain, record it as a lead for `code2skill-review-source`; do not expand it within this lightweight main-flow review.

### 4. Assign Main-Flow Status

Use exactly one of these statuses for each main goal:

- `Complete`: at least one source-proven representative standard path closes the loop, with no known main-flow gap within this lightweight scope;
- `Basically usable`: the representative standard path can complete without a blocker, but recoverable main-flow uncertainty remains or additional handling by the Agent, user, or Host is required;
- `Blocked`: a main Skill, required Tool/handoff is missing, an incorrect request is inevitable, or a step from another goal was incorrectly made a global prerequisite;
- `Unverified`: authorized source or offline evidence is insufficient to determine whether the request chain closes the loop.

Not calling a real API is a separate validation boundary. It does not automatically downgrade a goal whose source and offline checks already close the loop to `Unverified`.

Treat only `Blocked` as requiring a fix before delivery. `Complete` means only that the main flow closes within this lightweight scope; it does not mean field-level source accuracy or real-API validation. When a non-blocking difference in field origin, deterministic transformation, or critical dependency is found, record it only as a lead for further review and recommend `code2skill-review-source` for deeper inspection instead of expanding this Skill's scope.

If the Function already accepts the complete selected record and the upstream result provides it, but the Skill example shows only a simplified ID-only invocation, do not classify the main flow as blocked on that basis alone. When no evidence proves that ID-only must fail, record it as a recoverable guidance gap or `P2`. Classify it as `Blocked` only when the required record cannot be handed downstream or the standard path inevitably constructs an incorrect request.

### 5. Tests Are Supporting Evidence Only

Inspect package tests only after deriving the source goals and standard paths. Green tests prove only that the implementation matches the test author's expectations; they do not prove that no goal is missing.

You may run dry-run or mock tests that are confirmed not to access a real environment, but do not install, deploy, or register MCP for this review. If the user authorizes fixes, add tests only for the discovered blocking paths; do not rebuild a complete matrix of goals, fields, and branches.

## Output the Conclusion

Reply directly in the current session; do not create review files. Give the overall conclusion first, then the per-goal statuses:

| Main goal | Status | Standard-path evidence or gap | Real-interface status |
|---|---|---|---|

Then list only:

- `P1`: blocks a main goal and must be fixed before that goal can be classified as Complete or Basically usable;
- `P2`: the main flow can complete, but a recoverable flow uncertainty remains and does not block delivery;
- Boundary note: authorized source or offline evidence is insufficient to confirm the point.

Classification threshold: classify an issue as P1 (`Blocked`) only when it inevitably writes too early, inevitably takes the wrong branch, lacks a required Tool/handoff, or incorrectly adds a global prerequisite. Guidance issues recoverable by the Agent remain P2.

Each issue must include the affected goal, source location, generated-package location, impact on the standard path, and the minimum fix. The final response must clearly distinguish file existence, offline loadability, main-flow closure, source accuracy, real business usability, and deployment status.

These checks do not change this Skill's lightweight positioning: it still evaluates only representative main flows and does not expand into a source-precision audit. Source-level review remains the responsibility of `code2skill-review-source`.
