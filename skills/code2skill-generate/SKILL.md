---
name: code2skill-generate
description: 从已有前端、后端或全栈代码中提取业务功能，生成可运行、可安装的 Function、MCP 和 Agent Skill；适用于页面功能、接口功能、业务流程及已有生成结果的修正。
---

# Code2Skill

把已有应用中的业务能力转换成其他 Agent 可以使用的 Function、MCP Tools 和 Skill。默认目标是生成一份小而可靠的运行包，不是为源码制作审计档案。

使用当前编程 Agent 搜索、理解和修改用户授权的代码；不要另建扫描器或把某种多 Agent 能力当作运行前提。生成包的 Consumer 可能不是当前编程 Agent，因此不得假设它能读取原仓库、Producer 机器上的任意文件或 Producer 的会话状态。Consumer Host 显式交给 Tool 的受控附件路径或附件引用除外。

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

根 `SKILL.md` 与 `skills/*/SKILL.md` 二选一，不能同时存在。用户指定的页面或目录只是搜索范围：先识别其中可以独立完成的主要用户目标。只有一个目标时生成一个根 Skill；存在多个主要目标时，每个目标生成一个独立 Skill，共享同一套原子 Function/MCP。不要按接口数量拆 Skill，也不要用一个大 Skill 覆盖互不相同的目标。

多个目标使用 `skills/<goal-id>/SKILL.md` 时，需要的参考资料放在对应 Skill 自己的 `references/` 中；不要让已安装 Skill 依赖父目录文件。根 `references/feature-context.md` 只适用于单一根 Skill。

不要在默认包中生成 Canonical/Goal Contract、Source Topology、Capability Graph、Host Profile、兼容性报告、MCP 长文档、Verification Matrix、Approval Audit、live receipt、manifest、Hash 收据或其他审计文件。临时分析笔记和测试输出不进入交付包。

代码是后续维护依据：Function 是业务执行真相，MCP 是标准适配层，Skill 是 Agent 使用知识。避免用多份 JSON 和长文档重复描述同一事实。

## 默认工作流程

### 1. 确定范围

- 从用户指定的页面、目录、接口、路由、符号或功能目标开始。
- 只搜索用户明确授权的源码根；不要扫描整台机器寻找可能存在的后端。
- 把指定范围视为发现边界，先列出其中可以独立触发、引导和完成的主要用户目标；它可能产生一个或多个 Skill。
- Skill 的单位是主要用户目标，不是整个目录、单个文件、接口或输入框。
- 先读取目标仓库规则和已有测试，保留无关改动。

### 2. 从客户端确定能力面

对于前端功能，以客户端实际调用的后端 API 为 Function/MCP 候选面，并只引入会影响这些接口的前端逻辑：

- 请求方法、地址、query/header/body/multipart 构造；
- 前端真正使用的响应字段；
- 默认值、字段转换、动态选项、条件输入和错误处理；
- 用户目标、主要分支、停止点和提交前展示信息；
- 附件上传结果如何绑定后续请求。

不要因为后端存在某个内部方法就自动暴露 Tool，也不要把每个页面、请求、控件或输入框机械地变成 Tool。

页面写死的菜单、文案和配置优先写入 Skill 或可选 Feature Context。只有当一份本地数据可以独立满足用户目标、需要被多个能力复用，或确实需要运行时读取时，才生成 Tool。

### 3. 有限核对后端

后端默认只用于补齐或核对公开传输契约：

- Request/Response 结构与可空性；
- 鉴权头或公开身份边界；
- 统一响应信封及公开的 `code`、`message`、`data` 等字段；
- 明确公开的枚举及附件上传接口。

合同已经足够生成时停止。不要默认继续追踪 Service、持久化、消息、审批、下游 RPC、完整副作用和所有业务校验。

只有以下情况才继续深入：公开契约互相矛盾；操作具有明显金融、删除、发布或高风险影响；源码明确存在不可绕过的安全凭证/顺序；或用户明确要求深度审计。

