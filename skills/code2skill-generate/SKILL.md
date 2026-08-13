---
name: code2skill-generate
description: 从已有前端、后端或全栈代码中提取业务功能，生成可运行、可安装的 Function、MCP 和 Agent Skill；适用于页面功能、接口功能、业务流程及已有生成结果的修正。
---

# Code2Skill

把已有应用的业务能力转为其他 Agent 可用 Function、MCP Tools 和 Skill。默认目标是生成一份小而可靠的运行包，不是为源码制作审计档案。

使用当前编程 Agent 搜索、理解和修改用户授权的代码；不要另建扫描器或把某种多 Agent 能力当运行前提。生成包的 Consumer 可能不是当前编程 Agent，因此不得假设它能读取原仓库、Producer 机器上的任意文件或 Producer 的会话状态。Consumer Host 显式交给 Tool 的受控附件路径或附件引用除外。

## 默认生成结果

除非用户明确要求严格审计，默认只生成：

```text
generated/code2skill/<feature-id>/
├── SKILL.md                    # 只有一个主要目标时使用
├── skills/                     # 有多个主要目标时替代根 SKILL.md
│   ├── <goal-a>/SKILL.md
│   └── <goal-b>/SKILL.md
├── MCP-SETUP.md
├── package.json              # 包信息、运行脚本和依赖
├── function-core/
│   └── index.mjs
├── mcp-tool/
│   └── index.mjs
├── portable-agent-result.mjs
├── tests/
│   └── *.test.mjs
└── references/
    └── feature-context.md     # 仅在业务背景无法简洁写入 SKILL 时生成
```

根 `SKILL.md` 与 `skills/*/SKILL.md` 二选一，不能同时存在。用户指定的页面或目录只是搜索范围：先识别其中可独立完成的主要用户目标。单目标生成一个根 Skill；多主要目标时，每个目标生成一个独立 Skill，共享同套原子 Function/MCP。不要按接口数量拆 Skill，也不用一个大 Skill 覆盖互不相同目标。

多个目标使用 `skills/<goal-id>/SKILL.md` 时，参考资料放对应 Skill 的 `references/` 中；不要让已安装 Skill 依赖父目录文件。根 `references/feature-context.md` 只适用于单一根 Skill。

不要在默认包中生成 Canonical/Goal Contract、Source Topology、Capability Graph、Host Profile、兼容性报告、MCP 长文档、Verification Matrix、Approval Audit、live receipt、manifest、Hash 收据等审计文件。临时分析笔记/测试输出不进入交付包。

代码是后续维护依据：Function 是业务执行真相，MCP 是标准适配层，Skill 是 Agent 使用知识。避免用多份 JSON/长文档重复描述同一事实。

## 默认工作流程

### 1. 确定范围

- 从用户指定的页面、目录、接口、路由、符号或功能目标开始。
- 只搜索用户明确授权的源码根；不要扫描整台机器寻找可能存在的后端。未显式限定时沿同仓库直接 import/alias 追踪闭合依赖；跨仓库或限“仅限这些根”不越界。缺失依赖记录符号/文件/缺什么，不据此过早声明能力缺失。
- 把指定范围视为发现边界，先列出其中可独立触发、引导和完成的主要用户目标；它可能产生一个或多个 Skill。
- Skill 的单位是主要用户目标，不是整个目录、单个文件、接口或输入框。
- 先读取目标仓库规则和已有测试，保留无关改动。

### 2. 目标决策边界

Producer 先在**工作记忆**中形成每目标最小临时图，节点链：用户目标 → 已知与缺失信息 → 查询、选择或校验 → 分支与停止条件 → 写入前的展示或确认 → 写入 → 源码存在时的结果查询或对账。纯只读无写入节点；无源码证据不虚构。

两正交维度（互斥仅维度一内）：主要角色（每节点恰一个）＝Agent 判断/追问/选择｜用户交互/确认｜可独立命名/调用/复用/停止的 MCP Tool｜无需模型参与的 Function 内部确定性步骤｜完成/停止/无法确认的结果边界；约束所有者（可叠加于 Tool 节点或硬边，与角色不排斥）＝后端权威（普通业务校验响应原样交 Consumer Agent）｜Consumer Host 策略（如写入前确认）｜源码证明不可绕过的确定性 Guard。

