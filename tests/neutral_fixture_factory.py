from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill-generate"
VALIDATOR = SKILL_ROOT / "scripts" / "validate_core_export.py"
PORTABLE_RESULT = SKILL_ROOT / "assets" / "portable-agent-result.mjs"


FAKE_ZOD = """class Schema {
  constructor(parse) { this._parse = parse; }
  parse(value) { return this._parse(value); }
  optional() { return new Schema((value) => value === undefined ? undefined : this.parse(value)); }
  describe() { return this; }
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


BASE_PACKAGE = {
    "type": "module",
    "code2skill": {"profile": "core-export-v1"},
    "scripts": {"test": "node --test tests/*.test.mjs"},
    "dependencies": {"@modelcontextprotocol/sdk": "^1.0.0", "zod": "^3.0.0"},
}


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def install_fake_node_modules(candidate: Path) -> None:
    write(candidate / "node_modules" / "zod" / "package.json", '{"name":"zod","type":"module","exports":"./index.js"}\n')
    write(candidate / "node_modules" / "zod" / "index.js", FAKE_ZOD)
    write(
        candidate / "node_modules" / "@modelcontextprotocol" / "sdk" / "package.json",
        '{"name":"@modelcontextprotocol/sdk","type":"module","exports":{"./server/mcp.js":"./server/mcp.js","./server/stdio.js":"./server/stdio.js"}}\n',
    )
    write(
        candidate / "node_modules" / "@modelcontextprotocol" / "sdk" / "server" / "mcp.js",
        FAKE_MCP_SERVER,
    )
    write(
        candidate / "node_modules" / "@modelcontextprotocol" / "sdk" / "server" / "stdio.js",
        FAKE_MCP_STDIO,
    )


def base_skill_md(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {description}\n"


def run_validator(
    candidate: Path, *, skip_tests: bool = False
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(VALIDATOR)]
    if skip_tests:
        cmd.append("--skip-tests")
    cmd.append(str(candidate))
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def build_rpc_candidate(root: Path) -> Path:
    """Anonymous synchronous method-call package: fixed operation identity and spy."""
    candidate = root / "synthetic-rpc-core"
    write(
        candidate / "SKILL.md",
        base_skill_md("synthetic-rpc-core", "查询合成目录条目。"),
    )
    write(
        candidate / "MCP-SETUP.md",
        "# 安装与运行\n\n`npx skills add ./synthetic-rpc-core` 只安装 Skill；MCP 需要单独注册。\n启动前运行 `npm install`。\n",
    )
    write(candidate / "package.json", json.dumps(BASE_PACKAGE, indent=2, ensure_ascii=False))
    write(
        candidate / "function-core" / "adapter.mjs",
        """// Fake RPC adapter/spy for neutral fixture testing.
let calls = [];
export function resetCalls() { calls = []; }
export function getCalls() { return calls; }
export function rpcAdapter() {
  return {
    call: (operationIdentity, args, context) => {
      calls.push({operationIdentity, args, context});
      if (args[1] === 'throw') {
        const error = new Error('catalog unavailable');
        error.code = 'CATALOG_TIMEOUT';
        throw error;
      }
      return {catalogCode: args[0], itemId: args[1], name: `item-${args[1]}`};
    }
  };
}
""",
    )
    write(
        candidate / "function-core" / "index.mjs",
        """import { z } from 'zod';
import { rpcAdapter } from './adapter.mjs';
export const lookupCatalogItemInputSchema = z.object({
  catalogCode: z.unknown().optional().describe('目录编码'),
  itemId: z.unknown().optional().describe('条目标识'),
  routingKey: z.unknown().optional().describe('路由键'),
  tenant: z.unknown().optional().describe('租户上下文')
}).passthrough();
export async function lookupCatalogItem(input) {
  // Thin wrapper: fixed operation identity, parameter order preserved, context passed through.
  const adapter = rpcAdapter();
  return adapter.call('CatalogService.lookupItem',
    [input.catalogCode, input.itemId],
    {routingKey: input.routingKey, tenant: input.tenant}
  );
}
""",
    )
    write(
        candidate / "mcp-tool" / "index.mjs",
        """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { lookupCatalogItem, lookupCatalogItemInputSchema } from '../function-core/index.mjs';
