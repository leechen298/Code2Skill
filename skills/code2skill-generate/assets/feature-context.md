# 功能背景：<feature name>

> 这是 vNext 的业务背景模板。生成时复制到 `references/feature-context.md`，用源码事实替换所有占位符，并删除本说明。

<!-- code2skill-capability-contract-sha256:<sha256-after-derivation> -->

字段必填性、类型、动态值域、来源、有效期、副作用、错误和运行策略以 Canonical 派生的 `references/capability-contracts.json` 为准；本文解释业务含义并引用证据，不另写一份相互冲突的契约。

## 功能定位

<说明该业务功能解决的用户问题、真实 `featureSurface.kind` 和稳定标识。不要假设它必然是页面或路由。>

## 典型用户目标

- <可以独立完成的完整或局部目标>

## 能力来源与范围

- 客户端实际调用的 API：<列出候选 Function/MCP 能力面的真实请求家族与调用条件>
- 后端/协议/测试补充证据：<说明它们核对了哪些参数、动态值、权限、副作用、幂等或失败规则>
- 明确排除：<列出未被客户端调用、且用户没有扩大范围的后端内部能力>

<对 backend-only、RPC、message、worker 或其他 feature，改为说明真实公开入口。不要伪造客户端 API。>

## 参与者与权限

| 参与者 | 权限或角色 | 断言级别 | 证据 ID | 来源 ID | 可移植定位符 |
| --- | --- | --- | --- | --- | --- |
| <actor> | <permission> | fact/inference/unknown | `ev-<stable-id>` | `<sourceId>` | `<relative-path>#<symbol>` |

## 业务概念与字段语义

| 概念或字段 | 业务含义 | 来源或值域 | 必填性/条件 | 断言级别 | 证据 ID |
| --- | --- | --- | --- | --- | --- |
| <field> | <meaning> | <source> | <required/conditional/optional/derived/dynamic> | fact/inference/unknown | `ev-<stable-id>` |

## 动态依赖与失效规则

- <说明值的身份、租户、会话、版本、时间范围、刷新与失效条件>

## 状态与业务规则

- <状态、转移、条件必填或禁止规则>
- 普通业务校验：<说明真实后端 API 为权威，及 Agent 如何根据拒绝补充信息>
- 硬约束：<仅列出 Canonical Contract 已证明且由运行时强制的身份、确认、来源、事务、防重或未知结果约束；无则明确写无>

## 原客户端行为

1. <观察到的入口、客户端 API 调用与发生条件>
2. <可选分支、错误处理或局部目标的停止点>

<若本 feature 没有客户端，明确写“未发现客户端行为”，并在“能力来源与范围”中记录真实公开入口。>

## 结果与失败

- 成功、空结果与部分结果：<解释返回语义>
- 输入/结构错误：<如何纠正>
- 业务拒绝：<原始错误码/消息/字段细节及合理引导>
- 权限、上游/网络与响应契约错误：<是否可重试与停止条件>
- 未知写入结果：<如何停止、对账，且不自动重试>

## 相关能力

- `<tool-name>`：<独立价值、读/写分类、主要入参来源、输出和可选 handoff>

## 未知项

- <未知项、影响、所需证据，或本次不生成的能力>

## 证据索引

| 证据 ID | 来源 ID | 语义角色 | 断言级别 | 可移植定位符 |
| --- | --- | --- | --- | --- |
| `ev-<stable-id>` | `<sourceId>` | <semantic-role> | fact/inference/unknown | `<relative-path>#<symbol>` |

每个证据 ID 必须在 `canonical-contract.json.evidenceCatalog` 中恰好出现一次。不得写入绝对机器路径。
