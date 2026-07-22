# Code2Skill

Code2Skill 是一个可移植的 Agent Skill：让具备代码搜索、理解和测试能力的编程 Agent 从已有前端、后端或全栈代码中提取一个完整业务功能，生成可组合的 Function、MCP Tools 和 Observed Skill。

它不自研代码扫描器或新的 Coding Agent。代码搜索、理解、编辑和测试继续由 Producer 编程 Agent 完成；生成的 Skill 和 Tool 则可能运行在另一个 Consumer Host 中。Code2Skill 固化语义发现、证据规则、能力建模、完整交付契约与验收标准，但不把 Producer 的文件、终端或确认能力带入生成产物。

## 核心模型

```text
获授权的一个或多个源码根目录
   ↓ Producer 编程 Agent：按语义角色追踪证据
Portable Core
   ├── Canonical Contract   唯一业务事实来源
   ├── Goal Contract        目标、缺失信息与完成条件
   ├── Capability Graph     可复用能力、handoff 与硬前置条件
   └── references/feature-context.md / Observed Skill
   ↓ Runtime Profile
strict-export-v1 / node-stdio
   ↓ Consumer Host
渐进引导用户、组合 MCP 与 Skill、执行受保护的业务动作
```

核心原则：

> MCP Tool 提供可组合的执行能力；Skill 提供领域知识、选择策略和默认流程；Agent 根据用户目标决定本次组合；Schema、Handler、Server 或确定性 Workflow 强制不可绕过的约束。

Tool 数量不由页面、接口、请求或函数数量决定，而由独立业务语义、调用价值、契约稳定性和安全复用边界决定。

对客户端功能，Function 和 MCP 的候选能力面以客户端实际发起的后端 API 为主；页面未调用的后端内部方法不会因为“被搜到”就自动暴露为 Tool。授权范围内的后端源码、协议和测试用来补充核对参数、动态值、权限、副作用、幂等与失败规则。如果它们不可用，仍可基于客户端已证明的 API 契约生成诚实的部分产物，但必须标明未知项和安全边界。

源码发现同样不依赖某种语言或固定分层。`DTO`、`Request`、`Schema`、函数参数、协议定义或运行时对象都可能承担“数据传输契约”这一语义角色；文件名和框架惯例只是定位线索，不是事实成立条件。

vNext 的完整产品与迁移设计见 [稳定产物架构](skills/code2skill/references/vnext-architecture.md)。

## 安装

安装位置由实际 Producer 或 Consumer 的 Skill discovery 机制决定。下面的命令使用通用 Agent ID，不把 Code2Skill 或生成产物绑定到某个 Agent 品牌：

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill \
  -a "$AGENT_ID" \
  -g \
  -y
```

本地开发时：

```bash
npx skills add . --skill code2skill -a "$AGENT_ID" -g -y
```

## 使用

在目标代码仓库中调用。若前端、后端、接口契约或测试位于不同仓库，请把所有允许搜索的源码根目录一并提供；Code2Skill 不会扫描整台机器猜测后端位置：

```text
使用 $code2skill，把 /knowledge 的客户端功能生成完整 strict-export-v1。
允许搜索的源码根目录：当前前端仓库、../service、../contracts。
请沿前后端真实调用链实现 MCP Tools、Observed Skill，并完成协议与运行时验证。
```

目标单位是一个可验证的业务 feature，不要求一定存在前端页面。对于 API、RPC、消息消费者、定时任务或后端编排等 feature，`export-profile.json.featureSurface` 记录真实表面类型和稳定标识。vNext 不生成 `PAGE.md`，也不使用 `pageRoute`；业务背景统一写入 `references/feature-context.md`。旧包中的 `PAGE.md/pageRoute` 只是遗留兼容格式，不是 vNext 主产物。

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
├── SKILL.md
├── MCP.zh-CN.md
├── MCP-SETUP.md
├── references/
│   ├── feature-context.md
│   └── capability-contracts.json # Canonical 派生的文档事实与证据索引
├── function-core/
│   ├── index.mjs            # 自包含命名 Function 实现
│   ├── capability-bundle.json
│   └── schema-contract.json # Canonical 派生的 Function 输入/输出与条件规则
├── mcp-tool/
│   ├── index.mjs            # 可读的逐 Tool MCP adapter
│   ├── runtime.mjs          # 自包含 MCP SDK runtime
│   └── schema-contract.json # 与 Function 完全相同的 MCP Schema 契约
├── portable-workflow-guard.mjs # 仅存在不可绕过的硬约束时需要
├── portable-error-normalizer.mjs # 结构化错误与未知结果的审阅实现
├── workflow.json              # 仅旧版兼容包使用；vNext 禁止双重真相
├── preflight-report.json
├── approval-audit.json
├── live-verification.json
└── export-manifest.json
```