function toAgentResult(structuredContent) {
  return {content: [{type: 'text', text: JSON.stringify(structuredContent)}], structuredContent, isError: false};
}
function toAgentError(message) {
  return {content: [{type: 'text', text: message}], structuredContent: {message}, isError: true};
}
const server = new McpServer({name: 'synthetic-rpc-core', version: '1'});
server.registerTool("lookup_catalog_item", {
  title: '合成目录：查询条目',
  description: '按 catalogCode/itemId 调用 CatalogService.lookupItem；结果交给 Agent 判断。',
  inputSchema: lookupCatalogItemInputSchema,
  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}
}, async (input) => {
  if (process.env.CODE2SKILL_DRY_RUN === "1") {
    return toAgentResult({dryRun: true, validatedInput: input});
  }
  try {
    const result = await lookupCatalogItem(input);
    return toAgentResult(result);
  } catch (error) {
    return toAgentError(error.message);
  }
});
await server.connect(new StdioServerTransport());
""",
    )
    write(
        candidate / "tests" / "function.test.mjs",
        """import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lookupCatalogItem } from '../function-core/index.mjs';
import { getCalls, resetCalls } from '../function-core/adapter.mjs';
test('lookup_catalog_item preserves operation identity, argument order and context', async () => {
  resetCalls();
  const result = await lookupCatalogItem({catalogCode: 'main', itemId: 'alpha', routingKey: 'v1', tenant: 't1'});
  const calls = getCalls();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].operationIdentity, 'CatalogService.lookupItem');
  assert.deepEqual(calls[0].args, ['main', 'alpha']);
  assert.deepEqual(calls[0].context, {routingKey: 'v1', tenant: 't1'});
  assert.deepEqual(result, {catalogCode: 'main', itemId: 'alpha', name: 'item-alpha'});
});
test('lookup_catalog_item passes through exceptions', async () => {
  resetCalls();
  await assert.rejects(async () => {
    await lookupCatalogItem({catalogCode: 'main', itemId: 'throw'});
  }, /catalog unavailable/);
});
""",
    )
    shutil.copyfile(PORTABLE_RESULT, candidate / "portable-agent-result.mjs")
    install_fake_node_modules(candidate)
    return candidate


def build_wayb_candidate(root: Path) -> Path:
    """Anonymous in-runtime wrapper (way B): wrapper delegates, business formula stays put."""
    candidate = root / "synthetic-ledger-core"
    write(
        candidate / "SKILL.md",
        base_skill_md("synthetic-ledger-core", "在合成账本运行时内查询余额。"),
    )
    write(
        candidate / "MCP-SETUP.md",
        "# 安装与运行\n\n`npx skills add ./synthetic-ledger-core` 只安装 Skill；MCP 需要单独注册。\n启动前运行 `npm install`。\n",
    )
    write(candidate / "package.json", json.dumps(BASE_PACKAGE, indent=2, ensure_ascii=False))
    write(
        candidate / "function-core" / "original-runtime.mjs",
        """// Existing business capability inside the original runtime.
let callCount = 0;
export function originalComputeBalance(accountId, multiplier) {
  callCount += 1;
  return {accountId, balance: accountId.length * multiplier, invocationIndex: callCount};
}
export function getCallCount() { return callCount; }
export function resetCallCount() { callCount = 0; }
""",
    )
    write(
        candidate / "function-core" / "index.mjs",
        """import { z } from 'zod';
import { originalComputeBalance } from './original-runtime.mjs';
export const computeBalanceInputSchema = z.object({
  accountId: z.unknown().optional().describe('账户标识'),
  multiplier: z.unknown().optional().describe('系数')
}).passthrough();
export async function computeBalance(input) {
  // Way B: delegate once to the existing runtime method; do not copy its formula.
  return originalComputeBalance(input.accountId, input.multiplier);
}
""",
    )
    write(
        candidate / "mcp-tool" / "index.mjs",
        """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { computeBalance, computeBalanceInputSchema } from '../function-core/index.mjs';
function toAgentResult(structuredContent) {
  return {content: [{type: 'text', text: JSON.stringify(structuredContent)}], structuredContent, isError: false};
}
const server = new McpServer({name: 'synthetic-ledger-core', version: '1'});
server.registerTool("compute_balance", {
  title: '合成账本：计算余额',
  description: '在原始运行时内调用已有方法计算余额。',
  inputSchema: computeBalanceInputSchema,
  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}
}, async (input) => {
  if (process.env.CODE2SKILL_DRY_RUN === "1") {
    return toAgentResult({dryRun: true, validatedInput: input});
  }
  const result = await computeBalance(input);
  return toAgentResult(result);
});
await server.connect(new StdioServerTransport());
""",
    )
    write(
        candidate / "tests" / "function.test.mjs",
        """import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computeBalance } from '../function-core/index.mjs';
