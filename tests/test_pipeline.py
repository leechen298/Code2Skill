"""Regression tests for the staged Producer pipeline (run_pipeline.py).

All scenarios use generic synthetic projects only: a fictional read-only
knowledge-topic capability with local implementation, synthetic source roots,
and a self-contained minimal MCP stdio runtime. No real business system,
credential, or network target is involved.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill-generate"
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contract_model import operation_summary_for_capability  # noqa: E402
from tests.test_validate_artifacts import (  # noqa: E402
    create_base,
    install_document_contract_markers,
    write_json,
)
from tests.test_vnext_finalization import install_complete_readonly_vnext  # noqa: E402

PIPELINE = SCRIPTS / "run_pipeline.py"
READ_CAPABILITY_ID = "list-knowledge-topics"
READ_TOOL = "list_knowledge_topics"
WRITE_CAPABILITY_ID = "rebuild-knowledge-index"
WRITE_TOOL = "rebuild_knowledge_index"
CAPABILITY_ID = READ_CAPABILITY_ID
TOOL_NAME = READ_TOOL
GOAL_ID = "inspect-fictional-topics"
NODE_AVAILABLE = shutil.which("node") is not None

TOOL_TEXT = {
    READ_TOOL: {
        "title": "知识主题：列出可用主题",
        "description": "面向需要查看知识主题的用户，用于在调用检索能力前读取可靠目录；本工具无入参，返回主题代码与中文标签，可用于直接回答并停止，也可作为可靠输入交给下游继续检索；它在本地执行，不产生任何 HTTP 请求，属于只读能力且没有写入副作用，失败时应停止。",
    },
    WRITE_TOOL: {
        "title": "知识索引：更新主题索引",
        "description": "面向需要刷新知识主题索引的管理用户，用于在主题数据变更后重建本地索引快照；本工具无入参，返回是否完成重建的布尔结果，结果可交给下游检索能力使用，也可直接向用户报告并结束；它在本地执行，不产生任何 HTTP 请求，属于创建类写能力，会更新本地索引状态，失败时不得自动重试并应按未知结果处理。",
    },
}

MINIMAL_RUNTIME_JS = """// Minimal self-contained MCP stdio runtime for synthetic pipeline tests.
class StdioServerTransport {}
class McpServer {
  constructor(info) { this.info = info; this.tools = new Map(); }
  registerTool(name, config, callback) { this.tools.set(name, { config, callback }); }
  async connect(transport) { startStdio(this); }
}
const z = { note: 'synthetic tests declare plain JSON schemas instead of zod builders' };
export { McpServer, StdioServerTransport, z };

function send(value) { process.stdout.write(JSON.stringify(value) + '\\n'); }

function validateArguments(schema, args) {
  if (!schema || typeof schema !== 'object') return null;
  if (typeof args !== 'object' || args === null || Array.isArray(args)) return 'arguments must be an object';
  const properties = schema.properties || {};
  for (const key of schema.required || []) {
    if (!(key in args)) return `missing required argument: ${key}`;
  }
  if (schema.additionalProperties === false) {
    for (const key of Object.keys(args)) {
      if (!(key in properties)) return `unexpected argument: ${key}`;
    }
  }
  for (const [key, sub] of Object.entries(properties)) {
    if (!(key in args) || !sub || typeof sub !== 'object') continue;
    const value = args[key];
    const types = Array.isArray(sub.type) ? sub.type : [sub.type];
    const matches = types.some((type) => {
      if (type === 'null') return value === null;
      if (type === 'array') return Array.isArray(value);
      if (type === 'object') return typeof value === 'object' && value !== null && !Array.isArray(value);
      if (type === 'integer') return Number.isInteger(value);
      return typeof value === type;
    });
    if (!matches) return `argument ${key} has the wrong type`;
    if (Array.isArray(sub.enum) && !sub.enum.includes(value)) return `argument ${key} must be one of the declared enum values`;
  }
  return null;
}

function toolListing(name, tool) {
  return {
    name,
    title: tool.config.title,
    description: tool.config.description,
    inputSchema: tool.config.inputSchema,
    outputSchema: tool.config.outputSchema,
    annotations: tool.config.annotations,
  };
}

function handleMessage(server, message) {
  if (!message || typeof message !== 'object') return;
  if (message.method === 'notifications/initialized') return;
  if (message.method === 'initialize') {
    send({ jsonrpc: '2.0', id: message.id, result: { protocolVersion: '2025-11-25', capabilities: { tools: {} }, serverInfo: { name: server.info.name, version: server.info.version } } });
    return;
  }
  if (message.method === 'tools/list') {
    send({ jsonrpc: '2.0', id: message.id, result: { tools: [...server.tools.entries()].map(([name, tool]) => toolListing(name, tool)) } });
    return;
  }
  if (message.method === 'tools/call') {
    const name = message.params && message.params.name;
    const tool = server.tools.get(name);
    if (!tool) {
      send({ jsonrpc: '2.0', id: message.id, error: { code: -32602, message: `Unknown tool: ${name}` } });
      return;
    }
    const args = (message.params && message.params.arguments) || {};
    const problem = validateArguments(tool.config.inputSchema, args);
    if (problem) {
      send({ jsonrpc: '2.0', id: message.id, error: { code: -32602, message: `Invalid arguments: ${problem}` } });
      return;
    }
    Promise.resolve(tool.callback(args, {})).then(
      (result) => send({ jsonrpc: '2.0', id: message.id, result }),
      (error) => {
        const structured = { code: 'SYNTHETIC_RUNTIME_FAILURE', message: String((error && error.message) || error), details: {}, retryable: false };
        send({ jsonrpc: '2.0', id: message.id, result: { isError: true, structuredContent: structured, content: [{ type: 'text', text: JSON.stringify(structured) }] } });
      },
    );
  }
}