Tool 是执行能力，Guard/Host 是约束所有者；一个写入 Tool 可同时携带 Host 确认与 Guard，不得二选一。Guard 证据门槛见「设计能力」节：页面顺序/普通确认框/普通 POST/后端拒绝/共享查询不自动成 Guard。只存工作记忆，不生成中间文件、不进交付包与仓库；简单只读一句话带过，不扩规模。

### 3. 从客户端确定能力面

前端功能以客户端实际调用的后端 API 为 Function/MCP 候选面，只引入影响这些接口的前端逻辑：

- 请求方法、地址、query/header/body/multipart 构造；
- 前端真正使用的响应字段；
- 默认值、字段转换、动态选项、条件输入和错误处理；
- 用户目标、主要分支、停止点和提交前展示信息；
- 附件上传结果如何绑定后续请求。

不要因后端存在内部方法就自动暴露 Tool，也不要把各页面/请求/控件/输入框机械变 Tool。

页面写死的菜单、文案/配置优先写入 Skill 或可选 Feature Context。仅当本地数据可独立满足用户目标、需被多个能力复用，或需运行时读取时，才生成 Tool。

### 4. 有限核对后端

后端默认仅补齐或核对公开传输契约：

- Request/Response 结构与可空性；
- 鉴权头或公开身份边界；
- 统一响应信封及公开的 `code`、`message`、`data` 等字段；
- 明确公开的枚举及附件上传接口。

合同足够生成时停止。不要默认继续追踪 Service/持久化/消息/审批/下游 RPC/完整副作用/全部业务校验。

仅以下情况才继续深入：公开契约互相矛盾；操作具有明显金融/删除/发布/高风险影响；源码明确存在不可绕过的安全凭证/顺序；或用户明确要求深度审计。

普通业务是否接受请求，以真实后端 API 为权威。不要在 Function 中复制整套后端规则或预判 HTTP 状态/业务字段。把后端响应交给 Consumer Agent，由它判断、修正调用、补问或解释结果。

### 5. 设计能力

Tool 应表达可独立命名、调用、复用或停止的业务能力。按业务意义、输入输出稳定性/副作用拆分，而非按代码文件/HTTP 数量拆分。

拆出额外 Tool 的正面条件（满足一项或多项才拆）：中间结果改变后续调用/分支/请求参数；能完成独立部分目标或被复用；前后步骤权限/副作用/确认要求不同；中间阶段可合理停止、等待用户输入或选择；写入后有源码证明的异步状态查询或结果对账。

不拆 Tool 的反面条件：仅为了让模型多推理一次；请求组装/字段格式化/RAG 检索等确定性实现；无论中间结果如何下一步始终相同；拆开后暴露无业务意义的中间状态；多个调用属不可分割事务。

一个 Tool 可调多个内部 API，一个 API 可支持多个业务 Tool，勿按接口数量机械映射。仅主要角色为 MCP Tool 的节点才拆为 Tool；不得把 Agent 判断/追问、用户确认或 Function 内部确定性步骤改名凑拆分。

对每能力只确定执行所需最小契约：

- 稳定 Tool 名、中文标题和说明；
- 语义清楚的公共输入，及其到真实 API 字段映射；
- 已知参数的名称、来源和用途提示；
- 前端消费、下游 handoff 与判断下一步有用响应字段说明；
- 精确的请求方法、地址及 query/header/body/multipart 绑定；
- read/create/update/delete 副作用；
- 运行环境所需的认证与附件条件。

业务 API 基址属部署配置，非用户业务输入。按独立服务声明语义明确环境变量，例如 `CODE2SKILL_<FEATURE>_<SERVICE>_BASE_URL`；不得把基址公开成 Tool 参数让 Agent 临时填写，也不得把源码中测试/预发/生产域名作 Function 默认值。源码证明的环境地址可在 `MCP-SETUP.md` 作部署参考，但实际运行须由 Consumer Host 显式选择注入。后端响应或公开协议运行时给出的对象存储/回调/预签名等目标地址不属于静态基址。

