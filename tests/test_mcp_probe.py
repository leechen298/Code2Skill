from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "skills" / "code2skill" / "scripts" / "probe_mcp.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_candidate(
    root: Path,
    *,
    broken_result: bool = False,
    mismatched_content: bool = False,
    schema_type: str = "string",
    side_effect: str = "read",
    result_value_expression: str = "args.value",
    success_is_error_expression: str | None = "false",
) -> Path:
    candidate = root / "portable-synthetic-skill"
    (candidate / "mcp-tool").mkdir(parents=True)
    operation_policy = {
        "sideEffect": side_effect,
        "idempotency": "safe" if side_effect == "read" else "at-most-once",
        "automaticRetry": "read-only-bounded" if side_effect == "read" else "never",
        "confirmation": "not-required",
        "unknownOutcome": "not-applicable" if side_effect == "read" else "stop-and-reconcile",
    }
    annotations = {
        "readOnlyHint": side_effect == "read",
        "destructiveHint": side_effect != "read",
        "idempotentHint": side_effect == "read",
        "openWorldHint": False,
    }
    capability = {
            "capabilityId": "echo-value",
            "toolName": "echo_value",
            "functionExport": "echoValue",
            "description": "Echo one synthetic value.",
            "authentication": "none",
            "inputs": [{"name": "value", "description": "Synthetic value.", "type": "string", "required": True, "evidenceRefs": ["synthetic"]}],
            "outputs": [{"path": ["echo"], "type": "string", "description": "Echoed synthetic value.", "evidenceRefs": ["synthetic"]}],
            "errorContract": {
                "format": "structured",
                "preservesRecoveryContext": True,
                "codePath": ["code"],
                "messagePath": ["message"],
                "detailsPath": ["details"],
                "retryabilityPath": ["retryable"],
                "defaultRetryable": False,
                "evidenceRefs": ["synthetic"],
            },
            "implementation": {"kind": "local"},
            "successRule": {"kind": "output", "outputRequired": True, "forbiddenOutputKeys": ["error"], "requiredOutputPaths": [["echo"]], "evidenceRefs": ["synthetic"]},
            "sideEffect": side_effect,
            "operationPolicy": operation_policy,
            "annotations": annotations,
            "evidenceRefs": ["synthetic"],
        }
    write_json(candidate / "capability-bundle.json", {
        "schemaVersion": "v1",
        "recordingId": "synthetic-detached-probe",
        "server": {"name": "portable-synthetic-skill", "description": "Synthetic probe server.", "evidenceRefs": ["synthetic"]},
        "capabilities": [capability],
        "handoffs": [],
    })
    write_json(candidate / "canonical-contract.json", {
        "schemaVersion": "vNext",
        "contractId": "synthetic-detached-probe",
        "capabilities": [capability],
        "workflows": [],
    })
    write_json(candidate / "export-profile.json", {
        "schemaVersion": "v1",
        "profile": "strict-export-v1",
        "protocolVersion": "2025-11-25",
        "transport": "stdio",
        "documentationLanguage": "zh-CN",
        "featureSurface": {"kind": "other", "identifier": "synthetic-detached-probe"},
        "allowedRuntimeOrigins": ["https://application.example"],
        "dryRunEnvironmentVariable": "SYNTHETIC_DRY_RUN",
    })
    is_error_field = (
        ""
        if success_is_error_expression is None
        else f"isError: {success_is_error_expression}, "
    )
    result_expression = (
        f"{{ {is_error_field}structuredContent: {{ status: 'success', data: {{ echo: {result_value_expression} }} }}, "
        f"content: [{{ type: 'text', text: JSON.stringify({{ status: 'success', data: {{ echo: {result_value_expression} }} }}) }}] }}"
    )
    if broken_result:
        result_expression = f"{{ isError: false, structuredContent: {{ status: 'success', data: {{ echo: {result_value_expression} }} }} }}"
    elif mismatched_content:
        result_expression = (
            f"{{ isError: false, structuredContent: {{ status: 'success', data: {{ echo: {result_value_expression} }} }}, "
            "content: [{ type: 'text', text: JSON.stringify({ status: 'success', data: { echo: 'different' } }) }] }"
        )
    server_source = f"""
import {{ createInterface }} from 'node:readline';

const tools = [{{
  name: 'echo_value',
  title: '合成数据：读取回显值',
  description: '用于合成测试的本地只读能力。',
  inputSchema: {{ type: 'object', additionalProperties: false, properties: {{ value: {{ type: '{schema_type}', description: 'Synthetic value.' }} }}, required: ['value'] }},
  outputSchema: {{
    type: 'object',
    additionalProperties: false,
    properties: {{
      status: {{ type: 'string' }},
      data: {{
        type: 'object',
        additionalProperties: false,
        properties: {{ echo: {{ type: 'string', description: 'Echoed synthetic value.' }} }},
        required: ['echo']
      }}
    }},
    required: ['status', 'data']
  }},
  annotations: {json.dumps(annotations)}
}}];

function send(value) {{ process.stdout.write(JSON.stringify(value) + '\\n'); }}

createInterface({{ input: process.stdin }}).on('line', (line) => {{
  const message = JSON.parse(line);
  if (message.method === 'notifications/initialized') return;
  if (message.method === 'initialize') {{
    send({{ jsonrpc: '2.0', id: message.id, result: {{ protocolVersion: '2025-11-25', capabilities: {{ tools: {{}} }}, serverInfo: {{ name: 'synthetic', version: '1' }} }} }});
    return;
  }}
  if (message.method === 'tools/list') {{
    send({{ jsonrpc: '2.0', id: message.id, result: {{ tools }} }});
    return;
  }}
  if (message.method === 'tools/call') {{
    if (message.params?.name !== 'echo_value') {{
      send({{ jsonrpc: '2.0', id: message.id, error: {{ code: -32602, message: 'Unknown tool' }} }});
      return;
    }}
    const args = message.params.arguments ?? {{}};
    if (typeof args.value !== 'string') {{
      const structuredContent = {{ code: 'INVALID_ARGUMENT', message: 'value is required', details: {{ field: 'value' }}, retryable: true }};
      send({{ jsonrpc: '2.0', id: message.id, result: {{ isError: true, structuredContent, content: [{{ type: 'text', text: JSON.stringify(structuredContent) }}] }} }});
      return;
    }}
    if (args.value === '__error__') {{
      const structuredContent = {{ code: 'SYNTHETIC_EXECUTION_ERROR', message: 'synthetic execution failed', details: {{ field: 'value' }}, retryable: false }};
      send({{ jsonrpc: '2.0', id: message.id, result: {{ isError: true, structuredContent, content: [{{ type: 'text', text: JSON.stringify(structuredContent) }}] }} }});
      return;
    }}
    if (process.env.SYNTHETIC_DRY_RUN === '1') {{
      const structuredContent = {{
        dryRun: true,
        validatedInput: args,
        operationPolicy: {json.dumps(operation_policy)},
        operationSummary: {{ implementationKind: 'local', stepCount: 0, methods: [], origins: [], attachmentMode: 'none' }}
      }};
      send({{ jsonrpc: '2.0', id: message.id, result: {{ isError: false, structuredContent, content: [{{ type: 'text', text: JSON.stringify(structuredContent) }}] }} }});
      return;
    }}
    send({{ jsonrpc: '2.0', id: message.id, result: {result_expression} }});
  }}
}});
"""
    (candidate / "mcp-tool" / "index.mjs").write_text(server_source, encoding="utf-8")
    return candidate


class DetachedMcpProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is required for the detached MCP probe")

    def run_probe(self, candidate: Path, call: Path, dry_call: Path) -> subprocess.CompletedProcess[str]:
        error_call = call.parent / "error-call.json"
        write_json(error_call, {"name": "echo_value", "arguments": {"value": "__error__"}})
        return subprocess.run(
            [
                sys.executable,
                str(PROBE),
                str(candidate),
                "--call",
                str(call),
                "--error-call",
                str(error_call),
                "--dry-run-call",
                str(dry_call),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_probe_runs_list_call_errors_and_dry_run_from_detached_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root)
            call = root / "call.json"
            dry_call = root / "dry-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

            result = self.run_probe(candidate, call, dry_call)

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertIs(summary["detachedCopy"], True)
        self.assertEqual(summary["protocolVersion"], "2025-11-25")
        self.assertEqual(summary["tools"], ["echo_value"])
        self.assertEqual(summary["successfulCalls"], 1)
        self.assertEqual(summary["successfulDryRunCalls"], 1)
        self.assertEqual(summary["invalidArgumentsChecked"], 1)
        self.assertEqual(summary["structuredExecutionErrorsChecked"], 1)

    def test_probe_rejects_success_without_text_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root, broken_result=True)
            call = root / "call.json"
            dry_call = root / "dry-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "broken"}})
            write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

            result = self.run_probe(candidate, call, dry_call)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("structuredContent and matching content", result.stderr)

    def test_probe_rejects_mismatched_text_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root, mismatched_content=True)
            call = root / "call.json"
            dry_call = root / "dry-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

            result = self.run_probe(candidate, call, dry_call)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("matching structuredContent", result.stderr)

    def test_probe_requires_success_to_declare_boolean_is_error_false(self) -> None:
        for is_error_expression in (None, "null", "0"):
            with self.subTest(is_error_expression=is_error_expression), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                candidate = create_candidate(
                    root,
                    success_is_error_expression=is_error_expression,
                )
                call = root / "call.json"
                dry_call = root / "dry-call.json"
                write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
                write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

                result = self.run_probe(candidate, call, dry_call)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must declare isError=false", result.stderr)

    def test_probe_rejects_schema_drift_from_canonical_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root, schema_type="number")
            call = root / "call.json"
            dry_call = root / "dry-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

            result = self.run_probe(candidate, call, dry_call)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inputSchema must exactly match", result.stderr)

    def test_probe_rejects_success_result_that_violates_output_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root, result_value_expression="42")
            call = root / "call.json"
            dry_call = root / "dry-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

            result = self.run_probe(candidate, call, dry_call)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("violates the Canonical outputSchema", result.stderr)

    def test_probe_requires_a_structured_execution_error_case_for_every_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root)
            call = root / "call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            result = subprocess.run(
                [sys.executable, str(PROBE), str(candidate), "--call", str(call)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--error-call must include", result.stderr)

    def test_probe_rejects_zero_success_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root)
            result = subprocess.run(
                [sys.executable, str(PROBE), str(candidate)],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("successful case for every Tool", result.stderr)

    def test_probe_requires_a_dry_run_case_for_every_write_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root, side_effect="create")
            call = root / "call.json"
            error_call = root / "error-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            write_json(error_call, {"name": "echo_value", "arguments": {"value": "__error__"}})
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROBE),
                    str(candidate),
                    "--call",
                    str(call),
                    "--error-call",
                    str(error_call),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--dry-run-call must include every write Tool", result.stderr)

    def test_probe_accepts_complete_write_tool_success_error_and_dry_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_candidate(root, side_effect="create")
            call = root / "call.json"
            dry_call = root / "dry-call.json"
            write_json(call, {"name": "echo_value", "arguments": {"value": "normal"}})
            write_json(dry_call, {"name": "echo_value", "arguments": {"value": "dry"}})

            result = self.run_probe(candidate, call, dry_call)

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["successfulCalls"], 1)
        self.assertEqual(summary["successfulDryRunCalls"], 1)
        self.assertEqual(summary["structuredExecutionErrorsChecked"], 1)


if __name__ == "__main__":
    unittest.main()