普通业务是否接受请求，以真实后端 API 为权威。不要在 Function 中复制整套后端规则，也不要预先解释 HTTP 状态或业务字段。把后端响应交给 Consumer Agent，由它判断、修正调用、向用户补问信息或解释结果。

### 4. 设计能力

一个 Tool 应表达可独立命名、调用、复用或停止的业务能力。按业务意义、输入输出稳定性和副作用拆分，而不是按代码文件或 HTTP 数量拆分。

对每个能力只确定执行所需的最小契约：

- 稳定 Tool 名、中文标题和说明；
- 语义清楚的公共输入，以及它到真实 API 字段的映射；
- 已知参数的名称、来源和用途提示；
- 前端消费、下游 handoff 和判断下一步时有用的响应字段说明；
- 精确的请求方法、地址及 query/header/body/multipart 绑定；
- read/create/update/delete 副作用；
- 运行环境所需的认证与附件条件。

业务 API 基址属于部署配置，不属于用户业务输入。按独立服务分别声明语义明确的环境变量，例如 `CODE2SKILL_<FEATURE>_<SERVICE>_BASE_URL`；不得把基址公开成 Tool 参数让 Agent 临时填写，也不得把源码中的测试、预发或生产域名作为 Function 的默认值。源码证明的环境地址可以在 `MCP-SETUP.md` 中作为部署参考，但实际运行必须由 Consumer Host 显式选择并注入。后端响应或公开协议在运行时给出的对象存储、回调、预签名等目标地址不属于这种静态业务基址。

不要仅凭字段名判断语义。即使两个接口、页面状态或请求使用同名字段，也要追踪它从哪里取得、怎样赋值、最终用于什么。语义不同的同名字段在公共 Function/MCP/Skill 中分别使用能表达“目录筛选”和“最终操作”等真实用途的名称，在请求构造内部再映射回 API 原字段。

MCP 必须声明输入 Schema，但默认把它当作给 Agent 的参数说明，而不是业务拦截器。使用开放对象；已知业务字段优先使用带说明的 `unknown().optional()`，不默认生成枚举、格式、数值范围、条件必填或严格类型。只有缺少某个值就无法形成 URL、附件或其他传输结构时，才保留最低传输级约束。接受额外参数，不设置 `additionalProperties: false` 或 strict object。Function 只按源码证明的绑定组装请求；额外参数保留给 callback 和 Agent，但没有可证明的发送位置时不得猜测位置或声称已经发送。

默认不声明 `outputSchema`。Tool 描述和 Skill 可以说明已知响应字段，但 HTTP 状态、`null`、缺失字段、数字字符串、额外字段和其他真实变体必须先到达 Agent。只有用户明确需要机器强类型输出，且公开契约足够稳定时，才添加开放、不会阻断已知变体的可选 `outputSchema`。

普通写接口默认由后端负责业务校验。只有源码明确证明存在不可绕过的身份、来源、事务、单次凭证或顺序约束时，才实现确定性 Guard；页面确认框和普通 POST 本身不构成自定义 Host Guard 的证据。

### 5. 实现 Function 与 MCP

