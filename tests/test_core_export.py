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
VALIDATOR = SKILL_ROOT / "scripts" / "validate_core_export.py"


FUNCTION = """import { z } from 'zod';
export const lookupTopicInputSchema = z.object({
  topic: z.unknown().optional().describe('后端接受的主题标识；类型由 Agent 和后端协商')
}).passthrough();
export async function lookupTopic(input, context = {}) {
  const request = {method: 'GET', path: '/topics', query: {topic: input.topic}};
  context.captureRequest?.(request);
  if (input.topic === 'network-failure') {
    const error = new Error('socket closed');
    Object.defineProperty(error, 'code', {value: 'ECONNRESET'});
    Object.defineProperty(error, 'cause', {value: 'synthetic socket'});
    throw error;
  }
  if (input.topic === 'client-http-500') {
    const error = new Error('client rejected the HTTP status');
    Object.defineProperty(error, 'response', {
      value: {status: 500, data: {code: 'E_CLIENT', msg: 'response survived client throw'}}
    });
    throw error;
  }
  if (input.topic === 'http-500') {
    return {httpStatus: 500, bodyText: '{"code":"E_TEMP","msg":"backend supplied detail","data":{"accepted":false}}'};
  }
  if (input.topic === 'plain-text') {
    return {httpStatus: 502, bodyText: 'upstream returned plain text'};
  }
  if (input.topic === 'long-text') {
    return {httpStatus: 200, bodyText: 'x'.repeat(5000)};
  }
  if (input.topic === 'unknown-decision') {
    return {httpStatus: 200, bodyText: '{"needsReview":null}'};
  }
  return {httpStatus: 200, bodyText: JSON.stringify({topic: input.topic})};
}
"""

ADAPTER = """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  lookupTopic,
  lookupTopicInputSchema
} from '../function-core/index.mjs';
import {
  httpResultFromError,
  toAgentError,
  toAgentResult
} from '../portable-agent-result.mjs';
const server = new McpServer({name: 'synthetic-core', version: '1'});
server.registerTool("lookup_topic", {
  title: '主题：查询详情',
  description: '根据主题标识查询一个合成主题详情；参数和响应由 Agent 根据后端反馈判断。',
  inputSchema: lookupTopicInputSchema,
  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}
}, async (input, runtimeContext) => {
  if (process.env.CODE2SKILL_DRY_RUN === "1") {
    const dryRunResult = {dryRun: true, validatedInput: input};
    return toAgentResult(dryRunResult);
  }
  try {
    const result = await lookupTopic(input, runtimeContext);
    return toAgentResult(result);
  } catch (error) {
    const httpResult = httpResultFromError(error);
    if (httpResult) return toAgentResult(httpResult);
    return toAgentError(error);
  }
});
await server.connect(new StdioServerTransport());
"""

FAKE_ZOD = """class Schema {
  constructor(parse) { this._parse = parse; }
  parse(value) { return this._parse(value); }
  optional() { return new Schema((value) => value === undefined ? undefined : this.parse(value)); }
  describe() { return this; }
  min(size) {
    return new Schema((value) => {
      const parsed = this.parse(value);
      if (parsed.length < size) throw new Error('too small');
      return parsed;
    });
  }
}
function object(shape) {
  let strict = false;
  let passthrough = false;
  const schema = new Schema((value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('expected object');
    if (strict && Object.keys(value).some((key) => !(key in shape))) throw new Error('unknown key');
    const result = {};
    for (const [key, child] of Object.entries(shape)) {
      const parsed = child.parse(value[key]);
      if (parsed !== undefined || Object.hasOwn(value, key)) result[key] = parsed;
    }
    if (passthrough) for (const [key, child] of Object.entries(value)) if (!(key in shape)) result[key] = child;
    return result;
  });
  schema.shape = shape;
  schema.strict = () => { strict = true; return schema; };
  schema.passthrough = () => { passthrough = true; return schema; };
  return schema;
}
export const z = {
  object,
  strictObject: object,
  string: () => new Schema((value) => {
    if (typeof value !== 'string') throw new Error('expected string');
    return value;
  }),
  unknown: () => new Schema((value) => value),
  literal: (expected) => new Schema((value) => {
    if (value !== expected) throw new Error('unexpected literal');
    return value;
  })
};
"""

