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
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill"
VALIDATOR = SKILL_ROOT / "scripts" / "validate_core_export.py"


FUNCTION = """import { z } from 'zod';
export const lookupTopicInputSchema = z.object({topic: z.string().min(1)}).passthrough();
export const lookupTopicOutputSchema = z.object({
  status: z.unknown().optional(),
  data: z.unknown().optional()
}).passthrough();
export async function lookupTopic(input, context = {}) {
  const validated = lookupTopicInputSchema.parse(input);
  if (validated.topic === 'fail') {
    throw Object.assign(new Error('synthetic failure'), {code: 'SYNTHETIC_FAILURE', outcomeKnown: true});
  }
  context.captureRequest?.({method: 'GET', path: '/topics', query: {topic: validated.topic}});
  if (validated.topic === 'variant') {
    return {status: null, data: {topic: validated.topic}, message: 'preserved'};
  }
  return {status: 'success', data: {topic: validated.topic}};
}
"""

ADAPTER = """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  lookupTopic,
  lookupTopicInputSchema,
  lookupTopicOutputSchema
} from '../function-core/index.mjs';
import { normalizeToolError, toMcpResult } from '../portable-error-normalizer.mjs';
const server = new McpServer({name: 'synthetic-core', version: '1'});
server.registerTool("lookup_topic", {
  title: '主题：查询详情',
  description: '根据主题代码查询一个合成主题详情。',
  inputSchema: lookupTopicInputSchema,
  outputSchema: lookupTopicOutputSchema,
  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}
}, async (input, runtimeContext) => {
  if (process.env.CODE2SKILL_DRY_RUN === "1") {
    const dryRunResult = {dryRun: true, validatedInput: input};
    return toMcpResult(dryRunResult, false);
  }
  try {
    const result = await lookupTopic(input, runtimeContext);
    return toMcpResult(result, false);
  } catch (error) {
    const result = normalizeToolError(error, {sideEffect: 'read', automaticRetry: 'safe-read-only'});
    return toMcpResult(result, true);
  }
});
await server.connect(new StdioServerTransport());
"""

