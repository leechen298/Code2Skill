# Code2Skill

Code2Skill 是一个可移植的 Agent Skill：让具备代码搜索、理解和测试能力的编程 Agent 从已有前端、后端或全栈代码中提取一个完整业务功能，生成可组合的 Function、MCP Tools 和 Observed Skill。

它不自研代码扫描器或新的 Coding Agent。代码搜索、理解、编辑和测试继续由 Producer 编程 Agent 完成；生成的 Skill 和 Tool 则可能运行在另一个 Consumer Host 中。Code2Skill 固化能力发现、运行实现和最低稳定性要求，但不把 Producer 的文件、终端或确认能力带入生成产物。

## 默认模型

```text
获授权的前端/后端代码
   ↓ Producer 编程 Agent
精简 core-export-v1
   ├── Function Core        业务执行
   ├── MCP Tools            标准调用接口
   ├── one or more Skills   每个主要用户目标一份独立引导
   └── runnable tests       离线行为保障
   ↓ Consumer Host
安装 Skill、注册 MCP、渐进完成用户目标
```

核心原则：

> MCP Tool 提供可组合的原子能力；每个 Skill 服务一个主要用户目标；Agent 决定是否调用、如何传参、如何理解结果，以及继续调用还是向用户补问。Code2Skill 负责准确组装请求并尽量完整传递响应，不替 Agent 预判业务结果。

Tool 数量不由页面、接口、请求或函数数量决定，而由独立业务语义、调用价值、契约稳定性和安全复用边界决定。

对客户端功能，Function 和 MCP 的候选能力面以客户端实际发起的后端 API 为主；页面未调用的后端内部方法不会因为“被搜到”就自动暴露为 Tool。授权范围内的后端源码、协议和测试默认只用于补齐公开的 Request/Response、鉴权边界、枚举和附件接口；合同足够时停止，不追踪完整 Service、副作用和业务校验。只有公开契约矛盾、操作明显高风险或用户明确要求时才继续深入。如果后端源码不可用，仍可基于客户端已证明的 API 契约生成诚实的部分产物，并标明未知项和运行边界。

源码发现同样不依赖某种语言或固定分层。`DTO`、`Request`、`Schema`、函数参数、协议定义或运行时对象都可能承担“数据传输契约”这一语义角色；文件名和框架惯例只是定位线索，不是事实成立条件。

默认生成不制作完整源码审计档案。需要 Canonical/Goal Contract、Host compatibility、verification matrix、live receipt 或 finalization 时，显式选择兼容的 `strict-export-v1`。严格架构见 [稳定产物架构](skills/code2skill/references/vnext-architecture.md)。

精简包会在 `package.json` 中声明 `code2skill.profile=core-export-v1`，用于防止它被严格审计流水线误当成旧包迁移。Function Core 导出开放的 Zod 输入 Schema 供 MCP 描述参数；默认不声明输出 Schema，避免真实响应在到达 Agent 前因类型、`null` 或字段差异被拦截。

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
使用 $code2skill，把 /knowledge 的客户端功能生成为默认精简能力包。
允许搜索的源码根目录：当前前端仓库、../service、../contracts。
请以前端实际调用接口为能力面，实现 Function、MCP、Skill 和离线测试；
后端只用于补齐公开 Request/Response，真实接口验证保持关闭。
```

用户给出的页面、目录或接口只是搜索范围。Code2Skill 先识别其中可以独立完成的主要用户目标：单一目标生成一个 Skill，多个目标分别生成 Skill，并共享同一套 Function/MCP。API、RPC、消息消费者、定时任务或后端编排同样可以生成；默认不生成 `PAGE.md`，复杂业务背景才写入可选的 `references/feature-context.md`。

也可以用于纠正已有页面级大 Tool：

```text
使用 $code2skill 检查并修正当前生成包，按独立业务能力重新拆分，
更新 Function、MCP、Skill 和必要的冒烟测试，不扩展为严格审计。
```

默认输出：

```text
generated/code2skill/<feature-id>/
├── SKILL.md                  # 单一主要目标
├── skills/                   # 多个主要目标时替代根 SKILL.md
│   ├── <goal-a>/SKILL.md
│   └── <goal-b>/SKILL.md
├── MCP-SETUP.md
├── package.json
├── function-core/
│   └── index.mjs
├── mcp-tool/
│   └── index.mjs
├── portable-agent-result.mjs
├── tests/
│   └── *.test.mjs
└── references/
    └── feature-context.md   # 仅在复杂业务确有必要时生成
