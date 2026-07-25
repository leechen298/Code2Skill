# <feature name> 的 Skill 安装与 MCP 连接

> 这是 vNext 模板。生成时用实际 `<feature-id>`、包路径、环境变量和认证边界替换占位符，并删除本说明。不要写入真实密钥或特定 Host 的私有配置格式。

## Skill 安装

```bash
npx skills add ./generated/code2skill/<feature-id> -a <agent-id> -g -y
```

这个命令只安装 Skill 知识文件。它不会启动或注册 MCP，不会注入认证信息，也不能证明 Function、MCP 或真实业务环境已经可用。

## MCP 启动

使用生成包的绝对路径启动 stdio MCP Server：

```bash
node <absolute-package-path>/mcp-tool/index.mjs
```

<如果 Runtime Profile 不是 Node/stdio，改为 `export-profile.json` 证明的实际启动方式。>

stdio 与 Streamable HTTP 是 MCP 标准传输。本模板的 `node-stdio` Runtime Profile 使用本地 stdio；只有包已被独立部署为远程服务时，才改用 Consumer Host 的 Streamable HTTP 注册入口。

## Host 注册参数

将下列中立参数映射到 Consumer Host 支持的 MCP 注册方式：

```json
{
  "command": "node",
  "args": ["<absolute-package-path>/mcp-tool/index.mjs"],
  "cwd": "<absolute-package-path>",
  "env": {
    "<SOURCE_PROVEN_VARIABLE>": "<provided-by-deployment>"
  }
}
```

Code2Skill 只提供这些通用运行参数，不生成聊天通道、文件接收/下载或特定平台的私有适配器。部分 Host 使用 `mcpServers` 包裹这些字段，但那是 Host 配置惯例，不是 MCP 协议要求。

## 环境变量与认证

- `<DRY_RUN_VARIABLE>`：仅在值为 `1` 时进入 dry-run，不得产生外部副作用。
- `<SOURCE_PROVEN_VARIABLE>`：<说明来源、用途、必填性与不得记录的敏感边界。>
- 认证与用户/租户身份由部署 Host 或目标应用支持的认证边界注入。不得把 token、cookie、密钥或会话值写入 `SKILL.md`、`references/feature-context.md`、manifest 或示例命令。
- 每个 MCP Tool handler 的第二个参数是运行时提供的可信 `runtimeContext`。生成回调只能把 `(input, runtimeContext)` 原样交给对应 Function，不能从公开 Tool 参数构造身份、Guard、确认、会话、dispatcher 或 protected state。若部署运行时不能提供 Capability 声明的上下文设施，该能力必须禁用或保持 `requires-host-integration`。
- 若 `consumer-requirements.json` 声明 `attachment-resolution`，部署必须提供把不透明 Host 授权引用解析为受控内容或流的通用设施；业务上传 Tool 使用该结果，但本包不实现消息接入、附件接收或下载适配器。缺少该设施时，附件相关能力保持 `requires-host-integration`。

## 连通验证

1. 确认 MCP 进程能从独立复制的生成包启动。
2. 使用 MCP client 完成 `initialize`。
3. 调用 `tools/list`，核对 Tool 名称、Schema 与 Canonical Contract 一致。
4. 在安全 mock/测试边界为每个 Tool 提供一条符合输出 Schema 的成功用例和一条进入 handler 的结构化错误用例；handler 使用审阅过的 `portable-error-normalizer.mjs`，成功直接投影 Function 结果，失败保留 `code/message/details/retryable`，未知写入结果始终不可自动重试。在 `<DRY_RUN_VARIABLE>=1` 下覆盖每个写 Tool，核对完整 policy、原始已验证输入以及 `content`/`structuredContent`。另用可计数的 dispatcher 行为测试证明 dry-run 与 Guard 拒绝路径为零外部副作用。
5. 只对当前部署已授权且安全的能力执行真实 `tools/call`，并按 Capability 分别保留证据。无法安全调用的写能力保持未验证，不得为了探针而操作生产数据。

## 状态边界

- **Skill 已安装**：Host 的 Skill discovery 能找到知识文件。
- **MCP 已注册**：Host 已保存正确的 command/args/cwd/env 配置。
- **MCP 已连通**：`initialize` 和 `tools/list` 已通过。
- **行为已验证**：对应 Capability 的确定性测试已通过。
- **运行时已验证**：对应 Capability 拥有自己的真实 MCP 调用证据。
- **Host 已验证**：所需认证、确认、会话、附件或未知结果能力已按 `host-profile.json` 核对。
- **已部署**：独立的交付动作成功。

上述状态必须分别报告，不得由前一项推导后一项。