不要仅凭字段名判断语义。同名字段须追踪来源、赋值与用途；语义不同字段用真实用途公共名，内部映射回 API 原字段。对每个写能力及「查询→选择→后续请求」链在工作记忆做 source-binding 核对：沿上游响应→客户端归一化/页面状态→各下游 wire 追踪；同一上游值进多下游调用按使用点分别追踪转换与 wire，不因语义相近、共用 Tool 或某下游已有转换而复用同一表示；源码改写的上游值先追踪归一化，不把原始表示当下游可用值。

客户端若将选中结果的多个字段或整行对象展开、合并进下游请求，建模为选中记录交接。下游只读少数字段时逐项公开；转发整行时使用业务命名的开放对象（如 `selectedOrder`）。Function 按源码顺序合并且保持显式覆盖关系。除非证据证明只传标识符等价，Skill 的标准示例必须传递该记录；省略能否接受仍交给后端判断。

MCP 必须声明输入 Schema，但默认当作给 Agent 的参数说明，非业务拦截器。使用开放对象；已知业务字段优先用带说明的 `unknown().optional()`，不默认生成枚举/格式/数值范围/条件必填/严格类型。仅缺某值无法形成 URL/附件等传输结构时，才保留最低传输级约束。接受额外参数，不设置 `additionalProperties: false` 或 strict object。Function 只按源码证明的绑定组装请求；额外参数保留给 callback 和 Agent，无可证明发送位置时不得猜测位置或声称已发送。

默认不声明 `outputSchema`。Tool 描述/Skill 可说明已知响应字段，但 HTTP 状态/`null`/缺失字段/数字字符串/额外字段等真实变体必须先到 Agent。仅用户明确需机器强类型输出且公开契约足够稳定时，才添加开放、不会阻断已知变体的可选 `outputSchema`。

普通写接口默认由后端负责校验。只有源码明确证明存在不可绕过的身份、来源、事务、单次凭证或顺序约束时，才实现确定性 Guard；页面确认框和普通 POST 不构成自定义 Host Guard 的证据。

### 6. 实现 Function 与 MCP

- 每公共 Tool 有同名语义独立 async Function export。
- Function Core 导出 MCP 实际使用的开放输入 Zod Schema；公共字段名表达业务含义，内部再映射到真实 API 字段。Function 不得用更窄的第二套 Schema、类型转换或本地规则阻止 Agent 调用。
- Function 只负责认证、精确请求构造和响应传递。基于 `fetch` 的实现任何 HTTP 状态都返回 `httpStatus` 与未经截断/JSON 转换的完整 `bodyText`，由 Agent 自行解析。HTTP 客户端因 4xx/5xx 抛异常时须把状态/响应还原成普通 Tool 结果；仅确实未取得响应的底层异常才进入 `toAgentError`。不得根据响应信封或业务 `code` 添加成功、失败、结果未知或重试结论。源码可证明的确定性请求构造（日期/时间拼接、格式化、默认值、改名、数组/URL 拼接、派生值）必须由 Function 承担；同一值在不同调用点按其语义独立构造 wire，拼接/时区/格式化与归一化不交 Agent 猜测，共享 Tool 不同转换用业务参数或目标 wrapper，不要求 Agent 手拼 wire；不得以开放 Schema 或后端权威推给 Consumer Agent。
- MCP 使用官方 SDK 和 Zod，通过 `package.json` 固定显式版本范围；默认包不内嵌庞大 SDK bundle。
- 每个 Tool 在 `tools/list` 中提供稳定名称、`title`、`description`、开放 `inputSchema` 和 annotations；`outputSchema` 默认省略。可用紧凑的定义表、共享 Schema /共享 callback wrapper，不必为每个 Tool 复制模板代码。
- MCP 直接使用 Function 导出的开放输入 Schema，并复制 `assets/portable-agent-result.mjs` 到生成包。已取得 HTTP 响应时使用 `toAgentResult` 原样交给 Agent，包括 4xx/5xx；仅 callback 未取得响应而抛出的底层异常才用 `toAgentError` 做 JSON-safe 协议投影。该投影只保留原始 `name/message/code/cause` 和可序列化属性，不生成业务错误码、重试策略或结果判断。
- 外部动作在 Tool 调用后；模块 import/初始化不得发起业务请求。
- 使用明确的 dry-run 环境变量，dry-run 不发网络请求或写入。
- HTTP/RPC Function 从运行环境读取各业务服务基址，去除重复尾斜杠后与源码证明固定路径组合。缺少必需基址时发起请求前返回清楚配置错误，不得回退到测试/预发/生产或 Producer 当时环境。
- 默认环境不得自动指向真实业务环境或生成/验证请求真实接口。真实调用仅用户显式授权后进行。

