# Code2Skill vNext：稳定产物架构

## 目标

vNext 的目标不是生成更多文件，而是让产物更可靠：从真实代码中还原正确的业务契约，允许 Agent 按用户目标逐步补齐信息、自由组合能力，并确保写入和其他高风险动作无法绕过硬约束。

稳定产物应同时做到：

- **契约正确**：输入、输出、动态选项、条件必填、失败规则和副作用都有可追溯证据；
- **能力完整**：完成一个目标所依赖的查询、计算、校验、附件和提交能力没有被无意遗漏；
- **交互灵活**：用户不需要一次性提供全部信息，Agent 只补问当前真正缺少的内容；
- **可组合**：能力可以单独满足部分目标，也可以与其他 Tool 或 Skill 临时组合；
- **校验分层**：普通业务接受规则以真实后端 API 为权威，只有不可绕过的身份、确认、来源、事务和防重规则由运行时强制；
- **状态诚实**：每项能力分别说明生成、验证和宿主兼容状态，不能用一次成功掩盖其余未验证能力；
- **可移植**：业务理解不依赖某种语言、框架、目录习惯或 Agent 品牌。

## 四个边界清晰的层次

```text
获授权的真实源码与测试
        ↓
Producer：具备代码搜索、理解、编辑和测试能力的编程 Agent
        ↓
Portable Core：语言无关、宿主无关的业务与能力事实
        ↓
Runtime Profile：把 Portable Core 变成某种可执行 Tool 服务
        ↓
Consumer Host：发现 Skill、与用户交互并调用 Tool 的 Agent 宿主
```

### Producer

Code2Skill 默认在编程 Agent 中运行，因为生成工作需要阅读代码、追踪调用链和执行测试。但规范只依赖这些能力，不依赖某个具体产品的私有命令、记忆机制或交互方式。

Producer 只能搜索用户明确授权的源码根目录。它可以处理同仓前后端、多个本地仓库、独立接口契约库和测试库；不得为了“自动发现后端”扫描整台机器。某个根目录不可访问或关键实现不存在时，要记录搜索范围和缺口，而不是猜测。

对客户端 feature，Producer 先从客户端实际调用的后端 API 确定候选能力面，再用授权的后端、协议和测试代码补充核对契约和安全语义。后端中与该客户端调用链无关的内部方法，不会因为被搜到就自动暴露为 Function 或 Tool。用户明确指定的 backend-only feature 则以其真实对外入口为能力面。

### Portable Core

Portable Core 是唯一的业务事实来源。它回答：这个功能是什么、有哪些独立能力、完成用户目标需要哪些信息、这些信息从哪里来、哪些规则必须强制、已有证据能证明到什么程度。

Portable Core 不包含 Node、Python、stdio、某个 MCP SDK 或某个 Agent Host 的实现假设。它也不把 `DTO`、`Controller`、`Service` 等命名当成成立条件。

### Runtime Profile

Runtime Profile 负责把 Portable Core 变成可执行实现。一个 Profile 可以指定语言、SDK、传输、打包方式和静态检查面，但不能反过来改变业务契约。

现有 `strict-export-v1` 在 vNext 中明确为 **`node-stdio` 严格审计 Profile**：自包含 Node Function core、官方 MCP SDK、Zod、stdio transport、逐 Tool 字面注册和可复制运行包。它继续受支持，但只在用户明确要求完整证据、Host/运行时验证或 finalization 时启用；普通生成默认使用 `core-export-v1` 精简运行包。

vNext 不再保留页面形状的主产物。业务背景统一写入 `references/feature-context.md`，`export-profile.json.featureSurface` 记录真实类型和稳定标识，不生成 `PAGE.md`，也不使用 `pageRoute`。旧版包可继续被兼容读取，但不得将这两个遗留字段重新引入 vNext 契约。

未来增加其他 Runtime Profile 时，应复用相同 Portable Core，并通过等价性测试证明输入、输出、失败和硬约束一致，而不是重新理解一次业务。

### Consumer Host

Consumer Host 负责理解用户目标、渐进收集信息、选择 Skill/Tool、持有可信身份与会话、请求用户确认，以及展示结果。生成物不能假设 Consumer 拥有 Producer 的代码搜索、文件读取或开发工具。

