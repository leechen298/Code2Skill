# 调用方式与语言中立化：升级迭代方案

## 目标

把 Code2Skill 从“主要根据前端 HTTP 调用生成能力”升级为“根据源码中真实存在的业务调用入口生成能力”。用户仍然只调用同一个 `code2skill-generate`，无需选择 Dubbo、gRPC、Java、Python 等专用命令。

本轮只增强生成规则、产物选择和验证口径。Code2Skill 不开发通用 RPC/MQ 客户端、不维护框架清单，也不重新实现原系统业务代码。

## 核心定义

业务能力仍存在于原系统中。生成的 Function 是一层薄适配：

```text
Agent
→ MCP Tool
→ 生成的 Function 适配层
→ 原系统已有 HTTP / RPC / SDK / Service /消息或任务入口
```

Function 负责把 Agent 的业务语义输入稳定映射到原调用入口，并把原始结果或异常交回 Agent；它不复制业务实现。

优先采用目标项目已有的语言、依赖和调用方式：

- 能从生成包直接调用现有入口时，生成可运行的薄包装；
- 必须在原应用进程内调用时，生成适合接入原项目的同语言包装和 MCP 入口；
- 缺少运行上下文、依赖或安全入口时，明确标记“需要接入”，不得用说明文档冒充可运行 Function。

MCP 的 stdio 或 Streamable HTTP 是 Agent 到 Tool 的协议，不等于 Tool 到业务系统也必须使用 HTTP。

## 开发边界

- 保持调用方式：`使用 $code2skill-generate，生成 <代码范围> 中与 <业务目标> 有关的能力。`
- 自动根据源码选择调用方式和实现语言，不增加 `dubbo-generate`、`grpc-generate` 等命令。
- 不按语言或框架穷举规则；识别的是调用语义，而非产品名称。
- 不把任意 public 方法、Repository、消息消费者或定时任务自动暴露为 Tool。
- 不扫描注册中心、Broker、数据库或整台机器寻找能力。
- 默认不连接真实服务，不启动真实业务应用，不发布消息或执行任务。
- 不增加重型契约、能力图、审计报告或新的默认交付文档。
- 保持现有目标决策、Tool 拆分、开放 Schema、source-binding、确定性转换和 Agent 主导原则。
- `strict-export-v1` 本轮只保持兼容，不扩展为多语言执行平台。

## 阶段一：将能力发现改为“真实调用入口”

更新 `code2skill-generate` 以及两个 Review Skill。

发现顺序统一为：

1. 从用户指定的业务目标、代码范围、入口符号或调用方开始；
2. 有客户端或 Consumer 时，优先沿真实调用链追踪；
3. 没有客户端时，只从用户指定且源码证明可调用的公开业务入口开始；
4. 追踪输入来源、客户端或 Consumer 归一化、确定性转换、返回值、副作用与停止边界；
5. 合同足够生成时停止，不默认深入全部实现和下游依赖。

工作记忆中的调用契约使用中立概念：

- 调用目标与操作；
- 参数、消息或任务载荷及其来源；
- 身份、租户、事务等运行上下文由谁提供；
- 同步返回、异常、发布回执、任务 ID 或状态查询；
- 读写副作用、幂等和结果未知边界；
- 运行时怎样接入原能力。

HTTP 的 method/URL/query/header/body，RPC 的 service/method/arguments，消息的 destination/key/payload 等只是该契约在不同项目中的具体表现。

## 阶段二：让 Producer 选择最薄的实现方式

Producer 根据目标仓库的现有实现选择以下一种方式，不在 Code2Skill 中预置框架专用生成器。

### 方式 A：进程外直接调用

原能力已有可调用的 HTTP、RPC、gRPC、SDK 或命令客户端时，Function 复用该客户端，只封装参数映射、确定性转换、认证接入和结果传递。

### 方式 B：原运行时内包装

原能力依赖依赖注入、事务、拦截器、线程上下文或应用内 Service 时，在原项目技术栈内生成薄包装和 MCP 入口。不得把业务方法搬到新的 Node 包后假装语义等价。

### 方式 C：需要宿主接入

如果缺少可安全调用的客户端或运行上下文，保留可证明的 Skill、Tool 契约与接入说明，并明确能力尚不可运行。不得生成万能 `call_rpc`、`invoke_method` 或 `publish_message` Tool，也不得声称已经完成部署。

