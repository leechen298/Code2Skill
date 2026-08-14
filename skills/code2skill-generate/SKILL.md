---
name: code2skill-generate
description: 从已有前端、后端或全栈代码中提取业务功能，生成可运行、可安装的 Function、MCP 和 Agent Skill；适用于页面功能、接口功能、业务流程及已有生成结果的修正。
---

# Code2Skill

把已有应用的业务能力转为其他 Agent 可用 Function、MCP Tools 和 Skill。默认目标是生成一份小而可靠的运行包，不是为源码制作审计档案。

使用当前编程 Agent 搜索、理解和修改用户授权的代码；不要另建扫描器。生成包的 Consumer 可能不是当前 Agent，不得假设它能读取原仓库、Producer 机器文件或会话状态；Consumer Host 显式交给 Tool 的受控附件路径或附件引用除外。

## 默认生成结果

除非用户明确要求严格审计，默认只生成：

```text
generated/code2skill/<feature-id>/
├── SKILL.md                    # 只有一个主要目标时使用
├── skills/                     # 有多个主要目标时替代根 SKILL.md
│   ├── <goal-a>/SKILL.md
│   └── <goal-b>/SKILL.md
├── MCP-SETUP.md
├── package.json              # 当前 node-stdio profile 示例：包信息、运行脚本和依赖
├── function-core/
│   └── index.mjs             # 当前 node-stdio profile 示例
├── mcp-tool/
│   └── index.mjs             # 当前 node-stdio profile 示例
├── portable-agent-result.mjs # node-stdio profile 通用结果投影辅助库（readHttpResponse/httpResultFromError 仅 HTTP 使用）
├── tests/
│   └── *.test.mjs            # 当前 node-stdio profile 示例
└── references/
    └── feature-context.md     # 仅在业务背景无法简洁写入 SKILL 时生成
```

默认产物组成不变，扩展名、依赖、启动方式随 runtime profile；`core-export-v1` 由 `node-stdio` 实现。

根 `SKILL.md` 与 `skills/*/SKILL.md` 二选一。用户指定的页面或目录只是搜索范围：先识别其中可独立完成的主要用户目标。单目标生成根 Skill；多目标分别生成独立 Skill，共享同套原子 Function/MCP。不要按接口数量拆 Skill，也不用一个大 Skill 覆盖互不相同目标。

多个目标使用 `skills/<goal-id>/SKILL.md` 时，参考资料放对应 Skill 的 `references/` 中；不要让已安装 Skill 依赖父目录文件。根 `references/feature-context.md` 只适用于单一根 Skill。

不要在默认包中生成 Canonical/Goal Contract、Capability Graph、Host Profile、Verification Matrix、manifest、Hash 收据等审计文件、MCP 长文档或 live receipt。临时分析笔记/测试输出不进入交付包。

代码是后续维护依据：Function 是业务执行真相，MCP 是标准适配层，Skill 是 Agent 使用知识。避免用多份 JSON/长文档重复描述同一事实。

## 默认工作流程

### 1. 确定范围

- 从用户指定的页面、目录、接口、路由、符号或功能目标开始。
- 只搜索用户明确授权的源码根；不要扫描整台机器。未显式限定时沿同仓库直接 import/alias 追踪闭合依赖；跨仓库或“仅限这些根”不越界。缺失依赖记录符号/文件，不据此过早声明缺失。
- 把指定范围视为发现边界，先列出其中可独立触发、引导和完成的主要用户目标；它可能产生一个或多个 Skill。
- Skill 的单位是主要用户目标，不是目录、文件、接口或输入框。
- 先读取目标仓库规则和已有测试。

### 2. 目标决策边界

Producer 先在**工作记忆**中形成每目标最小临时图：用户目标 → 已知/缺失信息 → 查询/选择/校验 → 分支与停止条件 → 写入前展示/确认 → 写入 → 源码存在时的结果查询/对账。纯只读无写入节点；无源码证据不虚构。

节点角色（每节点恰一个）＝Agent 判断/追问/选择｜用户交互/确认｜可独立命名/调用/复用/停止的 MCP Tool｜Function 内部确定性步骤｜完成/停止/无法确认的结果边界。约束所有者（可叠加）＝后端权威｜Consumer Host 策略｜源码证明不可绕过的确定性 Guard。一个写入 Tool 可同时携带 Host 确认与 Guard，不得二选一。Guard 证据门槛见「设计能力」节；只存工作记忆，不生成中间文件、不进交付包。

### 3. 从真实调用入口确定能力面