宿主兼容性按能力判断，不按品牌判断。需要声明的能力包括 Skill discovery、MCP transport/runtime、认证注入、可信确认、会话状态、获批准附件的解析和未知结果对账。Host 只提供安全附件引用或受限内容；源码证明的业务上传由生成的 Function/MCP Tool 执行。缺少必要能力时应隐藏、禁用或标记相关能力为 `requires-host-integration`。

## 从代码发现语义，而不是寻找固定架构

发现过程应寻找“代码承担什么职责”，而不是只寻找某类文件名。常见语义角色包括：

- 用户或系统入口；
- 请求与响应的数据传输边界；
- 输入校验、默认值、序列化和转换；
- 身份、权限、租户和会话；
- 应用编排与业务规则；
- 外部 API、RPC、消息或文件服务；
- 持久化和状态变化；
- 测试、协议与运行时行为。

这些职责可能出现在任意语言、函数、类型、装饰器、配置、协议文件或运行时代码中。文件名和框架惯例只能帮助定位，不能单独证明契约。

## 多源码根与证据拓扑

`source-topology.json` 记录本次生成获授权且实际搜索过的根目录。每个根目录应有稳定 `sourceId`、用途、可访问状态和搜索结果摘要，例如客户端、服务端、协议或测试，但这些用途只是证据角色，不要求特定目录布局。

每条证据通过 `sourceId + 相对路径 + 符号/定位理由` 重新定位。绝对路径只用于当前执行环境，不进入可移植产物。无法访问的根、已搜索但未找到的语义角色和相互冲突的事实都必须显式保留。

若写能力缺少鉴权、重大副作用、幂等、可信确认或未知结果处理的权威证据，该能力不得进入可执行的 `ready` 状态。若只缺少普通业务校验的完整本地复制证据，不应自行猜测并生成前置 Guard；应让真实 API 保持权威，并将其业务拒绝作为结构化错误返回给 Agent。

## Canonical Contract：一份业务事实，多种确定性产物

`canonical-contract.json` 是 Function、MCP Tool、Skill、Workflow 和测试共同依赖的唯一权威契约。它不要求目标项目本身使用某种 Schema 或类型系统。

它至少表达：

- 能力的稳定身份、目的、输入和输出；
- 输出的静态值域、动态值域或明确不约束的来源形态；
- 始终必填、条件必填、条件禁止和跨字段规则；
- 用户提供、可信宿主上下文、上游 Tool、动态查询或派生计算等来源；
- 身份、租户、会话、版本、有效期和刷新条件；
- HTTP、RPC、本地或其他执行边界的精确请求与成功条件；
- 失败字段、固定判别值和最小可用结果；
- 副作用、确认、幂等、重试和未知结果策略；
- 每项关键结论的 `fact`、`inference` 或 `unknown` 以及证据引用。

派生器应从这份契约生成或核对公开输入、Function 校验、MCP Schema、文档表述和测试向量。任何两个交付面出现不一致都应失败，不能靠人工解释其“含义差不多”。

可执行事实必须绑定到当前操作：副作用、HTTP step 与字段绑定、输出与成功条件、条件规则、动态范围/有效期和复用策略分别引用语义匹配的 fact-level 证据。只证明“接口存在”的入口证据、推断，或另一条操作的证据，不能让当前能力进入 `ready`。

每个没有父级可继承的输出都显式声明 `valueDomain`。`static` 只包含 `kind/values/evidenceRefs`，值逐项满足输出 Schema；`dynamic` 显式声明 `identityScoped/tenantScoped/sessionScoped` 三个布尔值、freshness 和证据，不能冻结一次观测到的选项；`unconstrained` 只包含 `kind`，用于源码只证明类型而没有闭合或动态目录语义的结果。嵌套输出只有在路径确实位于已声明父输出下时才能继承父级值域。

Function 和 MCP 只确定性执行已证明的公开契约：基本结构、类型、绑定、序列化、安全边界和最小成功结果。后端返回的普通业务拒绝应保留为可机器区分的错误，至少能区分输入结构、业务、权限、上游/网络、响应契约与未知写入结果，并在证据可用时保留原始错误码、字段细节、可否重试与结果确定性。

