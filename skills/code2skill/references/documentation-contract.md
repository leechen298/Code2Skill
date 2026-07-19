# Chinese documentation contract

The `node-stdio` strict export uses Chinese documentation because an executable Tool contract alone does not preserve a feature's business meaning. All claims must agree with the Canonical Contract, Goal Contract, capability graph, Consumer requirements, and verification matrix; documentation may explain those contracts but must not create a second version of them. `PAGE.md` is a compatibility filename and does not imply that every frontend, backend, API, RPC, message, or worker feature has a UI page.

## PAGE.md

Frontmatter contains exactly the useful public metadata:

```yaml
---
name: knowledge-search
title: 知识内容检索与详情阅读页面说明
description: 说明用户如何在知识页面筛选内容、读取详情，并帮助 Agent 判断可以调用哪些只读能力以及何时停止。
surface: route
surface-id: /knowledge
route: /knowledge
language: zh-CN
---
```

`surface` is one of `route`, `backend-api`, `rpc`, `message`, `worker`, or `other`; `surface-id` is the source-proven route, API/RPC operation family, message topic/consumer identity, worker identity, or another stable feature identifier. For a route-less feature, keep `pageRoute` and PAGE `route` at the reserved `/__code2skill__/features/<feature-id>` value required by the current Runtime Profile, and state clearly that it is document identity rather than a deployed route or request target. Never invent screen regions for a route-less feature; interpret the required page-oriented headings as feature-surface sections.

Use a Chinese H1 and these H2 sections:

1. 页面定位
2. 典型用户目标
3. 页面区域与业务信息
4. 动态依赖与失效规则
5. 可用 MCP 能力
6. Agent 使用边界
7. 不属于本页面的能力
8. 推荐起点
9. 副作用与确认（存在 write Tool 时必需；纯只读 feature 可写明无副作用或省略）

Mention every Tool with backticks under “可用 MCP 能力”. State whether the feature is read-only. For each write Tool add a separate line under “副作用与确认” naming the action, trusted Host/runtime confirmation requirement, deterministic Guard boundary, no-automatic-retry rule, and human reconciliation for unknown outcomes. A route-less feature describes its real API/RPC/message/worker inputs and outputs instead of pretending that a page exists.

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

Under “输入与来源” and “意图路由”, explain progressive collection rather than demanding a complete form in the first message. Distinguish always-required, conditionally required, optional, derived, and dynamic information; state freshness and refresh rules. Tell the Agent to reuse valid known information, skip unnecessary lookups, and ask only for currently missing values.

Keep the twelve canonical H2 headings above verbatim. Additional subsections are allowed, but synonyms must not replace the canonical headings because consumers should be able to locate each contract deterministically.

The handoff section writes mappings in source-to-target form, for example `data.items[].id` → `itemId`, and states when prior values expire or must be refreshed.

The Skill must allow partial goals and freely composable calls. Never say every request must run the whole client flow. Explain how to stop when information is missing, ambiguous, stale, unauthorized, or outside scope.

Describe source-observed paths as `observed` and new contract-compatible paths as `derived composition`. State that derived write compositions retain every runtime guard and need separate verification. If `host-compatibility-report.json` disables a capability or marks it `requires-host-integration`, the Skill must not recommend it as immediately executable.

Cover failures from schema validation, provenance IDs/tokens, HTTP/network/timeout/disconnection, malformed output, empty/404 results, and retry policy. Explain dry-run. For writes, require trusted Host/runtime confirmation, prohibit automatic retry for non-idempotent operations, and stop for human reconciliation when dispatch outcome is unknown.

Provide at least three complete `### 示例...` blocks. Across them use at least three Tools when the bundle has three or more. Each example contains user goal, calls/arguments, stopping condition, and answer shape.

Across the examples, include at least one progressively collected goal and one case where already-complete information skips a question or lookup. Examples must not imply that the original page order is the only legal composition.

## MCP.zh-CN.md

Explain MCP, stdio transport, protocol `2025-11-25`, `tools/list`, `tools/call`, `title`, `description`, `inputSchema`, `outputSchema`, `structuredContent`, `isError`, `annotations`, dry-run, input, output, errors, examples, and handoff semantics.

Create one H2 section containing each `tool_name` in backticks. Every Tool section covers purpose/calling occasion, all inputs, required output leaf fields, HTTP or local behavior, failure mapping, independent stopping or handoff, and a complete `tools/call` example. Include at least one successful `{status, data}` `structuredContent` response and one `isError: true` response pattern.

Each Tool section contains at least 75 Chinese characters and uses the explicit labels “用途或调用时机”、“入参”、“出参”、“HTTP/本地行为”、“失败与错误”、“handoff/交接”和“示例”. Mention every input and required output leaf with backticks. Supply one literal JSON call containing both `"name"` and `"arguments"` for every Tool.

Do not pad the documents with repeated boilerplate. Use the required length to preserve field meaning, dynamic invalidation, boundary decisions, error recovery, and concrete calls.