源码中真实存在的业务调用入口是 Function/MCP 候选面。有客户端或 Consumer 时沿其调用链追踪；无客户端时从用户指定且源码证明可调用的公开 API、RPC、Service、消息或任务入口开始。只引入影响这些入口的逻辑：

- 调用目标与操作（HTTP：method/URL/query/header/body/multipart；RPC：service/method/arguments；消息/任务：destination/key/payload；应用内 Service：方法与运行上下文）；
- 调用方真正使用的响应字段、返回值、回执或任务 ID；
- 默认值、转换、动态选项、条件输入和错误处理；
- 用户目标、主要分支、停止点和提交前展示信息；
- 附件上传结果如何绑定后续调用。

不要因后端存在内部方法、任意 public 方法、Repository、消息消费者或定时任务就自动暴露 Tool，也不要把页面/请求/控件/输入框机械变 Tool。

页面写死的菜单、文案/配置优先写入 Skill 或可选 Feature Context。仅当本地数据可独立满足用户目标、需被多个能力复用，或需运行时读取时，才生成 Tool。

### 4. 有限核对传输契约

后端、协议或测试源码默认仅补齐公开传输契约：Request/Response、接口定义、Service 方法签名、消息/任务契约的结构与可空性；鉴权/身份边界/运行时上下文注入点；统一响应信封及公开的 `code`/`message`/`data` 等字段；明确公开的枚举及附件上传接口。合同足够生成时停止，不默认追踪 Service/持久化/消息/审批/下游 RPC/完整副作用/全部业务校验。

仅以下情况才继续深入：公开契约互相矛盾；操作具有明显金融/删除/发布/高风险影响；源码明确存在不可绕过的安全凭证/顺序；或用户明确要求深度审计。

普通业务是否接受调用，以真实后端调用入口为权威。不要在 Function 中复制整套后端规则或预判 HTTP 状态/业务字段。把后端响应或调用结果交给 Consumer Agent，由它判断、修正调用、补问或解释结果。

### 5. 设计能力

Tool 应表达可独立命名、调用、复用或停止的业务能力。按业务意义、输入输出稳定性/副作用拆分，而非按代码文件/HTTP 数量拆分。

拆出额外 Tool 的正面条件（满足一项即可）：中间结果改变后续调用/分支/参数；能独立完成部分目标或被复用；前后步骤权限/副作用/确认要求不同；中间阶段可停止/等待用户输入；写入后有源码证明的异步状态查询或对账。不拆 Tool 反面条件：仅为让模型多推理；请求组装/字段格式化/RAG 等确定性实现；无论中间结果下一步始终相同；拆开暴露无意义中间状态；多调用属不可分割事务。

一个 Tool 可调多个内部 API，一个 API 可支持多个业务 Tool，勿按接口数量机械映射。仅主要角色为 MCP Tool 的节点才拆为 Tool；不得把 Agent 判断/追问、用户确认或 Function 内部确定性步骤改名凑拆分。

对每能力只确定最小契约：稳定 operation identity（Tool 名、标题、调用目标、操作标识、版本/路由键）；公共输入到真实调用字段映射；已知参数名称、来源、用途及类型/顺序/序列化；下游 handoff 与下一步判断需要的响应字段/回执/任务 ID；绑定（HTTP：method/URL/query/header/body/multipart；RPC：service/method/arguments；消息/任务：destination/key/payload；应用内 Service：方法与运行上下文）；read/create/update/delete 副作用；认证、运行上下文与附件条件。routing/version/context、结果/异常/超时/重试边界由源码证明并由 Function 稳定还原。

HTTP 场景下，业务 API 基址属部署配置、非用户业务输入；其他场景下同类概念称「业务服务接入配置」。按独立服务声明环境变量，例如 HTTP 场景下 `CODE2SKILL_<FEATURE>_<SERVICE>_BASE_URL`；不得把基址公开成 Tool 参数，也不得把接入配置公开成参数，也不得把源码中测试/预发/生产域名或固定地址作默认值。源码证明的环境地址可在 `MCP-SETUP.md` 作部署参考，实际运行由 Consumer Host 显式注入。调用结果或后端响应动态给出的对象存储/回调/预签名地址不属于静态基址。

不要仅凭字段名判断语义；同名字段追踪来源、赋值与用途，语义不同用真实用途公共名并内部映射。对每个写能力及「查询→选择→后续调用」链做 source-binding：沿上游响应→调用方归一化→各下游 wire 追踪；同一上游值进多下游调用须逐点追踪「原始值→归一化值→各下游 wire」，不因语义相近或共用 Tool 复用表示；源码改写后的上游值须追踪归一化本身与各下游使用的归一化结果，不把原始表示当下游可用值。