副作用和确认采用一套闭合词汇：Capability 与 `operationPolicy.sideEffect` 使用 `read/create/update/delete`；`operationPolicy.confirmation` 使用 `not-required/trusted-confirmation-required/upload-confirmation-required`。真正的 enforcement owner 由 Consumer requirements 和 `workflows[].enforcement.owner` 表达，不再维护 `confirmationOwner` 等平行字段。

同一批源码和同一证据边界重复生成时，稳定业务身份、字段语义、能力边界、约束和 Goal 应保持一致。文件顺序、临时绝对路径、漂移行号或一次运行样本不能改变核心契约；若语义确实变化，应输出可审阅的契约差异，而不是悄悄生成另一套解释。

## Goal Contract：围绕目标收集信息

Canonical Contract 中的目标定义描述用户想完成的目标及其完成条件，再确定性投影为 `goal-contract.json`；它不把原页面点击顺序固化成唯一流程。

每项信息应标明：

- `required`：任何情况下都需要；
- `requiredWhen`：条件成立时才需要；
- `optional`：缺少时仍能完成目标；
- `derived`：只能来自明确 Capability 输出或已声明的可信 Host requirement，不能让用户自报，也不能写一个没有可执行契约的“本地推导”；
- `dynamic`：必须通过明确 Capability 输出或已声明的可信 Host requirement，在当前身份和有效期内动态获取，不能让用户自报，也不能把某次返回值写成固定枚举。

Skill 应指导 Consumer：

1. 先识别目标和用户已经给出的信息；
2. 根据当前条件计算缺失项；
3. 优先复用仍然有效的可信上下文和上游结果；
4. 能由只读 Tool 安全取得时先调用 Tool；
5. 只询问无法自动取得且当前确实需要的信息；
6. 条件变化或动态数据过期后重新计算缺失项；
7. 达到 completion predicate 后才进入确认或提交。

同一缺失信息存在多个兼容提供者时，Goal state 应把它们作为 `one-compatible-provider` 选择项交给 Consumer，而不是默认全部调用；仅来自可信 Host context 的值也应与“向用户提问”分开报告。用户一次给全时应直接跳过多余问答；用户只需要部分结果时应在部分目标完成后停止。

每个 information need 都声明类型和可执行 Schema，并通过 `supplies` 精确映射到参与 Goal 的 Capability 输入；每个目标输入在同一 Goal 中恰好由一个 need 供应。来源、Schema/基数和 mapping kind 必须兼容；一个 need 供应多个输入时，至少存在一个对全部目标都兼容的共同来源，可信 Host requirement ID 也必须精确一致。optional need 不能供应无条件必填输入。`requiredWhen` 路径必须能从这些 Schema 解析，并与目标 Capability 输入条件等价；acquisition provider、supplies 和 activation 组成的完整依赖图不能成环。object-form conditional Capability 复用其关联 need 的同一条件，显式 `conditionalNeedsOnlyWhenActive` 只能为 `true`。条件尚未确定时 Goal 保持 pending。`reuseWhile` 只接受有证据的可执行 true claims：当前刚取得的值以 `acquiredNow` 标记，缓存值必须逐项提供 `reuseProof`，裸 `fresh: true` 不能绕过。

## 能力图与动态组合

Canonical Contract 内的 `capabilityGraph` 描述能力之间可用的 handoff、可选依赖和硬前置条件。它不是固定流程图，也不再维护一份容易漂移的独立能力图文件。

每项能力都应声明：

- 能独立满足什么用户目标；
- 需要哪些输入，产生哪些可复用输出；
- 哪些输出可以交给哪些下游输入；
- 何时可以跳过，何时应停止；
- 是否有副作用；
- 哪些前置条件只是推荐，哪些必须由运行时强制。

Agent 可以按当前目标临时组合不同 MCP Tool 或 Skill。源码中已观察到的组合标为 `observed`；契约兼容但源码中没有出现的新组合标为 `derived composition`。只读的 derived composition 可以在契约和权限允许时执行；涉及写入时，仍必须经过相同的硬约束和单独验证。

页面控件不是 Tool 边界，原页面顺序也不是唯一组合。Tool 应按独立业务价值和安全复用边界拆分。

## 硬 Workflow 只保护不可绕过的子图

确定性 Workflow 只用于有证据表明在安全、事务或一致性上不能自由调整的部分，例如：

