# MCP 安装与运行

## 安装 Skill

```bash
npx skills add <bundle-path> --skill <skill-name> -a <agent-id> -g -y
```

这一步只安装 Agent Skill，不会自动安装或注册 MCP Server。

## 安装 MCP 依赖

```bash
cd <bundle-path>
npm install
```

## 启动与注册

MCP 入口：

```bash
node mcp-tool/index.mjs
```

把这条命令及生成包路径写入 Consumer Host 的 MCP 配置。认证信息由运行环境通过环境变量或已有凭证机制注入，不写入 Skill 或源码。

## 离线检查

```bash
CODE2SKILL_DRY_RUN=1 npm test
```

安装完成、MCP 可达、真实接口已验证和已部署是不同状态。默认验证不请求真实业务接口；只有用户明确授权时才执行真实调用。