客户端若将选中结果的多个字段或整行对象展开、合并进下游请求，建模为选中记录交接。下游只读少数字段时逐项公开；转发整行时使用业务命名的开放对象（如 `selectedOrder`）。Function 按源码顺序合并且保持显式覆盖关系。除非证据证明只传标识符等价，Skill 的标准示例必须传递该记录；省略能否接受仍交给后端判断。

MCP 必须声明输入 Schema，但默认是给 Agent 的参数说明，非业务拦截器。使用开放对象；已知业务字段优先用带说明的 `unknown().optional()`，不默认生成枚举/格式/范围/条件必填/严格类型。仅缺某值无法形成 URL/附件等传输结构时，才保留最低传输约束。接受额外参数，不设置 `additionalProperties: false` 或 strict object。Function 只按源码证明的绑定组装请求，不得用更窄 Schema/类型/本地规则阻止调用；额外参数保留给 callback 和 Agent，无发送位置时不得猜测或声称已发送。

默认不声明 `outputSchema`。Tool 描述/Skill 可说明已知响应字段，但 HTTP 状态/`null`/缺失字段/数字字符串/额外字段等真实变体必须先到 Agent。仅用户明确需机器强类型输出且公开契约足够稳定时，才添加开放、不会阻断已知变体的可选 `outputSchema`。

普通写接口默认由后端负责校验。只有源码明确证明存在不可绕过的身份、来源、事务、单次凭证或顺序约束时，才实现确定性 Guard；页面确认框、普通 POST、普通后端拒绝或共享查询不自动成为自定义 Host Guard 的证据。

### 6. 实现 Function 与 MCP

Producer 根据目标仓库现有实现选择方式，不在 Code2Skill 中预置框架专用生成器：

- **方式 A：可直接运行的薄包装。** 复用已有 HTTP、RPC、gRPC、SDK 或命令客户端，只封装参数映射、确定性转换、认证接入和结果传递。
- **方式 B：原运行时内包装。** 依赖注入、事务、拦截器、线程上下文或应用内 Service 场景下，在原项目技术栈内生成薄包装。不得把业务方法搬进新 Node 包假装语义等价；若目标运行时不是当前可验证的 `node-stdio` profile（如 Java/Python 应用内 Service），本版本按方式 C 处理。
- **方式 C：需要宿主接入。** 缺少可安全调用的客户端或运行上下文时，保留 Skill、Tool 契约与接入说明，在 `package.json` 标记 `code2skill.requiresHostIntegration`。不得生成万能 `call_rpc`、`invoke_method`、`publish_message` Tool 或声称已部署。

异步发布/任务入队只说明「已接收/已入队」；存在状态查询源码时才生成独立查询能力，不得把回执/任务 ID 写成业务完成。

通用规则：每 Tool 有同名独立 Function export；Function Core 导出 Zod Schema，公共字段名表达业务含义并内部映射真实字段；认证、调用构造、确定性转换必须由 Function 承担（日期/时间、格式化、默认值、改名、数组/URL、顺序、序列化、上下文）；拼接/格式化/归一化不得推给 Agent 或借开放 Schema/后端权威推卸；同一值在不同调用点独立构造 wire；MCP 使用 SDK/Zod（当前 `node-stdio` profile 示例）；每个 Tool 提供名称、`title`、`description`、开放 `inputSchema`、annotations；`outputSchema` 默认省略；已取得结果时用 `toAgentResult` 原样交 Agent；仅未取得响应的底层异常用 `toAgentError` 投影；dry-run 不发网络/写入；模块初始化不得发起业务请求；业务服务接入配置（HTTP 场景下为 API 基址）由环境注入，缺时调用前返回配置错误，不得回退到测试/预发/生产。

#### HTTP 场景具体规则

基于 `fetch` 的实现任何 HTTP 状态都返回 `httpStatus` 与完整 `bodyText`；HTTP 客户端因 4xx/5xx 抛异常时还原状态/响应为普通 Tool 结果；仅未取得响应的底层异常进入 `toAgentError`。不得根据响应信封或业务 `code` 添加成功/失败/结果未知/重试结论。`node-stdio` profile 下复制 `portable-agent-result.mjs`，HTTP 目标使用其中 `readHttpResponse`/`httpResultFromError`。

何时调用 Tool、如何补参数、是否先问用户、如何理解响应及是否再调用，由 Consumer Agent 结合用户目标和实际结果决定；Function/MCP 不硬编码统一重试/写入策略。

