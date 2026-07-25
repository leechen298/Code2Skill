# MCP 安装与运行

> 生成时用实际包路径、Agent ID、环境变量和 dry-run 变量替换占位符；没有对应环境变量时删除示例项。不得在交付文件中保留占位符或真实凭证。

## 安装 Skill

```bash
npx skills add <bundle-path> --skill '*' --agent <agent-id> --global --yes
```

这一步只安装 Agent Skill，不会安装依赖、启动或注册 MCP Server，也不会注入认证信息。

## 安装 MCP 依赖

生成包带有 `package-lock.json` 时：

```bash
cd <absolute-bundle-path>
npm ci
```

没有 lockfile 时使用 `npm install`。

## 本地 stdio MCP

默认生成包使用 MCP 标准 stdio 传输，由 Consumer Host 启动本地子进程：

```bash
node <absolute-bundle-path>/mcp-tool/index.mjs
```

把以下中立启动参数映射到 Consumer Host 的 MCP 注册入口：

```json
{
  "command": "node",
  "args": ["<absolute-bundle-path>/mcp-tool/index.mjs"],
  "cwd": "<absolute-bundle-path>",
  "env": {
    "<SOURCE_PROVEN_VARIABLE>": "<provided-by-deployment>"
  }
}
```

这是可移植的启动描述，不是某个 Host 的私有配置文件。使用绝对路径；stdout 仅输出 MCP 协议消息，普通日志写入 stderr。

## 远程 MCP

只有本包已经被独立部署为远程服务时，才按 Consumer Host 的方式注册 Streamable HTTP endpoint。Code2Skill 不负责部署远程网关，也不把某个 Host 的 `mcpServers` 等配置惯例写成 MCP 协议要求。

## 环境变量与认证

- 只列出源码或 Runtime Profile 能证明的环境变量。
- 认证、用户和租户身份由运行环境通过环境变量或已有凭证机制注入。
- 不把 token、Cookie、密钥、会话值或真实凭证写入 Skill、源码、示例命令或本文件。
- dry-run 变量：`<DRY_RUN_VARIABLE>`，仅在值为 `1` 时生效。

## 离线检查

```bash
<DRY_RUN_VARIABLE>=1 npm test
```

注册后使用 MCP client 完成 `initialize`、`tools/list` 和安全 mock/dry-run 的代表性 `tools/call`。真实业务接口默认不调用；只有用户明确授权时才执行，写接口不得为了探针自动调用。

## 状态边界

- **Skill 已安装**：Agent 能发现 Skill。
- **依赖已安装**：包的运行依赖存在。
- **MCP 已注册**：Host 保存了启动参数或远程 URL。
- **MCP 已连通**：`initialize` 和 `tools/list` 已通过。
- **离线行为已验证**：mock/dry-run 测试通过。
- **真实业务已验证**：授权的真实调用通过。
- **已部署**：独立部署动作完成。

这些状态必须分别报告，不能互相推导。
