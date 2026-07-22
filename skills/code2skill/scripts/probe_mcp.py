#!/usr/bin/env python3
"""Probe a generated stdio MCP server from a detached temporary copy.

The probe intentionally uses only the Python standard library.  It speaks the
public MCP JSON-RPC surface as a client; generated servers must still use an
official MCP SDK rather than implementing their own transport.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, TextIO

from contract_model import derive_schema_contract, json_schema_errors


PROTOCOL_VERSION = "2025-11-25"


class ProbeError(RuntimeError):
    """Raised when the detached MCP process violates the probe contract."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProbeError(f"cannot read JSON from {path}: {error}") from error


def load_cases(paths: list[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in paths:
        value = read_json(path)
        values = value if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                raise ProbeError(f"{path}[{index}] must be an object")
            name = item.get("name")
            arguments = item.get("arguments")
            if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                raise ProbeError(f"{path}[{index}] needs non-empty name and object arguments")
            cases.append({"name": name, "arguments": arguments})
    return cases


class StdioMcpClient:
    def __init__(self, process: subprocess.Popen[str], timeout: float) -> None:
        if process.stdin is None or process.stdout is None:
            raise ProbeError("stdio MCP process did not expose pipes")
        self.process = process
        self.stdin: TextIO = process.stdin
        self.stdout: TextIO = process.stdout
        self.timeout = timeout
        self.next_id = 1

    def send(self, message: dict[str, Any]) -> None:
        self.stdin.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError(f"timed out waiting for {method} response")
            ready, _, _ = select.select([self.stdout], [], [], remaining)
            if not ready:
                raise ProbeError(f"timed out waiting for {method} response")
            line = self.stdout.readline()
            if line == "":
                raise ProbeError(f"MCP process exited before replying to {method}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise ProbeError(f"MCP stdout contained non-JSON data: {line.rstrip()!r}") from error
            if not isinstance(message, dict):
                raise ProbeError("MCP response must be a JSON object")
            if message.get("id") == request_id:
                return message


def spawn_server(root: Path, timeout: float, *, dry_run: bool) -> tuple[subprocess.Popen[str], StdioMcpClient]:
    profile = read_json(root / "export-profile.json")
    if not isinstance(profile, dict):
        raise ProbeError("export-profile.json must be an object")
    environment = os.environ.copy()
    if dry_run:
        variable = profile.get("dryRunEnvironmentVariable")
        if not isinstance(variable, str) or not variable:
            raise ProbeError("dry-run case requires dryRunEnvironmentVariable")
        environment[variable] = "1"
    process = subprocess.Popen(
        ["node", "mcp-tool/index.mjs"],
        cwd=root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    return process, StdioMcpClient(process, timeout)


def stop_server(process: subprocess.Popen[str]) -> tuple[str, bool]:
    forced = False
    if process.stdin is not None:
        process.stdin.close()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        forced = True
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    return (process.stderr.read() if process.stderr is not None else ""), forced


def initialize(client: StdioMcpClient) -> None:
    response = client.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "code2skill-detached-probe", "version": "1.0.0"},
        },
    )
    result = response.get("result")
    if "error" in response or not isinstance(result, dict):
        raise ProbeError(f"initialize failed: {response}")
    if result.get("protocolVersion") != PROTOCOL_VERSION:
        raise ProbeError("server did not negotiate the declared MCP protocol version")
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})


def _matching_text_projection(content: Any, structured: dict[str, Any]) -> bool:
    if not isinstance(content, list) or not content:
        return False
    for block in content:
        if (
            not isinstance(block, dict)
            or block.get("type") != "text"
            or not isinstance(block.get("text"), str)
        ):
            continue
        try:
            projected = json.loads(block["text"])
        except json.JSONDecodeError:
            continue
        if projected == structured:
            return True
    return False


