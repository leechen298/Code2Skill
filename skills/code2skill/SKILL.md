---
name: code2skill
description: 从已有前端、后端或全栈代码中提取一个业务功能，生成精简、可运行、可安装的 Function、MCP 和 Agent Skill；适用于页面功能、接口功能、业务流程及已有生成包的修正。
---

# Code2Skill

把已有应用中的业务能力转换成其他 Agent 可以使用的 Function、MCP Tools 和 Skill。默认目标是生成一份小而可靠的运行包，不是为源码制作审计档案。

使用当前编程 Agent 搜索、理解和修改用户授权的代码；不要另建扫描器或自治 Agent。生成包的 Consumer 可能不是当前编程 Agent，因此不得假设它能读取原仓库、任意本地文件或 Producer 的会话状态。

## 默认交付：core-export-v1

除非用户明确要求严格审计，默认只生成：

```text
generated/code2skill/<feature-id>/
├── SKILL.md
├── MCP-SETUP.md
├── package.json              # 声明 code2skill.profile=core-export-v1
├── function-core/
│   └── index.mjs
├── mcp-tool/
│   └── index.mjs
├── portable-error-normalizer.mjs
├── tests/
│   └── *.test.mjs
└── references/
    └── feature-context.md     # 仅在业务背景无法简洁写入 SKILL 时生成
```

不要在默认包中生成 Canonical/Goal Contract、Source Topology、Capability Graph、Host Profile、兼容性报告、MCP 长文档、Verification Matrix、Approval Audit、live receipt、manifest、Hash 收据或其他审计文件。临时分析笔记和测试输出不进入交付包。

代码是后续维护依据：Function 是业务执行真相，MCP 是标准适配层，Skill 是 Agent 使用知识。避免用多份 JSON 和长文档重复描述同一事实。

## 默认工作流程

### 1. 确定范围

- 从用户指定的页面、目录、接口、路由、符号或功能目标开始。
- 只搜索用户明确授权的源码根；不要扫描整台机器寻找可能存在的后端。
- 目标单位是一个完整业务功能，不是整个仓库，也不是单个文件摘要。
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
- 统一响应信封、业务错误字段和成功条件；
- 明确公开的枚举及附件上传接口。

合同已经足够生成时停止。不要默认继续追踪 Service、持久化、消息、审批、下游 RPC、完整副作用和所有业务校验。

只有以下情况才继续深入：公开契约互相矛盾；操作具有明显金融、删除、发布或高风险影响；源码明确存在不可绕过的安全凭证/顺序；或用户明确要求深度审计。

普通业务是否接受请求，以真实后端 API 为权威。不要在 Function 中复制整套后端规则；保留结构化业务错误，让 Consumer Agent 补充信息或解释失败。

### 4. 设计能力

一个 Tool 应表达可独立命名、调用、复用或停止的业务能力。按业务意义、输入输出稳定性和副作用拆分，而不是按代码文件或 HTTP 数量拆分。

对每个能力只确定执行所需的最小契约：

- 稳定 Tool 名、中文标题和说明；
- 直接输入及运行时真正执行的闭合 Schema；
- 前端消费、下游 handoff 和最小成功判断所需的输出；
- 精确请求绑定和成功状态；
- read/create/update/delete 副作用；
- 结构化错误和自动重试策略。

不要枚举前端不读取的全部返回字段。未被使用的响应内容可以保留在开放的 `data` 对象中，不要根据单次样本把字符串、数字或对象永久收窄为 `null`。

普通写接口默认由后端负责业务校验。只有源码明确证明存在不可绕过的身份、来源、事务、单次凭证或顺序约束时，才实现确定性 Guard；页面确认框和普通 POST 本身不构成自定义 Host Guard 的证据。

### 5. 实现 Function 与 MCP

- 每个公共 Tool 有一个同名语义的独立 async Function export。
- 每个 Function 同文件导出可识别的输入/输出 Zod Schema（建议使用 `<functionName>InputSchema` 与 `<functionName>OutputSchema`）；Function 自身必须执行这些 Schema，不能只把 Schema 写给 MCP 看。
- Function 负责输入校验、请求构造、成功结果和结构化错误；MCP callback 只做协议适配，不复制业务请求。
- MCP 使用官方 SDK 和 Zod，通过 `package.json` 固定显式版本范围；默认包不内嵌庞大的 SDK bundle。
- 每个 Tool 字面注册，提供 `title`、`description`、`inputSchema`、`outputSchema` 和 annotations。
- MCP 直接复用 Function 导出的 Zod Schema，并从随 Skill 提供的 `portable-error-normalizer.mjs` 复用 `normalizeToolError` 和 `toMcpResult`；成功与失败由该共享 runtime 返回一致的 `content` 与 `structuredContent`，失败必须为 `isError: true`。
- 所有外部动作位于 Tool 调用之后；模块 import/初始化不得发起业务请求。
- 使用明确的 dry-run 环境变量，dry-run 不发网络请求或写入。
- 默认环境不得自动指向生产并在生成/验证时请求真实接口。真实调用只有用户显式授权后才能进行。