是否调用 Tool、如何补充或修正参数、是否先向用户提问、如何理解响应以及是否再次调用，都由 Consumer Agent 结合用户目标和实际结果决定。core Function/MCP 不硬编码统一重试或写入结果策略。

附件由 Consumer Host 提供，优先公开 `attachmentRef` 等不透明引用；仅 Host 明确保证来源与可访问性时，才用运行时注入的 `hostFilePath`。这是部署信任前提，非 Code2Skill 可验证保证；条件不满足时标附件能力为未满足。Code2Skill 不实现聊天/文件接收/下载或通用 Host 沙箱。若源码证明存在业务上传链，生成上传 Function/Tool 与下游绑定；Skill 必须禁止 Agent 猜测或构造本地路径。若只能取得 STS/预签名凭证却无法上传，应明确目标不完整，不假装已有 URL。

### 7. 编写 Skill

每个 Skill 只服务一个主要用户目标，独立描述该目标自身调用链；共享 Tool 是可复用原子能力，不形成跨 Skill 的公共必经流程。Skill 以前端业务功能和用户目标为核心，而非复述页面点击步骤。它应说明：

- 什么请求触发该 Skill；
- 每个 Tool 能做什么、何时调用或跳过；
- 哪些信息已知、缺失、条件必填、动态取得或可选；
- 如何逐步询问，而非要求用户一次给完整表单；
- 常见组合、部分目标、停止条件和结果展示；
- 如何把实际响应呈现给 Agent，以及 Agent 可继续调用、补问或直接说明结果；
- 源码能证明的写入影响、风险和用户可选择项；是否需要确认以及如何与用户沟通，由 Consumer Agent 或 Host 的策略决定，不在通用 Function/MCP 中强制。

对含多个决策节点的目标，Skill 需说明：已知/缺失/可安全取得信息；哪个结果影响下一步；何时可跳过、停止、继续补问或请求用户选择；写入前需展示影响与选择；哪些是 Agent/Host 策略、哪些是运行时硬约束；响应不明确时交 Agent，不能自动转为成功或失败。Skill 不是固定逐步脚本；信息齐全时不应无意义补问或重复查询。

根据当前 Skill 对应目标在前端中的直接调用链说明可用能力和通常顺序。某个查询或预校验被多个目标复用，只能说明它是共享 Tool；没有当前目标的直接调用链证据时，不得写成该 Skill 的前置步骤。Agent 可跳过不需要能力、临时组合 Tool、按响应调整调用或先与用户沟通。

若标准路径包含“查询结果 → 选择一项 → 下游操作”，Skill 应引导 Agent 保留并传递 Function 支持的选中记录；信息仍新鲜时直接复用，不重复查询。

决定下一步布尔、枚举或状态字段必须保留实际值；字段缺失、为 `null` 或形态无法识别时，不得擅自转换成 `false`、成功或失败。把实际结果交给 Agent，由它结合上下文判断或向用户说明无法确认。

背景知识较短时直接写入 `SKILL.md`；仅内容会明显干扰使用说明时，才生成 `references/feature-context.md`。不要重复维护同一段知识。

`MCP-SETUP.md` 使用 `assets/core-MCP-SETUP.md` 作起点，保持简短，交付前替换/删除占位符。只说明：`npx skills add` 只安装 Skill；有 lockfile 用 `npm ci` 装依赖、否则 `npm install`；本地 MCP 按标准 stdio `command/args/cwd/env` 中立启动参数注册，独立部署的远程服务才用 Streamable HTTP；每个业务服务基址、认证和 dry-run 环境变量如何由部署环境注入；缺基址时如何停止；安装、注册、连通、真实验证和部署是不同状态。不要把某 Host 的 `mcpServers` 等配置惯例写成协议要求。可选背景文档用 `assets/core-feature-context.md` 的精简结构；不要把 strict-export-vNext 模板复制进默认包。

### 8. 离线验证

默认不调用真实业务接口。至少运行：