附件由 Consumer Host 提供，优先 `attachmentRef` 等不透明引用；仅 Host 明确保证来源与可访问性时才用 `hostFilePath`，这是部署信任前提。条件不满足时标附件能力未满足；源码证明存在上传链时生成上传 Function/Tool 与下游绑定；Skill 禁止 Agent 猜测或构造本地路径。只能取得 STS/预签名凭证却无法上传时，须明确目标不完整，不假装已有 URL。

### 7. 编写 Skill

每个 Skill 只服务一个主要用户目标，独立描述其调用链；共享 Tool 是可复用原子能力，不形成跨 Skill 公共必经流程。Skill 以用户目标和源码证明的调用入口为核心，而非复述页面点击。它应说明：

- 什么调用触发该 Skill（HTTP、RPC service/method、消息 destination、任务入口、应用内 Service 等）；
- 每个 Tool 能做什么、何时调用或跳过；
- 哪些信息已知、缺失、条件必填、动态取得或可选；
- 如何逐步询问，而非要求用户一次给完整表单；
- 常见组合、部分目标、停止条件和结果展示；
- 如何把实际响应呈现给 Agent，以及 Agent 可继续调用、补问或直接说明结果；
- 源码能证明的写入影响、风险和用户可选择项；是否需要确认由 Consumer Agent 或 Host 策略决定，不在通用 Function/MCP 中强制。

对含多个决策节点的目标，Skill 需说明已知/缺失/可安全取得信息、哪个结果影响下一步、何时可跳过/停止/补问/选择、写入前展示影响、Agent/Host 策略与硬约束；响应不明确时交 Agent，不能自动转为成功或失败。Skill 不是固定逐步脚本；信息齐全时不应无意义补问或重复查询。

根据当前 Skill 对应目标在源码中的直接调用链说明可用能力和通常顺序。查询或预校验被多目标复用只能说明是共享 Tool；没有当前目标调用链证据时，不得写成该 Skill 的前置步骤。Agent 可跳过不需要能力、临时组合 Tool、按响应调整调用或先与用户沟通。

若标准路径包含“查询结果 → 选择一项 → 下游操作”，Skill 应引导 Agent 保留并传递 Function 支持的选中记录；信息仍新鲜时直接复用，不重复查询。

决定下一步布尔、枚举或状态字段必须保留实际值；字段缺失、为 `null` 或形态无法识别时，不得擅自转换成 `false`、成功或失败。把实际结果交给 Agent，由它结合上下文判断或向用户说明无法确认。

背景知识较短时直接写入 `SKILL.md`，明显干扰使用说明时才生成 `references/feature-context.md`，不要重复维护同一段知识。

`MCP-SETUP.md` 使用 `assets/core-MCP-SETUP.md` 作起点并保持简短。只说明：`npx skills add` 只安装 Skill；`node-stdio` profile 下有 lockfile 用 `npm ci`，否则 `npm install`；本地 MCP 按 stdio `command/args/cwd/env` 中立启动参数注册，独立部署远程服务才用 Streamable HTTP；业务接入配置（HTTP 场景下为基址）、认证、dry-run 环境变量如何注入；缺少运行上下文/依赖/安全入口时标记 `requires-host-integration`；缺基址时如何停止；安装/注册/连通/验证/部署分层报告。不把 Host 的 `mcpServers` 等惯例写成协议要求。背景文档用 `assets/core-feature-context.md`；不要把 strict-export-vNext 模板复制进默认包。

### 8. 离线验证

默认不调用真实业务接口。通用检查（目录、Skill、MCP discovery、安全边界）始终执行；语言特定构建与测试由已知可验证 runtime profile 处理。当前 `core-export-v1` 仅 `node-stdio` profile 可自动运行验证，其他原运行时包装按方式 C 处理。至少：

1. Function 冒烟：覆盖源码可见调用构造（HTTP：method/URL/query/header/body/multipart；RPC：service/method/arguments；消息/任务：destination/key/payload；应用内 Service：方法与运行上下文）。用类型变体、`null` 或额外参数证明调用不被 Schema 提前拦截。选中记录交接用两条不同的匿名记录切换调用，验证无前一条记录残值。
2. MCP 冒烟：initialize、`tools/list`、代表性 `tools/call`；证明省略 `outputSchema` 仍可调用，抽样覆盖 HTTP 4xx/5xx/非 JSON/长正文/底层异常，以及 RPC/消息/任务场景的异常与回执透传。
3. 写能力 dry-run：验证 dry-run 不发网络或写入；写接口不真调用。
4. 运行配置：HTTP 用 `.invalid`/mock/假基址验证 URL；RPC/Service/消息/任务用注入假客户端、Broker 句柄或运行上下文；证明缺必需配置时零外部调用，无环境默认回退。
5. 包测试：`node-stdio` profile 示例为 `npm test`，并运行精简校验器：

