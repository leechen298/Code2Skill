# 生成结果的结构和设计原则

Code2Skill 默认生成完成主要业务目标所需的可运行内容，而不是制作完整源码审计档案。程序内部仍使用 `core-export-v1` 识别这一目录格式，普通使用者不需要理解或填写这个名称。

## 能力发现

候选能力面来自源码中真实存在的业务调用入口：客户端功能以客户端/Consumer 实际触发的调用为主；没有客户端时，从用户指定的公开 API、RPC、Service、消息或任务入口开始。页面未调用的后端内部方法、任意 public 方法、Repository、消息消费者或定时任务不会因为“被搜索到”就自动暴露为 Tool。

授权范围内的源码、协议和测试默认只用于补齐：

- 公开 Request/Response、接口定义、Service 方法签名、消息/任务契约等传输结构；
- 鉴权与身份边界；
- 动态值域和枚举；
- 客户端直接使用的附件上传接口；
- 与客户端契约存在的明确矛盾。

公开契约足够时停止，不追踪完整 Service、副作用和内部校验。源码不可用时，可以基于已证明的调用契约生成诚实的部分产物，并明确未知项和运行边界。

源码发现不绑定语言或固定架构。`DTO`、`Request`、`Response`、`Schema`、函数参数、协议定义和运行时对象都可能承担数据传输契约；名称只是定位线索。

## 目标与 Tool

用户指定的页面、目录或接口只是搜索范围。Code2Skill 先识别其中可以独立完成的主要用户目标：

- 单一目标生成根 `SKILL.md`；
- 多个目标分别生成 `skills/<goal>/SKILL.md`；
- 多个 Skill 可以共享同一套 Function/MCP 原子能力；
- 每个 Skill 只描述自己的调用链，公共 Tool 不自动成为全局前置步骤。

Tool 数量由独立业务语义、调用价值、契约稳定性和安全复用边界决定，不由页面、接口或函数数量机械决定。

## 生成目录

默认产物的逻辑组成保持不变，具体扩展名、依赖清单和启动方式跟随目标技术栈的 runtime profile。当前 `core-export-v1` 默认格式由 `node-stdio` profile 实现：

```text
generated/code2skill/<feature-id>/
├── SKILL.md                  # 单一主要目标
├── skills/                   # 多目标时替代根 SKILL.md
│   ├── <goal-a>/SKILL.md
│   └── <goal-b>/SKILL.md
├── MCP-SETUP.md
├── package.json              # node-stdio profile 示例
├── function-core/index.mjs   # node-stdio profile 示例
├── mcp-tool/index.mjs        # node-stdio profile 示例
├── portable-agent-result.mjs # node-stdio profile 通用结果投影辅助库（其中 readHttpResponse/httpResultFromError 仅 HTTP 使用）
├── tests/*.test.mjs          # node-stdio profile 示例
└── references/
    └── feature-context.md    # 复杂业务确有必要时生成
```

根 `SKILL.md` 和 `skills/*/SKILL.md` 二选一。多目标包中，每个 Skill 需要的参考资料放在自己的 `references/` 下，不能依赖安装后不存在的父目录文件。

生成目录不携带重复 Contract、证据目录、Host 报告、验证矩阵、收据或 manifest。`package.json` 中的 `code2skill.profile=core-export-v1` 仅供校验程序识别包格式。

## 三种产出方式

Producer 根据目标仓库的现有实现选择以下一种方式，不在 Code2Skill 中预置框架专用生成器：

- **方式 A：可直接运行的薄包装**。原能力已有可调用的 HTTP、RPC、gRPC、SDK 或命令客户端时，Function 复用该客户端，只封装参数映射、确定性转换、认证接入和结果传递。
- **方式 B：原运行时内包装**。原能力依赖依赖注入、事务、拦截器、线程上下文或应用内 Service 时，在原项目技术栈内生成薄包装和 MCP 入口。不得把业务方法搬到新的 Node 包后假装语义等价。
- **方式 C：需要宿主接入**。如果缺少可安全调用的客户端或运行上下文，保留可证明的 Skill、Tool 契约与接入说明，并明确标记 `requires-host-integration`。不得生成万能 `call_rpc`、`invoke_method` 或 `publish_message` Tool，也不得声称已经完成部署。

异步发布或任务入队只说明「已接收/已入队」，源码存在状态查询时才生成独立查询能力；不得把发布回执或任务 ID 写成业务完成。

## 请求语义

Function 负责源码能够直接证明的请求构造：

- 字段来源按“接口/调用返回 → 页面或调用方状态 → 最终调用”追踪，不能按同名字段猜测语义；
- 当前选中结果若被整行展开或以多个字段并入下游请求，Function 公开语义明确的选中记录输入，Skill 的标准示例也真实传递该记录；未经证明不能擅自简化成只传 ID；
- 查询用途与最终写入用途不同的字段使用不同公共名称，内部再映射回 API 字段；
- 时间拼接、ISO 格式化、数组/URL 组合和展示值清理等确定性转换进入 Function；
- 没有直接调用链证据的公共能力不能提升为所有写操作的前置条件。