1. Function 冒烟：按源码中可见的调用覆盖基本 method/URL/query/header/body 或 multipart 组装；至少用一个类型变体、`null` 或额外参数证明请求不被业务 Schema 提前拦截，不扩展成业务规则组合矩阵。有选中记录交接时，用两条不同的匿名记录切换调用，确认请求无前一条记录残值且覆盖顺序正确。
2. MCP 冒烟：initialize、`tools/list`、代表性的 `tools/call`；证明省略 `outputSchema` 仍可调用，并抽样覆盖 4xx/5xx JSON 文本、非 JSON、长正文或底层异常的原样传递。不要求 MCP 逐个调用全部 Tool。
3. 写能力 dry-run：验证共享 dry-run 机制不发网络或写入；写接口不得在默认测试中真实调用。
4. 运行地址：使用 `.invalid`、本地 mock 或注入的假基址验证 URL 组合；证明缺少必需基址时零网络请求，且无测试/预发/生产环境默认回退。
5. 包测试：`npm test`，并运行精简校验器：

```bash
python3 <skill-root>/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

`package.json` 必须包含 `"code2skill": {"profile": "core-export-v1"}`，供校验程序识别目录格式。默认校验器执行语法检查，真实启动 MCP 完成 `initialize + tools/list`，并以凭证清理后的固定 `node --test` 命令运行包内测试；它不解析源码模板、不安装依赖、不宣称网络隔离，有 lockfile 时先运行 `npm ci`，否则 `npm install`。测试仍必须 mock 外部请求并遵守 `CODE2SKILL_DRY_RUN=1`。仅排查包结构时使用 `--skip-tests`，此时结果不得称为“已验证可运行”。

测试代码保留在包内，测试日志/收据不保留。这些测试只证明包能加载、注册、组装请求、构造确定性 Guard 与传递响应，不证明业务规则、真实响应、端到端或真实 Agent 行为；Skill 调用链、停止点、非全局前置属静态说明检查，由 code2skill-review-flow 独立复核，不声称测试证明真实 Agent 一定遵守。真实接口验证是显式授权后的可选动作，默认关闭；写接口永不自动调用。若某个能力无法离线证明，应在 Skill 或交付说明中写清边界，不要为通过验收生成伪证据。

生成包测试按目标实际结构组织。每个复杂目标一条正常代表路径；跨 Tool 交接验证选中数据或上游结果进入下游请求；有运行时硬边时保留零外部写入的绕过反例；普通后端拒绝仍原样到 Agent。测试用匿名、跨业务领域的合成案例：人物/账号/记录/附件与业务样本值匿名合成；源码证明且精确断言必需的 method、接口路径与 query/body/multipart 字段名保留，不因匿名改写真实契约；Code2Skill 自身 fixture/test 亦匿名。跨 Tool 测试从匿名上游响应开始，用 A/B 两记录验证下游 wire 随选择变化无残值；确定性转换用业务友好输入断言精确 wire 输出；同一匿名输入分别断言其在多下游请求的 wire，含「原始值→归一化值」案例验证各下游归一化结果、可发现直接透传原始响应与统一默认处理；预期独立来自源码，不得只手填最终正确参数。

### 9. 交付报告

只报告用户所需状态：生成哪些能力、离线测试是否通过、是否调用过真实环境、是否安装/注册/部署，以及仍存在具体限制。不要把“文件已生成”“MCP 能启动”“真实业务已验证”和“已部署”混成一个结论。

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
- 不因字段同名就复用语义；公共名称表达业务含义，内部再映射真实 API 字段。
- 不把动态目录冻结成一次样本枚举。
- 不把普通后端业务规则升级成虚构的硬 Workflow。
- 不把公共能力升级成未经证明的全局前置步骤。
- 不生成任意 `call_api` 或 Agent 自行构造的本地路径上传逃生口；Host 明确担保来源与可访问性的附件路径可以作为业务上传输入。
- 不把 HTTP 响应、底层异常或关键判断字段改写成 Code2Skill 自己的业务结论。
- 不把业务 API 基址作为 Tool 参数或写死为测试、预发、生产默认值；由 Consumer Host 按服务显式注入。
- 不用生成代码或它自己的绿测证明主流程完整或源码语义正确；这两项结论分别交给独立 Review Skill。
- 不在默认验证中访问真实业务环境。
- 不声称 Skill 安装等于 MCP 已注册、认证、验证或部署。