写操作不得自动重试。收到明确后端拒绝时返回可修正的业务错误；超时、断连或无法判断服务端是否已处理时返回不可重试的 `UNKNOWN_DISPATCH_OUTCOME`，要求人工对账。

附件由 Consumer Host 提供批准的引用或受限内容；Code2Skill 不实现聊天接入、文件接收或下载。若源码证明存在业务上传链，则生成上传 Function/Tool 与下游绑定；若只能取得 STS/预签名凭证却不能完成上传，应在 Skill 中明确该目标尚不完整，不能假装已有 URL。

### 6. 编写 Skill

Skill 以前端业务功能和用户目标为核心，而不是复述页面点击步骤。它应说明：

- 什么请求会触发该 Skill；
- 每个 Tool 能做什么、何时调用或跳过；
- 哪些信息已知、缺失、条件必填、动态取得或可选；
- 如何逐步询问，而不是要求用户一次提供完整表单；
- 常见组合、部分目标、停止条件和结果展示；
- 业务拒绝、鉴权、网络、响应异常和未知写入结果如何恢复；
- 写入前应向用户复述什么，但不得把调用者传入的 `confirmed: true` 当作可信确认。

当背景知识较短时直接写入 `SKILL.md`；只有内容会明显干扰使用说明时，才生成 `references/feature-context.md`。不要重复维护同一段知识。

`MCP-SETUP.md` 保持简短，只说明：`npx skills add` 只安装 Skill；`npm install` 安装 MCP 依赖；如何启动/注册 MCP；如何注入认证和 dry-run 环境变量；安装、可达、真实验证和部署是不同状态。

### 7. 离线验证

默认不调用真实业务接口。至少运行：

1. Function 测试：合法/非法输入、精确 method/URL/query/header/body、最小输出、业务错误、网络错误和写入结果未知。
2. MCP 测试：initialize、`tools/list`、每个 Tool 的 Schema、一次 mock/dry-run 成功、无效入参拒绝和结构化执行错误。
3. 写能力 dry-run：证明零网络、零派发、零写入。
4. 包测试：`npm test`，并运行精简校验器：

```bash
python3 <skill-root>/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

`package.json` 必须包含 `"code2skill": {"profile": "core-export-v1"}`。精简校验器会执行语法检查，并以凭证清理后的固定 `node --test` 命令运行包内测试；它不安装依赖，也不宣称网络隔离，因此先运行 `npm install`，测试自身仍必须 mock 外部请求并遵守 `CODE2SKILL_DRY_RUN=1`。只有排查包结构时才使用 `--skip-tests`，此时结果不得称为“已验证可运行”。

测试代码保留在包内，测试日志和收据不保留。若某个能力无法离线证明，应在 Skill 或交付说明中写清边界，不要为通过验收生成伪证据。

### 8. 交付报告

只报告用户真正需要的状态：生成了哪些能力、离线测试是否通过、是否调用过真实环境、是否安装/注册/部署，以及仍存在的具体限制。不要把“文件已生成”“MCP 能启动”“真实业务已验证”和“已部署”混成一个结论。

## 严格审计模式（显式开启）

`strict-export-v1` 保留兼容，但不再默认执行。只有用户明确要求以下任一内容时才启用：完整证据链、Canonical/Goal Contract、Host compatibility、逐能力 verification matrix、live receipt、finalization、完整 manifest、外部 evaluator 或合规/高风险审计。

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
- Schema 必须在 Function/MCP 运行时真正生效。
- 不把动态目录冻结成一次样本枚举。
- 不把普通后端业务规则升级成虚构的硬 Workflow。
- 不生成任意 `call_api`、本地路径上传或自动重试非幂等写入的逃生口。
- 不把错误压成无法恢复的一段字符串。
- 不在默认验证中访问真实业务环境。
- 不声称 Skill 安装等于 MCP 已注册、认证、验证或部署。