这不是三份说明文档：包内必须有独立命名 Function、可执行 MCP Server、逐 Tool 中文契约、真实检查记录和全文件完整性清单。当前 `strict-export-v1` 明确采用 `node-stdio` Runtime Profile；它是默认实现，不是 Portable Core 的唯一实现。

生成 Skill 不是死板的页面操作脚本。它应先识别用户目标，复用已经取得且仍有效的信息，只补问或查询当前缺失项；用户只要部分结果时可以提前停止，信息已经齐全时也不应重复调用。派生值和动态值只能由明确能力或可信运行环境提供，不能为了省一次调用而让用户自报。Agent 可以临时组合契约兼容的 MCP Tool 和 Skill；源码中未出现的新组合会标记为 `derived composition`，写入组合仍受运行时硬约束保护。

Canonical Contract 中可执行的副作用、请求绑定、输出/成功条件、条件规则和动态策略，都必须引用属于该操作且语义匹配的事实证据，不能靠“接口存在”或借用另一条操作的证据补齐。Goal 的每项信息也有 Schema 和 `supplies` 映射，明确它最终进入哪个 Capability 输入；条件依赖必须可解析且无环。当前新取得的信息用 `acquiredNow` 标记，复用缓存信息则逐项满足 `reuseWhile` 并提交 `reuseProof`，不能只声称 `fresh: true`。

输入输出类型以前端真实适配后的 API 边界和可执行传输契约为准，后端类型、序列化器与测试用于补充可空性等信息；单次运行样本只做验证，不能把一次 `null` 收窄成永久的 null-only 类型。vNext 区分“字段可缺省”和“值可为 null”，输出 Schema 支持一个真实类型加 `null` 的标准 nullable 联合类型。

普通业务校验以真实后端 API 为权威边界，Function/MCP 不需要重写一份容易漂移的后端规则。运行时应保留可机器区分的业务、权限、上游、网络和未知结果错误，使 Agent 能解释、补充信息或安全地重试。只有身份绑定、可信确认、附件来源、防重和未知写入结果等确实不能绕过的约束，才生成确定性 Guard；此时 `hardWorkflowEvidence` 必须分别证明受保护值的产生、最终请求绑定和派发前强制检查。仅有页面确认框和普通 POST 时保持后端权威写能力，不虚构 Host Guard。每条硬 Workflow 通过 Canonical `capabilityIds` 明确列出全部成员，Host 验证不能只检查入口能力。

当客户端正常通过上游 Tool 取得某个值、但目标接口是否允许省略仍未证明时，Canonical 用 `targetRequiredness: unproven` 明确保留这项疑问。公开 Schema 继续保持可选，生成 Skill 必须推荐正常 provider 并说明最终由目标 API 决定；验证矩阵会列出问题并要求受控缺省测试，但不会凭页面顺序把它升级为必填或 Host Guard。源码已明确允许省略时则标为 `proven-optional`。

当源码证明业务需要附件时，Code2Skill 生成业务上传、返回结果和下游绑定所需的 Function、MCP、Skill 说明和测试。上传结果必须通过同一个 Canonical Contract 同步绑定到下游输入、handoff、能力图和真实请求，不能退化为用户自报的 URL 或 token；STS/预签名凭证只是内部步骤，不是已完成的业务上传能力。附件的接收与提供属于 Consumer Host；Code2Skill 不实现聊天接入、文件下载或特定平台适配。不透明 Host 授权引用不能直接当作文件上传，生成实现必须经通用 `attachment-resolution` 边界取得受控内容或流；Canonical `attachments.contentBindings` 还必须逐项对应 `implementation.outputStepId` 中真实的 body/multipart 上传字段，并引用共同的事实级请求构造、序列化或传输契约证据。

当前可移植的不透明授权边界一次 Tool 调用处理一个附件；多个附件重复调用上传 Tool，再把各次返回的业务上传结果组合到下游请求。这样每个授权、元数据、确认和未知结果都能独立绑定与验证。

## 安装生成产物

生成 Skill 可使用通用命令安装：

```bash
npx skills add ./generated/code2skill/<feature-id> -a "$AGENT_ID" -g -y
```