```bash
python3 <skill-root>/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

`package.json` 须含 `code2skill.profile=core-export-v1`。`node-stdio` profile 下校验器做语法检查、启动 MCP 完成 `initialize + tools/list`、以清理凭证后 `node --test` 运行包内测试；它不解析源码模板、不安装依赖，有 lockfile 用 `npm ci`，否则 `npm install`；仅 `--skip-tests` 排查结构时结果不得称已验证可运行。无已知可验证 profile 时通用检查后输出「未完成自动运行验证」，不得伪造通过。测试须 mock 外部请求并遵守 dry-run。

测试代码保留在包内，日志/收据不保留。测试只证明包能加载、注册、组装调用、构造 Guard 与传递响应，不证明业务规则、真实响应、端到端或真实 Agent 行为；Skill 调用链、停止点、非全局前置由 code2skill-review-flow 复核。真实接口验证须显式授权，默认关闭；写接口永不自动调用；无法离线证明的能力须标记 `requires-host-integration`，不生成伪证据。

生成包测试按目标组织：每个复杂目标一条正常代表路径；跨 Tool 交接验证上游结果进入下游；运行时硬边保留零外部写入的绕过反例。用匿名、跨业务领域的合成案例；匿名化仍保留真实 method/path/query/body/service/method/destination/key 字段名；跨 Tool 测试从匿名上游响应开始，两条不同的匿名记录切换调用，验证下游 wire 无残值；确定性转换断言精确 wire；预期来自源码，不得只手填最终正确参数。

### 9. 交付报告

只报告用户所需状态：生成能力、离线测试是否通过、是否调用真实环境、安装/注册/部署状态及具体限制。标记 `requires-host-integration` 的包报告「静态结构与 MCP discovery 通过，运行验证未完成」。不要把“文件已生成”“MCP 能启动”“真实业务已验证”“已部署”混为一谈。

`code2skill-generate` 不自行声明主流程完整或源码精确。独立判断主要目标和代表性标准路径是否闭环时，交给 `code2skill-review-flow`；进一步核对字段来源、确定性转换和关键依赖时，交给 `code2skill-review-source`。

## 高级验证（显式开启）

内部 `strict-export-v1` 格式保留兼容，但不再默认执行。仅用户明确要求以下任一内容时启用：完整证据链、Canonical/Goal Contract、Host compatibility、逐能力 verification matrix、live receipt、finalization、完整 manifest、外部 evaluator 或合规/高风险审计。

不要因为用户说“稳定”“可用”“完整”就自行升级到严格模式。升级前说明会扩大源码范围、产物和耗时。

严格模式继续使用：

- [vnext-architecture.md](references/vnext-architecture.md)
- [capability-model.md](references/capability-model.md)
- [evidence-and-discovery.md](references/evidence-and-discovery.md)
- [mcp-tool-design.md](references/mcp-tool-design.md)
- [observed-skill-design.md](references/observed-skill-design.md)
- [documentation-contract.md](references/documentation-contract.md)
- [artifact-contract.md](references/artifact-contract.md)
- [verification.md](references/verification.md)
- `scripts/run_pipeline.py`

现有 strict 包和校验器继续兼容；不得在同一目录混合 core 与 strict 文件。从 core 升级为 strict 时，使用新的工作目录并补充严格模式所需证据，不把 core 的离线通过伪装成审计完成。

## 默认不可妥协的底线

- 不生成页面级 mega-tool，也不机械执行一接口一 Tool。
- 输入 Schema 只保持 MCP 所需的开放对象和最低传输结构，不用业务类型提前拦截 Agent；默认不声明输出 Schema。
- 不因字段同名就复用语义；公共名称表达业务含义，内部再映射真实调用字段。
- 不把动态目录冻结成一次样本枚举。
- 不把普通后端业务规则升级成虚构的硬 Workflow。
- 不把公共能力升级成未经证明的全局前置步骤。
- 不生成任意 `call_api` 或 Agent 自行构造的本地路径上传逃生口；Host 明确担保来源与可访问性的附件路径可以作为业务上传输入。
- 不把调用结果、HTTP 响应、底层异常或关键判断字段改写成 Code2Skill 自己的业务结论。
- HTTP 场景下不把业务 API 基址、其他场景下不把业务服务接入配置作为 Tool 参数或写死为测试/预发/生产默认值；由 Consumer Host 按服务显式注入。
- 不用生成代码或它自己的绿测证明主流程完整或源码语义正确；这两项结论分别交给独立 Review Skill。
- 不在默认验证中访问真实业务环境。
- 不声称 Skill 安装等于 MCP 已注册、认证、验证或部署。
