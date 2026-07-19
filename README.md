# Code2Skill

Code2Skill 是一个可移植的 Agent Skill：让具备代码搜索、理解和测试能力的编程 Agent 从已有前端、后端或全栈代码中提取业务背景，生成可组合的 MCP Tools，并还原原产品的 Observed Skill。

它不自研代码扫描器或新的 Coding Agent。代码搜索、理解、编辑和测试继续由 Producer 编程 Agent 完成；生成的 Skill 和 Tool 则可能运行在另一个 Consumer Host 中。Code2Skill 固化语义发现、证据规则、能力建模、完整交付契约与验收标准，但不把 Producer 的文件、终端或确认能力带入生成产物。

## 核心模型

```text
获授权的一个或多个源码根目录
   ↓ Producer 编程 Agent：按语义角色追踪证据
Portable Core
   ├── Canonical Contract   唯一业务事实来源
   ├── Goal Contract        目标、缺失信息与完成条件
   ├── Capability Graph     可复用能力、handoff 与硬前置条件
   └── Feature Context / Observed Skill
   ↓ Runtime Profile
strict-export-v1 / node-stdio
   ↓ Consumer Host
渐进引导用户、组合 MCP 与 Skill、执行受保护的业务动作
```

核心原则：

> MCP Tool 提供可组合的执行能力；Skill 提供领域知识、选择策略和默认流程；Agent 根据用户目标决定本次组合；Schema、Handler、Server 或确定性 Workflow 强制不可绕过的约束。

Tool 数量不由页面、接口、请求或函数数量决定，而由独立业务语义、调用价值、契约稳定性和安全复用边界决定。

源码发现同样不依赖某种语言或固定分层。`DTO`、`Request`、`Schema`、函数参数、协议定义或运行时对象都可能承担“数据传输契约”这一语义角色；文件名和框架惯例只是定位线索，不是事实成立条件。

vNext 的完整产品与迁移设计见 [稳定产物架构](skills/code2skill/references/vnext-architecture.md)。

## 安装

安装位置由实际 Producer 或 Consumer 的 Skill discovery 机制决定。下面的命令只是安装工具示例，不代表 Code2Skill 或生成产物绑定这些 Agent 品牌。

```bash
npx skills add leechen298/Code2Skill --skill code2skill
```

全局安装到 Codex 和 Claude Code：

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill \
  --global \
  --agent codex \
  --agent claude-code
