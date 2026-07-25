# 安装与 MCP 注册

Code2Skill 把安装分成三个独立层次：

1. 安装 Agent Skill，让 Agent 能发现并理解工作方法。
2. 安装生成包的运行依赖。
3. 在 Consumer Host 中注册并连接 MCP Server。

不存在一个跨所有 Agent/Host 的通用命令同时完成这三件事。Code2Skill 使用现有通用标准和各 Host 的注册入口，不发明私有的一键安装协议。

## 安装 Code2Skill

仓库包含三个可独立安装的 Skill：

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill-generate code2skill-review-flow code2skill-review-source \
  --agent "$AGENT_ID" \
  --global \
  --yes
```

`$AGENT_ID` 使用 `skills` CLI 支持的 Agent 标识，例如 `codex`、`openclaw` 或 `kimi-code-cli`。项目级安装时去掉 `--global`；本地开发时把仓库地址替换为 `.`。

查看、更新和移除：

```bash
npx skills list --global --agent "$AGENT_ID"
npx skills update --global --yes
npx skills remove --global --agent "$AGENT_ID" \
  code2skill-generate code2skill-review-flow code2skill-review-source
```

Code2Skill 使用的是通用 [`skills` CLI](https://github.com/vercel-labs/skills)，不是本仓库自行开发的安装器。

### 从旧生成名迁移

主生成 Skill 已从 `code2skill` 更名为 `code2skill-generate`。名称变化不能依赖普通 update 自动删除旧入口：先安装并确认新名称可发现，再移除旧名称。

```bash
npx skills list --global --agent "$AGENT_ID"
npx skills remove --global --agent "$AGENT_ID" code2skill
```

仓库不同时保留两个生成 Skill，避免 Agent 在 `code2skill` 和 `code2skill-generate` 之间重复发现或错误路由。

## 安装生成的 Skill

生成包包含一个或多个业务 Skill：

```bash
npx skills add ./generated/code2skill/<feature-id> \
  --skill '*' \
  --agent "$AGENT_ID" \
  --global \
  --yes
```

这一步只安装 Skill 知识与引导文件，不会安装 Node 依赖、启动 MCP、注入认证或验证真实业务。

## 安装 MCP 依赖

在生成包内安装锁定依赖：

```bash
cd /absolute/path/to/generated/code2skill/<feature-id>
npm ci
```

没有 `package-lock.json` 时使用 `npm install`。安装依赖不等于 MCP 已注册或已连通。

## 通用 MCP 注册模型

根据 [MCP transport specification](https://modelcontextprotocol.io/specification/draft/basic/transports)，标准传输包括：

- **stdio**：Consumer Host 启动本地子进程。适合 Code2Skill 默认生成的本地 Node MCP。
- **Streamable HTTP**：Host 连接已经部署的远程 MCP endpoint。

本地 stdio 注册的可移植信息是启动描述，而不是某个 Host 的配置文件格式：

```json
{
  "command": "node",
  "args": [
    "/absolute/path/to/generated/code2skill/<feature-id>/mcp-tool/index.mjs"
  ],
  "cwd": "/absolute/path/to/generated/code2skill/<feature-id>",
  "env": {
    "<SOURCE_PROVEN_VARIABLE>": "<provided-by-deployment>"
  }
}
```

Consumer Host 将 `command`、`args`、`cwd` 和 `env` 映射到自己的 MCP 注册方式。部分 Host 使用名为 `mcpServers` 的 JSON 容器，另一些提供 CLI 或图形界面；`mcpServers` 是 Host 配置惯例，不是 MCP 协议本身。

使用绝对路径可以避免桌面 Host 或不同工作目录导致入口解析失败。MCP Server 的 stdout 只输出协议消息，普通日志写入 stderr。

如果生成包被独立部署为远程服务，则向 Consumer Host 提供 Streamable HTTP endpoint URL，并通过该 Host 支持的安全凭证机制配置认证。远程注册没有跨 Host 统一的 JSON 文件格式；Code2Skill 不负责部署远程网关，也不把认证值写进 Skill、源码或示例配置。

## Codex 注册示例

Codex 当前 CLI 可以直接注册本地 stdio Server：

```bash
codex mcp add <feature-id> -- \
  node /absolute/path/to/generated/code2skill/<feature-id>/mcp-tool/index.mjs
codex mcp list --json
```

非敏感配置可以按 CLI 支持的 `--env KEY=VALUE` 传入；密钥、Cookie 和会话值应通过实际 Host 的安全环境或凭证机制提供，避免出现在仓库和命令历史中。

已经部署的远程 Server 可使用：

```bash
codex mcp add <feature-id> \
  --url https://mcp.example.invalid/mcp \
  --bearer-token-env-var <TOKEN_ENV_VAR>
```

这里传入的是保存令牌的环境变量名，不是令牌值。

其他 Host 使用生成包 `MCP-SETUP.md` 中相同的中立启动参数完成注册，不需要 Code2Skill 为每个平台生成不同业务实现。

## 连通与状态

注册后至少完成：

1. MCP `initialize` 成功；
2. `tools/list` 返回预期 Tool；
3. dry-run 或 mock 下的代表性 `tools/call` 成功；
4. 真实接口调用只在用户明确授权后进行，写能力不得为了探针自动执行。

以下状态不能互相推导：

- **Skill 已安装**：Agent 能发现 `SKILL.md`。
- **依赖已安装**：生成包的运行依赖存在。
- **MCP 已注册**：Host 保存了启动参数或远程 URL。
- **MCP 已连通**：`initialize` 与 `tools/list` 已通过。
- **离线行为已验证**：本地 mock/dry-run 测试通过。
- **真实业务已验证**：授权的真实环境调用通过。
- **已部署**：独立部署动作完成。

生成包自己的 `MCP-SETUP.md` 应列出准确入口、依赖、环境变量和认证边界，但不得声称前一状态自动证明后一状态。