import { originalComputeBalance, getCallCount, resetCallCount } from '../function-core/original-runtime.mjs';
test('compute_balance delegates to original runtime exactly once', async () => {
  resetCallCount();
  const wrapperResult = await computeBalance({accountId: 'acct-xyz', multiplier: 3});
  const directResult = originalComputeBalance('acct-xyz', 3);
  assert.equal(wrapperResult.accountId, directResult.accountId);
  assert.equal(wrapperResult.balance, directResult.balance);
  assert.equal(getCallCount(), 2);
});
""",
    )
    shutil.copyfile(PORTABLE_RESULT, candidate / "portable-agent-result.mjs")
    install_fake_node_modules(candidate)
    return candidate


def build_async_candidate(root: Path) -> Path:
    """Anonymous async submission package: receipt only, no completion claim."""
    candidate = root / "synthetic-task-core"
    write(
        candidate / "SKILL.md",
        base_skill_md("synthetic-task-core", "提交合成事件并返回回执。"),
    )
    write(
        candidate / "MCP-SETUP.md",
        "# 安装与运行\n\n`npx skills add ./synthetic-task-core` 只安装 Skill；MCP 需要单独注册。\n启动前运行 `npm install`。\n",
    )
    write(candidate / "package.json", json.dumps(BASE_PACKAGE, indent=2, ensure_ascii=False))
    write(
        candidate / "function-core" / "index.mjs",
        """import { z } from 'zod';
let published = [];
export function resetPublished() { published = []; }
export function getPublished() { return published; }
export const publishEventInputSchema = z.object({
  target: z.unknown().optional().describe('目标 destination/topic'),
  payload: z.unknown().optional().describe('事件载荷'),
  context: z.unknown().optional().describe('发布上下文')
}).passthrough();
export async function publishEvent(input) {
  // Async submission: records target/payload/context, returns receipt only.
  published.push({target: input.target, payload: input.payload, context: input.context});
  if (input.target === 'fail') {
    throw new Error('broker rejected');
  }
  return {received: true, receiptId: `rcpt-${published.length}`};
}
""",
    )
    write(
        candidate / "mcp-tool" / "index.mjs",
        """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { publishEvent, publishEventInputSchema } from '../function-core/index.mjs';
function toAgentResult(structuredContent) {
  return {content: [{type: 'text', text: JSON.stringify(structuredContent)}], structuredContent, isError: false};
}
function toAgentError(message) {
  return {content: [{type: 'text', text: message}], structuredContent: {message}, isError: true};
}
const server = new McpServer({name: 'synthetic-task-core', version: '1'});
server.registerTool("publish_event", {
  title: '合成事件：提交',
  description: '提交一个合成事件并返回回执；业务完成需另外查询。',
  inputSchema: publishEventInputSchema,
  annotations: {readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false}
}, async (input) => {
  if (process.env.CODE2SKILL_DRY_RUN === "1") {
    return toAgentResult({dryRun: true, validatedInput: input});
  }
  try {
    const result = await publishEvent(input);
    return toAgentResult(result);
  } catch (error) {
    return toAgentError(error.message);
  }
});
await server.connect(new StdioServerTransport());
""",
    )
    write(
        candidate / "tests" / "function.test.mjs",
        """import { test } from 'node:test';
import assert from 'node:assert/strict';
import { publishEvent, getPublished, resetPublished } from '../function-core/index.mjs';
test('publish_event records target/payload and returns a receipt', async () => {
  resetPublished();
  const result = await publishEvent({target: 'orders', payload: {value: 7}, context: {traceId: 'tx-1'}});
  assert.deepEqual(Object.keys(result).sort(), ['receiptId', 'received']);
  assert.equal(result.received, true);
  assert.match(result.receiptId, /^rcpt-/);
  const published = getPublished();
  assert.equal(published.length, 1);
  assert.equal(published[0].target, 'orders');
  assert.deepEqual(published[0].payload, {value: 7});
  assert.deepEqual(published[0].context, {traceId: 'tx-1'});
});
test('publish_event passes through broker exceptions', async () => {
  resetPublished();
  await assert.rejects(async () => {
    await publishEvent({target: 'fail', payload: {}});
  }, /broker rejected/);
});
""",
    )
    shutil.copyfile(PORTABLE_RESULT, candidate / "portable-agent-result.mjs")
    install_fake_node_modules(candidate)
    return candidate


def build_host_integration_candidate(root: Path) -> Path:
    """Anonymous way C package: requires-host-integration, not runnable."""
    candidate = root / "synthetic-unavailable-core"
    write(
        candidate / "SKILL.md",
        base_skill_md("synthetic-unavailable-core", "需要宿主接入的合成能力。"),
    )
    write(
        candidate / "MCP-SETUP.md",
        "# 安装与运行\n\n`npx skills add ./synthetic-unavailable-core` 只安装 Skill；MCP 需要单独注册。\n启动前运行 `npm install`。\n该能力需要 Consumer Host 提供专有运行时接入，标记为 requires-host-integration。\n",
    )
    package = {
        **BASE_PACKAGE,
        "code2skill": {"profile": "core-export-v1", "requiresHostIntegration": True},
    }
    write(candidate / "package.json", json.dumps(package, indent=2, ensure_ascii=False))
    write(
        candidate / "function-core" / "index.mjs",
        """import { z } from 'zod';
