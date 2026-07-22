#!/usr/bin/env python3
"""Validate the small default Code2Skill delivery package.

The core validator protects runtime basics without recreating the strict audit
profile. It checks a compact package shape, shared Function/MCP contracts,
JavaScript syntax, and repository-fixed offline tests. It never installs
dependencies, executes npm lifecycle hooks, or calls a business API itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


CORE_PROFILE = "core-export-v1"
REQUIRED_FILES = (
    "SKILL.md",
    "MCP-SETUP.md",
    "package.json",
    "function-core/index.mjs",
    "mcp-tool/index.mjs",
    "portable-error-normalizer.mjs",
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

REGISTER_TOOL = re.compile(
    r"server\.registerTool\(\s*(['\"])([a-z][a-z0-9_]*?)\1\s*,"
)
FUNCTION_EXPORT = re.compile(
    r"\bexport\s+async\s+function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
FUNCTION_IMPORT = re.compile(
    r"import\s*\{(?P<names>[^}]+)\}\s*from\s*['\"]\.\./function-core/index\.mjs['\"]"
)
RUNTIME_IMPORT = re.compile(
    r"import\s*\{(?P<names>[^}]+)\}\s*from\s*['\"]\.\./portable-error-normalizer\.mjs['\"]"
)
SCHEMA_DEFINITION = re.compile(
    r"\b(?:const|let)\s+([A-Za-z_$][A-Za-z0-9_$]*Schema)\s*=\s*"
    r"z\.(?:object|strictObject)\s*\("
)


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        errors.append(f"{path.name}: cannot read UTF-8 text ({error})")
        return ""


def strip_js_comments(source: str) -> str:
    """Remove comments while preserving strings used by real tests."""
    result: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            result.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def balanced_call(source: str, start: int) -> str | None:
    """Return one balanced parenthesized JavaScript call."""
    if start < 0 or start >= len(source) or source[start] != "(":
        return None
    depth = 0
    index = start
    quote: str | None = None
    escaped = False
    while index < len(source):
        char = source[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    return None


def tool_blocks(source: str, errors: list[str]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in REGISTER_TOOL.finditer(source):
        start = source.find("(", match.start())
        block = balanced_call(source, start)
        if block is None:
            errors.append(
                f"mcp-tool/index.mjs: cannot parse Tool block {match.group(2)}"
            )
        else:
            blocks.append((match.group(2), block))
    return blocks


def imported_names(pattern: re.Pattern[str], source: str) -> set[str]:
    names: set[str] = set()
    for match in pattern.finditer(source):
        names.update(
            name.strip()
            for name in match.group("names").split(",")
            if name.strip()
        )
    return names


def frontmatter_fields(text: str) -> set[str]:
    if not text.startswith("---\n"):
        return set()
    end = text.find("\n---\n", 4)
    if end < 0:
        return set()
    return {
        line.split(":", 1)[0].strip()
        for line in text[4:end].splitlines()
        if ":" in line
    }


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


def validate(candidate: Path, *, run_tests: bool = True) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (candidate / relative).is_file():
            errors.append(f"{relative}: required core-export-v1 file is missing")
    for relative in STRICT_ONLY_FILES:
        if (candidate / relative).exists():
            errors.append(
                f"{relative}: strict audit artifact is not part of core-export-v1"
            )

    test_files = sorted((candidate / "tests").glob("*.test.mjs"))
    if not test_files:
        errors.append(
            "tests: core-export-v1 requires at least one runnable *.test.mjs file"
        )
    test_code = strip_js_comments(
        "\n".join(read_text(path, errors) for path in test_files)
    )

    skill = read_text(candidate / "SKILL.md", errors)
    if not {"name", "description"}.issubset(frontmatter_fields(skill)):
        errors.append("SKILL.md: frontmatter must contain name and description")

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
    profile = metadata.get("profile") if isinstance(metadata, dict) else None
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
    if test_script not in {"node --test", "node --test tests/*.test.mjs"}:
        errors.append("package.json: scripts.test must be a plain node --test command")
    if isinstance(scripts, dict) and any(
        name in scripts for name in ("pretest", "posttest")
    ):
        errors.append(
            "package.json: pretest/posttest lifecycle hooks are not allowed in a core package"
        )

    function_path = candidate / "function-core" / "index.mjs"
    function_code = strip_js_comments(read_text(function_path, errors))
    functions = FUNCTION_EXPORT.findall(function_code)
    if not functions:
        errors.append("function-core/index.mjs: no named async Function export found")
    if len(functions) != len(set(functions)):
        errors.append("function-core/index.mjs: Function export names must be unique")
    schemas = set(SCHEMA_DEFINITION.findall(function_code))
    if "from 'zod'" not in function_code and 'from "zod"' not in function_code:
        errors.append("function-core/index.mjs: must import Zod for runtime schemas")
    if len(schemas) < 2 * len(functions):
        errors.append(
            "function-core/index.mjs: each Function needs reusable input and output Zod schemas"
        )
    parse_count = len(
        re.findall(r"\.(?:parse|parseAsync|safeParse|safeParseAsync)\s*\(", function_code)
    )
    if parse_count < 2 * len(functions):
        errors.append(
            "function-core/index.mjs: input and output schemas must execute at runtime"
        )

    adapter_path = candidate / "mcp-tool" / "index.mjs"
    adapter_code = strip_js_comments(read_text(adapter_path, errors))
    blocks = tool_blocks(adapter_code, errors)
    tools = [name for name, _block in blocks]
    if not tools:
        errors.append("mcp-tool/index.mjs: no literal server.registerTool call found")
    if len(tools) != len(set(tools)):
        errors.append("mcp-tool/index.mjs: Tool names must be unique")
    if tools and functions and len(tools) != len(functions):
        errors.append("mcp-tool/index.mjs: Tool count must match Function count")

    core_imports = imported_names(FUNCTION_IMPORT, adapter_code)
    missing_functions = sorted(set(functions) - core_imports)
    if missing_functions:
        errors.append(
            "mcp-tool/index.mjs: missing Function imports "
            + ", ".join(missing_functions)
        )
    mapped_functions: list[str] = []
    has_write = False
    for tool_name, block in blocks:
        called = [
            name
            for name in functions
            if re.search(rf"\b(?:await\s+)?{re.escape(name)}\s*\(", block)
        ]
        if len(called) != 1:
            errors.append(
                f"mcp-tool/index.mjs: Tool {tool_name} must call one public Function"
            )
        else:
            mapped_functions.append(called[0])
        for field in ("inputSchema", "outputSchema"):
            match = re.search(
                rf"\b{field}\s*:\s*([A-Za-z_$][A-Za-z0-9_$]*)", block
            )
            if match is None or match.group(1) not in schemas & core_imports:
                errors.append(
                    f"mcp-tool/index.mjs: Tool {tool_name} must reuse a Function-core Zod {field}"
                )
        for token in ("title", "description", "annotations", "normalizeToolError"):
            if token not in block:
                errors.append(f"mcp-tool/index.mjs: Tool {tool_name} is missing {token}")
        if not re.search(
            r"process\.env\.CODE2SKILL_DRY_RUN\s*===\s*['\"]1['\"]", block
        ):
            errors.append(
                f"mcp-tool/index.mjs: Tool {tool_name} needs CODE2SKILL_DRY_RUN"
            )
        for error_flag in ("false", "true"):
            if not re.search(
                rf"\btoMcpResult\s*\([^,]+,\s*{error_flag}\s*\)",
                block,
                re.DOTALL,
            ):
                errors.append(
                    f"mcp-tool/index.mjs: Tool {tool_name} must return "
                    f"toMcpResult(..., {error_flag})"
                )
        is_write = re.search(r"\breadOnlyHint\s*:\s*false\b", block) is not None
        has_write = has_write or is_write
        if is_write:
            if not re.search(
                r"\bsideEffect\s*:\s*['\"](?:create|update|delete)['\"]", block
            ):
                errors.append(
                    f"mcp-tool/index.mjs: write Tool {tool_name} needs a sideEffect policy"
                )
            if not re.search(
                r"\bautomaticRetry\s*:\s*['\"]never['\"]", block
            ):
                errors.append(
                    f"mcp-tool/index.mjs: write Tool {tool_name} must disable automatic retry"
                )
    if sorted(mapped_functions) != sorted(functions):
        errors.append("mcp-tool/index.mjs: every Function must map to exactly one Tool")

    runtime_imports = imported_names(RUNTIME_IMPORT, adapter_code)
    if not {"normalizeToolError", "toMcpResult"}.issubset(runtime_imports):
        errors.append(
            "mcp-tool/index.mjs: must import normalizeToolError and toMcpResult "
            "from the reviewed shared runtime"
        )
    for token in (
        "@modelcontextprotocol/sdk",
        "McpServer",
        "StdioServerTransport",
        "server.connect(new StdioServerTransport())",
    ):
        if token not in adapter_code:
            errors.append(f"mcp-tool/index.mjs: missing required runtime surface {token}")

    test_imports = imported_names(FUNCTION_IMPORT, test_code)
    for function_name in functions:
        if function_name not in test_imports:
            errors.append(f"tests: Function tests must import {function_name}")
    if "node:assert" not in test_code:
        errors.append("tests: runnable tests must use node:assert")
    if not re.search(r"\bassert\.(?:rejects|throws)\s*\(", test_code):
        errors.append("tests: Function tests must assert invalid input")
    for token in ("tools/list", "tools/call", "structuredContent", "isError"):
        if token not in test_code:
            errors.append(f"tests: MCP tests must exercise {token}")
    for tool_name in tools:
        if tool_name not in test_code:
            errors.append(f"tests: MCP tests must reference Tool {tool_name}")
    if has_write and "UNKNOWN_DISPATCH_OUTCOME" not in test_code:
        errors.append("tests: write capabilities must cover UNKNOWN_DISPATCH_OUTCOME")

    normalizer = candidate / "portable-error-normalizer.mjs"
    reviewed = (
        Path(__file__).resolve().parent.parent
        / "assets"
        / "portable-error-normalizer.mjs"
    )
    if normalizer.is_file() and reviewed.is_file():
        if normalizer.read_bytes() != reviewed.read_bytes():
            errors.append(
                "portable-error-normalizer.mjs: must match the reviewed shared runtime"
            )

    for path in (function_path, adapter_path):
        if path.is_file():
            run_check(["node", "--check", str(path)], candidate, path.name, errors)
    if run_tests and package_path.is_file() and test_files:
        run_check(
            ["node", "--test", *(str(path) for path in test_files)],
            candidate,
            "fixed node --test",
            errors,
            environment=clean_test_environment(),
        )
    return errors


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
    errors = validate(candidate, run_tests=not args.skip_tests)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    file_count = sum(
        1
        for path in candidate.rglob("*")
        if path.is_file() and "node_modules" not in path.relative_to(candidate).parts
    )
    tool_count = len(
        REGISTER_TOOL.findall(
            strip_js_comments(
                (candidate / "mcp-tool/index.mjs").read_text(encoding="utf-8")
            )
        )
    )
    summary = (
        "Code2Skill core export is valid and offline tests passed"
        if not args.skip_tests
        else "Code2Skill core structure is valid; package tests were skipped"
    )
    print(f"{summary}: {tool_count} tools, {file_count} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
