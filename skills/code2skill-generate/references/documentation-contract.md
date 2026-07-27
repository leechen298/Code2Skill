# Chinese documentation contract

The `node-stdio` strict export uses Chinese documentation because an executable Tool contract alone does not preserve a feature's business meaning. All claims must agree with the Canonical Contract, Goal Contract, capability graph, typed handoffs, Consumer requirements, hard workflows, conflicts, and verification matrix; documentation may explain those contracts but must not create a second version of them. vNext derives all of those prose-relevant facts into `references/capability-contracts.json` as the authoritative documentation surface and generates `references/feature-context.md`, `SKILL.md`, `MCP.zh-CN.md`, and `MCP-SETUP.md`. The three Agent-facing documents name that file and carry its exact SHA-256 marker, so any covered Canonical change forces explicit documentation review. They must not restate contradictory requiredness or operation policy. vNext does not generate `PAGE.md` and does not require `pageRoute`. A legacy package may retain those names only through its legacy compatibility path.

## references/feature-context.md

Use a Chinese H1 and these H2 sections:

1. 功能定位
2. 典型用户目标
3. 能力来源与范围
4. 参与者与权限
5. 业务概念与字段语义
6. 动态依赖与失效规则
7. 状态与业务规则
8. 原客户端行为
9. 结果与失败
10. 相关能力
11. 未知项
12. 证据索引

Under “能力来源与范围”, state the real `featureSurface.kind` and identifier. For a client feature, list the client-observed backend API families that define the candidate Function/MCP surface and explain that backend/contract/test code supplements their field, permission, side-effect, idempotency, and error meaning. Explicitly exclude backend-internal methods that are outside the scoped client call graph unless the user expanded scope. For a backend-only, RPC, message, worker, or other feature, describe the actual public entry surface without inventing a screen or route.

Under “原客户端行为” record the observed API calls, conditions, branches, error handling, and stopping points. If no client exists, state that explicitly instead of inventing one. Mention every Tool with backticks under “相关能力” and state whether it is read or write. Describe ordinary business validation as target-API authoritative. Under “结果与失败” distinguish correctable business errors, input/schema errors, authorization, upstream/network, malformed output, and unknown write outcomes. For each write Tool, state confirmation, retry, and reconciliation policy. Mention a deterministic Guard only when the Canonical Contract declares a proven hard Workflow; do not imply every write has one.

Every material row cites an `evidenceId` that exists exactly once in `canonical-contract.json.evidenceCatalog`, along with its `sourceId` and portable locator. Do not include absolute machine paths. The document is business background for the generated Skill, not a duplicate Tool schema or fixed operation transcript.

## SKILL.md

Frontmatter contains only `name` and a Chinese `description` long enough to explain triggers. Use a Chinese H1 and the following H2 sections (accepted wording may be slightly expanded, but keep the keywords):

1. 定位与适用范围
2. 能力目录
3. 输入与来源
4. 状态与交接
5. 意图路由
6. 推荐组合
7. 自由组合边界
8. 输出组织
9. 失败分类与恢复
10. 安全与副作用
11. 完整调用示例
12. Agent 自检清单

Under “能力目录”, add one `### ... \`tool_name\`` block per Tool. Each block contains at least 70 Chinese characters and explicitly covers:

- calling occasion and when not to call;
- every input name, type, required/optional status, semantic source, and provenance rule;
- required output leaf names and interpretation;
- downstream handoff or the fact that the Tool can answer and stop independently;
- read/write classification and side-effect policy.

Under “输入与来源” and “意图路由”, explain progressive collection rather than demanding a complete form in the first message. Distinguish always-required, conditionally required, optional, derived, and dynamic information; state freshness and refresh rules. Derived and dynamic Goal information comes only from an exact Capability output or declared trusted Host requirement, never a user answer or an unimplemented local derivation. Tell the Agent to reuse valid known information, skip unnecessary lookups, and ask only for currently missing user-providable values.

When an optional input declares `targetRequiredness.status: unproven`, describe its exact `normalProvider` as a recommendation, not a hard precondition. Use business-specific Chinese wording equivalent to: “正常流程建议先调用 `<provider tool>` 获得该值；最终是否接受缺省值由目标后端决定。” Preserve any resulting backend rejection as the structured recovery path. The validator requires the input, provider Tool, recommendation language, omission language, explicit “是否接受/拒绝” uncertainty, and target-API decision authority in one coherent paragraph. It rejects `必须`、`务必`、`需要先调用`、`只有…才能` and similar mandatory wording, as well as an unsupported definite claim such as “缺少时后端拒绝”. A `proven-optional` input does not inherit this uncertainty wording. Do not silently turn the observed UI sequence into requiredness or a deterministic Workflow.

Keep the twelve canonical H2 headings above verbatim. Additional subsections are allowed, but synonyms must not replace the canonical headings because consumers should be able to locate each contract deterministically.

The handoff section writes mappings in source-to-target form, for example `data.items[].id` → `itemId`, and states when prior values expire or must be refreshed.

The Skill must allow partial goals and freely composable calls. Never say every request must run the whole client flow. Explain how to stop when information is missing, ambiguous, stale, unauthorized, or outside scope.

