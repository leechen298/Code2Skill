# Code2Skill

Code2Skill 是一个可移植的 Agent Skill：让 Claude Code、Codex 等现成编程 Agent 从已有前端、后端或全栈代码中提取业务背景，生成可组合的 MCP Tools，并还原原产品的 Observed Skill。

它不自研代码扫描器或新的 Coding Agent。代码搜索、理解、编辑和测试继续由宿主编程 Agent 完成；Code2Skill 固化能力建模方法、证据规则、完整交付契约与验收标准。

## 核心模型

```text
现有代码
   ↓
Feature Context       这个功能和字段在业务中是什么意思
   +
Atomic MCP Tools      Agent 可独立选择、复用和组合的执行能力
   +
Observed Skill        原产品已有的使用知识、条件路径与恢复方式
   ↓
strict-export-v1      可执行、可审计、可由外部评测器验收的完整能力包
```

核心原则：

> MCP Tool 提供可组合的执行能力；Skill 提供领域知识、选择策略和默认流程；Agent 根据用户目标决定本次组合；Schema、Handler、Server 或确定性 Workflow 强制不可绕过的约束。

Tool 数量不由页面、接口、请求或函数数量决定，而由独立业务语义、调用价值、契约稳定性和安全复用边界决定。

## 安装

```bash
npx skills add leechen298/Code2Skill --skill code2skill
```

全局安装到 Codex 和 Claude Code：

```bash
npx skills add leechen298/Code2Skill \
  --skill code2skill \
  --global \
  --agent codex \
  --agent claude-code
```

本地开发时：

```bash
npx skills add . --skill code2skill --global --agent codex --yes
```

## 使用

在目标代码仓库中调用：

```text
使用 $code2skill，把 /knowledge 的客户端功能生成完整 strict-export-v1。
请沿前后端真实调用链实现 MCP Tools、Observed Skill，并完成协议与运行时验证。
```

也可以用于纠正已有页面级大 Tool：

```text
使用 $code2skill 审计当前实现，按独立业务能力重新拆分，
重建 Function、MCP、Skill、测试和当前 Golden；旧结果只保留为 superseded 历史。
```

默认输出：

```text
generated/code2skill/<feature-id>/
├── export-profile.json
├── capability-bundle.json
├── capability-draft.json
├── PAGE.md
├── SKILL.md
├── MCP.zh-CN.md
├── function-core/
├── mcp-tool/
├── workflow.json              # 仅硬写入子图需要
├── preflight-report.json
├── approval-audit.json
├── live-verification.json
└── export-manifest.json
```

这不是三份说明文档：包内必须有独立命名 Function、可执行 stdio MCP Server、逐 Tool 中文契约、真实检查记录、live 调用哈希和全文件完整性清单。

## 校验与收口

生成阶段：

```bash
python3 skills/code2skill/scripts/validate_artifacts.py \
  generated/code2skill/<feature-id> \
  --source-root . \
  --pre-finalize
```

完成真实单元、协议和 live 调用后：

```bash
python3 skills/code2skill/scripts/finalize_export.py \
  generated/code2skill/<feature-id> \
  --verification-report /path/to/executed-checks.json \
  --live-input /path/to/sanitized-input.json \
  --live-result /path/to/sanitized-result.json
```

`finalize_export.py` 不接受失败的 live 结果，也不接受没有实际命令的检查报告。无法 live 验证时，产物只能报告为 generated / built，不能伪造 passed / approved。

运行仓库测试：

```bash
python3 -m unittest discover -s tests -v
```

## 仓库边界

Code2Skill 只包含通用建模规范、模板和校验器。目标项目的代码、私有评测器、案例答案、Golden、业务常量和运行时密钥都只能在仓外测试时读取或注入，不能复制进本仓库。

Skill 遵循 [Agent Skills specification](https://agentskills.io/specification)。安装命令使用 [vercel-labs/skills](https://github.com/vercel-labs/skills)。MCP 产物遵循目标项目声明的 MCP SDK 与协议版本。
