# Code2Skill

English | [简体中文](README.zh-CN.md)

Code2Skill is a collection of installable Agent Skills that helps coding agents understand business functionality in user-authorized frontend, backend, or full-stack source code, then generate Functions, MCP tools, workflow Skills, and offline tests for other agents to use.

Current release: [v1.1.2](https://github.com/leechen298/Code2Skill/releases/tag/v1.1.2).

```text
Existing application code
  ↓ Code2Skill
Functions + MCP Tools + Skills + Tests
  ↓
An agent gathers the required information and completes the user's goal
```

Functions and MCP tools provide business capabilities. Skills guide an agent in using those capabilities. The consuming agent still decides whether to call a tool, what to clarify, how to interpret a response, and what to do next.

## What It Does

- Generates capabilities from business invocation points that actually exist in source code. Client-backed features start from calls made by the client or consumer; projects without a client start from user-specified public APIs, RPCs, services, messages, or task entry points and follow their public request, response, and contract types as needed.
- Identifies independently completable goals within a user-specified page, directory, feature, or public entry point.
- Places field provenance, selected-record handoffs between tools, request assembly, and deterministic transformations in Functions.
- Generates a Skill for each primary goal while reusing the necessary Functions and MCP tools.
- Defaults to offline technical validation and does not call live business APIs.

## Supported Agents

You can run Code2Skill with mainstream coding agents such as Codex, Claude Code, and Kimi Code. Generated Skills can be installed in Codex, Claude Code, Cursor, OpenClaw, and other environments that support Agent Skills.

See the [`skills` CLI compatibility list](https://github.com/vercel-labs/skills#supported-agents) for more environments. To perform live business operations, register the generated MCP server as described in each package's `MCP-SETUP.md`.

## Installation

Install all three Skills with the standard Agent Skills CLI:

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill-generate code2skill-review-flow code2skill-review-source \
  --agent "$AGENT_ID" \
  --global \
  --yes
```

- `code2skill-generate`: generates Functions, MCP tools, workflow Skills, and offline tests.
- `code2skill-review-flow`: checks whether a user can complete the main goals through the generated workflows.
- `code2skill-review-source`: reviews request fields, transformations, and invocation chains against the authorized source code.

Routine generation only requires `code2skill-generate`. Run the two review Skills independently when needed. See the [installation guide](docs/installation.md) for migration from older versions, generated-package dependencies, and MCP registration. The detailed documentation is currently written in Chinese.

### DeepSeek Harness

DeepSeek Harness users can install the three Skills as a Bundle in a selected profile:

```bash
dsh plugin --profile web add github:leechen298/Code2Skill#v1.1.2
```

See the [DeepSeek Harness integration guide](docs/deepseek-harness.md) for installation, verification, headless profiles, and removal. Generated business MCP servers must still be registered separately according to their own `MCP-SETUP.md` files.

## Usage Boundaries

Code2Skill produces runnable, editable first drafts of business capabilities. It does not prove that every business rule or real environment has been validated. Results depend on the generation model, source completeness, and the scope the user authorizes.

For complex writes or high-value workflows, review cross-tool data provenance, same-name field semantics, deterministic request transformations, goal-specific prerequisites, attachment uploads, and downstream bindings. Use `code2skill-review-flow` to check the main workflow and `code2skill-review-source` to inspect critical source semantics. Offline tests do not replace real API or deployment acceptance.

## Quick Start

Invoke the generation Skill inside the target repository and explicitly authorize the source roots it may inspect:

```text
Use $code2skill-generate to turn <page, directory, feature path, or public entry point>
into runnable Functions, MCP tools, and Skills.
Authorized source roots: <frontend>, <backend>, <protocol>, and <service/message/task directories>.
Use invocation points that actually exist in source code as the capability source.
Do not call live business APIs.
```

For independent reviews:

```text
Use $code2skill-review-flow to review whether the primary goals in <generated package path> can be completed.

Use $code2skill-review-source to review whether <specific Skill or capability> in
<generated package path> matches the authorized source code.
```

## Generated Package

The logical output stays consistent while file extensions, dependencies, and startup commands follow the target stack's runtime profile. The current `core-export-v1` default is implemented by the `node-stdio` profile:

```text
generated/code2skill/<feature-id>/
├── SKILL.md or skills/*/SKILL.md
├── function-core/index.mjs      # node-stdio profile example
├── mcp-tool/index.mjs           # node-stdio profile example
├── portable-agent-result.mjs    # helper for HTTP scenarios
├── tests/
├── package.json
├── MCP-SETUP.md
└── references/feature-context.md  # generated only when business context needs it
```

Each generated `MCP-SETUP.md` records the runtime language, dependency installation, startup command, environment variables, unmet prerequisites, and MCP registration steps. A Skill being installed, an MCP server being connected, and the live business workflow being validated are three separate states.

## Generation Results

Three runs against the same anonymized, multi-goal source package:

| Generation model / configuration | Date | Generation time | Composite reference score |
|---|---|---:|---:|
| GPT-5.6 Sol (Ultra) | 2026-07-24 | 47m 45s | **9.4** |
| Kimi K3 (Max reasoning) | 2026-07-24 | about 93m | **8.9** |
| GPT-5.6 Sol (High) | 2026-07-24 | 20m 29s | **8.4** |

Timing ends when generation and that run's offline validation finish; it excludes later scoring, directory cleanup, installation, and deployment. See the [evaluation report](docs/evaluation.md) for the two scoring systems, methodology, and privacy boundaries. The report is currently written in Chinese.

## Documentation

- [Install Skills, generated dependencies, and MCP servers](docs/installation.md) (Chinese)
- [Generated package structure and design principles](docs/generated-results.md) (Chinese)
- [Runtime-neutral generation design](docs/development/runtime-neutral-generation-v1.zh-CN.md) (Chinese)
- [Optional advanced validation](docs/advanced-validation.md) (Chinese)
- [Models, scoring, and anonymized evaluation results](docs/evaluation.md) (Chinese)
- [Full documentation index](docs/README.md) (Chinese)

The Skills follow the [Agent Skills specification](https://agentskills.io/specification) and use [vercel-labs/skills](https://github.com/vercel-labs/skills) for installation. Generated MCP servers use standard stdio or Streamable HTTP transport.