def assert_tool_result(
    response: dict[str, Any],
    schema_contract: dict[str, Any],
    arguments: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    result = response.get("result")
    if "error" in response or not isinstance(result, dict):
        raise ProbeError(f"tools/call failed: {response}")
    if result.get("isError") is not False:
        raise ProbeError(
            "successful Tool calls must declare isError=false; "
            f"received: {response}"
        )
    structured = result.get("structuredContent")
    content = result.get("content")
    if not isinstance(structured, dict) or not isinstance(content, list) or not content:
        raise ProbeError("successful Tool calls need structuredContent and matching content")
    if not _matching_text_projection(content, structured):
        raise ProbeError(
            "successful Tool content must contain a JSON text projection matching structuredContent"
        )
    if dry_run:
        required_fields = {
            "dryRun",
            "validatedInput",
            "operationPolicy",
            "operationSummary",
        }
        if set(structured) != required_fields:
            raise ProbeError(
                "dry-run result must contain exactly dryRun, validatedInput, operationPolicy, and operationSummary"
            )
        if structured.get("dryRun") is not True:
            raise ProbeError("dry-run Tool call did not return dryRun=true")
        if structured.get("validatedInput") != arguments:
            raise ProbeError("dry-run validatedInput must exactly match the probed arguments")
        if structured.get("operationPolicy") != schema_contract.get("operationPolicy"):
            raise ProbeError("dry-run operationPolicy must exactly match the Canonical policy")
        if structured.get("operationSummary") != schema_contract.get("operationSummary"):
            raise ProbeError("dry-run operationSummary must exactly match the Canonical request plan")
        return
    schema_errors = json_schema_errors(
        structured,
        schema_contract.get("outputSchema"),
    )
    if schema_errors:
        raise ProbeError(
            "successful Tool result violates the Canonical outputSchema: "
            + "; ".join(schema_errors)
        )


def _value_at_path(value: Any, path: Any) -> Any:
    current = value
    if not isinstance(path, list) or not path:
        return None
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def assert_tool_error_result(
    result: dict[str, Any],
    capability: dict[str, Any],
) -> None:
    tool_name = str(capability.get("toolName"))
    if result.get("isError") is not True:
        raise ProbeError(f"Tool {tool_name} did not return isError=true")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise ProbeError(f"Tool {tool_name} execution error needs structuredContent")
    error_contract = capability.get("errorContract")
    if not isinstance(error_contract, dict):
        raise ProbeError(f"Tool {tool_name} needs a Canonical errorContract")
    resolved_error_values: dict[str, Any] = {}
    for path_name in ("codePath", "messagePath", "detailsPath"):
        value = _value_at_path(structured, error_contract.get(path_name))
        resolved_error_values[path_name] = value
        if value is None:
            raise ProbeError(
                f"Tool {tool_name} execution error is missing Canonical {path_name}"
            )
    if not isinstance(resolved_error_values["codePath"], str) or not resolved_error_values["codePath"].strip():
        raise ProbeError(f"Tool {tool_name} execution error code must be a non-empty string")
    if not isinstance(resolved_error_values["messagePath"], str) or not resolved_error_values["messagePath"].strip():
        raise ProbeError(f"Tool {tool_name} execution error message must be a non-empty string")
    if not isinstance(resolved_error_values["detailsPath"], (dict, list)):
        raise ProbeError(f"Tool {tool_name} execution error details must be structured")
    retryability_path = error_contract.get("retryabilityPath")
    if retryability_path is not None and not isinstance(
        _value_at_path(structured, retryability_path),
        bool,
    ):
        raise ProbeError(
            f"Tool {tool_name} execution error is missing boolean Canonical retryabilityPath"
        )
    if not _matching_text_projection(result.get("content"), structured):
        raise ProbeError(
            f"Tool {tool_name} execution error content must match structuredContent"
        )


def _schema_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("type") != "object":
        raise ProbeError(f"{location} must be an object JSON Schema")
    if value.get("additionalProperties") is not False:
        raise ProbeError(f"{location} must set additionalProperties=false")
    if not isinstance(value.get("properties"), dict):
        raise ProbeError(f"{location}.properties must be an object")
    required = value.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise ProbeError(f"{location}.required must be an array of property names")
    return value


def _normalize_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_schema(child)
            for key, child in value.items()
            if key != "$schema"
        }
    if isinstance(value, list):
        return [_normalize_schema(item) for item in value]
    return value


def _assert_output_path(
    schema: dict[str, Any],
    path: list[Any],
    location: str,
) -> dict[str, Any]:
    current: Any = schema
    traversed: list[str] = []
    for segment in path:
        if segment == "*":
            if (
                not isinstance(current, dict)
                or current.get("type") != "array"
                or not isinstance(current.get("items"), dict)
            ):
                raise ProbeError(
                    f"{location} path {'.'.join(traversed + ['*'])} must traverse an array schema"
                )
            current = current["items"]
            traversed.append("*")
            continue
        if not isinstance(segment, str) or not segment:
            raise ProbeError(f"{location} contains an invalid output path segment")
        if not isinstance(current, dict) or current.get("type") != "object":
            raise ProbeError(
                f"{location} path {'.'.join(traversed)} must traverse an object schema"
            )
        properties = current.get("properties")
        required = current.get("required")
        if not isinstance(properties, dict) or segment not in properties:
            raise ProbeError(
                f"{location} is missing output property {'.'.join(traversed + [segment])}"
            )
        if not isinstance(required, list) or segment not in required:
            raise ProbeError(
                f"{location} must require output property {'.'.join(traversed + [segment])}"
            )
        current = properties[segment]
        traversed.append(segment)
    if not isinstance(current, dict):
        raise ProbeError(f"{location} output path {'.'.join(traversed)} must end in a schema")
    return current