这个命令只安装 Skill 知识层，不会启动或注册 MCP，也不会注入认证信息。每个 vNext 包都必须在 `MCP-SETUP.md` 单独说明 MCP 启动命令、Host 注册所需的 command/args、环境变量、认证注入与连通验证。“Skill 已安装”、“MCP 已连通”和“真实业务已验证”是三个独立状态。

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

使用独立临时副本运行 MCP 协议探针：

```bash
python3 skills/code2skill/scripts/probe_mcp.py \
  generated/code2skill/<feature-id> \
  --call /path/to/valid-tool-call.json \
  --error-call /path/to/execution-error-tool-call.json \
  --dry-run-call /path/to/dry-run-tool-call.json
```

该探针会验证 `initialize`、`tools/list`、未知 Tool 协议错误、每个 Tool 的无效入参拒绝（缺少必填项，或零入参 Tool 的额外字段）、成功调用和一条真正到达 Tool handler 的结构化执行错误，以及每个写 Tool 的 dry-run。它精确比较 Canonical 派生的完整输入/输出 Schema 和四个 annotations，按输出 Schema 验证成功结果，并要求 `content` 是与 `structuredContent` 一致的 JSON 文本投影。dry-run 还必须原样返回已验证输入和完整操作策略；零外部调用仍由带 dispatch 计数器的 Function/Guard 行为测试证明。复制后的 MCP 不能依赖源仓库的 `node_modules`。

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

每个 Capability 的最低 `checkId` 由 Canonical Contract 机械推导；passed phase 少一项就不能收口。附件 runtime proof 还要精确绑定 Canonical `stepId/location/path`，其 `traceEvidenceHash` 与检查的 `evidenceHash` 必须是同一份 trace 的 SHA-256。`hostVerified` 只在 Host phase 通过且兼容性为 `enabled` 时成立。URL 使用标准 JSON Schema `format: "uri"`。Tool catch 必须以精确的 `normalizeToolError(error, <literal Canonical operationPolicy>)` 两参数形式调用错误规范化器；写 Function 只有在明确收到后端拒绝或确定性前置拒绝时才标记 `outcomeKnown: true`，传输错误及其他未标记写错误一律按不可重试的 `UNKNOWN_DISPATCH_OUTCOME` 处理。模块加载也不能触发业务网络、文件、进程、上传或派发副作用。

`verification-matrix.json.reviewItems` 会从具体的 `missingEvidence`、未证明的 `targetRequiredness`、未解决冲突和 Host 缺失要求机械生成，并给出稳定问题引用、当前降级状态和通用建议动作；`approval-audit.json` 同步保留每项能力的原因和问题引用。校验器不接受手写警告替代这些事实，也不会因为写了一条风险备注就把错误类型、残缺附件链或虚构 Guard 判成可用。

`--live-input` 与 `--live-result` 按顺序成对，可重复传入，也可在一个文件中使用 `capabilities` 数组批量提供。每条 vNext live 证据都带 `capabilityId`，输入必须包含真实 Canonical Tool 名称，结果必须是成功且满足输出契约的 MCP 结果。只有拥有自身匹配 live pair 的 Capability 才能升级为 `runtime-verified`；一次只读调用不能批准整个包。无法 live 验证时，相关能力保持 `requires-review`。旧版 aggregate report 和单一 live pair 只兼容没有 Canonical Contract 的单个只读 Tool，不能用于 vNext、多 Tool 或写能力。

Finalizer 会把每个 passed runtime check 的 `toolName/inputHash/resultHash` 与对应 live pair 逐项核对。最终校验失败时会恢复进入 finalization 前的审计文件，不会把一套看似已批准但实际无效的 receipt、matrix、approval 或 manifest 留在候选包中。

运行仓库测试：

```bash
python3 -m unittest discover -s tests -v
```

## 仓库边界

Code2Skill 只包含通用建模规范、模板、派生器、校验器和虚构合成测试。目标项目的代码、接口路径、字段、枚举、业务名称、日志、私有评测器、案例答案、Golden、fixture、业务常量和运行时密钥都只能在仓外测试时读取或注入，不能复制进本仓库。真实案例只能先抽象成跨项目规则，再用无业务含义的合成数据回归。

Skill 遵循 [Agent Skills specification](https://agentskills.io/specification)。安装命令使用 [vercel-labs/skills](https://github.com/vercel-labs/skills)。MCP 产物遵循目标项目声明的 MCP SDK 与协议版本。