- 每个公共 Tool 有一个同名语义的独立 async Function export。
- Function Core 导出 MCP 实际使用的开放输入 Zod Schema；公共字段名表达业务含义，内部再映射到真实 API 字段。Function 不得用更窄的第二套 Schema、类型转换或本地业务规则阻止 Agent 的调用。
- Function 只负责认证、精确请求构造和响应传递。基于 `fetch` 的实现收到任何 HTTP 状态都返回 `httpStatus` 和未经截断、未经 JSON 转换的完整 `bodyText`，由 Agent 自行解析。若使用的 HTTP 客户端会因 4xx/5xx 抛出带响应的异常，必须把其中的状态和响应数据还原成普通 Tool 结果；只有确实没有取得响应的底层异常才进入 `toAgentError`。不得根据响应信封或业务 `code` 添加成功、失败、结果未知或重试结论。
- MCP 使用官方 SDK 和 Zod，通过 `package.json` 固定显式版本范围；默认包不内嵌庞大的 SDK bundle。
- 每个 Tool 在 `tools/list` 中提供稳定名称、`title`、`description`、开放 `inputSchema` 和 annotations；`outputSchema` 默认省略。可以使用紧凑的定义表、共享 Schema 和共享 callback wrapper，不必为每个 Tool 复制模板代码。
- MCP 直接使用 Function 导出的开放输入 Schema，并复制 `assets/portable-agent-result.mjs` 到生成包。已取得 HTTP 响应时使用 `toAgentResult` 原样交给 Agent，包括 4xx/5xx；只有 callback 没有取得响应而抛出的底层异常才使用 `toAgentError` 做 JSON-safe 协议投影。该投影只保留原始 `name/message/code/cause` 和可序列化属性，不生成新的业务错误码、重试策略或结果判断。
- 所有外部动作位于 Tool 调用之后；模块 import/初始化不得发起业务请求。
- 使用明确的 dry-run 环境变量，dry-run 不发网络请求或写入。
- HTTP/RPC Function 从运行环境读取每个业务服务的基址，去除重复尾斜杠后与源码证明的固定路径组合。缺少必需基址时在发起请求前返回清楚的配置错误，不得回退到测试、预发、生产或 Producer 当时使用的环境。
- 默认环境不得自动指向任何真实业务环境并在生成/验证时请求真实接口。真实调用只有用户显式授权后才能进行。

是否调用 Tool、如何补充或修正参数、是否先向用户提问、如何理解响应以及是否再次调用，都由 Consumer Agent 结合用户目标和实际结果决定。core Function/MCP 不硬编码统一的重试或写入结果策略。

附件由 Consumer Host 提供，优先公开为 `attachmentRef` 等不透明引用；只有 Host 明确保证来源与可访问性时，才使用运行时注入的 `hostFilePath`。这是一项部署信任前提，不是 Code2Skill 可验证的保证；条件不满足时将附件能力标为运行条件未满足。Code2Skill 不实现聊天接入、文件接收、下载或通用 Host 沙箱。若源码证明存在业务上传链，则生成上传 Function/Tool 与下游绑定；Skill 必须禁止 Agent 猜测或构造本地路径。若只能取得 STS/预签名凭证却不能完成上传，应明确目标尚不完整，不能假装已有 URL。

### 6. 编写 Skill

每个 Skill 只服务一个主要用户目标，独立描述该目标自己的调用链；共享 Tool 是可复用的原子能力，不形成跨 Skill 的公共必经流程。Skill 以前端业务功能和用户目标为核心，而不是复述页面点击步骤。它应说明：

- 什么请求会触发该 Skill；
- 每个 Tool 能做什么、何时调用或跳过；
- 哪些信息已知、缺失、条件必填、动态取得或可选；
- 如何逐步询问，而不是要求用户一次提供完整表单；
- 常见组合、部分目标、停止条件和结果展示；
- 如何把实际响应呈现给 Agent，以及 Agent 可以继续调用、向用户补问或直接说明结果；
- 源码能够证明的写入影响、风险和用户可选择项；是否需要确认以及如何与用户沟通，由 Consumer Agent 或 Host 的策略决定，不在通用 Function/MCP 中强制。

根据当前 Skill 对应目标在前端中的直接调用链说明可用能力和通常顺序。某个查询或预校验被多个目标复用，只能说明它是共享 Tool；没有当前目标的直接调用链证据时，不得写成该 Skill 的前置步骤。Agent 可以跳过不需要的能力、临时组合 Tool、根据响应调整调用，或先与用户沟通。

决定下一步的布尔、枚举或状态字段必须保留实际值；字段缺失、为 `null` 或形态无法识别时，不得擅自转换成 `false`、成功或失败。把实际结果交给 Agent，由它结合上下文判断或向用户说明无法确认。

当背景知识较短时直接写入 `SKILL.md`；只有内容会明显干扰使用说明时，才生成 `references/feature-context.md`。不要重复维护同一段知识。

