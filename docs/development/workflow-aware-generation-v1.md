# Workflow-Aware Generation: Lightweight Enhancement Development Task

## Goal

Enhance business decision-boundary recognition in the existing `code2skill-generate` so that complex goals can more reliably distinguish Agent judgment and follow-up questions, user confirmation, independently callable Tools, deterministic steps inside Functions, Host policies, runtime hard constraints, and completion or stop conditions.

This iteration enhances the default generation flow. It does not add a `strict generate` command, does not change the audit meaning of `strict-export-v1`, and does not increase model reasoning turns by mechanically splitting Tools into smaller pieces.

## Development Boundaries

- Preserve the current invocation: `/skill:code2skill-generate generate <source scope>`.
- Default artifacts remain compact Functions, MCP, Skills, tests, and installation instructions.
- The decision-boundary graph is temporary analysis used only during generation and does not enter the delivered package.
- Ordinary business validation remains the backend's responsibility, and responses are passed through unchanged to the Consumer Agent.
- Generate a deterministic Guard only when source explicitly proves a non-bypassable identity, provenance, transaction, one-time credential, ordering, or similar hard constraint.
- Page order, an ordinary confirmation dialog, an ordinary POST, a backend rejection, or a shared query must not automatically become a hard Workflow.
- Do not add a Canonical/Goal Contract, Capability Graph, audit report, verification matrix, or any other default deliverable file.
- Do not modify the currently untracked article and images: `docs/juejin-code2skill-launch.md`, `docs/assets/`.

## Phase 1: Complete the Default Generation Analysis Rules

Add an explicit “goal decision boundaries” step to `skills/code2skill-generate/SKILL.md`.

For each main user goal, the Producer must first form a minimum temporary graph in working memory:

```text
User goal
→ Known and missing information
→ Query, selection, or validation
→ Branches and stop conditions
→ Presentation or confirmation before writing
→ Write
→ Result query or reconciliation when present in source
```

Each node must belong to one category:

1. Agent judgment, follow-up question, or selection;
2. user interaction or confirmation;
3. an MCP Tool that can be independently named, invoked, reused, or stopped after;
4. a deterministic step inside a Function that does not require model participation;
5. Consumer Host policy;
6. a source-proven non-bypassable deterministic Guard;
7. a completion, stop, or unconfirmable-result boundary.

This analysis must constrain subsequent Tool boundaries and Skill wording, but it does not require generating a new intermediate file.

## Phase 2: Clarify Tool Splitting and Merging Rules

Extend the existing capability-design rules: consider extracting an additional Tool only when one or more of the following applies:

- an intermediate result changes the subsequent invocation, branch, or request parameters;
- it completes an independent partial goal or can be reused by another goal;
- permissions, side effects, or confirmation requirements differ before and after the step;
- the intermediate stage is a reasonable place to stop, wait for user input, or wait for user selection;
- after a write, source proves an asynchronous status-query or result-reconciliation capability.

Do not split a Tool when:

- the only purpose is to make the model reason one more time;
- the work is a deterministic implementation such as request assembly, field formatting, or an internal RAG retrieval step;
- the next step is always the same regardless of the intermediate result;
- splitting exposes intermediate state with no business meaning;
- multiple invocations belong to an indivisible transaction boundary.

One Tool may invoke multiple internal APIs, and one API may support multiple business Tools. Do not map mechanically by interface count.

## Phase 3: Enhance Skills and Lightweight Tests

### Skill

For a goal containing multiple decision nodes, the Skill should concisely explain:

- known information, missing information, and information that can be obtained safely;
- which result affects the next step;
- when to skip, stop, continue asking follow-up questions, or request user selection;
- the impact and choices that must be presented to the user before writing;
- which constraints are Agent/Host policies and which are runtime hard constraints;
- that an unclear actual response must be explained by the Agent and cannot be automatically converted into success or failure.

The Skill is still not a fixed step-by-step script. When information is already complete, it should not generate meaningless follow-up questions or repeated queries.

### Offline Tests

Add tests only according to the actual goal structure; do not build a business-rule combination matrix:

- one normal representative path for each complex goal;
- when cross-Tool data handoff exists, verify that selected data or an upstream result enters the downstream request correctly;
- when source proves a stop branch, verify that the Skill does not describe the subsequent write as unconditional;
- a shared Tool must not be incorrectly elevated into a global prerequisite for another goal;
- when source proves a runtime hard edge, retain a bypass counterexample with zero external writes;
- ordinary backend rejection still reaches the Agent unchanged.

Tests use anonymous synthetic cases across business domains and contain none of the current private business, page, interface, field, or path information.

## Phase 4: Enhance Lightweight Review and Regress

Update `code2skill-review-flow` at the same time:

- continue to evaluate only representative main flows, without becoming a source-precision audit;
- for a complex write goal, additionally inspect one real critical decision branch;
- check for omitted intermediate results, stop points, or pre-write prerequisites that would change the next step;
- check whether Agent follow-up questions, user confirmation, page order, or ordinary business validation were incorrectly generated as a Tool/global Workflow;
- classify an issue as P1 only when it inevitably writes too early, inevitably takes the wrong branch, lacks a required Tool/handoff, or incorrectly adds a global prerequisite; guidance issues recoverable by the Agent remain P2.

Add or update anonymous regression tests covering at least:

1. a simple read-only query: it must not be over-split;
2. query/selection/prevalidation/write: decision boundaries are correct, and follow-up questions and confirmation are not Tools;
3. asynchronous write/status query: generate or describe status capability only when source provides it;
4. ordinary backend validation: it must not be fabricated as a deterministic Guard.

Run all current repository tests and `git diff --check`. Do not call real business interfaces.

## Acceptance Criteria

- Users still invoke only the existing `code2skill-generate` and do not need to understand a new command.
- The size and number of steps in default artifacts for a simple query do not increase materially.
- Complex goals clearly distinguish the responsibilities of the Agent, user, Tool, Function, Host, and Guard.
- Do not turn every step into a Tool or use increased reasoning turns as a reason to split.
- Do not automatically elevate an ordinary write, page confirmation, or backend validation into a hard Workflow.
- Do not add new default deliverable file types or restore a heavyweight audit process.
- `code2skill-review-flow` can detect premature writes, missing critical decision boundaries, and incorrect global prerequisites without demanding every business branch.
- Anonymous tests, the full test suite, and `git diff --check` pass.
- Do not modify, commit, or delete the user's existing untracked articles or images.

## Collaboration and Delivery Rules

- `codex-volc-deepseek-flash` performs the actual development in Phase 1–4 order.
- After each phase, DeepSeek must report to `kimi-share-test`: modified files, key design decisions, test results, and unverified boundaries, then wait for review.
- `kimi-share-test` only performs 15-minute inspections, independent review, and required read-only checks or tests, and returns issues to DeepSeek; it must not modify code itself.
- Kimi gives minimum change requirements when it finds an issue. DeepSeek fixes the issue and reports again, repeating until acceptance passes.
- Do not commit or push. Kimi provides the final summary of phase results, complete validation, `git status`, and remaining boundaries.
- When the two sessions send tmux messages, they must actually send Enter and then read the pane to confirm that the text entered the other session instead of remaining only in the input box.