export const placeholderInputSchema = z.object({}).passthrough();
export async function placeholder() {
  throw new Error('requires-host-integration: no runnable client available in this package');
}
""",
    )
    write(
        candidate / "mcp-tool" / "index.mjs",
        """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { placeholderInputSchema } from '../function-core/index.mjs';
function toAgentError(message) {
  return {content: [{type: 'text', text: message}], structuredContent: {message}, isError: true};
}
const server = new McpServer({name: 'synthetic-unavailable-core', version: '1'});
server.registerTool("placeholder", {
  title: '合成能力占位',
  description: '需要宿主接入；本包不声称可运行。',
  inputSchema: placeholderInputSchema,
  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}
}, async () => {
  return toAgentError('requires-host-integration: no runnable client available in this package');
});
await server.connect(new StdioServerTransport());
""",
    )
    write(
        candidate / "tests" / "placeholder.test.mjs",
        """import { test } from 'node:test';
test('placeholder', () => {});
""",
    )
    shutil.copyfile(PORTABLE_RESULT, candidate / "portable-agent-result.mjs")
    install_fake_node_modules(candidate)
    return candidate


def build_http_candidate(root: Path) -> Path:
    """Minimal HTTP candidate to confirm no regression of HTTP path."""
    candidate = root / "synthetic-http-core"
    write(
        candidate / "SKILL.md",
        base_skill_md("synthetic-http-core", "查询合成 HTTP 资源。"),
    )
    write(
        candidate / "MCP-SETUP.md",
        "# 安装与运行\n\n`npx skills add ./synthetic-http-core` 只安装 Skill；MCP 需要单独注册。\n启动前运行 `npm install`。\n",
    )
    write(candidate / "package.json", json.dumps(BASE_PACKAGE, indent=2, ensure_ascii=False))
    write(
        candidate / "function-core" / "index.mjs",
        """import { z } from 'zod';
export const fetchResourceInputSchema = z.object({
  id: z.unknown().optional().describe('资源标识')
}).passthrough();
export async function fetchResource(input) {
  return {httpStatus: 200, bodyText: JSON.stringify({id: input.id})};
}
""",
    )
    write(
        candidate / "mcp-tool" / "index.mjs",
        """import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { fetchResource, fetchResourceInputSchema } from '../function-core/index.mjs';
function toAgentResult(structuredContent) {
  return {content: [{type: 'text', text: JSON.stringify(structuredContent)}], structuredContent, isError: false};
}
const server = new McpServer({name: 'synthetic-http-core', version: '1'});
server.registerTool("fetch_resource", {
  title: '合成资源：获取',
  description: '通过 HTTP 获取合成资源。',
  inputSchema: fetchResourceInputSchema,
  annotations: {readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false}
}, async (input) => {
  if (process.env.CODE2SKILL_DRY_RUN === "1") {
    return toAgentResult({dryRun: true, validatedInput: input});
  }
  const result = await fetchResource(input);
  return toAgentResult(result);
});
await server.connect(new StdioServerTransport());
""",
    )
    write(
        candidate / "tests" / "function.test.mjs",
        """import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fetchResource } from '../function-core/index.mjs';
test('fetch_resource preserves httpStatus and bodyText', async () => {
  const result = await fetchResource({id: 'abc'});
  assert.equal(result.httpStatus, 200);
  assert.equal(result.bodyText, '{"id":"abc"}');
});
""",
    )
    shutil.copyfile(PORTABLE_RESULT, candidate / "portable-agent-result.mjs")
    install_fake_node_modules(candidate)
    return candidate