FAKE_MCP_SERVER = """export class McpServer {
  constructor(info) { this.info = info; this.tools = new Map(); }
  registerTool(name, config, callback) { this.tools.set(name, {config, callback}); }
  async connect(transport) { await transport.connect(this); }
}
"""

FAKE_MCP_STDIO = """import readline from 'node:readline';
function send(value) { process.stdout.write(JSON.stringify(value) + '\\n'); }
export class StdioServerTransport {
  async connect(server) {
    const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
    for await (const line of lines) {
      const message = JSON.parse(line);
      if (message.method === 'initialize') {
        send({jsonrpc: '2.0', id: message.id, result: {protocolVersion: 'test', capabilities: {tools: {}}, serverInfo: server.info}});
      } else if (message.method === 'tools/list') {
        send({jsonrpc: '2.0', id: message.id, result: {tools: [...server.tools].map(([name, tool]) => ({name, ...tool.config}))}});
      } else if (message.method === 'tools/call') {
        const tool = server.tools.get(message.params.name);
        try {
          const args = message.params.arguments || {};
          const parsedArgs = tool.config.inputSchema.parse(args);
          const result = await tool.callback(parsedArgs, {});
          if (!result.isError && tool.config.outputSchema) tool.config.outputSchema.parse(result.structuredContent);
          send({jsonrpc: '2.0', id: message.id, result});
        } catch (error) {
          send({jsonrpc: '2.0', id: message.id, error: {code: -32602, message: error.message}});
        }
      }
    }
  }
}
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_candidate(root: Path) -> Path:
    candidate = root / "synthetic-core"
    write(
        candidate / "SKILL.md",
        "---\nname: synthetic-core\ndescription: 查询合成主题详情。\n---\n\n# 合成主题\n",
    )
    write(
        candidate / "MCP-SETUP.md",
        "# 安装与运行\n\n`npx skills add ./synthetic-core` 只安装 Skill；MCP 需要单独注册。\n",
    )
    write(
        candidate / "package.json",
        '{\n  "type": "module",\n  "code2skill": {"profile": "core-export-v1"},\n  "scripts": {"test": "node --test tests/*.test.mjs"},\n  "dependencies": {"@modelcontextprotocol/sdk": "^1.0.0", "zod": "^3.0.0"}\n}\n',
    )
    write(candidate / "function-core" / "index.mjs", FUNCTION)
    write(candidate / "mcp-tool" / "index.mjs", ADAPTER)
    shutil.copyfile(
        SKILL_ROOT / "assets" / "portable-agent-result.mjs",
        candidate / "portable-agent-result.mjs",
    )
    write(
        candidate / "tests" / "function.test.mjs",
        "import { test } from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { lookupTopic } from '../function-core/index.mjs';\n"
        "test('lookup_topic preserves Agent-provided value shapes', async () => {\n"
        "  let capturedRequest;\n"
        "  assert.deepEqual(await lookupTopic({topic: 42, unexpected: 'Agent context'}, "
        "{captureRequest: (request) => { capturedRequest = request; }}), "
        "{httpStatus: 200, bodyText: '{\"topic\":42}'});\n"
        "  assert.deepEqual(capturedRequest, {method: 'GET', path: '/topics', query: {topic: 42}});\n"
        "  assert.deepEqual(await lookupTopic({topic: null}), "
        "{httpStatus: 200, bodyText: '{\"topic\":null}'});\n"
        "  assert.deepEqual(await lookupTopic({}), {httpStatus: 200, bodyText: '{}'});\n"
        "});\n",
    )
    write(
        candidate / "tests" / "result.test.mjs",
        "import { test } from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { readHttpResponse, toAgentResult } from '../portable-agent-result.mjs';\n"
        "test('readHttpResponse preserves every HTTP status and complete body', async () => {\n"
        "  const jsonText = '{\"code\":\"E_TEMP\",\"msg\":\"backend detail\","
        "\"data\":{\"accepted\":false},\"large\":9007199254740993}';\n"
        "  const httpResult = await readHttpResponse({status: 500, text: async () => jsonText});\n"
        "  assert.deepEqual(httpResult, {httpStatus: 500, bodyText: jsonText});\n"
        "  const projectedHttpResult = toAgentResult(httpResult);\n"
        "  assert.equal(projectedHttpResult.structuredContent.bodyText, jsonText);\n"
        "  assert.deepEqual(JSON.parse(projectedHttpResult.content[0].text), "
        "projectedHttpResult.structuredContent);\n"
        "  assert.deepEqual(await readHttpResponse({status: 400, text: async () => 'plain rejection'}), "
        "{httpStatus: 400, bodyText: 'plain rejection'});\n"
        "  assert.deepEqual(await readHttpResponse({status: 200, text: async () => '42'}), "
        "{httpStatus: 200, bodyText: '42'});\n"
        "  assert.deepEqual(await readHttpResponse({status: 200, text: async () => 'null'}), "
        "{httpStatus: 200, bodyText: 'null'});\n"
        "  assert.equal((await readHttpResponse({status: 200, text: async () => "
        "'x'.repeat(5000)})).bodyText.length, 5000);\n"
        "  assert.deepEqual(await readHttpResponse({status: 204, text: async () => ''}), "
        "{httpStatus: 204, bodyText: ''});\n"
        "});\n"
        "test('toAgentResult preserves business fields and keeps projections consistent', () => {\n"
        "  const projected = toAgentResult({body: {stack: 'business value', present: false, "
        "unknown: null, missing: undefined}});\n"
        "  assert.deepEqual(projected.structuredContent, "
        "{body: {stack: 'business value', present: false, unknown: null}});\n"
        "  assert.deepEqual(JSON.parse(projected.content[0].text), projected.structuredContent);\n"
        "  for (const value of ['plain', [1, null, false]]) {\n"
        "    const result = toAgentResult(value);\n"
        "    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);\n"
        "  }\n"
        "});\n",
    )
    write(
        candidate / "tests" / "mcp.test.mjs",
        "import { test } from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { spawn } from 'node:child_process';\n"
        "function exchange(messages, dryRun = '1') {\n"
        "  return new Promise((resolve, reject) => {\n"
        "    const child = spawn(process.execPath, ['mcp-tool/index.mjs'], {\n"
        "      cwd: new URL('..', import.meta.url),\n"
        "      env: {...process.env, CODE2SKILL_DRY_RUN: dryRun},\n"
        "      stdio: ['pipe', 'pipe', 'pipe']\n"
        "    });\n"
        "    let stdout = ''; let stderr = '';\n"
        "    child.stdout.on('data', (chunk) => { stdout += chunk; });\n"
        "    child.stderr.on('data', (chunk) => { stderr += chunk; });\n"
        "    child.on('error', reject);\n"
        "    child.on('close', (code) => {\n"
        "      if (code !== 0) return reject(new Error(stderr));\n"
        "      resolve(stdout.trim().split('\\n').filter(Boolean).map(JSON.parse));\n"
        "    });\n"
        "    for (const message of messages) child.stdin.write(JSON.stringify(message) + '\\n');\n"
        "    child.stdin.end();\n"
        "  });\n"
        "}\n"
        "test('tools/list and tools/call leave parameters and responses to the Agent', async () => {\n"
        "  const replies = await exchange([\n"
        "    {jsonrpc: '2.0', id: 1, method: 'initialize', params: {}},\n"
        "    {jsonrpc: '2.0', id: 2, method: 'tools/list', params: {}},\n"
        "    {jsonrpc: '2.0', id: 3, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: null, extra: 'kept'}}},\n"
        "    {jsonrpc: '2.0', id: 4, method: 'tools/call', params: {name: 'lookup_topic', arguments: {}}}\n"
        "  ]);\n"
        "  const backendReplies = await exchange([\n"
        "    {jsonrpc: '2.0', id: 10, method: 'initialize', params: {}},\n"
        "    {jsonrpc: '2.0', id: 11, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'http-500'}}},\n"
        "    {jsonrpc: '2.0', id: 12, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'plain-text'}}},\n"
        "    {jsonrpc: '2.0', id: 13, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'long-text'}}},\n"
        "    {jsonrpc: '2.0', id: 14, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'unknown-decision'}}},\n"
        "    {jsonrpc: '2.0', id: 15, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'client-http-500'}}},\n"
        "    {jsonrpc: '2.0', id: 16, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'network-failure'}}}\n"
        "  ], '0');\n"
        "  assert.equal(replies[1].result.tools[0].name, 'lookup_topic');\n"
        "  assert.equal('outputSchema' in replies[1].result.tools[0], false);\n"
        "  assert.equal(replies[2].result.isError, false);\n"
        "  assert.deepEqual(replies[2].result.structuredContent.validatedInput, {topic: null, extra: 'kept'});\n"
        "  assert.deepEqual(replies[3].result.structuredContent.validatedInput, {});\n"
        "  assert.equal(backendReplies[1].result.isError, false);\n"
        "  assert.equal(backendReplies[1].result.structuredContent.httpStatus, 500);\n"
        "  assert.equal(backendReplies[1].result.structuredContent.bodyText, '{\"code\":\"E_TEMP\",\"msg\":\"backend supplied detail\",\"data\":{\"accepted\":false}}');\n"
        "  assert.equal(backendReplies[2].result.structuredContent.bodyText, 'upstream returned plain text');\n"
        "  assert.equal(backendReplies[3].result.structuredContent.bodyText.length, 5000);\n"
        "  assert.equal(backendReplies[4].result.structuredContent.bodyText, '{\"needsReview\":null}');\n"
        "  assert.equal(backendReplies[5].result.isError, false);\n"
        "  assert.equal(backendReplies[5].result.structuredContent.httpStatus, 500);\n"
        "  assert.equal(backendReplies[5].result.structuredContent.body.msg, 'response survived client throw');\n"
        "  assert.equal(backendReplies[6].result.isError, true);\n"
        "  assert.equal(backendReplies[6].result.structuredContent.code, 'ECONNRESET');\n"
        "  assert.equal(backendReplies[6].result.structuredContent.message, 'socket closed');\n"
        "  assert.equal(backendReplies[6].result.structuredContent.cause, 'synthetic socket');\n"
        "  assert.equal('retryable' in backendReplies[6].result.structuredContent, false);\n"
        "  assert.equal('outcomeKnown' in backendReplies[6].result.structuredContent, false);\n"
        "  assert.equal(JSON.parse(backendReplies[3].result.content[0].text).bodyText.length, 5000);\n"
        "});\n",
    )
    write(
        candidate / "node_modules" / "zod" / "package.json",
        '{"name":"zod","type":"module","exports":"./index.js"}\n',
    )
    write(candidate / "node_modules" / "zod" / "index.js", FAKE_ZOD)
    write(
        candidate
        / "node_modules"
        / "@modelcontextprotocol"
        / "sdk"
        / "package.json",
        '{"name":"@modelcontextprotocol/sdk","type":"module","exports":{"./server/mcp.js":"./server/mcp.js","./server/stdio.js":"./server/stdio.js"}}\n',
    )
    write(
        candidate
        / "node_modules"
        / "@modelcontextprotocol"
        / "sdk"
        / "server"
        / "mcp.js",
        FAKE_MCP_SERVER,
    )
    write(
        candidate
        / "node_modules"
        / "@modelcontextprotocol"
        / "sdk"
        / "server"
        / "stdio.js",
        FAKE_MCP_STDIO,
    )
    setup = candidate / "MCP-SETUP.md"
    setup.write_text(
        setup.read_text(encoding="utf-8") + "启动前运行 `npm install`。\n",
        encoding="utf-8",
    )
    return candidate


def run_validator(
    candidate: Path, *, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )


class CoreExportValidatorTest(unittest.TestCase):
    def test_repository_skill_defaults_to_core_without_reloading_strict_audit(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        core_setup = (SKILL_ROOT / "assets" / "core-MCP-SETUP.md").read_text(
            encoding="utf-8"
        )
        core_context = (
            SKILL_ROOT / "assets" / "core-feature-context.md"
        ).read_text(encoding="utf-8")
        self.assertIn("默认生成结果", skill)
        self.assertIn("`strict-export-v1` 格式保留兼容，但不再默认执行", skill)
        self.assertIn("不要在默认包中生成 Canonical/Goal Contract", skill)
        self.assertIn("不要仅凭字段名判断语义", skill)
        self.assertIn("每个 Skill 只服务一个主要用户目标", skill)
        self.assertIn("不得写成该 Skill 的前置步骤", skill)
        self.assertIn("部署信任前提", skill)
        self.assertIn("默认不声明 `outputSchema`", skill)
        self.assertIn("由 Consumer Agent 结合用户目标和实际结果决定", skill)
        self.assertIn("业务 API 基址属部署配置", skill)
        self.assertIn("不得把基址公开成 Tool 参数", skill)
        self.assertIn("不得回退到测试/预发/生产", skill)
        self.assertIn("assets/core-MCP-SETUP.md", skill)
        self.assertIn("assets/core-feature-context.md", skill)
        self.assertNotIn("UNKNOWN_DISPATCH_OUTCOME", skill)
        for core_template in (core_setup, core_context):
            self.assertNotIn("portable-error-normalizer", core_template)
            self.assertNotIn("UNKNOWN_DISPATCH_OUTCOME", core_template)
            self.assertNotIn("canonical-contract", core_template)
        for registration_term in (
            "stdio",
            "Streamable HTTP",
            '"command"',
            '"args"',
            '"cwd"',
            '"env"',
            "绝对路径",
        ):
            with self.subTest(registration_term=registration_term):
                self.assertIn(registration_term, core_setup)
        for endpoint_rule in (
            "每个独立服务",
            "Consumer Host 显式注入",
            "不默认指向测试、预发或生产环境",
            "业务 API 基址不作为 Tool 参数",
            "缺少必需基址时",
            "`.invalid`",
        ):
            with self.subTest(endpoint_rule=endpoint_rule):
                self.assertIn(endpoint_rule, core_setup)
        self.assertLess(
            len(skill.encode("utf-8")),
            23_500,
            "the always-loaded Skill prompt must not grow back into the strict audit manual",
        )

    def test_accepts_small_runnable_delivery_without_audit_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MCP discovery, and package tests passed", result.stdout)
            self.assertFalse((candidate / "canonical-contract.json").exists())

    def test_accepts_multiple_independent_goal_skills_with_shared_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            root_skill = candidate / "SKILL.md"
            first_skill = candidate / "skills" / "inspect-topic" / "SKILL.md"
            first_skill.parent.mkdir(parents=True)
            root_skill.rename(first_skill)
            write(
                candidate / "skills" / "refresh-topic" / "SKILL.md",
                "---\nname: refresh-topic\ndescription: 刷新合成主题。\n---\n\n# 刷新主题\n",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_root_skill_that_would_shadow_goal_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            write(
                candidate / "skills" / "refresh-topic" / "SKILL.md",
                "---\nname: refresh-topic\ndescription: 刷新合成主题。\n---\n",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("root Skill shadows nested skills", result.stderr)

    def test_rejects_duplicate_goal_skill_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            first_skill = candidate / "skills" / "inspect-topic" / "SKILL.md"
            first_skill.parent.mkdir(parents=True)
            (candidate / "SKILL.md").rename(first_skill)
            write(
                candidate / "skills" / "refresh-topic" / "SKILL.md",
                "---\nname: synthetic-core\ndescription: 刷新合成主题。\n---\n",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("duplicate Skill name", result.stderr)

    def test_rejects_invalid_goal_skill_frontmatter_values(self) -> None:
        for name, description in (
            ("", "有效说明"),
            ("123", "有效说明"),
            ("Bad_Name", "有效说明"),
            ("valid-name", ""),
            ("valid-name", "123"),
            ("valid-name", "false"),
            ("valid-name", "null"),
            ("valid-name", "[]"),
        ):
            with self.subTest(name=name, description=description):
                with tempfile.TemporaryDirectory() as directory:
                    candidate = create_candidate(Path(directory))
                    write(
                        candidate / "SKILL.md",
                        f"---\nname: {name}\ndescription: {description}\n---\n",
                    )
                    result = run_validator(candidate)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("frontmatter", result.stderr)

    def test_requires_at_least_one_goal_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            (candidate / "SKILL.md").unlink()
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("requires SKILL.md", result.stderr)

    def test_rejects_strict_audit_artifacts_in_default_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            write(candidate / "verification-matrix.json", "{}\n")
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("strict audit artifact", result.stderr)

    def test_requires_runnable_tests_but_not_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            for test_file in (candidate / "tests").glob("*.test.mjs"):
                test_file.unlink()
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("runnable *.test.mjs", result.stderr)

    def test_requires_protocol_smoke_without_static_per_function_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            write(
                candidate / "tests" / "function.test.mjs",
                "import { test } from 'node:test';\n"
                "import assert from 'node:assert/strict';\n"
                "test('package-level smoke', () => assert.ok(true));\n",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_table_driven_tool_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            adapter = candidate / "mcp-tool" / "index.mjs"
            adapter.write_text(
                adapter.read_text(encoding="utf-8").replace(
                    'server.registerTool("lookup_topic", {',
                    "const register = (...args) => server.registerTool(...args);\n"
                    'register("lookup_topic", {',
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_closed_schemas_reported_by_tools_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            stdio = (
                candidate
                / "node_modules"
                / "@modelcontextprotocol"
                / "sdk"
                / "server"
                / "stdio.js"
            )
            stdio.write_text(
                stdio.read_text(encoding="utf-8").replace(
                    "({name, ...tool.config})",
                    "({name, ...tool.config, inputSchema: {type: 'object', additionalProperties: false}})",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("rejects undeclared fields", result.stderr)

    def test_requires_discovery_metadata_and_standard_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            adapter = candidate / "mcp-tool" / "index.mjs"
            adapter.write_text(
                adapter.read_text(encoding="utf-8")
                .replace("  title: '主题：查询详情',\n", "")
                .replace(
                    "  description: '根据主题标识查询一个合成主题详情；参数和响应由 Agent 根据后端反馈判断。',\n",
                    "",
                )
                .replace(
                    "  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}\n",
                    "  annotations: {readOnlyHint: 'yes'}\n",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("has no title", result.stderr)
            self.assertIn("has no description", result.stderr)
            self.assertIn("annotation readOnlyHint must be boolean", result.stderr)
            self.assertIn("annotation destructiveHint must be boolean", result.stderr)

    def test_requires_profile_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            package = candidate / "package.json"
            package.write_text(
                package.read_text(encoding="utf-8").replace(
                    '  "code2skill": {"profile": "core-export-v1"},\n', ""
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("code2skill.profile", result.stderr)

    def test_rejects_strict_schemas_that_block_extra_agent_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "}).passthrough();",
                    "}).strict();",
                    1,
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_rejects_schemas_that_silently_strip_extra_agent_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "}).passthrough();",
                    "});",
                    1,
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_rejects_business_type_schema_that_blocks_agent_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "z.unknown().optional().describe('后端接受的主题标识；类型由 Agent 和后端协商')",
                    "z.string().optional()",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_requires_transport_exception_to_reach_agent_as_tool_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            adapter = candidate / "mcp-tool" / "index.mjs"
            source = adapter.read_text(encoding="utf-8")
            adapter.write_text(
                source.replace("return toAgentError(error);", "return toAgentResult(error);"),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_executes_fixed_node_tests_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            test_file = candidate / "tests" / "function.test.mjs"
            test_file.write_text(
                test_file.read_text(encoding="utf-8")
                + "test('intentional failure', () => assert.fail('proof fixed tests ran'));\n",
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_never_executes_candidate_npm_lifecycle_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            package_path = candidate / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["scripts"]["pretest"] = (
                "node -e \"require('node:fs').writeFileSync('pretest-ran', 'bad')\""
            )
            package_path.write_text(json.dumps(package) + "\n", encoding="utf-8")
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("lifecycle hooks are not allowed", result.stderr)
            self.assertFalse((candidate / "pretest-ran").exists())

    def test_rejects_test_script_that_only_mentions_node_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            package_path = candidate / "package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["scripts"]["test"] = "node -e \"console.log('node --test')\""
            package_path.write_text(json.dumps(package) + "\n", encoding="utf-8")
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("plain node --test command", result.stderr)

    def test_fixed_tests_do_not_inherit_business_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            test_file = candidate / "tests" / "function.test.mjs"
            test_file.write_text(
                test_file.read_text(encoding="utf-8")
                + "test('Producer credential is absent', () => "
                "assert.equal(process.env.SYNTHETIC_BUSINESS_TOKEN, undefined));\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["SYNTHETIC_BUSINESS_TOKEN"] = "must-not-leak"
            result = run_validator(candidate, environment=environment)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_optional_skill_frontmatter_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            skill = candidate / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "description: 查询合成主题详情。\n",
                    "description: 查询合成主题详情。\nlicense: MIT\n",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_equivalent_schema_names_and_post_exports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            source = function.read_text(encoding="utf-8")
            source = source.replace("lookupTopicInputSchema", "topicRequestSchema")
            source = source.replace("export const topicRequestSchema", "const topicRequestSchema")
            source += "export { topicRequestSchema };\n"
            function.write_text(source, encoding="utf-8")
            adapter = candidate / "mcp-tool" / "index.mjs"
            adapter.write_text(
                adapter.read_text(encoding="utf-8")
                .replace("lookupTopicInputSchema", "topicRequestSchema"),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_optional_open_output_schema_when_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            adapter = candidate / "mcp-tool" / "index.mjs"
            adapter.write_text(
                adapter.read_text(encoding="utf-8")
                .replace(
                    "import { StdioServerTransport }",
                    "import { z } from 'zod';\nimport { StdioServerTransport }",
                )
                .replace(
                    "  inputSchema: lookupTopicInputSchema,\n",
                    "  inputSchema: lookupTopicInputSchema,\n"
                    "  outputSchema: z.object({}).passthrough(),\n",
                ),
                encoding="utf-8",
            )
            mcp_test = candidate / "tests" / "mcp.test.mjs"
            mcp_test.write_text(
                mcp_test.read_text(encoding="utf-8").replace(
                    "assert.equal('outputSchema' in replies[1].result.tools[0], false);",
                    "assert.equal('outputSchema' in replies[1].result.tools[0], true);",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_allows_agent_result_adapter_refactor_when_behavior_stays_green(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            with (candidate / "portable-agent-result.mjs").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write("// drift\n")
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_repository_skill_records_decision_boundary_rules(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("目标决策边界", skill)
        self.assertIn("工作记忆", skill)
        self.assertIn("不生成中间文件", skill)
        self.assertIn("主要角色", skill)
        self.assertIn("约束所有者", skill)
        self.assertIn("同时携带", skill)
        self.assertIn("后端权威", skill)
        self.assertIn("拆出额外 Tool 的正面条件", skill)
        self.assertIn("不拆 Tool", skill)
        self.assertIn("按接口数量机械映射", skill)
        self.assertIn("多个决策节点", skill)
        self.assertIn("不能自动转为成功或失败", skill)
        self.assertIn("不是固定逐步脚本", skill)
        self.assertIn("每个复杂目标一条正常代表路径", skill)
        self.assertIn("零外部写入的绕过反例", skill)
        self.assertIn("匿名、跨业务领域的合成案例", skill)
        self.assertIn("source-binding", skill)
        self.assertIn("必须由 Function 承担", skill)
        self.assertIn("直接 import/alias", skill)
        self.assertIn("不得只手填最终正确参数", skill)
        self.assertIn("多下游调用", skill)
        self.assertIn("归一化", skill)
        self.assertNotIn("只归入一类", skill)


if __name__ == "__main__":
    unittest.main()