def assert_tool_schema(
    tool: dict[str, Any],
    capability: dict[str, Any],
    schema_contract: dict[str, Any],
) -> None:
    tool_name = capability.get("toolName")
    location = f"tools/list[{tool_name}]"
    if not isinstance(tool.get("title"), str) or not tool["title"].strip():
        raise ProbeError(f"{location}.title must be non-empty")
    if not isinstance(tool.get("description"), str) or not tool["description"].strip():
        raise ProbeError(f"{location}.description must be non-empty")
    if tool.get("annotations") != schema_contract.get("annotations"):
        raise ProbeError(f"{location}.annotations must exactly match the Canonical Tool hints")
    if _normalize_schema(tool.get("inputSchema")) != _normalize_schema(schema_contract.get("inputSchema")):
        raise ProbeError(f"{location}.inputSchema must exactly match the Canonical schema projection")
    if _normalize_schema(tool.get("outputSchema")) != _normalize_schema(schema_contract.get("outputSchema")):
        raise ProbeError(f"{location}.outputSchema must exactly match the Canonical schema projection")


def run_session(
    root: Path,
    capabilities: list[dict[str, Any]],
    schema_contracts: dict[str, dict[str, Any]],
    cases: list[dict[str, Any]],
    error_cases: list[dict[str, Any]],
    timeout: float,
    *,
    dry_run: bool,
    check_protocol_errors: bool,
) -> tuple[int, int, int]:
    process, client = spawn_server(root, timeout, dry_run=dry_run)
    completed = 0
    invalid_arguments_checked = 0
    execution_errors_checked = 0
    try:
        initialize(client)
        listed = client.request("tools/list", {})
        result = listed.get("result")
        tools = result.get("tools") if isinstance(result, dict) else None
        names = sorted(
            item.get("name") for item in tools
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ) if isinstance(tools, list) else []
        expected_tools = [item["toolName"] for item in capabilities]
        if names != sorted(expected_tools):
            raise ProbeError(f"tools/list mismatch: expected {sorted(expected_tools)}, got {names}")
        tools_by_name = {
            item["name"]: item
            for item in tools
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        } if isinstance(tools, list) else {}
        for capability in capabilities:
            tool_name = capability["toolName"]
            assert_tool_schema(
                tools_by_name[tool_name],
                capability,
                schema_contracts[tool_name],
            )
        capabilities_by_tool = {
            capability["toolName"]: capability for capability in capabilities
        }

        if check_protocol_errors:
            unknown = client.request(
                "tools/call",
                {"name": "__code2skill_unknown_tool__", "arguments": {}},
            )
            if "error" not in unknown:
                raise ProbeError("unknown Tool must produce a JSON-RPC protocol error")
            argument_contract_tools = [
                item
                for item in tools
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and isinstance(item.get("inputSchema"), dict)
            ] if isinstance(tools, list) else []
            for contract_tool in argument_contract_tools:
                required = contract_tool["inputSchema"].get("required", [])
                invalid_arguments = (
                    {}
                    if isinstance(required, list) and required
                    else {"__code2skill_unexpected_argument__": True}
                )
                invalid = client.request(
                    "tools/call",
                    {"name": contract_tool["name"], "arguments": invalid_arguments},
                )
                invalid_result = invalid.get("result")
                if "error" not in invalid:
                    if not isinstance(invalid_result, dict):
                        raise ProbeError(
                            "invalid Tool arguments must produce a protocol or Tool execution error"
                        )
                    assert_tool_error_result(
                        invalid_result,
                        capabilities_by_tool[contract_tool["name"]],
                    )
                invalid_arguments_checked += 1

        for case in cases:
            response = client.request("tools/call", case)
            assert_tool_result(
                response,
                schema_contracts[case["name"]],
                case["arguments"],
                dry_run=dry_run,
            )
            completed += 1
        for case in error_cases:
            response = client.request("tools/call", case)
            result = response.get("result")
            if "error" in response or not isinstance(result, dict):
                raise ProbeError(
                    f"explicit Tool execution error case must return a Tool result, not a JSON-RPC protocol error: {response}"
                )
            assert_tool_error_result(result, capabilities_by_tool[case["name"]])
            execution_errors_checked += 1
    finally:
        stderr, forced = stop_server(process)
        if not forced and process.returncode not in {0, None}:
            detail = f": {stderr.strip()}" if stderr.strip() else ""
            raise ProbeError(f"MCP process exited with code {process.returncode}{detail}")
    return completed, invalid_arguments_checked, execution_errors_checked


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--call", type=Path, action="append", default=[], help="JSON Tool call case; repeat as needed")
    parser.add_argument("--error-call", type=Path, action="append", default=[], help="JSON Tool call case that must reach a structured Tool execution error")
    parser.add_argument("--dry-run-call", type=Path, action="append", default=[], help="JSON Tool call case executed with the declared dry-run variable")
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        raise ProbeError("--timeout must be positive")
    source = args.artifact_root.resolve()
    bundle = read_json(source / "capability-bundle.json")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("capabilities"), list):
        raise ProbeError("capability-bundle.json must declare capabilities")
    capabilities = [
        item for item in bundle["capabilities"]
        if isinstance(item, dict) and isinstance(item.get("toolName"), str)
    ]
    expected_tools = [item["toolName"] for item in capabilities]
    if not capabilities:
        raise ProbeError("candidate must expose at least one Tool")
    canonical = read_json(source / "canonical-contract.json")
    if not isinstance(canonical, dict):
        raise ProbeError("canonical-contract.json must be an object")
    schema_projection = derive_schema_contract(canonical)
    schema_contracts = {
        item["toolName"]: item
        for item in schema_projection.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("toolName"), str)
    }
    if set(schema_contracts) != set(expected_tools):
        raise ProbeError("Canonical schema projection does not cover every Tool")

    def validate_cases(cases: list[dict[str, Any]], label: str) -> None:
        for index, case in enumerate(cases):
            name = case["name"]
            if name not in schema_contracts:
                raise ProbeError(f"{label}[{index}] references unknown Tool {name}")
            errors = json_schema_errors(
                case["arguments"],
                schema_contracts[name]["inputSchema"],
            )
            if errors:
                raise ProbeError(
                    f"{label}[{index}] arguments must satisfy the Canonical inputSchema so the case reaches the Tool handler: "
                    + "; ".join(errors)
                )
    normal_cases = load_cases(args.call)
    validate_cases(normal_cases, "--call")
    normal_names = {item["name"] for item in normal_cases}
    missing_normal = sorted(set(expected_tools) - normal_names)
    if missing_normal:
        raise ProbeError(
            f"--call must include a successful case for every Tool; missing {missing_normal}"
        )
    error_cases = load_cases(args.error_call)
    validate_cases(error_cases, "--error-call")
    missing_errors = sorted(set(expected_tools) - {item["name"] for item in error_cases})
    if missing_errors:
        raise ProbeError(
            f"--error-call must include a structured execution-error case for every Tool; missing {missing_errors}"
        )
    dry_cases = load_cases(args.dry_run_call)
    validate_cases(dry_cases, "--dry-run-call")
    write_tools = {
        item["toolName"]
        for item in capabilities
        if item.get("sideEffect") != "read"
    }
    missing_dry = sorted(write_tools - {item["name"] for item in dry_cases})
    if missing_dry:
        raise ProbeError(
            f"--dry-run-call must include every write Tool; missing {missing_dry}"
        )

    with tempfile.TemporaryDirectory(prefix="code2skill-detached-") as directory:
        detached = Path(directory) / source.name
        shutil.copytree(source, detached)
        normal_count, invalid_arguments_checked, execution_errors_checked = run_session(
            detached,
            capabilities,
            schema_contracts,
            normal_cases,
            error_cases,
            args.timeout,
            dry_run=False,
            check_protocol_errors=True,
        )
        dry_count = 0
        if dry_cases:
            dry_count, _, _ = run_session(
                detached,
                capabilities,
                schema_contracts,
                dry_cases,
                [],
                args.timeout,
                dry_run=True,
                check_protocol_errors=False,
            )

    print(json.dumps({
        "protocolVersion": PROTOCOL_VERSION,
        "detachedCopy": True,
        "tools": sorted(expected_tools),
        "successfulCalls": normal_count,
        "successfulDryRunCalls": dry_count,
        "invalidArgumentsChecked": invalid_arguments_checked,
        "structuredExecutionErrorsChecked": execution_errors_checked,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as error:
        print(f"ERROR {error}", file=sys.stderr)
        raise SystemExit(1)