普通业务校验以真实后端调用入口为权威边界。Function/MCP 不复制整套后端规则，Agent 根据实际响应补问、修正、继续或停止。

存在选中记录交接时，离线测试至少用两条不同的匿名记录切换调用一次，确认请求字段随当前选择完整切换、没有残留前一条记录的值。该测试只验证源码已证明的请求构造，不扩展成后端业务规则矩阵。

## 运行地址与环境

业务 API 基址是部署配置，不是用户业务参数；其他场景下同类概念称为「业务服务接入配置」：

- 每个独立服务使用语义明确的环境变量；
- Consumer Host 显式选择并注入实际地址；
- Function 不默认指向源码中的测试、预发或生产环境；
- 缺少必需基址时在请求前停止，不静默回退；
- Tool 参数只承载业务输入，不允许 Agent 临时指定请求域名；
- 离线测试使用 `.invalid`、本地 Mock 或注入的假基址。

源码中发现的环境地址可以写入 `MCP-SETUP.md` 供部署人员参考，但不代表该环境已经配置、连通或验证。公开协议固定的第三方 endpoint，以及后端运行时返回的上传、回调或预签名地址，不属于业务服务的隐藏默认值。

## Schema 与响应

输入 Schema 用于向 Agent 描述已知参数，默认：

- 使用开放对象；
- 业务字段采用带说明的宽松值；
- 不因常见数值/字符串、`null`、缺失或额外参数差异提前阻断；
- Function 只把源码证明有发送位置的参数写入真实请求。

默认不声明输出 Schema，避免真实响应在到达 Agent 前被严格校验拦截。

HTTP 场景下，基于 `fetch` 的 Function 收到任何 HTTP 状态时返回：

- `httpStatus`；
- 未经业务判断的完整 `bodyText`。

若底层客户端因 4xx/5xx 抛出带响应异常，也尽量还原状态和响应正文为普通 Tool 结果。Code2Skill 不替 Agent添加成功、失败、重试或写入结果判断。只有完全没有响应的底层异常才通过 MCP `isError` 传递可序列化信息。

## 附件边界

附件接收属于 Consumer Host；Code2Skill 只生成源码证明的业务上传和下游绑定：

- 优先接收 `attachmentRef` 等 Host 提供的不透明引用；
- Host 明确保证来源和可访问性时，可使用运行时注入的 `hostFilePath`；
- Function/MCP 负责业务 STS、预签名、对象存储上传以及业务 URL 绑定；
- Code2Skill 不实现聊天消息接入、文件下载或通用 Host 沙箱。

如果源码只能证明取得上传凭证，无法证明完成上传和绑定，就应明确标记目标未闭环，不能接受用户自报 URL 来伪装完成。

## Feature Context

默认不生成 `PAGE.md`。只有业务背景、动态信息、跨目标共享概念或重要边界无法在 Skill/Function 中清楚表达时，才生成可选的 `references/feature-context.md`。

它是业务理解背景，不是主要产物、执行契约或页面专属文档。

## 离线验证

```bash
cd generated/code2skill/<feature-id> && npm install
cd -
python3 skills/code2skill-generate/scripts/validate_core_export.py \
  generated/code2skill/<feature-id>
```

校验器检查：

- 最小目录和依赖声明；
- JavaScript 语法；
- MCP `initialize + tools/list`；
- 包内固定离线测试。

校验默认清理业务凭证，不执行真实接口和候选声明的任意 lifecycle 命令，也不声称业务正确。测试必须 mock 外部请求。若包在 `package.json` 标记 `code2skill.requiresHostIntegration`，校验器报告「静态结构与 MCP discovery 通过，运行验证未完成」。

`code2skill-generate` 不自行声明主流程完整或源码精确。需要完成度判断时使用 `code2skill-review-flow`；高价值或可疑目标再使用 `code2skill-review-source`。两个 Review 都默认只读、离线。

## 仓库与隐私边界

Code2Skill 仓库只保存通用规范、模板、生成器、校验器和虚构合成测试。目标项目中的以下内容只能在仓外、用户授权的生成或评估过程中读取：

- 私有源码、接口路径、字段、枚举和业务名称；
- 日志、真实响应、运行地址和业务常量；
- 私有 evaluator、Golden、fixture、源码快照和录制证据；
- token、Cookie、密钥、会话或其他运行时凭证。

不得为了复现真实案例把这些内容复制回本仓库。可复用结论应先抽象为跨项目规则，再以无业务含义的合成数据编写回归测试。