`MCP-SETUP.md` 使用 `assets/core-MCP-SETUP.md` 作为起点，保持简短，并在交付前替换或删除全部占位符。它只说明：`npx skills add` 只安装 Skill；有 lockfile 时用 `npm ci` 安装依赖、否则用 `npm install`；本地 MCP 按标准 stdio 的 `command/args/cwd/env` 中立启动参数注册，独立部署的远程服务才使用 Streamable HTTP；每个业务服务基址、认证和 dry-run 环境变量如何由部署环境注入；缺少必需基址时如何停止；安装、注册、连通、真实验证和部署是不同状态。不要把某个 Host 的 `mcpServers` 等配置惯例写成协议要求。可选背景文档使用 `assets/core-feature-context.md` 的精简结构；不要把 strict-export-vNext 的模板复制进默认包。

### 7. 离线验证

默认不调用真实业务接口。至少运行：

1. Function 冒烟：按源码中明确可见的调用覆盖基本 method/URL/query/header/body 或 multipart 组装；至少用一个类型变体、`null` 或额外参数证明请求不会被业务 Schema 提前拦截，不扩展成业务规则组合矩阵。
2. MCP 冒烟：initialize、`tools/list`、代表性的 `tools/call`；证明省略 `outputSchema` 仍可调用，并抽样覆盖 4xx/5xx JSON 文本、非 JSON、长正文或底层异常的原样传递。不要求通过 MCP 逐个调用全部 Tool。
3. 写能力 dry-run：验证共享 dry-run 机制不会发起网络或写入；写接口不得在默认测试中真实调用。
4. 运行地址：使用 `.invalid`、本地 mock 或注入的假基址验证 URL 组合；证明缺少必需基址时零网络请求，且实现没有测试、预发或生产环境的默认回退。
5. 包测试：`npm test`，并运行精简校验器：

```bash
python3 <skill-root>/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

`package.json` 必须包含 `"code2skill": {"profile": "core-export-v1"}`，供校验程序识别目录格式。默认校验器会执行语法检查，真实启动 MCP 完成 `initialize + tools/list`，并以凭证清理后的固定 `node --test` 命令运行包内测试；它不解析源码模板、不安装依赖，也不宣称网络隔离，因此有 lockfile 时先运行 `npm ci`，否则运行 `npm install`。测试自身仍必须 mock 外部请求并遵守 `CODE2SKILL_DRY_RUN=1`。只有排查包结构时才使用 `--skip-tests`，此时结果不得称为“已验证可运行”。

测试代码保留在包内，测试日志和收据不保留。这些测试只证明包能加载、注册并按已知客户端契约组装基本请求，不证明所有业务规则、真实响应或端到端流程正确。真实接口验证是显式授权后的可选动作，默认关闭；写接口永不自动调用。若某个能力无法离线证明，应在 Skill 或交付说明中写清边界，不要为通过验收生成伪证据。

### 8. 交付报告

只报告用户真正需要的状态：生成了哪些能力、离线测试是否通过、是否调用过真实环境、是否安装/注册/部署，以及仍存在的具体限制。不要把“文件已生成”“MCP 能启动”“真实业务已验证”和“已部署”混成一个结论。

`code2skill-generate` 不自行声明主流程完整或源码精确。需要独立判断主要目标和代表性标准路径是否闭环时，交给 `code2skill-review-flow`；需要进一步核对字段来源、确定性转换和关键依赖时，交给 `code2skill-review-source`。

## 高级验证（显式开启）

内部的 `strict-export-v1` 格式保留兼容，但不再默认执行。只有用户明确要求以下任一内容时才启用：完整证据链、Canonical/Goal Contract、Host compatibility、逐能力 verification matrix、live receipt、finalization、完整 manifest、外部 evaluator 或合规/高风险审计。

不要因为用户说“稳定”“可用”“完整”就自行升级到严格模式。升级前说明它会扩大源码范围、产物和耗时。

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

现有 strict 包和校验器继续兼容；不得在同一目录混合 core 与 strict 文件。需要从 core 升级为 strict 时，使用新的工作目录并补充严格模式所需证据，不把 core 的离线通过伪装成审计完成。

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