function startStdio(server) {
  let buffer = '';
  process.stdin.on('data', (chunk) => {
    buffer += chunk;
    let index = buffer.indexOf('\\n');
    while (index >= 0) {
      const line = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      index = buffer.indexOf('\\n');
      if (!line.trim()) continue;
      let message = null;
      try { message = JSON.parse(line); } catch (error) { continue; }
      handleMessage(server, message);
    }
  });
}
"""

FUNCTION_CORE_JS = """function assertZeroInput(input, capability) {
  const unexpected = Object.keys(input || {});
  if (unexpected.length > 0) {
    const error = new Error('unexpected input for a zero-input capability: ' + capability);
    error.code = 'INVALID_INPUT';
    error.details = { unexpected };
    error.retryable = true;
    throw error;
  }
}
export async function listKnowledgeTopics(input, context = {}) {
  assertZeroInput(input, 'list_knowledge_topics');
  return { status: 'success', data: { topics: ['synthetic-topic-alpha', 'synthetic-topic-beta'] } };
}
export async function rebuildKnowledgeIndex(input, context = {}) {
  assertZeroInput(input, 'rebuild_knowledge_index');
  return { status: 'success', data: { rebuilt: true } };
}
"""

ADAPTER_HEADER = """import { McpServer, StdioServerTransport, z } from './runtime.mjs';
import { %s } from '../function-core/index.mjs';
import { normalizeToolError } from '../portable-error-normalizer.mjs';
const server = new McpServer({name: 'knowledge-capabilities', version: '1'});
"""

REGISTRATION_TEMPLATE = """server.registerTool("%s", {
title: '%s',
description: '%s',
inputSchema: %s,
outputSchema: %s,
annotations: %s}, async (input, runtimeContext) => {
if (process.env.CODE2SKILL_DRY_RUN === "1") {
const dryRunResult = {dryRun: true, validatedInput: input, operationPolicy: %s, operationSummary: %s};
return {structuredContent: dryRunResult, content: [{type: 'text', text: JSON.stringify(dryRunResult)}], isError: false}; }
try { const functionResult = await %s(input, runtimeContext);
return {structuredContent: functionResult, content: [{type: 'text', text: JSON.stringify(functionResult)}], isError: false};
} catch (error) { const toolError = normalizeToolError(error, %s);
return {structuredContent: toolError, content: [{type: 'text', text: JSON.stringify(toolError)}], isError: true}; } });
"""

ADAPTER_FOOTER = """await server.connect(new StdioServerTransport());
"""


def build_adapter(schema_contract: dict, contract: dict) -> str:
    exports = ", ".join(
        capability["functionExport"] for capability in contract["capabilities"]
    )
    blocks = []
    for capability in contract["capabilities"]:
        tool = capability["toolName"]
        projected = next(
            item
            for item in schema_contract["capabilities"]
            if item["capabilityId"] == capability["capabilityId"]
        )
        policy = json.dumps(
            capability["operationPolicy"], ensure_ascii=False, separators=(",", ":")
        )
        summary = json.dumps(
            operation_summary_for_capability(capability),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        blocks.append(
            REGISTRATION_TEMPLATE
            % (
                tool,
                TOOL_TEXT[tool]["title"],
                TOOL_TEXT[tool]["description"],
                json.dumps(projected["inputSchema"], ensure_ascii=False),
                json.dumps(projected["outputSchema"], ensure_ascii=False),
                js_annotations(capability["annotations"]),
                policy,
                summary,
                capability["functionExport"],
                policy,
            )
        )
    return ADAPTER_HEADER % exports + "".join(blocks) + ADAPTER_FOOTER


def js_annotations(annotations: dict) -> str:
    """Format annotations as an unquoted-key JS literal (validator idiom)."""
    parts = ", ".join(
        f"{key}: {str(value).lower()}" for key, value in annotations.items()
    )
    return "{" + parts + "}"

WRITE_SKILL_SECTION = """
### `rebuild_knowledge_index`

适用场景：当用户明确要求刷新或重建知识主题索引时调用，用于把本地索引快照更新到最新状态。输入：本工具无入参，调用时传空对象即可，不需要也不接受任何参数。输出：返回 `rebuilt` 布尔结果，表示本次索引快照是否完成重建。交接：重建结果可以传给下游检索能力继续使用，也可以直接向用户报告并独立结束任务。边界：不要把它当作只读查询重复调用，不得用于日常浏览主题，不适用任何写入业务实体的场景；它是创建类写能力，失败时不得自动重试，应按未知结果处理并停止。

### 示例：重建索引

用户确认需要刷新索引时，直接调用 `rebuild_knowledge_index` 并读取 `rebuilt` 结果；如果返回结构化错误，先检查是否仍在 dry-run，再决定停止。

### 示例：只读组合

用户只想看主题时只调用 `list_knowledge_topics`，无需也不应触发 `rebuild_knowledge_index`。

### 示例：失败后恢复

`rebuild_knowledge_index` 返回 `isError` 时，不要自动重试；向用户说明未知结果，再等待明确指示。
"""

WRITE_MCP_SECTION = """
## `rebuild_knowledge_index`

用途：重建知识主题的本地索引快照，适用于用户明确要求刷新索引的场景；它是创建类写能力。入参：无入参，调用时传空对象 `{}`，多余参数会被直接拒绝。出参：`structuredContent.data` 包含 `rebuilt` 布尔字段，文本 content 是同一 JSON 投影。行为：本工具在本地执行，0 次请求、0 HTTP 调用，不访问任何外部系统。失败与错误：结构化错误包含 `code`、`message`、`details`、`retryable` 四个路径；写结果未知时错误码为 `UNKNOWN_DISPATCH_OUTCOME` 且不可重试，示例：`{"isError": true, "structuredContent": {"code": "UNKNOWN_DISPATCH_OUTCOME", "message": "...", "details": {}, "retryable": false}}`。handoff：重建成功后可以把结果交给下游检索能力，也可以直接向用户报告并结束。

调用示例：

```json
{"name": "rebuild_knowledge_index", "arguments": {}}
```

错误示例：

```json
{"isError": true, "content": [{"type": "text", "text": "{\\"code\\":\\"INVALID_INPUT\\"}"}], "structuredContent": {"code": "INVALID_INPUT", "message": "unexpected input", "details": {}, "retryable": true}}
```
"""

WRITE_FEATURE_CONTEXT = """
主题索引重建（`rebuild_knowledge_index`）是同一功能面内的创建类写能力：用户在主题数据变更后要求刷新索引时触发，本地执行并返回 `rebuilt` 结果；失败后不得自动重试，未知结果必须人工核对。

## 副作用、确认与写入

