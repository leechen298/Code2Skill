# Code2Skill vNext：稳定产物架构

## 目标

vNext 的目标不是生成更多文件，而是让产物更可靠：从真实代码中还原正确的业务契约，允许 Agent 按用户目标逐步补齐信息、自由组合能力，并确保写入和其他高风险动作无法绕过硬约束。

稳定产物应同时做到：

- **契约正确**：输入、输出、动态选项、条件必填、失败规则和副作用都有可追溯证据；
- **能力完整**：完成一个目标所依赖的查询、计算、校验、附件和提交能力没有被无意遗漏；
- **交互灵活**：用户不需要一次性提供全部信息，Agent 只补问当前真正缺少的内容；
- **可组合**：能力可以单独满足部分目标，也可以与其他 Tool 或 Skill 临时组合；
- **约束可执行**：必须执行的校验、确认、身份绑定和防重规则由运行时强制；
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

### Portable Core

Portable Core 是唯一的业务事实来源。它回答：这个功能是什么、有哪些独立能力、完成用户目标需要哪些信息、这些信息从哪里来、哪些规则必须强制、已有证据能证明到什么程度。

Portable Core 不包含 Node、Python、stdio、某个 MCP SDK 或某个 Agent Host 的实现假设。它也不把 `DTO`、`Controller`、`Service` 等命名当成成立条件。

### Runtime Profile

Runtime Profile 负责把 Portable Core 变成可执行实现。一个 Profile 可以指定语言、SDK、传输、打包方式和静态检查面，但不能反过来改变业务契约。

现有 `strict-export-v1` 在 vNext 中明确为 **`node-stdio` Runtime Profile**：自包含 Node Function core、官方 MCP SDK、Zod、stdio transport、逐 Tool 字面注册和可复制运行包。它仍是默认且受支持的交付路径，但不再代表 Portable Core 的唯一实现。

这个 Profile 为兼容现有交付仍保留 `PAGE.md` 和 `pageRoute`。它们不是 Portable Core 的“必须有 UI 页面”假设。对 API、RPC、消息、worker 等 route-less feature，`featureSurface` 记录真实类型和稳定标识，`pageRoute` 使用 `/__code2skill__/features/<feature-id>` 作为文档键；不得把该保留值描述成真实路由或执行 URL。

未来增加其他 Runtime Profile 时，应复用相同 Portable Core，并通过等价性测试证明输入、输出、失败和硬约束一致，而不是重新理解一次业务。

### Consumer Host

Consumer Host 负责理解用户目标、渐进收集信息、选择 Skill/Tool、持有可信身份与会话、请求用户确认，以及展示结果。生成物不能假设 Consumer 拥有 Producer 的代码搜索、文件读取或开发工具。

宿主兼容性按能力判断，不按品牌判断。需要声明的能力包括 Skill discovery、MCP transport/runtime、认证注入、可信确认、会话状态、附件解析、安全上传和未知结果对账。缺少必要能力时应隐藏、禁用或标记相关能力为 `requires-host-integration`。

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

若写能力缺少鉴权、条件校验、副作用、幂等或未知结果处理的权威证据，该能力不得进入可执行的 `ready` 状态。

## Canonical Contract：一份业务事实，多种确定性产物

`canonical-contract.json` 是 Function、MCP Tool、Skill、Workflow 和测试共同依赖的唯一权威契约。它不要求目标项目本身使用某种 Schema 或类型系统。

它至少表达：

- 能力的稳定身份、目的、输入和输出；
- 静态值域或当前身份下动态取得的值域；
- 始终必填、条件必填、条件禁止和跨字段规则；
- 用户提供、可信宿主上下文、上游 Tool、动态查询或派生计算等来源；
- 身份、租户、会话、版本、有效期和刷新条件；
- HTTP、RPC、本地或其他执行边界的精确请求与成功条件；
- 失败字段、固定判别值和最小可用结果；
- 副作用、确认、幂等、重试和未知结果策略；
- 每项关键结论的 `fact`、`inference` 或 `unknown` 以及证据引用。

派生器应从这份契约生成或核对公开输入、Function 校验、MCP Schema、文档表述和测试向量。任何两个交付面出现不一致都应失败，不能靠人工解释其“含义差不多”。

副作用和确认采用一套闭合词汇：Capability 与 `operationPolicy.sideEffect` 使用 `read/create/update/delete`；`operationPolicy.confirmation` 使用 `not-required/trusted-confirmation-required/upload-confirmation-required`。真正的 enforcement owner 由 Consumer requirements 和 `workflows[].enforcement.owner` 表达，不再维护 `confirmationOwner` 等平行字段。

