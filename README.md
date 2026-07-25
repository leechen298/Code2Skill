# Code2Skill

Code2Skill 是一个可移植的 Agent Skill：让具备代码搜索、理解和测试能力的编程 Agent，从授权的前端、后端或全栈代码中提取业务功能，生成精简、可运行、可安装的 Function、MCP Tools 和 Agent Skills。

```text
授权源码
  ↓ Producer 编程 Agent
core-export-v1
  ├── Function Core       组装并执行真实业务请求
  ├── MCP Tools           提供可组合的原子能力
  ├── one or more Skills  每个主要用户目标一份引导
  └── runnable tests      离线技术保障
  ↓ Consumer Agent / Host
渐进收集信息并完成用户目标
```

核心原则：

> Function/MCP 负责准确提供能力和尽量完整传递响应；Skill 负责目标引导；Agent 决定是否调用、如何补问、如何理解结果和下一步做什么。

- 客户端功能以前端实际调用的后端 API 为主要能力面；后端源码默认只用于补齐公开 Request/Response、枚举、认证和附件接口。
- 用户指定的页面或目录是搜索范围，不是一个固定 Skill；多个独立目标会生成多个 Skill，并共享必要的 Function/MCP。
- 源码明确的字段来源和确定性转换进入 Function；普通业务判断和后端反馈交给调用 Agent。
- 默认生成精简 `core-export-v1`；只有明确需要完整证据链或合规审计时才使用 `strict-export-v1`。

## 安装

使用通用 Agent Skills CLI 一次安装三个 Skill：

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill-generate code2skill-review-flow code2skill-review-source \
  --agent "$AGENT_ID" \
  --global \
  --yes
```

本地开发时把仓库地址替换为 `.`。三个 Skill 可以独立使用：

- `code2skill-generate`：生成 Function、MCP、业务 Skill 和离线测试。
- `code2skill-review-flow`：从源码独立识别主要目标，检查代表性标准路径。
- `code2skill-review-source`：对指定目标或能力深入检查字段来源、转换、调用链和关键依赖。

旧生成名 `code2skill` 已更名为 `code2skill-generate`，旧名称不再保留为重复入口；`code2skill-review` 也已拆分。三个 Skill 不强制串行，日常生成只需 `code2skill-generate`。

`npx skills add` 只安装 Skill。生成包的依赖安装和 MCP 注册是独立步骤，详见[安装与 MCP 注册](docs/installation.md)。

## 快速使用

在目标代码仓库中调用，并明确所有允许搜索的源码根目录：

```text
使用 $code2skill-generate，把 /knowledge 的客户端功能生成为默认精简能力包。
允许搜索的源码根目录：当前前端仓库、../service、../contracts。
请以前端实际调用接口为能力面，实现 Function、MCP、Skill 和离线测试；
后端只用于补齐公开 Request/Response，真实接口验证保持关闭。
```

按需独立复核：

```text
使用 $code2skill-review-flow，审核 <生成包路径> 的主要目标和代表性标准路径是否闭环。

使用 $code2skill-review-source，审核 <生成包路径> 中 <指定 Skill 或能力> 与授权源码的请求语义是否一致。
```

## 默认产物

```text
generated/code2skill/<feature-id>/
├── SKILL.md 或 skills/*/SKILL.md
├── function-core/index.mjs
├── mcp-tool/index.mjs
├── portable-agent-result.mjs
├── tests/
├── package.json
├── MCP-SETUP.md
└── references/feature-context.md  # 复杂业务才生成
```

默认包不携带重复 Contract、证据目录、Host 报告、验证矩阵或收据。完整产物规则见 [`core-export-v1`](docs/core-export.md)。

## 离线验证

```bash
cd generated/code2skill/<feature-id> && npm install
cd -
python3 skills/code2skill-generate/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

验证覆盖包结构、依赖声明、JavaScript 语法、MCP `initialize + tools/list` 和包内测试；默认不调用真实业务接口。

## 生成质量评估

同一私有、多目标源码范围的三次独立生成结果。业务内容保持匿名，但生成模型/运行配置公开：

| 生成模型/运行配置 | 主流程完成度 | 业务语义精确度 | 综合参考分 |
|---|---:|---:|---:|
| Codex（Ultra） | **9.6** | **9.0** | **9.4** |
| Kimi Code（K3） | **9.5** | **8.0** | **8.9** |
| Codex（High） | **9.0** | **7.5** | **8.4** |

- **主流程完成度**：用户能否通过 Skill 与 Function/MCP 完成代表性工作，允许 Agent 处理可恢复差异。
- **业务语义精确度**：生成结果是否准确还原接口、字段来源、确定性转换和目标分支。

综合参考分采用 `主流程 × 60% + 业务语义 × 40%`，反映当前“先保证主要工作可用”的产品目标。评估从源码重新建立基线，不采用生成结果自己的 Review 报告，也没有调用真实业务接口。完整口径、方法、扣分规则、规模与边界见[评估报告](docs/evaluation.md)。

## 文档

- [文档索引](docs/README.md)
- [安装 Skill、依赖与注册 MCP](docs/installation.md)
- [默认 `core-export-v1` 产物规范](docs/core-export.md)
- [可选 `strict-export-v1` 流水线](docs/strict-export.md)
- [生成模型与产物评估](docs/evaluation.md)
- [稳定产物架构](skills/code2skill-generate/references/vnext-architecture.md)

Skill 遵循 [Agent Skills specification](https://agentskills.io/specification)，安装使用 [vercel-labs/skills](https://github.com/vercel-labs/skills)。MCP 产物使用标准 stdio 或 Streamable HTTP 传输，不要求 Consumer Host 采用 Code2Skill 私有配置格式。
