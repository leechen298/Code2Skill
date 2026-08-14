#!/usr/bin/env python3
"""Validate the small default Code2Skill delivery package.

The core validator protects runtime basics without recreating the strict audit
profile. It checks a compact package shape, JavaScript syntax, MCP discovery,
and package-provided offline smoke tests. It does not parse implementation
templates or try to prove business correctness. It never installs dependencies,
executes npm lifecycle hooks, or calls a business API itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


CORE_PROFILE = "core-export-v1"
REQUIRED_FILES = (
    "MCP-SETUP.md",
    "package.json",
    "function-core/index.mjs",
    "mcp-tool/index.mjs",
    "portable-agent-result.mjs",
)
STRICT_ONLY_FILES = (
    "approval-audit.json",
    "canonical-contract.json",
    "capability-bundle.json",
    "capability-draft.json",
    "consumer-requirements.json",
    "export-manifest.json",
    "export-profile.json",
    "goal-contract.json",
    "host-compatibility-report.json",
    "host-profile.json",
    "live-verification.json",
    "MCP.zh-CN.md",
    "preflight-report.json",
    "source-topology.json",
    "verification-matrix.json",
)


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(f"{path.name}: cannot read UTF-8 text ({error})")
        return ""


def frontmatter_scalar(value: str) -> object:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"null", "~"}:
        return None
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return float(value)
    return value


def frontmatter_values(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, object] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = frontmatter_scalar(value)
    return result


def discover_skill_files(candidate: Path, errors: list[str]) -> list[Path]:
    """Accept one root Skill or a collection of independent goal Skills."""
    root_skill = candidate / "SKILL.md"
    nested_skills = sorted((candidate / "skills").glob("*/SKILL.md"))
    if root_skill.is_file() and nested_skills:
        errors.append(
            "SKILL.md: a root Skill shadows nested skills; use the root file for one "
            "goal or skills/<goal-id>/SKILL.md for multiple goals, never both"
        )
        return [root_skill, *nested_skills]
    if root_skill.is_file():
        return [root_skill]
    if nested_skills:
        return nested_skills
    errors.append(
        "Skill: core-export-v1 requires SKILL.md or at least one "
        "skills/<goal-id>/SKILL.md"
    )
    return []


def clean_test_environment() -> dict[str, str]:
    """Keep process basics while withholding Producer business credentials."""
    environment: dict[str, str] = {}
    for key in (
        "PATH",
        "TMPDIR",
        "TMP",
        "TEMP",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "LANG",
        "LC_ALL",
    ):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    environment.update(CODE2SKILL_DRY_RUN="1", CI="1")
    return environment


def run_check(
    command: list[str],
    candidate: Path,
    label: str,
    errors: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> None:
    executable = shutil.which(command[0])
    if executable is None:
        errors.append(f"{label}: required executable is unavailable: {command[0]}")
        return
    try:
        result = subprocess.run(
            [executable, *command[1:]],
            cwd=candidate,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        errors.append(f"{label}: could not complete ({error})")
        return
    if result.returncode == 0:
        return
    output = (result.stderr or result.stdout).strip()
    if len(output) > 800:
        output = output[-800:]
    errors.append(f"{label}: command failed ({output or f'exit {result.returncode}'})")


def run_mcp_protocol_probe(candidate: Path, errors: list[str]) -> None:
    """Start the generated server and verify discovery without calling a Tool."""
    executable = shutil.which("node")
    if executable is None:
        errors.append("MCP protocol smoke: required executable is unavailable: node")
        return
    messages = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "code2skill-validator", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    payload = "".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages)
    try:
        result = subprocess.run(
            [executable, "mcp-tool/index.mjs"],
            cwd=candidate,
            env=clean_test_environment(),
            input=payload,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        errors.append(f"MCP protocol smoke: could not complete ({error})")
        return
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        errors.append(
            f"MCP protocol smoke: server failed ({output[-800:] or f'exit {result.returncode}'})"
        )
        return
    replies: dict[int, dict[str, object]] = {}
    try:
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            message = json.loads(line)
            if isinstance(message, dict) and isinstance(message.get("id"), int):
                replies[message["id"]] = message
    except json.JSONDecodeError as error:
        errors.append(f"MCP protocol smoke: stdout is not clean JSON-RPC ({error})")
        return
    if not isinstance(replies.get(1, {}).get("result"), dict):
        errors.append("MCP protocol smoke: initialize did not return a result")
    list_result = replies.get(2, {}).get("result")
    tools = list_result.get("tools") if isinstance(list_result, dict) else None
    if not isinstance(tools, list) or not tools:
        errors.append("MCP protocol smoke: tools/list did not return any Tools")
        return
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            errors.append(f"MCP protocol smoke: Tool #{index + 1} is not an object")
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"MCP protocol smoke: Tool #{index + 1} has no name")
            name = f"#{index + 1}"
        for field in ("title", "description"):
            value = tool.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"MCP protocol smoke: Tool {name} has no {field}")
        annotations = tool.get("annotations")
        if not isinstance(annotations, dict):
            errors.append(f"MCP protocol smoke: Tool {name} has no annotations")
        else:
            for hint in (
                "readOnlyHint",
                "destructiveHint",
                "idempotentHint",
                "openWorldHint",
            ):
                if not isinstance(annotations.get(hint), bool):
                    errors.append(
                        f"MCP protocol smoke: Tool {name} annotation {hint} must be boolean"
                    )
        input_schema = tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            errors.append(f"MCP protocol smoke: Tool {name} has no inputSchema")
        elif input_schema.get("additionalProperties") is False:
            errors.append(
                f"MCP protocol smoke: Tool {name} inputSchema rejects undeclared fields; "
                "core schemas must remain open"
            )
        if "outputSchema" in tool:
            output_schema = tool.get("outputSchema")
            if not isinstance(output_schema, dict):
                errors.append(
                    f"MCP protocol smoke: Tool {name} outputSchema must be an object when declared"
                )
            elif output_schema.get("additionalProperties") is False:
                errors.append(
                    f"MCP protocol smoke: Tool {name} outputSchema rejects undeclared fields; "
                    "optional core output schemas must remain open"
                )


def validate(candidate: Path, *, run_tests: bool = True) -> tuple[list[str], bool]:
    errors: list[str] = []
    requires_host_integration = False
    for relative in REQUIRED_FILES:
        if not (candidate / relative).is_file():
            errors.append(f"{relative}: required core-export-v1 file is missing")
    for relative in STRICT_ONLY_FILES:
        if (candidate / relative).exists():
            errors.append(
                f"{relative}: strict audit artifact is not part of core-export-v1"
            )

    test_files = sorted((candidate / "tests").rglob("*.test.mjs"))
    if not test_files:
        errors.append(
            "tests: core-export-v1 requires at least one runnable *.test.mjs file"
        )
    skill_files = discover_skill_files(candidate, errors)
    skill_names: set[str] = set()
    for skill_path in skill_files:
        skill = read_text(skill_path, errors)
        location = skill_path.relative_to(candidate)
        frontmatter = frontmatter_values(skill)
        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(description, str)
            or not description
        ):
            errors.append(
                f"{location}: frontmatter must contain non-empty string name and description"
            )
            continue
        if name.isdigit() or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
            errors.append(
                f"{location}: frontmatter name must be lowercase words separated by hyphens"
            )
        if name in skill_names:
            errors.append(f"{location}: duplicate Skill name {name!r}")
        skill_names.add(name)

    setup = read_text(candidate / "MCP-SETUP.md", errors)
    for phrase in ("npx skills add", "npm install", "MCP"):
        if phrase not in setup:
            errors.append(f"MCP-SETUP.md: must explain {phrase!r}")
    if re.search(
        r"(?:npx\s+skills\s+add|skills?\s+install(?:ation)?)"
        r".{0,100}(?:only|仅|只).{0,40}(?:skills?|技能)",
        setup,
        re.IGNORECASE | re.DOTALL,
    ) is None:
        errors.append(
            "MCP-SETUP.md: must state that skills installation only installs Skill"
        )

    package_path = candidate / "package.json"
    package: dict[str, object] = {}
    try:
        parsed = json.loads(package_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            package = parsed
        else:
            errors.append("package.json: must contain an object")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        errors.append(f"package.json: cannot parse ({error})")
    if package.get("type") != "module":
        errors.append("package.json: type must equal module")
    metadata = package.get("code2skill")
    if isinstance(metadata, dict):
        profile = metadata.get("profile")
        requires_host_integration = bool(metadata.get("requiresHostIntegration"))
    else:
        profile = None
    if profile != CORE_PROFILE:
        errors.append(f"package.json: code2skill.profile must equal {CORE_PROFILE}")
    dependencies = package.get("dependencies")
    if not isinstance(dependencies, dict):
        dependencies = {}
        errors.append("package.json: dependencies must be an object")
    for dependency in ("@modelcontextprotocol/sdk", "zod"):
        version = dependencies.get(dependency)
        if not isinstance(version, str) or version in {"", "*", "latest"}:
            errors.append(
                f"package.json: dependency {dependency} must use an explicit version range"
            )
    scripts = package.get("scripts")
    test_script = scripts.get("test") if isinstance(scripts, dict) else None
    try:
        test_tokens = shlex.split(test_script) if isinstance(test_script, str) else []
    except ValueError:
        test_tokens = []
    if (
        len(test_tokens) < 2
        or test_tokens[:2] != ["node", "--test"]
        or re.search(r"[;&|<>`\r\n]|\$\(", test_script or "") is not None
    ):
        errors.append("package.json: scripts.test must be a plain node --test command")
    if isinstance(scripts, dict) and any(
        name in scripts for name in ("pretest", "posttest")
    ):
        errors.append(
            "package.json: pretest/posttest lifecycle hooks are not allowed in a core package"
        )

    function_path = candidate / "function-core" / "index.mjs"
    adapter_path = candidate / "mcp-tool" / "index.mjs"
    result_adapter_path = candidate / "portable-agent-result.mjs"
    read_text(function_path, errors)
    read_text(adapter_path, errors)
    read_text(result_adapter_path, errors)

    for path in (function_path, adapter_path, result_adapter_path):
        if path.is_file():
            run_check(["node", "--check", str(path)], candidate, path.name, errors)
    if run_tests and package_path.is_file() and test_files:
        run_mcp_protocol_probe(candidate, errors)
        run_check(
            ["node", "--test", *(str(path) for path in test_files)],
            candidate,
            "fixed node --test",
            errors,
            environment=clean_test_environment(),
        )
    return errors, requires_host_integration


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="check structure and syntax only; never report the package as runnable",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = args.candidate.resolve()
    if not candidate.is_dir():
        print(f"ERROR: candidate directory does not exist: {candidate}", file=sys.stderr)
        return 1
    errors, requires_host_integration = validate(candidate, run_tests=not args.skip_tests)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    file_count = sum(
        1
        for path in candidate.rglob("*")
        if path.is_file() and "node_modules" not in path.relative_to(candidate).parts
    )
    if requires_host_integration:
        summary = (
            "Code2Skill core structure and MCP discovery are valid; "
            f"runtime verification is incomplete: requires-host-integration: {file_count} files"
        )
    elif args.skip_tests:
        summary = "Code2Skill core structure is valid; package tests were skipped"
    else:
        summary = (
            "Code2Skill core structure, MCP discovery, and package tests passed"
        )
    print(f"{summary}: {file_count} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