`rebuild_knowledge_index` 属于创建类写能力：它会更新本地索引快照，存在明确副作用；调用前需要用户明确提出重建意图，执行结果必须向用户报告；任何失败或超时都按未知结果处理，不得自动重试，需要人工确认后再决定是否重新发起。
"""


def rebuild_evidence(
    evidence_id: str, source_id: str, locator: str, role: str
) -> dict[str, object]:
    return {
        "evidenceId": evidence_id,
        "sourceId": source_id,
        "locator": locator,
        "semanticRole": role,
        "assertionLevel": "fact",
    }


def install_write_capability(contract: dict) -> None:
    """Add a synthetic local write capability with complete write evidence."""
    error_contract = next(
        item for item in contract["evidenceCatalog"] if item["semanticRole"] == "transport-contract"
    )
    contract["evidenceCatalog"].extend([
        rebuild_evidence("ev-rebuild-request", "fictional-topic-contract", "README.md#synthetic-rebuild-request", "client-api-call"),
        rebuild_evidence("ev-rebuild-contract", "fictional-topic-service", "code2skill-generate/SKILL.md#synthetic-rebuild-contract", "transport-contract"),
        rebuild_evidence("ev-rebuild-side-effect", "fictional-topic-service", "code2skill-generate/SKILL.md#synthetic-rebuild-side-effect", "side-effect"),
        rebuild_evidence("ev-rebuild-auth", "fictional-topic-service", "code2skill-generate/SKILL.md#synthetic-rebuild-auth", "authorization"),
        rebuild_evidence("ev-rebuild-validation", "fictional-topic-service", "code2skill-generate/SKILL.md#synthetic-rebuild-validation", "validation"),
        rebuild_evidence("ev-rebuild-idempotency", "fictional-topic-service", "code2skill-generate/SKILL.md#synthetic-rebuild-idempotency", "idempotency"),
        rebuild_evidence("ev-rebuild-unknown-outcome", "fictional-topic-service", "code2skill-generate/SKILL.md#synthetic-rebuild-unknown-outcome", "unknown-outcome"),
    ])
    read_capability = contract["capabilities"][0]
    write_capability = {
        "capabilityId": WRITE_CAPABILITY_ID,
        "toolName": WRITE_TOOL,
        "functionExport": "rebuildKnowledgeIndex",
        "description": "Rebuild the fictional topic index snapshot.",
        "authentication": "none",
        "readiness": "ready",
        "missingEvidence": [],
        "exposure": {
            "kind": "client-request",
            "evidenceRefs": ["ev-rebuild-request"],
            "supplementalEvidenceRefs": [
                "ev-rebuild-contract",
                "ev-rebuild-side-effect",
                "ev-rebuild-auth",
                "ev-rebuild-validation",
                "ev-rebuild-idempotency",
                "ev-rebuild-unknown-outcome",
            ],
        },
        "inputs": [],
        "outputs": [{
            "path": ["rebuilt"],
            "type": "boolean",
            "schema": {"type": "boolean"},
            "valueDomain": {
                "kind": "static",
                "values": [True],
                "evidenceRefs": ["ev-rebuild-contract"],
            },
            "description": "Whether the synthetic index snapshot was rebuilt.",
            "evidenceRefs": ["ev-rebuild-contract"],
        }],
        "constraints": [],
        "attachments": {"mode": "none"},
        "implementation": {"kind": "local"},
        "successRule": {
            "kind": "output",
            "outputRequired": True,
            "forbiddenOutputKeys": ["error"],
            "requiredOutputPaths": [["rebuilt"]],
            "evidenceRefs": ["ev-rebuild-contract"],
        },
        "errorContract": read_capability["errorContract"],
        "operationPolicy": {
            "sideEffect": "create",
            "idempotency": "at-most-once",
            "automaticRetry": "never",
            "confirmation": "not-required",
            "unknownOutcome": "stop-and-reconcile",
        },
        "runtimeProtection": {
            "mode": "backend-authoritative",
            "owner": "target-api",
            "evidenceRefs": ["ev-rebuild-validation"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        "sideEffect": "create",
        "hostRequirements": [
            "agent-skills-discovery",
            "mcp-tool-invocation",
            "unknown-outcome-reconciliation",
        ],
        "evidenceCoverage": {
            "sideEffect": {"declaredSideEffect": "create", "assertionLevel": "fact", "evidenceRefs": ["ev-rebuild-side-effect"]},
            "backendContract": {"assertionLevel": "fact", "evidenceRefs": ["ev-rebuild-contract"]},
            "authorization": {"assertionLevel": "fact", "evidenceRefs": ["ev-rebuild-auth"]},
            "validation": {"assertionLevel": "fact", "evidenceRefs": ["ev-rebuild-validation"]},
            "idempotency": {"assertionLevel": "fact", "evidenceRefs": ["ev-rebuild-idempotency"]},
            "unknownOutcome": {"assertionLevel": "fact", "evidenceRefs": ["ev-rebuild-unknown-outcome"]},
        },
        "verificationChecks": [],
        "evidenceRefs": [
            "ev-rebuild-request",
            "ev-rebuild-contract",
            "ev-rebuild-side-effect",
            "ev-rebuild-auth",
            "ev-rebuild-validation",
            "ev-rebuild-idempotency",
            "ev-rebuild-unknown-outcome",
        ],
    }
    contract["capabilities"].append(write_capability)
    contract["capabilityGraph"]["nodes"].append({
        "capabilityId": WRITE_CAPABILITY_ID,
        "independentValue": "Rebuild the fictional topic index on explicit user request.",
    })
    contract["consumerRequirements"]["requirements"].append({
        "requirementId": "unknown-outcome-reconciliation",
        "hostCapability": "unknownOutcomeReconciliation",
        "description": "Reconcile unknown outcomes of the synthetic index rebuild.",
        "onMissing": "disable",
    })
    goal = contract["goals"][0]
    goal["informationNeeds"].append({
        "informationId": "topic-filter",
        "classification": "required",
        "type": "string",
        "schema": {"type": "string"},
        "satisfiedBy": [{"kind": "user"}],
    })
    goal["completionPredicate"]["informationIds"] = ["current-topics", "topic-filter"]
    contract["goals"].append({
        "goalId": "rebuild-index-on-request",
        "intent": "Rebuild the fictional topic index on explicit user request.",
        "informationNeeds": [{
            "informationId": "rebuild-result",
            "classification": "required",
            "type": "boolean",
            "schema": {"type": "boolean"},
            "satisfiedBy": [{
                "kind": "capability",
                "capabilityId": WRITE_CAPABILITY_ID,
                "outputPath": ["rebuilt"],
            }],
        }],
        "completionPredicate": {
            "operator": "all-satisfied",
            "informationIds": ["rebuild-result"],
        },
        "agentPolicy": {
            "acceptInformationInAnyOrder": True,
            "reuseFreshInformation": True,
            "askOnlyCurrentlyMissing": True,
            "skipUnnecessaryCapabilities": True,
            "stopWhenPredicateSatisfied": True,
        },
        "requiredCapabilityIds": [WRITE_CAPABILITY_ID],
        "conditionalCapabilityIds": [],
        "optionalCapabilityIds": [],
        "supplies": [],
    })


def extend_topology(topology: dict) -> None:
    service = next(
        source for source in topology["sources"] if source["sourceId"] == "fictional-topic-service"
    )
    service["semanticRoles"] = sorted(
        set(service["semanticRoles"])
        | {"side-effect", "authorization", "validation", "idempotency", "unknown-outcome"}
    )


_MODULE_TMP: tempfile.TemporaryDirectory | None = None
BASE_CANDIDATE: Path | None = None


def setUpModule() -> None:
    global _MODULE_TMP, BASE_CANDIDATE
    _MODULE_TMP = tempfile.TemporaryDirectory(prefix="code2skill-pipeline-base-")
    base_root = Path(_MODULE_TMP.name)
    candidate = create_base(base_root)
    contract = install_complete_readonly_vnext(candidate)
    # Extend the fixture: one synthetic local write capability plus a genuine
    # two-need goal, static output domains so the compiler can derive the
    # Function core, then re-derive every projection and refresh the document
    # contract markers so the candidate stays fully valid. Executable
    # artifacts (function-core, mcp adapter) are produced by the repository
    # compiler itself, which this fixture therefore exercises end to end.
    contract["capabilities"][0]["verificationChecks"] = []
    contract["capabilities"][0]["outputs"][0]["valueDomain"] = {
        "kind": "static",
        "values": [["synthetic-topic-alpha", "synthetic-topic-beta"]],
        "evidenceRefs": ["ev-fictional-topic-response"],
    }
    install_write_capability(contract)
    write_json(candidate / "canonical-contract.json", contract)
    host_profile = json.loads(
        (candidate / "host-profile.json").read_text(encoding="utf-8")
    )
    host_profile["capabilities"]["unknownOutcomeReconciliation"] = {
        "status": "supported"
    }
    write_json(candidate / "host-profile.json", host_profile)
    topology = json.loads(
        (candidate / "source-topology.json").read_text(encoding="utf-8")
    )
    extend_topology(topology)
    write_json(candidate / "source-topology.json", topology)
    derived = subprocess.run(
        [sys.executable, str(SCRIPTS / "derive_artifacts.py"), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
    )
    if derived.returncode != 0:
        raise AssertionError(derived.stderr)
    (candidate / "SKILL.md").write_text(
        (candidate / "SKILL.md").read_text(encoding="utf-8") + WRITE_SKILL_SECTION,
        encoding="utf-8",
    )
    (candidate / "MCP.zh-CN.md").write_text(
        (candidate / "MCP.zh-CN.md").read_text(encoding="utf-8") + WRITE_MCP_SECTION,
        encoding="utf-8",
    )
    (candidate / "references" / "feature-context.md").write_text(
        (candidate / "references" / "feature-context.md").read_text(encoding="utf-8")
        + WRITE_FEATURE_CONTEXT,
        encoding="utf-8",
    )
    install_document_contract_markers(
        candidate,
        json.loads(
            (candidate / "references" / "capability-contracts.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    (candidate / "mcp-tool" / "runtime.mjs").write_text(
        MINIMAL_RUNTIME_JS, encoding="utf-8"
    )
    authoring = candidate / "authoring"
    authoring.mkdir(exist_ok=True)
    write_json(
        authoring / "tool-docs.json",
        {
            tool: {"title": text["title"], "description": text["description"]}
            for tool, text in TOOL_TEXT.items()
        },
    )
    compiled = subprocess.run(
        [sys.executable, str(SCRIPTS / "compile_artifacts.py"), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
    )
    if compiled.returncode != 0:
        raise AssertionError(compiled.stdout + compiled.stderr)
    BASE_CANDIDATE = candidate


def tearDownModule() -> None:
    global _MODULE_TMP
    if _MODULE_TMP is not None:
        _MODULE_TMP.cleanup()
        _MODULE_TMP = None


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="code2skill-pipeline-test-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def run_pipeline(self, *args: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        if env:
            environment.update(env)
        return subprocess.run(
            [sys.executable, str(PIPELINE), *[str(arg) for arg in args]],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def install_candidate(self, *, path: Path | None = None) -> tuple[Path, Path]:
        assert BASE_CANDIDATE is not None
        candidate = path or (self.root / BASE_CANDIDATE.name)
        shutil.copytree(BASE_CANDIDATE, candidate, dirs_exist_ok=True)
        contract_root = self.root / "sources" / "contract-root"
        service_root = self.root / "sources" / "service-root"
        contract_root.mkdir(parents=True, exist_ok=True)
        (service_root / "code2skill-generate").mkdir(parents=True, exist_ok=True)
        (contract_root / "README.md").write_text(
            "# synthetic client contract evidence\n", encoding="utf-8"
        )
        (service_root / "code2skill-generate" / "SKILL.md").write_text(
            "# synthetic transport contract evidence\n", encoding="utf-8"
        )
        state_dir = self.root / f"{candidate.name}.producer-state"
        return candidate, state_dir

    def init_pipeline(self, candidate: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_pipeline(
            "init",
            candidate,
            "--source-map",
            f"fictional-topic-contract={self.root / 'sources' / 'contract-root'}",
            "--source-map",
            f"fictional-topic-service={self.root / 'sources' / 'service-root'}",
            *extra,
        )

    def load_state(self, state_dir: Path) -> dict[str, object]:
        return json.loads((state_dir / "run-state.json").read_text(encoding="utf-8"))

    def load_pipeline_report(self, state_dir: Path) -> dict[str, object]:
        return json.loads(
            (state_dir / "verification" / "reports" / "pipeline-report.json").read_text(
                encoding="utf-8"
            )
        )

    def stage_entry(self, state_dir: Path, stage: str) -> dict[str, object]:
        return self.load_state(state_dir)["stages"][stage]

    def full_default_run(self, candidate: Path) -> subprocess.CompletedProcess[str]:
        init = self.init_pipeline(candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self.run_pipeline("run", candidate)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result


def require_node(test_method):
    return unittest.skipUnless(NODE_AVAILABLE, "Node.js is required for MCP stages")(test_method)


class FreshAndModeTest(PipelineTestCase):
    def test_core_profile_is_not_misclassified_as_a_strict_migration(self) -> None:
        candidate = self.root / "small-core-package"
        candidate.mkdir()
        (candidate / "package.json").write_text(
            json.dumps(
                {
                    "type": "module",
                    "code2skill": {"profile": "core-export-v1"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = self.run_pipeline("init", candidate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("validate_core_export.py", result.stderr)
        self.assertIn("separate directory", result.stderr)
        self.assertFalse(
            (self.root / "small-core-package.producer-state").exists(),
            "strict state must not be created beside a core package",
        )

    @require_node
    def test_fresh_mode_and_stage_progression(self) -> None:
        candidate = self.root / "knowledge-search"
        init = self.run_pipeline("init", candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertIn("MODE fresh", init.stdout)
        self.assertTrue(candidate.is_dir(), "fresh init creates the candidate directory")
        first = self.run_pipeline("run", candidate)
        self.assertEqual(first.returncode, 1)
        self.assertIn("status=failed", first.stdout)
        self.assertIn("required authoring input is missing", first.stdout)

        # Author the candidate into the SAME directory the fresh init created.
        candidate, state_dir = self.install_candidate(path=candidate)
        init = self.init_pipeline(candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self.run_pipeline("run", candidate)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for stage in ("analyze", "generate", "verify", "finalize"):
            self.assertIn(f"STAGE {stage}", result.stdout)
        self.assertIn("action=skipped-disabled", result.stdout)
        self.assertIn(
            "DELIVERY generated=yes behavior-verified=yes runtime-verified=no "
            "host-verified=no deployed=no",
            result.stdout,
        )
        report = self.load_pipeline_report(state_dir)
        expected_runs = {"analyze": 2, "generate": 1, "verify": 1, "finalize": 1}
        for stage in ("analyze", "generate", "verify", "finalize"):
            entry = report["stages"][stage]
            self.assertEqual(entry["status"], "completed", stage)
            self.assertEqual(entry["lastAction"], "executed", stage)
            self.assertIsInstance(entry["durationMs"], int, stage)
            self.assertEqual(entry["runs"], expected_runs[stage], stage)
            self.assertIsNotNone(entry["startedAt"], stage)
            self.assertIsNotNone(entry["endedAt"], stage)
        self.assertEqual(report["stages"]["runtime-verify"]["lastAction"], "skipped-disabled")
        self.assertEqual(report["decision"], "requires-review")
        state = self.load_state(state_dir)
        self.assertEqual(state["mode"], "changed-only")
        self.assertEqual(state["runtimeVerify"], {})
        self.assertEqual(
            report["runtimeVerify"]["authorization"],
            "per-invocation; never persisted",
        )

    def test_migrate_mode_requires_acknowledgement_before_any_change(self) -> None:
        candidate = create_base(self.root)
        before = {
            path.relative_to(candidate).as_posix(): path.read_bytes()
            for path in sorted(candidate.rglob("*"))
            if path.is_file()
        }
        init = self.run_pipeline("init", candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertIn("MODE migrate", init.stdout)
        self.assertIn("acknowledged=False", init.stdout)
        state_dir = self.root / f"{candidate.name}.producer-state"
        summary = json.loads((state_dir / "mode-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["mode"], "migrate")
        self.assertGreaterEqual(len(summary["legacyFiles"]), 3)

        refused = self.run_pipeline("run", candidate)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--acknowledge-migration", refused.stderr)

        init = self.run_pipeline("init", candidate, "--acknowledge-migration")
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertIn("acknowledged=True", init.stdout)
        attempt = self.run_pipeline("run", candidate)
        self.assertEqual(attempt.returncode, 1)
        self.assertIn("required authoring input is missing", attempt.stdout)

        after = {
            path.relative_to(candidate).as_posix(): path.read_bytes()
            for path in sorted(candidate.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(before, after, "migrate mode must not modify legacy artifacts")

    @require_node
    def test_changed_only_mode_reports_capability_diff(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["description"] = "List the curated topic catalog."
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        init = self.init_pipeline(candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertIn("MODE changed-only", init.stdout)
        self.assertIn(f"changed=['{CAPABILITY_ID}']", init.stdout)
        summary = json.loads((state_dir / "mode-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["capabilities"]["changed"], [CAPABILITY_ID])
        self.assertIn("informational", summary["note"])


class ResumeAndInvalidationTest(PipelineTestCase):
    @require_node
    def test_resume_after_interrupt_never_reruns_unchanged_stages(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        first = {
            stage: self.stage_entry(state_dir, stage)["runs"] for stage in ("analyze", "generate", "verify", "finalize")
        }
        self.assertEqual(first, {"analyze": 1, "generate": 1, "verify": 1, "finalize": 1})

        second = self.run_pipeline("run", candidate)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(second.stdout.count("action=skipped-unchanged"), 4)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["runs"], 1)

        # Simulate an interrupted producer: verify is stuck in `running`.
        state = self.load_state(state_dir)
        state["stages"]["verify"]["status"] = "running"
        write_json(state_dir / "run-state.json", state)
        resumed = self.run_pipeline("run", candidate)
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["runs"], 1)
        self.assertEqual(self.stage_entry(state_dir, "generate")["runs"], 1)
        self.assertEqual(self.stage_entry(state_dir, "verify")["runs"], 2)
        self.assertEqual(self.stage_entry(state_dir, "verify")["status"], "completed")
        report = self.load_pipeline_report(state_dir)
        self.assertEqual(report["stages"]["analyze"]["lastAction"], "skipped-unchanged")
        self.assertEqual(report["stages"]["verify"]["lastAction"], "executed")

    @require_node
    def test_upstream_change_invalidates_only_affected_stages(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)

        # A pure source change re-runs analyze only; downstream inputs are
        # content-identical, so completed stages stay untouched.
        evidence = (
            self.root
            / "sources"
            / "service-root"
            / "code2skill-generate"
            / "SKILL.md"
        )
        evidence.write_text(
            "# synthetic transport contract evidence\nadditional inspected detail\n",
            encoding="utf-8",
        )
        second = self.run_pipeline("run", candidate)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["runs"], 2)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["lastAction"], "executed")
        for stage in ("generate", "verify", "finalize"):
            entry = self.stage_entry(state_dir, stage)
            self.assertEqual(entry["runs"], 1, stage)
            self.assertEqual(entry["lastAction"], "skipped-unchanged", stage)

        # A Canonical Contract change re-runs analyze and every downstream
        # stage, and the compiler regenerates the Function core deterministically.
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["outputs"][0]["valueDomain"]["values"] = [
            ["synthetic-topic-alpha", "synthetic-topic-gamma"]
        ]
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        third = self.run_pipeline("run", candidate)
        self.assertEqual(third.returncode, 0, third.stderr + third.stdout)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["runs"], 3)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["lastAction"], "executed")
        self.assertEqual(self.stage_entry(state_dir, "generate")["runs"], 2)
        self.assertEqual(self.stage_entry(state_dir, "verify")["runs"], 2)
        self.assertEqual(self.stage_entry(state_dir, "finalize")["runs"], 2)
        compiled_core = (candidate / "function-core" / "index.mjs").read_text(
            encoding="utf-8"
        )
        self.assertIn("synthetic-topic-gamma", compiled_core)

    @require_node
    def test_forced_rerun_produces_stable_evidence_hashes(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        results_dir = state_dir / "verification" / "results"
        first_hashes = {
            path.name: json.loads(path.read_text(encoding="utf-8"))["evidenceHash"]
            for path in sorted(results_dir.glob("*.json"))
        }
        self.assertGreaterEqual(len(first_hashes), 9)
        rerun = self.run_pipeline("run", candidate, "--force")
        self.assertEqual(rerun.returncode, 0, rerun.stderr + rerun.stdout)
        second_hashes = {
            path.name: json.loads(path.read_text(encoding="utf-8"))["evidenceHash"]
            for path in sorted(results_dir.glob("*.json"))
        }
        self.assertEqual(first_hashes, second_hashes)


class OfflineVerificationTest(PipelineTestCase):
    @require_node
    def test_default_verify_never_touches_live_systems(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        probe_log = (
            state_dir
            / "verification"
            / "logs"
            / "global--global--pipeline:mcp-protocol-offline.log"
        ).read_text(encoding="utf-8")
        self.assertIn('"offline": true', probe_log)
        self.assertIn('"successfulCalls": 0', probe_log)
        self.assertIn('"runtimeVerificationRequired": true', probe_log)

        report = json.loads(
            (state_dir / "verification" / "reports" / "verification-report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(report["capabilities"]), 2)
        for capability in report["capabilities"]:
            self.assertEqual(capability["behavior"]["status"], "passed", capability)
            self.assertEqual(capability["runtime"], {"status": "not-run", "checks": []})
            self.assertEqual(capability["host"], {"status": "not-run", "checks": []})
        live_dir = state_dir / "verification" / "live"
        self.assertEqual(
            sorted(path.name for path in live_dir.iterdir()),
            [
                "no-runtime-verification.input.json",
                "no-runtime-verification.result.json",
            ],
        )
        pipeline_report = self.load_pipeline_report(state_dir)
        self.assertEqual(pipeline_report["delivery"]["runtimeVerified"], "no")
        self.assertEqual(pipeline_report["delivery"]["hostVerified"], "no")
        self.assertEqual(pipeline_report["decision"], "requires-review")
        self.assertEqual(
            pipeline_report["stages"]["runtime-verify"]["lastAction"], "skipped-disabled"
        )

    @require_node
    def test_no_runtime_verified_claims_without_explicit_opt_in(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        matrix = json.loads(
            (candidate / "verification-matrix.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(matrix["capabilities"]), 2)
        for capability in matrix["capabilities"]:
            status = capability["status"]
            self.assertTrue(status["generated"])
            self.assertTrue(status["behaviorVerified"])
            self.assertFalse(status["runtimeVerified"])
            self.assertFalse(status["hostVerified"])
        approval = json.loads(
            (candidate / "approval-audit.json").read_text(encoding="utf-8")
        )
        self.assertEqual(approval["decision"], "requires-review")

    @require_node
    def test_runtime_verify_is_never_part_of_the_default_flow(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        refused = self.run_pipeline("run", candidate, "--only", "runtime-verify")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("--enable-runtime-verify", refused.stderr)


class RuntimeVerifyTest(PipelineTestCase):
    @require_node
    def test_live_read_verification_binds_persisted_evidence(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        result = self.run_pipeline("run", candidate, "--enable-runtime-verify")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        matrix = json.loads(
            (candidate / "verification-matrix.json").read_text(encoding="utf-8")
        )
        statuses = {
            item["capabilityId"]: item["status"] for item in matrix["capabilities"]
        }
        self.assertTrue(statuses[READ_CAPABILITY_ID]["behaviorVerified"])
        self.assertTrue(statuses[READ_CAPABILITY_ID]["runtimeVerified"])
        # The write capability was not authorized, so it must stay unverified.
        self.assertTrue(statuses[WRITE_CAPABILITY_ID]["behaviorVerified"])
        self.assertFalse(statuses[WRITE_CAPABILITY_ID]["runtimeVerified"])
        record = json.loads(
            (
                state_dir
                / "verification"
                / "results"
                / f"runtime--{READ_CAPABILITY_ID}--runtime-call-{READ_CAPABILITY_ID}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(record["toolName"], READ_TOOL)
        self.assertRegex(record["inputHash"], r"^[a-f0-9]{64}$")
        self.assertRegex(record["resultHash"], r"^[a-f0-9]{64}$")
        for key in ("liveInputPath", "liveResultPath"):
            self.assertTrue((state_dir / "verification" / record[key]).is_file())

    @require_node
    def test_live_write_is_never_triggered_without_explicit_authorization(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        result = self.run_pipeline("run", candidate, "--enable-runtime-verify")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        live_dir = state_dir / "verification" / "live"
        self.assertTrue((live_dir / f"{READ_CAPABILITY_ID}.result.json").is_file())
        self.assertFalse(
            (live_dir / f"{WRITE_CAPABILITY_ID}.result.json").exists(),
            "an unauthorized write must never execute",
        )
        self.assertFalse(
            (
                state_dir
                / "verification"
                / "results"
                / f"runtime--{WRITE_CAPABILITY_ID}--runtime-call-{WRITE_CAPABILITY_ID}.json"
            ).exists(),
            "an unauthorized write must not even produce a runtime record",
        )
        state = self.load_state(state_dir)
        self.assertEqual(
            state["runtimeVerify"]["lastSkipped"],
            [
                {
                    "checkId": f"runtime-call-{WRITE_CAPABILITY_ID}",
                    "capabilityId": WRITE_CAPABILITY_ID,
                    "reason": "write-authorization-required",
                }
            ],
        )
        self.assertIn("--authorize-write", result.stdout)

        authorized = self.run_pipeline(
            "run",
            candidate,
            "--enable-runtime-verify",
            "--authorize-write",
            WRITE_CAPABILITY_ID,
        )
        self.assertEqual(authorized.returncode, 0, authorized.stderr + authorized.stdout)
        self.assertTrue(
            (live_dir / f"{WRITE_CAPABILITY_ID}.result.json").is_file(),
            "an explicitly authorized write may execute",
        )
        state = self.load_state(state_dir)
        self.assertEqual(state["runtimeVerify"]["lastSkipped"], [])

    @require_node
    def test_runtime_authorization_never_persists_across_runs(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        authorized = self.run_pipeline(
            "run",
            candidate,
            "--enable-runtime-verify",
            "--authorize-write",
            WRITE_CAPABILITY_ID,
        )
        self.assertEqual(authorized.returncode, 0, authorized.stderr + authorized.stdout)
        self.assertEqual(self.stage_entry(state_dir, "runtime-verify")["runs"], 1)
        # A later plain run must not inherit the earlier enable/authorization:
        # the stage is not re-executed and is reported as skipped-disabled.
        plain = self.run_pipeline("run", candidate)
        self.assertEqual(plain.returncode, 0, plain.stderr + plain.stdout)
        entry = self.stage_entry(state_dir, "runtime-verify")
        self.assertEqual(entry["runs"], 1, "authorization must not persist into later runs")
        self.assertEqual(entry["lastAction"], "skipped-disabled")
        state = self.load_state(state_dir)
        self.assertNotIn("enabled", state["runtimeVerify"])
        self.assertNotIn("authorizedWrites", state["runtimeVerify"])

    @require_node
    def test_stale_runtime_evidence_is_voided_before_finalize(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        authorized = self.run_pipeline(
            "run",
            candidate,
            "--enable-runtime-verify",
            "--authorize-write",
            WRITE_CAPABILITY_ID,
        )
        self.assertEqual(authorized.returncode, 0, authorized.stderr + authorized.stdout)
        matrix = json.loads(
            (candidate / "verification-matrix.json").read_text(encoding="utf-8")
        )
        self.assertTrue(matrix["capabilities"][0]["status"]["runtimeVerified"])
        # An authoring input change invalidates the live proof; a plain run
        # must void it BEFORE finalize can reuse it.
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["outputs"][0]["valueDomain"]["values"] = [
            ["synthetic-topic-alpha", "synthetic-topic-gamma"]
        ]
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        plain = self.run_pipeline("run", candidate)
        self.assertEqual(plain.returncode, 0, plain.stderr + plain.stdout)
        entry = self.stage_entry(state_dir, "runtime-verify")
        self.assertEqual(entry["status"], "invalidated")
        self.assertIn("voided", entry["invalidatedReason"])
        matrix = json.loads(
            (candidate / "verification-matrix.json").read_text(encoding="utf-8")
        )
        for capability in matrix["capabilities"]:
            self.assertFalse(
                capability["status"]["runtimeVerified"],
                "stale runtime proof must never survive into a new finalization",
            )
        report = self.load_pipeline_report(state_dir)
        self.assertEqual(report["delivery"]["runtimeVerified"], "no")


class PersistentEvidenceTest(PipelineTestCase):
    @require_node
    def test_verification_materials_are_persistent_and_tmp_free(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        report_text = (
            state_dir / "verification" / "reports" / "verification-report.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn(str(self.root), report_text)
        self.assertNotIn("/tmp", report_text)
        for artifact in ("preflight-report.json", "export-manifest.json", "live-verification.json"):
            text = (candidate / artifact).read_text(encoding="utf-8")
            self.assertNotIn(str(self.root), text, artifact)
            self.assertNotIn("/tmp", text, artifact)
        results_dir = state_dir / "verification" / "results"
        for record_path in sorted(results_dir.glob("*.json")):
            record = json.loads(record_path.read_text(encoding="utf-8"))
            evidence = state_dir / "verification" / record["evidencePath"]
            self.assertTrue(evidence.is_file(), record["checkId"])
            self.assertTrue(
                evidence.resolve().is_relative_to(state_dir.resolve()),
                "evidence must stay inside the persistent producer sidecar",
            )

    @require_node
    def test_finalize_refuses_missing_or_tampered_evidence(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        evidence_dir = state_dir / "verification" / "vectors" / "vector-evidence"
        victim = sorted(evidence_dir.glob("behavior--*.json"))[0]
        original = victim.read_bytes()
        victim.unlink()
        refused = self.run_pipeline("run", candidate, "--only", "finalize", "--force")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("evidence is missing", refused.stdout)

        repaired = self.run_pipeline("run", candidate, "--only", "verify", "--force")
        self.assertEqual(repaired.returncode, 0, repaired.stderr + repaired.stdout)
        recovered = self.run_pipeline("run", candidate, "--only", "finalize", "--force")
        self.assertEqual(recovered.returncode, 0, recovered.stderr + recovered.stdout)

        victim.write_bytes(original + b"tampered\n")
        refused = self.run_pipeline("run", candidate, "--only", "finalize", "--force")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("modified after hashing", refused.stdout)

    @require_node
    def test_evidence_symlink_escape_is_rejected(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        outside = self.root / "outside-evidence.json"
        outside.write_text('{"checkId": "forged", "status": "passed"}\n', encoding="utf-8")
        evidence_dir = state_dir / "verification" / "vectors" / "vector-evidence"
        victim = sorted(evidence_dir.glob("behavior--*.json"))[0]
        victim.unlink()
        victim.symlink_to(outside)
        refused = self.run_pipeline("run", candidate, "--only", "finalize", "--force")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("escapes the persistent verification", refused.stdout)


class DiagnosticsTest(PipelineTestCase):
    @require_node
    def test_diagnose_reports_root_cause_first_with_stable_summary(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        # A Canonical Contract edit without re-derivation cascades into many
        # downstream derived-view errors; diagnose must surface the root first.
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["description"] = "List the curated topic catalog."
        contract["capabilities"][0]["outputs"][0]["description"] = (
            "An updated fictional topic catalog."
        )
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        diagnosed = self.run_pipeline("diagnose", candidate)
        self.assertEqual(diagnosed.returncode, 1)
        output = diagnosed.stdout
        self.assertTrue(output.startswith("DIAGNOSIS candidate="), output[:200])
        root_index = output.index("ROOT-CAUSE canonical")
        suppressed_index = output.index("DOWNSTREAM-SUPPRESSED")
        self.assertLess(root_index, suppressed_index)
        self.assertIn("function/mcp=", output)
        self.assertIn("documentation=", output)
        summary_lines = [
            line for line in output.splitlines() if line.startswith(("ROOT-CAUSE", "CATEGORY", "DOWNSTREAM-SUPPRESSED"))
        ]
        self.assertLessEqual(len(summary_lines), 8, "diagnostics must stay converged")

        full = self.run_pipeline("diagnose", candidate, "--full")
        self.assertEqual(full.returncode, 1)
        self.assertNotIn("DOWNSTREAM-SUPPRESSED", full.stdout)
        self.assertGreater(full.stdout.count("\n  "), output.count("\n  "))

        machine = self.run_pipeline("diagnose", candidate, "--json")
        self.assertEqual(machine.returncode, 1)
        payload = json.loads(machine.stdout)
        self.assertGreater(payload["errors"], 0)
        self.assertTrue(payload["suppressedDownstream"])
        self.assertTrue(
            any(category["rootCause"] for category in payload["categories"])
        )

    @require_node
    def test_diagnose_capability_filter(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        adapter = candidate / "mcp-tool" / "index.mjs"
        adapter.write_text(
            adapter.read_text(encoding="utf-8").replace(
                "import { listKnowledgeTopics, rebuildKnowledgeIndex } from '../function-core/index.mjs';",
                "",
            ),
            encoding="utf-8",
        )
        scoped = self.run_pipeline("diagnose", candidate, "--capability", CAPABILITY_ID)
        self.assertEqual(scoped.returncode, 1)
        self.assertIn(f"capability:{CAPABILITY_ID}", scoped.stdout)
        for line in scoped.stdout.splitlines():
            if line.startswith("  "):
                self.assertIn(TOOL_NAME, line)
        # The adapter defect belongs to later stages; filtering to analyze
        # converges to zero errors instead of repeating downstream noise.
        analyze_only = self.run_pipeline("diagnose", candidate, "--stage", "analyze")
        self.assertEqual(analyze_only.returncode, 0, analyze_only.stdout)
        generate = self.run_pipeline("diagnose", candidate, "--stage", "generate")
        self.assertEqual(generate.returncode, 1)
        self.assertIn(f"capability:{CAPABILITY_ID}", generate.stdout)

    @require_node
    def test_diagnose_stage_filter_and_clean_tree(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        clean = self.run_pipeline("diagnose", candidate)
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertIn("errors=0", clean.stdout)


class StageReportTest(PipelineTestCase):
    @require_node
    def test_stage_durations_and_skip_reasons_are_reviewable(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        second = self.run_pipeline("run", candidate)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        status = self.run_pipeline("status", candidate, "--json")
        self.assertEqual(status.returncode, 0, status.stderr)
        report = json.loads(status.stdout)
        for stage in ("analyze", "generate", "verify", "finalize"):
            entry = report["stages"][stage]
            self.assertEqual(entry["status"], "completed", stage)
            self.assertEqual(entry["lastAction"], "skipped-unchanged", stage)
            self.assertEqual(entry["skipReason"], "inputs unchanged since the completed run")
            self.assertIsInstance(entry["durationMs"], int, stage)
            self.assertIsInstance(entry["startedAt"], str, stage)
            self.assertIsInstance(entry["endedAt"], str, stage)
            self.assertTrue(entry["command"], stage)
        runtime_entry = report["stages"]["runtime-verify"]
        self.assertEqual(runtime_entry["lastAction"], "skipped-disabled")
        self.assertIn("--enable-runtime-verify", runtime_entry["skipReason"])
        self.assertIn("delivery", report)
        self.assertIn("nextSteps", report)
        human = self.run_pipeline("status", candidate)
        self.assertIn("DELIVERY generated=yes", human.stdout)
        self.assertIn("NEXT", human.stdout)


class InvalidationTest(PipelineTestCase):
    @require_node
    def test_upstream_failure_invalidates_downstream_stages(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["schemaVersion"] = "v1"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        result = self.run_pipeline("run", candidate)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.stage_entry(state_dir, "analyze")["status"], "failed")
        for stage in ("verify", "finalize"):
            entry = self.stage_entry(state_dir, stage)
            self.assertEqual(entry["status"], "invalidated", stage)
            self.assertIn("stale", entry["invalidatedReason"], stage)
        report = self.load_pipeline_report(state_dir)
        self.assertEqual(report["delivery"]["behaviorVerified"], "no")
        self.assertEqual(report["delivery"]["runtimeVerified"], "no")
        self.assertIsNone(report["decision"])
        self.assertTrue(
            any("analyze" in step for step in report["nextSteps"]),
            report["nextSteps"],
        )

    @require_node
    def test_only_run_cannot_bypass_stale_stages(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["description"] = "List the curated topic catalog."
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        refused = self.run_pipeline("run", candidate, "--only", "finalize")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("stale or incomplete upstream", refused.stderr)
        self.assertIn("analyze", refused.stderr)


class FinalizeOutputsTest(PipelineTestCase):
    @require_node
    def test_finalize_reruns_when_final_outputs_deleted(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        manifest = candidate / "export-manifest.json"
        self.assertTrue(manifest.is_file())
        manifest.unlink()
        result = self.run_pipeline("run", candidate)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        entry = self.stage_entry(state_dir, "finalize")
        self.assertEqual(entry["runs"], 2)
        self.assertEqual(entry["status"], "completed")
        self.assertTrue(manifest.is_file(), "finalize must restore missing outputs")

    @require_node
    def test_finalize_reruns_when_final_outputs_tampered(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        preflight = candidate / "preflight-report.json"
        preflight.write_text(
            preflight.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        result = self.run_pipeline("run", candidate)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        entry = self.stage_entry(state_dir, "finalize")
        self.assertEqual(entry["runs"], 2)
        self.assertEqual(entry["status"], "completed")
        report = self.load_pipeline_report(state_dir)
        self.assertEqual(report["stages"]["finalize"]["lastAction"], "executed")


class CrossCapabilityEvidenceTest(PipelineTestCase):
    @require_node
    def test_tampered_second_capability_evidence_fails_finalize(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        victim = (
            state_dir
            / "verification"
            / "vectors"
            / "vector-evidence"
            / f"behavior--{WRITE_CAPABILITY_ID}--valid-input-and-output-contract.json"
        )
        victim.write_bytes(victim.read_bytes() + b"tampered\n")
        refused = self.run_pipeline("run", candidate, "--only", "finalize", "--force")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("modified after hashing", refused.stdout)
        self.assertIn("valid-input-and-output-contract", refused.stdout)
        self.assertIn(WRITE_CAPABILITY_ID, refused.stdout)

    @require_node
    def test_missing_second_capability_evidence_fails_finalize(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        victim = (
            state_dir
            / "verification"
            / "vectors"
            / "vector-evidence"
            / f"behavior--{WRITE_CAPABILITY_ID}--valid-input-and-output-contract.json"
        )
        victim.unlink()
        refused = self.run_pipeline("run", candidate, "--only", "finalize", "--force")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("evidence is missing", refused.stdout)


class VectorPrecisionTest(PipelineTestCase):
    def run_vectors(self, candidate: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "run_vectors.py"),
                str(candidate),
                "--out",
                str(self.root / "vectors"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    @require_node
    def test_output_schema_violation_fails_instead_of_fake_passing(self) -> None:
        candidate, state_dir = self.install_candidate()
        core = candidate / "function-core" / "index.mjs"
        corrupted = core.read_text(encoding="utf-8").replace(
            '"synthetic-topic-alpha"', "1"
        ).replace('"synthetic-topic-beta"', "2")
        core.write_text(corrupted, encoding="utf-8")
        result = self.run_vectors(candidate)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        valid = next(
            check
            for check in report["checks"]
            if check["checkId"] == "valid-input-and-output-contract"
            and check["capabilityId"] == READ_CAPABILITY_ID
        )
        self.assertEqual(valid["status"], "failed")
        self.assertIn("output schema violation", valid["detail"])

    @require_node
    def test_http_binding_detects_wrong_body_and_rejection(self) -> None:
        from tests.test_product_scenarios import one_capability_model
        from tests.test_vnext_contracts import ASSETS as VNEXT_ASSETS
        from tests.test_vnext_contracts import evidence_path, read_json

        topology, contract = one_capability_model("validate-sample-request")
        candidate = self.root / "http-candidate"
        candidate.mkdir()
        for item in contract["evidenceCatalog"]:
            path = self.root / "src" / item["sourceId"] / evidence_path(item["locator"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic evidence\n", encoding="utf-8")
        write_json(candidate / "source-topology.json", topology)
        write_json(candidate / "canonical-contract.json", contract)
        write_json(
            candidate / "host-profile.json",
            read_json(VNEXT_ASSETS / "host-profile.json"),
        )
        write_json(candidate / "export-profile.json", {
            "schemaVersion": "v1",
            "profile": "strict-export-v1",
            "protocolVersion": "2025-11-25",
            "transport": "stdio",
            "documentationLanguage": "zh-CN",
            "featureSurface": {"kind": "backend-api", "identifier": "synthetic-validate"},
            "allowedRuntimeOrigins": ["https://application.example"],
            "dryRunEnvironmentVariable": "SYNTHETIC_DRY_RUN",
        })
        write_json(candidate / "authoring" / "tool-docs.json", {
            "validate_sample_request": {
                "title": "样品请求：校验请求数据",
                "description": "面向需要提交样品请求的用户，用于在正式提交前校验请求数据是否满足服务端约束；本工具需要请求数据与选择授权两个入参，返回校验结果与后续提交所需的授权信息，结果要交给下游提交能力继续执行；它通过一次 HTTP POST 调用目标接口，属于只读校验能力且没有写入副作用，失败时应按结构化错误恢复。",
            }
        })
        compiled = subprocess.run(
            [sys.executable, str(SCRIPTS / "compile_artifacts.py"), str(candidate)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        result = self.run_vectors(candidate)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        binding = next(
            check
            for check in report["checks"]
            if check["checkId"] == "exact-request-binding-and-success-status"
        )
        self.assertEqual(binding["status"], "passed", binding["detail"])

        core = candidate / "function-core" / "index.mjs"
        forged = core.read_text(encoding="utf-8").replace(
            '"requestData": input', '"forgedData": input', 1
        )
        core.write_text(forged, encoding="utf-8")
        result = self.run_vectors(candidate)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        binding = next(
            check
            for check in report["checks"]
            if check["checkId"] == "exact-request-binding-and-success-status"
        )
        self.assertEqual(binding["status"], "failed")
        self.assertIn("body must equal", binding["detail"])


class LiveCaseTest(PipelineTestCase):
    @require_node
    def test_required_input_without_case_is_not_run_and_never_fabricated(self) -> None:
        candidate, state_dir = self.install_candidate()
        self.full_default_run(candidate)
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["inputs"].append({
            "name": "topicId",
            "description": "Synthetic required topic identifier.",
            "type": "string",
            "schema": {"type": "string"},
            "required": True,
            "evidenceRefs": ["ev-fictional-topic-request"],
        })
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        import argparse

        import run_pipeline

        args = argparse.Namespace(enable_runtime_verify=True, authorize_write=[])
        ctx = run_pipeline.StageContext(
            candidate, state_dir, {"sourceMaps": {}, "runtimeVerify": {}}, args
        )
        ok, error, _commands = run_pipeline.run_runtime_verify(ctx)
        self.assertTrue(ok, error)
        skipped = ctx.state["runtimeVerify"]["lastSkipped"]
        self.assertIn(
            {
                "checkId": f"runtime-call-{READ_CAPABILITY_ID}",
                "capabilityId": READ_CAPABILITY_ID,
                "reason": "no-live-case",
            },
            skipped,
        )
        self.assertFalse(
            (
                state_dir / "verification" / "live" / f"{READ_CAPABILITY_ID}.result.json"
            ).exists(),
            "a capability without an explicit case must never be called with fabricated arguments",
        )

    @require_node
    def test_generate_fails_honestly_when_tool_docs_missing(self) -> None:
        candidate, state_dir = self.install_candidate()
        (candidate / "authoring" / "tool-docs.json").unlink()
        init = self.init_pipeline(candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self.run_pipeline("run", candidate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("tool-docs", result.stdout)


class UncoveredStatusTest(PipelineTestCase):
    @require_node
    def test_uncovered_vectors_keep_behavior_unverified(self) -> None:
        candidate, state_dir = self.install_candidate()
        contract_path = candidate / "canonical-contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["capabilities"][0]["verificationChecks"] = ["custom-uncoverable-check"]
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        init = self.init_pipeline(candidate)
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self.run_pipeline(
            "run", candidate, "--only", "analyze,generate,verify"
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        status = self.run_pipeline("status", candidate, "--json")
        report = json.loads(status.stdout)
        self.assertNotEqual(report["delivery"]["behaviorVerified"], "yes")
        self.assertEqual(report["delivery"]["behaviorVerified"], "partial")


if __name__ == "__main__":
    unittest.main()