```

根 `SKILL.md` 与 `skills/*/SKILL.md` 二选一，不能同时存在，避免根 Skill 遮蔽独立目标 Skill。

多目标包中，每个 Skill 需要的参考资料放在它自己的 `references/` 下，避免安装后依赖父目录文件；根 `references/feature-context.md` 只用于单一根 Skill。

默认包不携带重复 Contract、证据目录、Host 报告、MCP 长文档、验证矩阵、收据和 manifest。Function、MCP、Skill 与可运行测试是主要产物；MCP 通过 `package.json` 使用官方 SDK 和 Zod，不再默认内嵌庞大的 SDK bundle。

精简包使用以下离线校验：

```bash
cd generated/code2skill/<feature-id> && npm install
cd -
python3 skills/code2skill/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

校验关注最小运行边界：包结构、依赖声明、JavaScript 语法、真实 MCP `initialize + tools/list` 和包内冒烟测试。它不解析 Function/MCP 的源码模板，因此允许定义表注册、共享 Schema 和共享 wrapper。默认以清理业务凭证后的固定 `node --test` 命令运行测试，不执行候选声明的 npm lifecycle；它不提供网络隔离，因此测试必须 mock 外部请求且不得调用真实业务接口。它不要求非法参数矩阵或逐 Tool MCP 调用，也不生成、验证审计证明或声称业务正确。

生成 Skill 不是死板的页面操作脚本。每个 Skill 独立服务一个主要目标，并描述该目标自己的调用链；共享 Tool 只是原子能力，不形成跨 Skill 的全局流程。Agent 可以复用已有信息、只补问当前缺失项、跳过不需要的 Tool、根据响应修正调用，或者先与用户沟通。

字段含义必须按来源、赋值过程和最终用途判断，不能按名称猜测。同名的查询参数和写入参数如果语义不同，应在公共 Function/MCP/Skill 中分别使用能表达“目录筛选”和“最终操作”等真实用途的名称，内部再映射回 API 原字段。公共能力也不等于全局前置条件；每个写能力只采用其直接客户端调用链证明的前置步骤。

输入 Schema 主要用于提示 Agent 已知参数：使用开放对象，业务字段默认采用带说明的宽松值，不生成会提前拦截常见类型差异、`null`、缺失或额外参数的严格规则。Function 仍按源码证明的字段来源和用途组装固定接口；额外参数保留给 callback 和 Agent，但没有可证明的发送位置时不能猜测位置或假装已经发送。

core 包默认不声明输出 Schema。基于 `fetch` 的 Function 收到任何 HTTP 状态都返回 `httpStatus` 和未经截断、未经 JSON 转换的完整 `bodyText`。如果所用客户端会因 4xx/5xx 抛出带响应的异常，Function 仍将其中的状态和响应数据还原为普通结果。400、500、业务 `code`、非 JSON、长正文、`null` 和缺失字段都交给 Agent；Code2Skill 不添加成功、失败、是否重试或结果是否未知等判断。

普通业务校验以真实后端 API 为权威边界，Function/MCP 不重写整套后端规则。已取得 HTTP 响应时作为普通 Tool 结果原样传递；只有没有取得响应的底层异常才使用 MCP `isError` 传递其原始可序列化信息，不生成 Code2Skill 自己的错误分类。Agent 决定如何解释、补问、修正或再次调用。

附件接收属于 Consumer Host；Code2Skill 只生成源码证明的业务上传与下游绑定。优先使用 `attachmentRef` 等不透明引用；只有 Host 明确保证来源与可访问性时，才把运行时注入的路径公开为 `hostFilePath`。这是一项部署信任前提，不是 Skill 文案能证明的安全保证；条件不满足时应报告附件运行条件未满足。Code2Skill 不实现消息接入、下载或通用 Host 沙箱。如果只能取得 STS/预签名凭证而无法完成上传，应明确说明目标未闭环，不能接受用户自报 URL 来伪装完成。

## 安装生成产物

生成 Skill 可使用通用命令安装：

```bash
npx skills add ./generated/code2skill/<feature-id> -a "$AGENT_ID" -g -y
```

这个命令只安装 Skill 知识层，不会安装依赖、启动或注册 MCP，也不会注入认证信息。每个生成包都在 `MCP-SETUP.md` 单独说明 `npm install`、MCP 启动、Host 注册和认证环境变量。“Skill 已安装”、“MCP 已连通”和“真实业务已验证”是三个独立状态。

## 可选 strict-export-v1

只有用户明确要求完整证据链、Canonical/Goal Contract、Host compatibility、逐能力验证、live receipt、finalization、manifest、外部 evaluator 或合规审计时，才启用 `strict-export-v1`。不要从“稳定”“可用”自动推断严格审计。

严格模式保留现有完整产物、校验器和分阶段流水线，旧包继续兼容；它不再是默认交付。

### Strict Producer 流水线

严格模式拆成五个显式阶段，由 `skills/code2skill/scripts/run_pipeline.py` 驱动：`analyze`（源码范围、证据解析与 Canonical Contract 校验）→ `generate`（`compile_artifacts.py` 从 Canonical Contract 确定性编译 Function 核心与 MCP adapter，再派生全部视图并刷新文档 SHA 标记；Tool 标题/描述来自 Agent 编写的 `authoring/tool-docs.json`，绝不编造文案，不可推导项报精确原因）→ `verify`（仅离线行为验证）→ `runtime-verify`（显式 opt-in 的真实环境验证，默认关闭）→ `finalize`（证据门控收口与最终报告）。

```bash
python3 skills/code2skill/scripts/run_pipeline.py init \
  generated/code2skill/<feature-id> \
  --source-map client=/authorized/client-root \
  --source-map service=/authorized/service-root
python3 skills/code2skill/scripts/run_pipeline.py run generated/code2skill/<feature-id>
python3 skills/code2skill/scripts/run_pipeline.py status generated/code2skill/<feature-id>
python3 skills/code2skill/scripts/run_pipeline.py diagnose generated/code2skill/<feature-id>
```

- 默认流程只完成 `generated + behavior-verified`，且只运行本仓库维护的固定验证步骤：`validate_artifacts.py --pre-finalize` 静态校验、`probe_mcp.py --offline` 协议测试（initialize/tools-list/协议错误/dry-run，使用脱敏无凭证环境，但它不是网络隔离证明）、`run_vectors.py` 从 Canonical Contract 确定性派生的 Function/Goal/mock-dispatcher 向量。流水线不执行候选方声明的任意命令；本轮无法机械证明的检查（动态值、附件、组合、条件谓词）保留 `requires-review`，不用脚本硬凑。真实读取必须用 `--enable-runtime-verify` 显式开启，由仓库固定 live 调用器执行真实 `tools/call`；业务入参绝不编造——每次调用使用 `verification/cases/live/<capabilityId>.json` 中调用方已脱敏的显式用例（零入参 Tool 才有机械空用例，缺失即 `not-run`）。真实写入还要在同一行命令上逐项 `--authorize-write <capabilityId>`。启用和授权只对本次调用生效，绝不写入状态；一旦输入变化，旧 live 证据及其结论会在 finalize 之前作废。
- `init` 先判定 `fresh`、`migrate` 或 `changed-only` 并输出迁移/变更摘要；`migrate` 必须先审阅摘要并用 `--acknowledge-migration` 确认后才允许 `run`，旧产物不会被静默删除或覆盖。
- 运行状态保存在候选包之外的 `<feature-id>.producer-state/` sidecar；各阶段按输入指纹内容寻址，输入未变化的已完成阶段不会重跑，上游变化只失效受影响的下游阶段，中断后可安全续跑。上游阶段失败时，所有下游已完成阶段会被标记为 `invalidated`（陈旧证明），报告不再沿用旧结论；`--only` 只允许跳过“所选阶段上游且已完成且指纹当前”的阶段。finalize 会保存自身输出 Hash，receipt/manifest 被删除或篡改后必定重跑。
- 向量证据、日志、live 证据对和报告都持久化在 `<state>/verification/`；顺序固定为执行 → 持久化 → 计算 Hash → 生成报告 → finalize；Hash 之后修改证据会被 finalize 拒绝，证据路径经符号链接解析后也必须留在 verification 目录内；报告、preflight、receipt 和 manifest 不引用 `/tmp` 等临时文件；证据守卫按 capability/workflow 精确匹配。Host 验证本轮不进入流水线，仍作为 verification matrix 中的独立状态报告。
- `diagnose` 按根因/阶段聚合错误（source/topology、canonical、capability、function/mcp、documentation、verification、finalization），优先输出阻断派生的根因并汇总被抑制的下游错误（`--full` 查看全部）；`status` 与最终报告分别列出 `generated`、`behavior-verified`、`runtime-verified`、`host-verified`、`deployed`，以及每个阶段的耗时、跳过依据、失败原因和下一步。
- 耗时基准：`python3 tests/benchmark_pipeline.py` 测量同一合成候选的首次、增量（一个契约字段变化）与无变化三种运行，输出各阶段耗时与跳过明细。基准只覆盖确定性流水线（契约→编译→验证→收口秒级完成）；Agent 的源码阅读与契约编写时间恰是被避免重复的部分，增量与无变化运行中 Agent 触碰文件数与重读源码数均为 0。

### Strict 校验与收口

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