Describe source-observed paths as `observed` and new contract-compatible paths as `derived composition`. State that derived write compositions retain every runtime guard and need separate verification. If `host-compatibility-report.json` disables a capability or marks it `requires-host-integration`, the Skill must not recommend it as immediately executable.

Cover failures from schema validation, provenance IDs/tokens, backend business rejection, authorization, HTTP/network/timeout/disconnection, malformed output, empty/404 results, and retry policy. Tell the Agent how to use structured error category, source code/message, field details, retryability, and outcome certainty to decide whether to ask for corrected information, re-authenticate, retry a safe read, or stop. Explain dry-run. For writes, require trusted Host/runtime confirmation only when the Canonical policy requires it, prohibit automatic retry for non-idempotent operations, and stop for human reconciliation when dispatch outcome is unknown. Do not describe ordinary backend business validation as a mandatory preflight or hard Workflow.

Provide at least three complete `### 示例...` blocks. Across them use at least three Tools when the bundle has three or more. Each example contains user goal, calls/arguments, stopping condition, and answer shape.

Across the examples, include at least one progressively collected goal and one case where already-complete information skips a question or lookup. Examples must not imply that the original page order is the only legal composition.

## MCP.zh-CN.md

Explain MCP, stdio transport, protocol `2025-11-25`, `tools/list`, `tools/call`, `title`, `description`, `inputSchema`, `outputSchema`, `structuredContent`, `isError`, `annotations`, dry-run, input, output, structured error categories, examples, and handoff semantics.

Create one H2 section containing each `tool_name` in backticks. Every Tool section covers purpose/calling occasion, all inputs, required output leaf fields, HTTP or local behavior, failure mapping, independent stopping or handoff, and a complete `tools/call` example. Every Tool section includes both a successful `{status, data}` `structuredContent` response and an `"isError": true` response with `structuredContent`. For vNext, spell every declared `errorContract.codePath`, `messagePath`, `detailsPath`, and optional `retryabilityPath` as its complete dot-joined path in backticks, for example `error.code`; when no retryability path exists, state that the default is not retryable.

Each Tool section contains at least 75 Chinese characters and uses the explicit labels “用途或调用时机”、“入参”、“出参”、“HTTP/本地行为”、“失败与错误”、“handoff/交接”和“示例”. Mention every input and required output leaf with backticks. Supply one literal JSON call containing both `"name"` and `"arguments"` for every Tool.

Do not pad the documents with repeated boilerplate. Use the required length to preserve field meaning, dynamic invalidation, boundary decisions, error recovery, and concrete calls.

## MCP-SETUP.md

Generate a short platform-neutral setup document with these H2 sections:

1. Skill 安装
2. MCP 启动
3. Host 注册参数
4. 环境变量与认证
5. 连通验证
6. 状态边界

Under “Skill 安装” include:

```bash
npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y
```

Those angle-bracket values exist only in the authoring template. Before export, replace every placeholder with the actual package name, Agent selector, startup path, Runtime Profile, and exact `export-profile.json.dryRunEnvironmentVariable`; the strict validator rejects unresolved placeholders and setup/profile drift.

Immediately state that this installs only the Skill knowledge package. It does not start or register MCP, inject authentication, set environment variables, or prove runtime/business availability.

Under “MCP 启动” and “Host 注册参数” give the executable `node <absolute-package-path>/mcp-tool/index.mjs` form and the equivalent platform-neutral `command`, `args`, `cwd`, and `env` fields. State that stdio and Streamable HTTP are the standard MCP transports: this local `node-stdio` profile uses stdio, while only an independently deployed remote service uses a Streamable HTTP endpoint. Do not include a branded Host configuration file, assume one Host's private schema, or present a common `mcpServers` wrapper as part of the MCP protocol.

List only source-/profile-proven environment variables. For HTTP/RPC business services, document one semantically named required base-URL binding per independent service, state that the deployment Host must inject the selected target, and prohibit development, staging, or production defaults in generated Functions. Source-observed environment URLs may be listed only as deployment references. The business base URL is not a public Tool argument, and a missing required binding stops before dispatch. Explain that credentials and identity come from the deployment Host or target application's supported authentication boundary and must not be written into `SKILL.md`, Feature Context, manifests, or example commands. If any capability requires `attachment-resolution`, explain that the deployment must provide this generic approved-reference-to-content/stream facility, that Code2Skill does not implement message/file ingress, and that the dependent capability remains `requires-host-integration` when it is absent. Connectivity verification covers process startup, MCP initialize, exact `tools/list`, one output-Schema-valid safe/mock success and one structured handler error per Tool, a Canonical-policy-matching dry-run call per write Tool, a separate counted-dispatcher proof of zero external effects, and only the real calls actually safe and authorized for that deployment. Attachment runtime verification additionally uses resolver and business-request spies to prove one resolution and dispatch on success, zero dispatch on resolution failure, no raw grant forwarding, correct target-field binding, and size/digest agreement. If a write cannot be exercised safely, leave its runtime state unverified rather than calling production merely to satisfy the probe.

The status section must distinguish: Skill installed, MCP registered, MCP reachable, capability behavior verified, runtime verified, Host verified, and deployed. Never collapse them into one “installed” or “available” claim.