- 服务端签发了不可伪造的校验凭证，且源码证明它必须与最终请求完全一致；
- 动态选择值必须来自当前身份下仍有效的查询；
- 上传结果必须来自批准的附件；
- 可信确认必须绑定源码证明的最小字段；只有真实契约存在会话、请求摘要、校验凭证、有效期或单次使用语义时才加入这些绑定；
- 非幂等写入最多派发一次；
- 派发后结果不确定时停止并对账，不能自动重试。

vNext 的 `canonical-contract.json.workflows[]` 只包含这类已证明的硬约束，必须以非空 `capabilityIds` 明确覆盖成员并包含 `entryCapabilityId`，指向实际 enforcement owner，并有运行时 guard 和绕过测试；不得再手写一份 `workflow.json` 形成双重真相。每个绑定明确实际来源、受保护的期望来源、比较方式和证据；期望值不能来自同一个公开 Tool 参数。通用 Guard 不执行任意 verifier 回调，避免在 Guard 消费操作前隐藏网络或文件副作用。没有硬约束的简单写能力可以直接调用真实 API，普通业务校验失败通过结构化错误恢复，不生成通用 preflight、validation grant 或 Workflow。旧版 bundle-only 包仍使用原有 `workflow.json`。若真正不可绕过的条件只能写在 Skill 文档中，相关写路径保持 `requires-review`。

每个写能力都用 `runtimeProtection.mode` 明确分类：`backend-authoritative` 表示真实目标 API 负责普通校验；`deterministic-workflow` 表示存在已证明且必须在派发前执行的硬边；`unresolved` 表示客户端调用已证实但后端保护边界缺失。`unresolved` 只能是 `requires-review` 或 `blocked`，不得猜测 owner、Workflow 或生产安全性。

## 附件是完整能力链，不是一个 URL 字段

附件模型应覆盖：宿主提供用户批准的附件引用或受限内容，生成的业务能力根据源码契约获取上传授权、执行上传、取得结果令牌、URL、文件 ID、对象键或对象，并把结果绑定到下游请求。上传输出、下游输入来源、typed handoff、observed graph edge、consumer binding 与实际请求字段必须相互一致，不能让用户自行填一个看似合法的结果冒充上传链路。若输入是 Host 的不透明授权引用，它本身只是引用和元数据，生成实现必须先通过通用 `attachment-resolution` 能力解析成受控内容或流，再绑定到源码证明的 body/multipart 字段；不能把授权对象 JSON 当成文件上传。`attachments.contentBindings` 必须把这一事实逐项写成 input、resolver requirement、最终请求 step、location 和 path，并与 `implementation.outputStepId` 中全部解析后绑定唯一且逐字段一致。每个真实 body/multipart 目标字段必须由 fact-level 的 request-construction、serialization 或 transport-contract 证据证明，并与可执行绑定共享该证据；仅证明入口、接口存在或副作用发生不足以证明精确字段。

公开 Tool 只能接收：

- Host 批准的附件引用；或
- 受限内容以及源码或部署边界要求的文件名、媒体类型、大小、Hash 等元数据。

永远不能让 Agent 传入任意本地文件路径。Code2Skill 不实现消息通道、文件接收/下载或特定宿主适配器；这些是外部运行环境的责任。若 Consumer 不能提供已批准附件，相关目标应标记 `requires-host-integration` 或 `blocked`，而不是接受一个未经证明的 URL 假装链路完整。

## Skill 安装与 MCP 连接是两个独立阶段

生成的 Skill 应可通过 `npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y` 安装到支持 Agent Skills 的 Consumer。该命令只安装 Skill 知识文件，不会启动或注册 MCP，也不提供认证与环境变量。

每个 vNext 包必须生成平台中立的 `MCP-SETUP.md`，分别说明 MCP 启动命令、Host 注册所需 command/args/cwd、必需环境变量、认证注入边界和 `tools/list/tools/call` 连通验证。安装、MCP 连通、Host 兼容和真实业务验证必须分别报告。

## 宿主要求与安全降级

Canonical Contract 内声明每项能力需要的宿主能力，再确定性投影为 `consumer-requirements.json`。`host-profile.json` 由实际宿主或部署者提供。`host-compatibility-report.json` 对二者做确定性比较，并按能力和目标输出。该状态只描述 Host 可达性；Canonical `readiness: requires-review` 继续由 verification matrix 表达，不能伪装成 `requires-host-integration`：

