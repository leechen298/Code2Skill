# 在 DeepSeek Harness 中使用 Code2Skill

Code2Skill 同时以 DeepSeek Harness Bundle 的形式发布。Bundle 只把仓库中的三个 Agent Skill 挂载到 Harness 的 Skill Registry，不安装业务依赖、不注册生成后的业务 MCP，也不执行安装脚本。

## 安装

先安装 DeepSeek Harness 和 `pnpm`，然后把固定版本安装到需要使用的 profile：

```bash
dsh plugin --profile web add github:leechen298/Code2Skill#v1.1.3
```

如果使用一次性 headless profile，需要单独安装：

```bash
dsh plugin --profile headless add github:leechen298/Code2Skill#v1.1.3
```

每个 profile 管理自己的依赖，因此安装到 `web` 不会自动安装到 `headless`。

## 验证

不启动模型即可确认 Bundle 已加入配置层：

```bash
dsh --profile web --dump-default-config
```

输出中应包含：

```text
code2skill-bundled-skills
code2skill-bundle
```

启动 Web UI 后，在 standard 或 code 类型的 Agent 会话中确认以下三个 Skill 可见：

- `code2skill-generate`
- `code2skill-review-flow`
- `code2skill-review-source`

Harness 的 minimal Agent preset 按设计只保留最小工具集合，不加载 Skill Tool；这不属于 Code2Skill 安装失败。

## 使用

在已选择源码 workspace 的会话中调用：

```text
使用 $code2skill-generate，生成 <代码路径> 中与 <业务目标> 有关的能力。
不调用真实业务服务。
```

Code2Skill 生成的业务 MCP 仍需按照每份产物中的 `MCP-SETUP.md` 单独安装和注册。安装 Code2Skill Bundle、加载生成后的 Skill、连接业务 MCP 和验证真实业务结果是四个独立状态。

## 卸载

```bash
dsh plugin --profile web remove @leechen298/code2skill
```

DeepSeek Harness 当前仍处于 Developer Preview，Bundle/Profile 契约可能出现不兼容变化。Code2Skill 会以固定 Tag 发布已验证版本；生产或团队环境不建议长期跟随可变的默认分支。
