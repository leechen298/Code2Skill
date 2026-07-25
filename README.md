# Code2Skill

Code2Skill 是一组可安装的 Agent Skills。它帮助编程 Agent 从用户授权的前端、后端或全栈代码中理解业务功能，并生成可供其他 Agent 使用的 Function、MCP Tools、业务 Skills 和离线测试。

```text
现有代码
  ↓ Code2Skill
Function + MCP Tools + Skills + Tests
  ↓
Agent 逐步取得信息并完成用户目标
```

Function 和 MCP 提供业务能力，Skill 负责引导 Agent 使用这些能力。是否调用、如何补问、如何理解接口响应以及下一步做什么，由实际调用的 Agent 决定。

## 它会做什么

- 以前端实际调用的后端接口为主要能力来源，按需读取后端公开请求和响应结构。
- 从用户指定的页面、目录或功能中识别可以独立完成的主要目标。
- 将字段来源、请求组装和确定性的格式转换写入 Function。
- 为主要目标分别生成 Skill，并复用必要的 Function 和 MCP Tool。
- 默认只做离线技术验证，不主动调用真实业务接口。

## 安装

使用通用 Agent Skills CLI 一次安装三个 Skill：

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill-generate code2skill-review-flow code2skill-review-source \
  --agent "$AGENT_ID" \
  --global \
  --yes
```

- `code2skill-generate`：生成 Function、MCP、业务 Skill 和离线测试。
- `code2skill-review-flow`：检查用户能否通过主要流程完成目标。
- `code2skill-review-source`：深入检查请求字段、转换和调用链是否符合源码。

日常生成只需要 `code2skill-generate`，两个 Review Skill 按需独立使用。旧版本迁移、生成结果的依赖安装和 MCP 注册见[安装说明](docs/installation.md)。

## 快速使用

在目标代码仓库中调用，并明确允许搜索的源码范围：

```text
使用 $code2skill-generate，把 <页面、目录或功能路径> 生成为可运行的 Function、MCP 和 Skills。
允许搜索的源码根目录：<前端目录>、<后端目录>、<协议目录>。
以前端实际调用的接口为主要能力来源，不调用真实业务接口。
```

需要复核时：

```text
使用 $code2skill-review-flow，审核 <生成结果路径> 的主要目标是否能够完成。

使用 $code2skill-review-source，审核 <生成结果路径> 中 <指定 Skill 或能力> 与授权源码是否一致。
```

## 生成结果

```text
generated/code2skill/<feature-id>/
├── SKILL.md 或 skills/*/SKILL.md
├── function-core/index.mjs
├── mcp-tool/index.mjs
├── portable-agent-result.mjs
├── tests/
├── package.json
├── MCP-SETUP.md
└── references/feature-context.md  # 复杂业务才生成
```

每个生成目录的 `MCP-SETUP.md` 会说明依赖安装、启动方式、环境变量和 MCP 注册方法。Skill 已安装、MCP 已连接和真实业务已验证是三个独立状态。

## 生成效果参考

同一份匿名、多目标源码的三次生成记录：

| 生成模型/运行配置 | 生成日期 | 生成耗时 | 综合参考分 |
|---|---|---:|---:|
| Codex（Ultra） | 2026-07-24 | 47 分 45 秒 | **9.4** |
| Kimi Code（K3） | 2026-07-24 | 约 93 分钟 | **8.9** |
| Codex（High） | 2026-07-24 | 20 分 29 秒 | **8.4** |

耗时统计到生成和当轮离线验证完成，不包含之后单独进行的评分、目录调整、安装或部署。评分方法、两套评分体系和隐私边界见[完整评估报告](docs/evaluation.md)。

## 文档

- [安装 Skill、生成结果依赖与注册 MCP](docs/installation.md)
- [生成结果的结构和设计原则](docs/generated-results.md)
- [可选的高级验证流程](docs/advanced-validation.md)
- [生成模型、评分方法与匿名评估结果](docs/evaluation.md)
- [完整文档索引](docs/README.md)

Skill 遵循 [Agent Skills specification](https://agentskills.io/specification)，安装使用 [vercel-labs/skills](https://github.com/vercel-labs/skills)。生成的 MCP 使用标准 stdio 或 Streamable HTTP 传输。