- `enabled`：宿主具备执行与安全保障；
- `requires-host-integration`：业务契约完整，但缺少宿主桥接；
- `disabled`：在该宿主中不应暴露；
- `blocked`：源码或运行时证据本身不足。

例如，缺少可信确认时可保留只读能力，但禁用依赖确认的最终写入；缺少会话状态时禁用需要一次性凭证绑定的非幂等流程；缺少附件桥接时禁用依赖附件的路径。降级应精确到能力和目标，不必让整个 Skill 一律失败。

## 逐能力、逐 Workflow 验证

`verification-matrix.json` 记录每项能力和每个硬 Workflow 的证据，不再用一个包级成功状态代替全部验证。状态至少区分：

- `generated`：产物存在且可解析；
- `behavior-verified`：输入、输出、失败和组合测试通过；
- `runtime-verified`：真实 MCP client/runtime 已调用；
- `host-verified`：在声明的 Host Profile 中完成兼容验证；
- `requires-review`：契约或安全证明不足，需人工或额外环境；
- `blocked`：已知条件不满足，当前不可用。

只读 Tool 的一次成功调用不能批准其他 Tool。无法安全进行真实写入时，写能力可以保持 `requires-review`，但不能被其他能力的 `runtime-verified` 覆盖。Finalization 应允许诚实的部分可用包，同时拒绝把未验证能力标成已批准。

验证还应覆盖不同信息到达顺序、信息已齐全时跳过多余调用、derived composition、过期/错身份/错会话/重复凭证、每条硬约束的绕过、附件链、未知写入结果以及宿主能力降级。

Finalization 的输入报告使用 `assets/verification-report.schema.json`：Capability 逐项记录 behavior/runtime/host，Workflow 逐项记录 bypass/runtime/host。passed runtime check 必须绑定 Canonical Tool 名称以及匹配 live input/result 的 Hash；passed bypass check 必须证明零外部写入。live input/result 以 Capability ID 成对提供，可以重复传入，但不能用一个成功命令或一个只读 Tool 的 live 结果替代其他行的证据。

每个 Capability 的最低验证 `checkId` 由契约机械派生，手写检查只能追加；passed phase 缺少任何适用检查即失败。附件 runtime proof 精确绑定 Canonical `stepId/location/path`，并要求 trace digest 与 check evidence digest 自洽。`hostVerified` 只有在 Host phase passed 且 compatibility 为 `enabled` 时成立；写能力始终需要该 Host 验证，Canonical `requires-review` 不能改写成宿主缺口。

## strict-export-v1 的迁移边界

vNext 采用增量迁移，不让当前可用输出突然失效：

1. `strict-export-v1` 的 Node/stdio 行为继续受支持，并明确命名为 `node-stdio` Runtime Profile；vNext 文档树改为 `references/feature-context.md`、`SKILL.md`、`MCP.zh-CN.md` 和 `MCP-SETUP.md`。
2. 新增 Portable Core 文件后，现有 `capability-bundle.json` 可作为 Canonical Contract 的执行视图，但不再承担 Goal、来源拓扑、宿主要求和逐能力验证的全部职责。
3. 旧版包在旧校验器下仍可验证；存在 `canonical-contract.json` 且其 `schemaVersion` 为 `vNext` 时视为声明 vNext，必须包含新增契约并通过新增一致性检查。
4. vNext 的 Function、MCP、文档和测试都从 Canonical Contract 派生或核对。Runtime Profile 只添加执行细节，不能改字段名、必填性、值域或安全策略。
5. 包级 `approved` 逐步迁移为能力级和 Workflow 级状态；迁移期仍可生成汇总状态，但必须由所有明细状态计算，不能反向覆盖明细。
6. 增加新 Runtime Profile 时必须新增等价性验证，不得复制并分叉 Portable Core。

## 仓库污染边界

真实项目案例只在仓外用于验证 Code2Skill。Code2Skill 仓库只能保留通用规范、通用实现和虚构合成测试，不能复制真实项目的代码、接口路径、字段名、枚举、业务名称、日志、密钥、私有 evaluator、Golden 或 fixture。

从真实案例得到的经验必须先抽象为跨项目成立的规则，再用无业务含义的合成样例验证。污染扫描是 finalization 前的必做门禁。