无论采用哪种方式：

- Tool 仍按业务决策边界设计，不按接口或方法数量机械映射；
- Function 不要求 Agent 手工拼协议 wire；
- 原系统返回值和异常尽量原样交给 Agent，不统一猜测业务成功；
- 异步发布或任务入队只说明“已接收/已入队”，源码存在状态查询时再生成独立查询能力；
- 运行配置由部署环境提供，不作为用户业务参数，也不写死测试、预发或生产值。

## 阶段三：放宽产物与验证的语言假设

默认产物的逻辑组成保持不变：Function、MCP、Skill、测试和安装说明；具体文件扩展名、依赖清单和启动方式允许跟随目标技术栈。

同步调整：

- `SKILL.md` 中把 `fetch`、HTTP 状态和 API 基址改为 HTTP 场景的具体规则，不再作为所有 Function 的定义；
- `MCP-SETUP.md` 说明实际运行语言、依赖、启动命令、运行配置和未满足条件；
- 校验器保留目录、Skill、MCP discovery 和安全边界检查，把语言特定的构建与测试交给受控的已知 profile；
- 没有对应 profile 时，运行目标项目已有的离线测试或明确标记“未完成自动运行验证”，不能伪造通过；
- Review 从“比较最终 HTTP 请求”升级为“比较最终业务调用”，继续核对参数来源、顺序、转换、上下文和结果边界。

## 阶段四：匿名验证与代表性重跑

增加少量按调用语义划分的匿名测试，不建设框架组合矩阵：

1. 同步请求—响应：现有 HTTP 场景不得退化；
2. 同步方法调用：使用匿名接口/DTO/Consumer，验证 service/method、参数顺序、确定性转换和异常透传；
3. 应用内 Service：验证 Producer 选择原运行时包装，而不是复制业务实现；
4. 异步提交：验证发布回执或任务 ID 不被写成业务完成；
5. 无可用运行边界：必须输出“需要接入”，不得生成虚假的可运行能力。

随后选择两个代表性代码范围重跑：

- 一个现有 HTTP/前端案例，用来确认旧能力和产物规模没有明显回归；
- 一个非 HTTP、最好来自不同语言的调用案例，用来确认同一命令能生成合理的薄包装或诚实的接入边界。

所有测试默认离线，不调用真实业务接口、RPC、Broker、任务或数据库。

## 验收标准

- 用户仍使用一个 `code2skill-generate`，无需了解底层框架专用命令。
- Generator 不再把 Function 等同于 JavaScript `fetch`。
- Producer 能从真实 Consumer、SDK、公开 Service 或任务入口识别业务能力。
- 生成代码复用原系统能力，不复制业务实现，不将内部方法批量暴露成 Tool。
- 能运行的产物提供真实可执行薄包装；不能运行的产物准确说明缺失接入条件。
- HTTP 现有代表案例的主流程、测试和产物规模没有明显退化。
- 至少一个非 HTTP 匿名案例通过离线生成与 Review。
- README、生成结果说明、三个 Skill、模板和相关测试表达同一套边界。
- 全量测试与 `git diff --check` 通过；没有真实业务调用。

## 停止条件

达到上述验收标准即停止本轮，不继续追求：

- 穷举所有语言、RPC、消息和任务框架；
- 在 Code2Skill 中实现通用调用中间件；
- 自动解决注册中心、服务治理、事务、身份或部署平台问题；
- 为每种技术栈增加专用命令和模板；
- 证明生成结果在所有项目中都能直接上线。

后续只根据真实使用中重复出现的通用缺口继续迭代。单一框架或单一项目问题优先留给生成 Agent 和使用方调整，不上升为 Code2Skill 的默认复杂度。

## 建议修改范围

- `skills/code2skill-generate/SKILL.md`
- `skills/code2skill-review-flow/SKILL.md`
- `skills/code2skill-review-source/SKILL.md`
- `skills/code2skill-generate/assets/core-feature-context.md`
- `skills/code2skill-generate/assets/core-MCP-SETUP.md`
- `skills/code2skill-generate/scripts/validate_core_export.py`（仅必要的 profile/语言中立调整）
- `README.md`
- `docs/generated-results.md`
- 匿名测试与 fixture

开发时保留用户现有未提交内容，不修改文章与图片，不提交、不推送，除非用户另行要求。
