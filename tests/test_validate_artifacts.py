from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "code2skill" / "scripts"
VALIDATOR = SCRIPTS / "validate_artifacts.py"
FINALIZER = SCRIPTS / "finalize_export.py"
DERIVER = SCRIPTS / "derive_artifacts.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def long_skill() -> str:
    detail = "智能体必须根据用户已经提供的信息选择最小调用集合，核对字段来源，解释返回值，并在目标完成或证据不足时停止。" * 18
    return f"""---
name: use-knowledge-search
description: 当用户需要查看知识主题、理解主题代码含义或为后续检索收集可靠输入时，使用本技能选择只读工具并组织中文回答。
---

# 使用知识检索能力

## 定位与适用范围

本 Skill 是只读使用知识，不是固定脚本。{detail}

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
{{"isError":true,"content":[{{"type":"text","text":"错误：输出结构不符合契约"}}]}}
```

{detail}
"""


def create_base(root: Path, *, write_side_effect: bool = False) -> Path:
    candidate = root / "candidate"
    candidate.mkdir()
    profile = {
        "schemaVersion": "v1",
        "profile": "strict-export-v1",
        "protocolVersion": "2025-11-25",
        "transport": "stdio",
        "documentationLanguage": "zh-CN",
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
    (candidate / "mcp-tool").mkdir()
    (candidate / "mcp-tool/runtime.mjs").write_text(
        "class McpServer {} class StdioServerTransport {} const z = {}; export { McpServer, StdioServerTransport, z };\n",
        encoding="utf-8",
    )
    (candidate / "mcp-tool/index.mjs").write_text(
        "import { McpServer, StdioServerTransport, z } from './runtime.mjs'; "
        "const server = new McpServer({name: 'knowledge-capabilities', version: '1'}); "
        "const structuredContent = {}; const isError = true; "
        "server.registerTool('list_knowledge_topics', {"
        "title: '知识主题：列出可用主题', "
        "description: '面向需要查看知识主题的用户，用于在调用检索能力前读取可靠目录；本工具无入参，返回主题代码与中文标签，可用于直接回答并停止，也可作为可靠输入交给下游继续检索；它在本地执行，不产生任何 HTTP 请求，属于只读能力且没有写入副作用，失败时应停止。', "
        "inputSchema: {}, outputSchema: {}}, async (input) => { "
        "if (process.env.CODE2SKILL_DRY_RUN === '1') return {structuredContent: {dryRun: true, validatedInput: input, operationPolicy: {}, operationSummary: {}}, isError: false}; "
        "return {structuredContent, isError}; }); "
        "await server.connect(new StdioServerTransport());\n",
        encoding="utf-8",
    )
    (candidate / "PAGE.md").write_text(long_page(), encoding="utf-8")
    (candidate / "SKILL.md").write_text(long_skill(), encoding="utf-8")
    (candidate / "MCP.zh-CN.md").write_text(long_mcp(), encoding="utf-8")
    return candidate


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

    def test_write_bundle_requires_workflow(self) -> None:
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