```

本地开发时：

```bash
npx skills add . --skill code2skill --global --agent codex --yes
```

## 使用

在目标代码仓库中调用。若前端、后端、接口契约或测试位于不同仓库，请把所有允许搜索的源码根目录一并提供；Code2Skill 不会扫描整台机器猜测后端位置：

```text
使用 $code2skill，把 /knowledge 的客户端功能生成完整 strict-export-v1。
允许搜索的源码根目录：当前前端仓库、../service、../contracts。
请沿前后端真实调用链实现 MCP Tools、Observed Skill，并完成协议与运行时验证。
```

目标单位是一个可验证的业务 feature，不要求一定存在前端页面。对于只有 API、RPC、消息消费者、定时任务或后端编排的 feature，`export-profile.json.featureSurface` 记录真实表面类型和稳定标识；`pageRoute` 仅为 `node-stdio` 兼容文档键，使用 `/__code2skill__/features/<feature-id>`，不得伪装成真实应用路由或运行时请求地址。

也可以用于纠正已有页面级大 Tool：

```text
使用 $code2skill 审计当前实现，按独立业务能力重新拆分，
重建 Function、MCP、Skill、测试和当前 Golden；旧结果只保留为 superseded 历史。
```

默认输出：

```text
generated/code2skill/<feature-id>/
├── export-profile.json
├── source-topology.json
├── canonical-contract.json
├── goal-contract.json
├── consumer-requirements.json
├── host-profile.json
├── host-compatibility-report.json
├── verification-matrix.json
├── capability-bundle.json
├── capability-draft.json
├── PAGE.md
├── SKILL.md
├── MCP.zh-CN.md
├── function-core/
├── mcp-tool/
├── portable-workflow-guard.mjs # vNext 写能力需要
├── workflow.json              # 仅旧版兼容包使用；vNext 禁止双重真相
├── preflight-report.json
├── approval-audit.json
├── live-verification.json
└── export-manifest.json
```

这不是三份说明文档：包内必须有独立命名 Function、可执行 MCP Server、逐 Tool 中文契约、真实检查记录和全文件完整性清单。当前 `strict-export-v1` 明确采用 `node-stdio` Runtime Profile；它是默认实现，不是 Portable Core 的唯一实现。

生成 Skill 不是死板的页面操作脚本。它应先识别用户目标，复用已经取得且仍有效的信息，只补问或查询当前缺失项；用户只要部分结果时可以提前停止，信息已经齐全时也不应重复调用。Agent 可以临时组合契约兼容的 MCP Tool 和 Skill；源码中未出现的新组合会标记为 `derived composition`，写入组合仍受运行时硬约束保护。

## 校验与收口

生成阶段：

```bash
python3 skills/code2skill/scripts/validate_artifacts.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --pre-finalize
```

每个 `sourceId=/绝对路径` 必须与 `source-topology.json` 一一对应；可重复传入前端、后端、协议和测试仓库。只有单根或共同工作区内的旧包，才使用 `--source-root` 兼容模式。校验器只解析这些明确映射，不做机器级搜索。

完成真实单元、协议和 live 调用后：

```bash
python3 skills/code2skill/scripts/finalize_export.py \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root \
  --verification-report /path/to/executed-checks.json \
  --live-input /path/to/read-capability-input.json \
  --live-result /path/to/read-capability-result.json \
  --live-input /path/to/write-capability-input.json \
  --live-result /path/to/write-capability-result.json
```

vNext 的 `--verification-report` 必须是符合 [`verification-report.schema.json`](skills/code2skill/assets/verification-report.schema.json) 的 JSON：`contractId` 与 Canonical Contract 相同，每个 Canonical Capability 和 Workflow 恰好一行，Capability 分别记录 `behavior/runtime/host`，Workflow 分别记录 `bypass/runtime/host`。每个 passed phase 都要给出实际执行的命令、退出码和证据 SHA-256；passed runtime check 还必须绑定 Canonical `toolName` 以及匹配 live pair 的 `inputHash/resultHash`，passed bypass check 必须证明 `zeroExternalWrites: true`。未运行的 phase 明确写 `not-run`，不能省略整行。

`--live-input` 与 `--live-result` 按顺序成对，可重复传入，也可在一个文件中使用 `capabilities` 数组批量提供。每条 vNext live 证据都带 `capabilityId`，输入必须包含真实 Canonical Tool 名称，结果必须是成功且满足输出契约的 MCP 结果。只有拥有自身匹配 live pair 的 Capability 才能升级为 `runtime-verified`；一次只读调用不能批准整个包。无法 live 验证时，相关能力保持 `requires-review`。旧版 aggregate report 和单一 live pair 只兼容没有 Canonical Contract 的单个只读 Tool，不能用于 vNext、多 Tool 或写能力。

Finalizer 会把每个 passed runtime check 的 `toolName/inputHash/resultHash` 与对应 live pair 逐项核对。最终校验失败时会恢复进入 finalization 前的审计文件，不会把一套看似已批准但实际无效的 receipt、matrix、approval 或 manifest 留在候选包中。

运行仓库测试：

```bash
python3 -m unittest discover -s tests -v
```

## 仓库边界

Code2Skill 只包含通用建模规范、模板、派生器、校验器和虚构合成测试。目标项目的代码、接口路径、字段、枚举、业务名称、日志、私有评测器、案例答案、Golden、fixture、业务常量和运行时密钥都只能在仓外测试时读取或注入，不能复制进本仓库。真实案例只能先抽象成跨项目规则，再用无业务含义的合成数据回归。

Skill 遵循 [Agent Skills specification](https://agentskills.io/specification)。安装命令使用 [vercel-labs/skills](https://github.com/vercel-labs/skills)。MCP 产物遵循目标项目声明的 MCP SDK 与协议版本。