同一批源码和同一证据边界重复生成时，稳定业务身份、字段语义、能力边界、约束和 Goal 应保持一致。文件顺序、临时绝对路径、漂移行号或一次运行样本不能改变核心契约；若语义确实变化，应输出可审阅的契约差异，而不是悄悄生成另一套解释。

## Goal Contract：围绕目标收集信息

Canonical Contract 中的目标定义描述用户想完成的目标及其完成条件，再确定性投影为 `goal-contract.json`；它不把原页面点击顺序固化成唯一流程。

每项信息应标明：

- `required`：任何情况下都需要；
- `requiredWhen`：条件成立时才需要；
- `optional`：缺少时仍能完成目标；
- `derived`：应由可信计算或上游结果产生，不能让用户随意填写；
- `dynamic`：必须在当前身份和有效期内动态获取，不能把某次返回值写成固定枚举。

Skill 应指导 Consumer：

1. 先识别目标和用户已经给出的信息；
2. 根据当前条件计算缺失项；
3. 优先复用仍然有效的可信上下文和上游结果；
4. 能由只读 Tool 安全取得时先调用 Tool；
5. 只询问无法自动取得且当前确实需要的信息；
6. 条件变化或动态数据过期后重新计算缺失项；
7. 达到 completion predicate 后才进入确认或提交。

用户一次给全时应直接跳过多余问答；用户只需要部分结果时应在部分目标完成后停止。

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

确定性 Workflow 只用于安全、事务或一致性上不能自由调整的部分，例如：

- 服务端校验结果必须与最终请求完全一致；
- 动态选择值必须来自当前身份下仍有效的查询；
- 上传结果必须来自批准的附件；
- 可信确认必须绑定用户、会话、目标、请求摘要、校验凭证、有效期和单次使用；
- 非幂等写入最多派发一次；
- 派发后结果不确定时停止并对账，不能自动重试。

vNext 的 `canonical-contract.json.workflows[]` 必须指向实际 enforcement owner，并有运行时 guard 和绕过测试；不得再手写一份 `workflow.json` 形成双重真相。旧版 bundle-only 包仍使用原有 `workflow.json`。若这些条件只能写在 Skill 文档中，写能力保持 `requires-review`，不得暴露为完整可用。

## 附件是完整能力链，不是一个 URL 字段

附件模型应覆盖：宿主取得用户批准的附件引用、解析受限元数据或内容、获取上传授权、执行安全上传、取得结果令牌或 URL、把结果绑定到下游请求。

公开 Tool 只能接收：

- Host 批准的附件引用；或
- 受限的文件名、媒体类型、大小、Hash 和内容表示。

永远不能让 Agent 传入任意本地文件路径。若 Consumer 不支持附件解析或安全上传，相关目标应标记 `requires-host-integration` 或 `blocked`，而不是接受一个未经证明的 URL 假装链路完整。

## 宿主要求与安全降级

Canonical Contract 内声明每项能力需要的宿主能力，再确定性投影为 `consumer-requirements.json`。`host-profile.json` 由实际宿主或部署者提供。`host-compatibility-report.json` 对二者做确定性比较，并按能力和目标输出：

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

## strict-export-v1 的迁移边界

vNext 采用增量迁移，不让当前可用输出突然失效：

1. `strict-export-v1` 的现有目录和 Node/stdio 行为继续受支持，并明确命名为 `node-stdio` Runtime Profile。
2. 新增 Portable Core 文件后，现有 `capability-bundle.json` 可作为 Canonical Contract 的执行视图，但不再承担 Goal、来源拓扑、宿主要求和逐能力验证的全部职责。
3. 旧版包在旧校验器下仍可验证；存在 `canonical-contract.json` 且其 `schemaVersion` 为 `vNext` 时视为声明 vNext，必须包含新增契约并通过新增一致性检查。
4. vNext 的 Function、MCP、文档和测试都从 Canonical Contract 派生或核对。Runtime Profile 只添加执行细节，不能改字段名、必填性、值域或安全策略。
5. 包级 `approved` 逐步迁移为能力级和 Workflow 级状态；迁移期仍可生成汇总状态，但必须由所有明细状态计算，不能反向覆盖明细。
6. 增加新 Runtime Profile 时必须新增等价性验证，不得复制并分叉 Portable Core。

## 仓库污染边界

真实项目案例只在仓外用于验证 Code2Skill。Code2Skill 仓库只能保留通用规范、通用实现和虚构合成测试，不能复制真实项目的代码、接口路径、字段名、枚举、业务名称、日志、密钥、私有 evaluator、Golden 或 fixture。

从真实案例得到的经验必须先抽象为跨项目成立的规则，再用无业务含义的合成样例验证。污染扫描是 finalization 前的必做门禁。