FAKE_ZOD = """class Schema {
  constructor(parse) { this._parse = parse; }
  parse(value) { return this._parse(value); }
  optional() { return new Schema((value) => value === undefined ? undefined : this.parse(value)); }
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
    for (const [key, child] of Object.entries(shape)) result[key] = child.parse(value[key]);
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
        SKILL_ROOT / "assets" / "portable-error-normalizer.mjs",
        candidate / "portable-error-normalizer.mjs",
    )
    write(
        candidate / "tests" / "function.test.mjs",
        "import { test } from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "import { lookupTopic } from '../function-core/index.mjs';\n"
        "test('lookup_topic validates and returns the topic', async () => {\n"
        "  let capturedRequest;\n"
        "  assert.deepEqual(await lookupTopic({topic: 'alpha', unexpected: 'ignored'}, "
        "{captureRequest: (request) => { capturedRequest = request; }}), "
        "{status: 'success', data: {topic: 'alpha'}});\n"
        "  assert.deepEqual(capturedRequest, {method: 'GET', path: '/topics', query: {topic: 'alpha'}});\n"
        "  await assert.rejects(() => lookupTopic({topic: ''}));\n"
        "  await assert.rejects(() => lookupTopic(null));\n"
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
        "test('tools/list and tools/call expose lookup_topic structuredContent and isError', async () => {\n"
        "  const replies = await exchange([\n"
        "    {jsonrpc: '2.0', id: 1, method: 'initialize', params: {}},\n"
        "    {jsonrpc: '2.0', id: 2, method: 'tools/list', params: {}},\n"
        "    {jsonrpc: '2.0', id: 3, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'alpha'}}},\n"
        "    {jsonrpc: '2.0', id: 4, method: 'tools/call', params: {name: 'lookup_topic', arguments: {}}}\n"
        "  ]);\n"
        "  const failureReplies = await exchange([\n"
        "    {jsonrpc: '2.0', id: 10, method: 'initialize', params: {}},\n"
        "    {jsonrpc: '2.0', id: 11, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'fail'}}},\n"
        "    {jsonrpc: '2.0', id: 12, method: 'tools/call', params: {name: 'lookup_topic', arguments: {topic: 'variant'}}}\n"
        "  ], '0');\n"
        "  assert.equal(replies[1].result.tools[0].name, 'lookup_topic');\n"
        "  assert.equal(replies[2].result.isError, false);\n"
        "  assert.deepEqual(JSON.parse(replies[2].result.content[0].text), replies[2].result.structuredContent);\n"
        "  assert.equal(replies[3].error.code, -32602);\n"
        "  assert.equal(failureReplies[1].result.isError, true);\n"
        "  assert.equal(failureReplies[1].result.structuredContent.code, 'SYNTHETIC_FAILURE');\n"
        "  assert.equal(failureReplies[2].result.isError, false);\n"
        "  assert.equal(failureReplies[2].result.structuredContent.message, 'preserved');\n"
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
        self.assertIn("默认交付：core-export-v1", skill)
        self.assertIn("strict-export-v1` 保留兼容，但不再默认执行", skill)
        self.assertIn("不要在默认包中生成 Canonical/Goal Contract", skill)
        self.assertIn("不要仅凭字段名判断语义", skill)
        self.assertIn("不得把它提升为所有写操作的全局必经步骤", skill)
        self.assertIn("部署信任前提", skill)
        self.assertIn("输出 Schema 是低约束的可执行边界", skill)
        self.assertLess(
            len(skill.encode("utf-8")),
            20_000,
            "the always-loaded Skill prompt must not grow back into the strict audit manual",
        )

    def test_accepts_small_runnable_delivery_without_audit_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MCP discovery, and package tests passed", result.stdout)
            self.assertFalse((candidate / "canonical-contract.json").exists())

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
                .replace("  description: '根据主题代码查询一个合成主题详情。',\n", "")
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

    def test_rejects_input_schemas_that_are_declared_but_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "  const validated = lookupTopicInputSchema.parse(input);",
                    "  const validated = input;",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_rejects_strict_schemas_that_block_extra_agent_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "z.object({topic: z.string().min(1)})",
                    "z.object({topic: z.string().min(1)}).strict()",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_package_smoke_catches_unknown_input_forwarding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "query: {topic: validated.topic}", "query: {...validated}"
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("fixed node --test: command failed", result.stderr)

    def test_allows_nonblocking_output_schema_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            function = candidate / "function-core" / "index.mjs"
            function.write_text(
                function.read_text(encoding="utf-8").replace(
                    "  return {status: 'success', data: {topic: validated.topic}};",
                    "  return lookupTopicOutputSchema.parse({status: 'success', data: {topic: validated.topic}});",
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_does_not_require_invalid_input_business_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            test_file = candidate / "tests" / "function.test.mjs"
            test_file.write_text(
                test_file.read_text(encoding="utf-8").replace(
                    "  await assert.rejects(() => lookupTopic({topic: ''}));\n", ""
                ).replace(
                    "  await assert.rejects(() => lookupTopic(null));\n", ""
                ),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_error_result_marked_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            adapter = candidate / "mcp-tool" / "index.mjs"
            source = adapter.read_text(encoding="utf-8")
            adapter.write_text(
                source.replace("return toMcpResult(result, true);", "return toMcpResult(result, false);"),
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
            source = source.replace("lookupTopicOutputSchema", "topicResultSchema")
            source = source.replace("export const topicRequestSchema", "const topicRequestSchema")
            source = source.replace("export const topicResultSchema", "const topicResultSchema")
            source += "export { topicRequestSchema, topicResultSchema };\n"
            function.write_text(source, encoding="utf-8")
            adapter = candidate / "mcp-tool" / "index.mjs"
            adapter.write_text(
                adapter.read_text(encoding="utf-8")
                .replace("lookupTopicInputSchema", "topicRequestSchema")
                .replace("lookupTopicOutputSchema", "topicResultSchema"),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_output_schema_and_structured_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            adapter = candidate / "mcp-tool" / "index.mjs"
            adapter.write_text(
                adapter.read_text(encoding="utf-8").replace("outputSchema", "omittedSchema"),
                encoding="utf-8",
            )
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 1)
            self.assertIn("outputSchema", result.stderr)

    def test_allows_error_normalizer_refactor_when_behavior_stays_green(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = create_candidate(Path(directory))
            with (candidate / "portable-error-normalizer.mjs").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write("// drift\n")
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
