#!/usr/bin/env python3
"""Validate a self-contained Code2Skill strict export without dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from validate_vnext import validate_vnext_artifacts


BASE_FILES = {
    "capability-bundle.json",
    "function-core/capability-bundle.json",
    "function-core/index.mjs",
    "mcp-tool/index.mjs",
    "mcp-tool/runtime.mjs",
    "MCP.zh-CN.md",
    "PAGE.md",
    "SKILL.md",
    "capability-draft.json",
    "export-profile.json",
}
FINAL_FILES = {
    "function-core/validation-receipt.json",
    "preflight-report.json",
    "approval-audit.json",
    "live-verification.json",
    "export-manifest.json",
}
AUTHENTICATION = {"none", "cookie_session", "runtime_context", "cookie_and_runtime_context"}
INPUT_TYPES = {"string", "number", "boolean", "object", "array"}
SIDE_EFFECTS = {"read", "create", "update", "delete"}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
WORKFLOW_OWNERS = {"agent_host", "mcp_runtime", "mcp_session_runtime", "target_api"}
WORKFLOW_RETRIES = {"read_only_bounded", "not_applicable", "never"}
WORKFLOW_CONSTRAINTS = {
    "selection_tokens_same_origin",
    "attachment_tokens_from_approved_upload",
    "request_equal_to_validated_request",
    "confirmation_before_side_effect",
    "upload_confirmation_before_transfer",
    "create_at_most_once_no_retry",
}
HEX64 = re.compile(r"^[a-f0-9]{64}$")
CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
FUNCTION_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]{0,80}$")


class Diagnostics:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def warn(self, location: str, message: str) -> None:
        self.warnings.append(f"{location}: {message}")


def read_json(path: Path, diagnostics: Diagnostics, *, required: bool = True) -> Any:
    if not path.is_file():
        if required:
            diagnostics.error(path.name, "required file is missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        diagnostics.error(path.name, f"invalid JSON: {error}")
        return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nonempty(value: Any, location: str, diagnostics: Diagnostics) -> str | None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.error(location, "must be a non-empty string")
        return None
    return value


def array(value: Any, location: str, diagnostics: Diagnostics) -> list[Any]:
    if not isinstance(value, list):
        diagnostics.error(location, "must be an array")
        return []
    return value


def evidence_refs(value: Any, location: str, diagnostics: Diagnostics) -> list[str]:
    refs = array(value, location, diagnostics)
    if not refs:
        diagnostics.error(location, "must contain at least one evidence reference")
    for index, ref in enumerate(refs):
        nonempty(ref, f"{location}[{index}]", diagnostics)
    return [ref for ref in refs if isinstance(ref, str) and ref.strip()]


def validate_profile(profile: Any, diagnostics: Diagnostics) -> tuple[set[str], str, str | None]:
    if not isinstance(profile, dict):
        diagnostics.error("export-profile.json", "must be an object")
        return set(), "", None
    if profile.get("schemaVersion") != "v1" or profile.get("profile") != "strict-export-v1":
        diagnostics.error("export-profile.json", "must select strict-export-v1 schema v1")
    if profile.get("protocolVersion") != "2025-11-25":
        diagnostics.error("export-profile.protocolVersion", "must equal 2025-11-25")
    if profile.get("transport") != "stdio":
        diagnostics.error("export-profile.transport", "must equal stdio")
    if profile.get("documentationLanguage") != "zh-CN":
        diagnostics.error("export-profile.documentationLanguage", "must equal zh-CN")
    dry_run = nonempty(profile.get("dryRunEnvironmentVariable"), "export-profile.dryRunEnvironmentVariable", diagnostics) or ""
    if dry_run and not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", dry_run):
        diagnostics.error("export-profile.dryRunEnvironmentVariable", "must be a safe uppercase environment variable name")
    route = nonempty(profile.get("pageRoute"), "export-profile.pageRoute", diagnostics)
    if route and not re.fullmatch(r"/[A-Za-z0-9/_-]*", route):
        diagnostics.error("export-profile.pageRoute", "must be an absolute application route")
    origins: set[str] = set()
    for index, origin in enumerate(array(profile.get("allowedRuntimeOrigins"), "export-profile.allowedRuntimeOrigins", diagnostics)):
        text = nonempty(origin, f"export-profile.allowedRuntimeOrigins[{index}]", diagnostics)
        if not text:
            continue
        parsed = urlparse(text)
        canonical = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or text != canonical:
            diagnostics.error(f"export-profile.allowedRuntimeOrigins[{index}]", "must be an HTTP(S) origin without path, query, or credentials")
        origins.add(text)
    if not origins:
        diagnostics.error("export-profile.allowedRuntimeOrigins", "must contain at least one allowed origin")
    return origins, dry_run, route


def validate_success_rule(value: Any, location: str, kind: str, diagnostics: Diagnostics) -> list[list[str]]:
    if not isinstance(value, dict):
        diagnostics.error(location, "must be an object")
        return []
    expected = "output" if kind == "local" else "http_status_and_output"
    if value.get("kind") != expected:
        diagnostics.error(f"{location}.kind", f"must equal {expected}")
    if not isinstance(value.get("outputRequired"), bool):
        diagnostics.error(f"{location}.outputRequired", "must be boolean")
    array(value.get("forbiddenOutputKeys"), f"{location}.forbiddenOutputKeys", diagnostics)
    paths = array(value.get("requiredOutputPaths"), f"{location}.requiredOutputPaths", diagnostics)
    result: list[list[str]] = []
    for index, path in enumerate(paths):
        segments = array(path, f"{location}.requiredOutputPaths[{index}]", diagnostics)
        if not segments or any(not isinstance(segment, str) or not segment for segment in segments):
            diagnostics.error(f"{location}.requiredOutputPaths[{index}]", "must be a non-empty string path")
        else:
            if segments[0] == "data":
                diagnostics.error(
                    f"{location}.requiredOutputPaths[{index}]",
                    "must be relative to Function result.data and must not start with data",
                )
            result.append(segments)
    evidence_refs(value.get("evidenceRefs"), f"{location}.evidenceRefs", diagnostics)
    return result


def validate_bundle(bundle: Any, allowed_origins: set[str], diagnostics: Diagnostics) -> dict[str, dict[str, Any]]:
    if not isinstance(bundle, dict):
        diagnostics.error("capability-bundle.json", "must be an object")
        return {}
    if bundle.get("schemaVersion") != "v1":
        diagnostics.error("bundle.schemaVersion", "must equal v1")
    nonempty(bundle.get("recordingId"), "bundle.recordingId", diagnostics)
    server = bundle.get("server")
    if not isinstance(server, dict):
        diagnostics.error("bundle.server", "must be an object")
    else:
        name = nonempty(server.get("name"), "bundle.server.name", diagnostics)
        if name and not CAPABILITY_ID.fullmatch(name):
            diagnostics.error("bundle.server.name", "must be lower-case hyphenated")
        nonempty(server.get("description"), "bundle.server.description", diagnostics)
        evidence_refs(server.get("evidenceRefs"), "bundle.server.evidenceRefs", diagnostics)

    capabilities = array(bundle.get("capabilities"), "bundle.capabilities", diagnostics)
    if not capabilities:
        diagnostics.error("bundle.capabilities", "must contain at least one capability")
    by_id: dict[str, dict[str, Any]] = {}
    tool_names: set[str] = set()
    exports: set[str] = set()
    for index, capability in enumerate(capabilities):
        location = f"bundle.capabilities[{index}]"
        if not isinstance(capability, dict):
            diagnostics.error(location, "must be an object")
            continue
        capability_id = nonempty(capability.get("capabilityId"), f"{location}.capabilityId", diagnostics)
        tool_name = nonempty(capability.get("toolName"), f"{location}.toolName", diagnostics)
        function_export = nonempty(capability.get("functionExport"), f"{location}.functionExport", diagnostics)
        if capability_id and not CAPABILITY_ID.fullmatch(capability_id):
            diagnostics.error(f"{location}.capabilityId", "invalid capability id")
        if tool_name and not TOOL_NAME.fullmatch(tool_name):
            diagnostics.error(f"{location}.toolName", "invalid Tool name")
        if function_export and not FUNCTION_NAME.fullmatch(function_export):
            diagnostics.error(f"{location}.functionExport", "invalid JavaScript export")
        for value, seen, label in ((capability_id, by_id, "capabilityId"), (tool_name, tool_names, "toolName"), (function_export, exports, "functionExport")):
            if value and value in seen:
                diagnostics.error(f"{location}.{label}", f"duplicate {label}: {value}")
        if capability_id:
            by_id[capability_id] = capability
        if tool_name:
            tool_names.add(tool_name)
        if function_export:
            exports.add(function_export)
        nonempty(capability.get("description"), f"{location}.description", diagnostics)
        if capability.get("authentication") not in AUTHENTICATION:
            diagnostics.error(f"{location}.authentication", "invalid authentication mode")
        input_names: set[str] = set()
        for input_index, item in enumerate(array(capability.get("inputs"), f"{location}.inputs", diagnostics)):
            input_location = f"{location}.inputs[{input_index}]"
            if not isinstance(item, dict):
                diagnostics.error(input_location, "must be an object")
                continue
            name = nonempty(item.get("name"), f"{input_location}.name", diagnostics)
            nonempty(item.get("description"), f"{input_location}.description", diagnostics)
            if item.get("type") not in INPUT_TYPES:
                diagnostics.error(f"{input_location}.type", "invalid input type")
            if not isinstance(item.get("required"), bool):
                diagnostics.error(f"{input_location}.required", "must be boolean")
            evidence_refs(item.get("evidenceRefs"), f"{input_location}.evidenceRefs", diagnostics)
            if name in input_names:
                diagnostics.error(f"{input_location}.name", f"duplicate input: {name}")
            if name:
                input_names.add(name)
        implementation = capability.get("implementation")
        kind = implementation.get("kind") if isinstance(implementation, dict) else None
        if kind not in {"local", "http"}:
            diagnostics.error(f"{location}.implementation.kind", "must be local or http")
            kind = "local"
        if kind == "http":
            steps = array(implementation.get("steps"), f"{location}.implementation.steps", diagnostics)
            output_step = nonempty(implementation.get("outputStepId"), f"{location}.implementation.outputStepId", diagnostics)
            seen_steps: set[str] = set()
            for step_index, step in enumerate(steps):
                step_location = f"{location}.implementation.steps[{step_index}]"
                if not isinstance(step, dict):
                    diagnostics.error(step_location, "must be an object")
                    continue
                step_id = nonempty(step.get("stepId"), f"{step_location}.stepId", diagnostics)
                if step_id in seen_steps:
                    diagnostics.error(f"{step_location}.stepId", "duplicate step id")
                if step.get("method") not in METHODS:
                    diagnostics.error(f"{step_location}.method", "invalid HTTP method")
                if step.get("authentication") not in AUTHENTICATION:
                    diagnostics.error(f"{step_location}.authentication", "invalid authentication mode")
                url = nonempty(step.get("url"), f"{step_location}.url", diagnostics)
                if url:
                    parsed = urlparse(url)
                    origin = f"{parsed.scheme}://{parsed.netloc}"
                    if origin not in allowed_origins:
                        diagnostics.error(f"{step_location}.url", "origin is not allowlisted by export-profile.json")
                if not isinstance(step.get("headers"), dict):
                    diagnostics.error(f"{step_location}.headers", "must be an object")
                codes = array(step.get("successStatusCodes"), f"{step_location}.successStatusCodes", diagnostics)
                if not codes or any(not isinstance(code, int) or not 100 <= code <= 599 for code in codes):
                    diagnostics.error(f"{step_location}.successStatusCodes", "must contain valid HTTP status codes")
                evidence_refs(step.get("evidenceRefs"), f"{step_location}.evidenceRefs", diagnostics)
                for binding_index, binding in enumerate(array(step.get("bindings"), f"{step_location}.bindings", diagnostics)):
                    binding_location = f"{step_location}.bindings[{binding_index}]"
                    if not isinstance(binding, dict):
                        diagnostics.error(binding_location, "must be an object")
                        continue
                    source = binding.get("source")
                    if not isinstance(source, dict) or source.get("kind") not in {"input", "prior_response"}:
                        diagnostics.error(f"{binding_location}.source", "invalid source")
                    elif source["kind"] == "input" and source.get("inputName") not in input_names:
                        diagnostics.error(f"{binding_location}.source.inputName", "unknown input")
                    elif source["kind"] == "prior_response" and source.get("stepId") not in seen_steps:
                        diagnostics.error(f"{binding_location}.source.stepId", "must reference an earlier step")
                    if binding.get("location") not in {"path", "query", "body", "header", "multipart"}:
                        diagnostics.error(f"{binding_location}.location", "invalid binding location")
                    path = array(binding.get("path"), f"{binding_location}.path", diagnostics)
                    if not path:
                        diagnostics.error(f"{binding_location}.path", "must not be empty")
                if step_id:
                    seen_steps.add(step_id)
            if output_step and output_step not in seen_steps:
                diagnostics.error(f"{location}.implementation.outputStepId", "must name an existing step")
        validate_success_rule(capability.get("successRule"), f"{location}.successRule", kind, diagnostics)
        if capability.get("sideEffect") not in SIDE_EFFECTS:
            diagnostics.error(f"{location}.sideEffect", "invalid side effect")
        evidence_refs(capability.get("evidenceRefs"), f"{location}.evidenceRefs", diagnostics)

    for index, handoff in enumerate(array(bundle.get("handoffs"), "bundle.handoffs", diagnostics)):
        location = f"bundle.handoffs[{index}]"
        if not isinstance(handoff, dict):
            diagnostics.error(location, "must be an object")
            continue
        source = handoff.get("fromCapabilityId")
        target = handoff.get("toCapabilityId")
        if source not in by_id or target not in by_id or source == target:
            diagnostics.error(location, "handoff must connect two declared capabilities")
        target_inputs = {item.get("name") for item in by_id.get(target, {}).get("inputs", []) if isinstance(item, dict)}
        for mapping_index, mapping in enumerate(array(handoff.get("mappings"), f"{location}.mappings", diagnostics)):
            mapping_location = f"{location}.mappings[{mapping_index}]"
            if not isinstance(mapping, dict):
                diagnostics.error(mapping_location, "must be an object")
                continue
            if not array(mapping.get("sourcePath"), f"{mapping_location}.sourcePath", diagnostics):
                diagnostics.error(f"{mapping_location}.sourcePath", "must not be empty")
            if mapping.get("targetInput") not in target_inputs:
                diagnostics.error(f"{mapping_location}.targetInput", "must name an input of the target capability")
        if not isinstance(handoff.get("required"), bool):
            diagnostics.error(f"{location}.required", "must be boolean")
        evidence_refs(handoff.get("evidenceRefs"), f"{location}.evidenceRefs", diagnostics)
    return by_id


def chinese_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def markdown_section(text: str, heading_pattern: str, level: int = 2) -> str | None:
    match = re.search(rf"^{'#' * level}\s+.*{heading_pattern}.*$", text, re.MULTILINE)
    if not match:
        return None
    next_heading = re.search(rf"^{'#' * level}\s+", text[match.end():], re.MULTILINE)
    end = len(text) if next_heading is None else match.end() + next_heading.start()
    return text[match.end():end].strip()


def validate_documents(root: Path, profile: Any, capabilities: dict[str, dict[str, Any]], diagnostics: Diagnostics) -> None:
    tools = [item.get("toolName") for item in capabilities.values() if isinstance(item.get("toolName"), str)]
    page = (root / "PAGE.md").read_text(encoding="utf-8")
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    mcp = (root / "MCP.zh-CN.md").read_text(encoding="utf-8")
    route = profile.get("pageRoute") if isinstance(profile, dict) else None
    required_page = ["页面定位", "典型用户目标", "页面区域与业务信息", "动态依赖与失效规则", "可用 MCP 能力", "Agent 使用边界", "不属于本页面的能力", "推荐起点"]
    body_start = page.find("\n---\n", 4)
    body = page[body_start + 5:] if body_start >= 0 else page
    frontmatter = page[:body_start + 5] if body_start >= 0 else ""
    page_chinese = chinese_count(body)
    if len(body) < 800 or len(body) > 3600 or page_chinese < 300 or page_chinese > 1800:
        diagnostics.error("PAGE.md", "body must contain 800-3600 characters and 300-1800 Chinese characters")
    name_match = re.search(r"^name:\s*([a-z][a-z0-9-]{2,100})\s*$", frontmatter, re.MULTILINE)
    title_match = re.search(r"^title:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    language_match = re.search(r"^language:\s*zh-CN\s*$", frontmatter, re.MULTILINE)
    if not name_match or not language_match:
        diagnostics.error("PAGE.md", "frontmatter must contain a lower-case name and language zh-CN")
    if not title_match or not 8 <= len(title_match.group(1)) <= 80 or chinese_count(title_match.group(1)) == 0:
        diagnostics.error("PAGE.md", "frontmatter title must be 8-80 characters and contain Chinese")
    if not description_match or not 40 <= len(description_match.group(1)) <= 240 or chinese_count(description_match.group(1)) == 0:
        diagnostics.error("PAGE.md", "frontmatter description must be 40-240 characters and contain Chinese")
    for heading in required_page:
        section = markdown_section(body, re.escape(heading))
        if section is None:
            diagnostics.error("PAGE.md", f"missing section: {heading}")
        elif len(section) < 40:
            diagnostics.error("PAGE.md", f"section is too short: {heading}")
    if route and not re.search(rf"^route:\s*{re.escape(route)}\s*$", page, re.MULTILINE):
        diagnostics.error("PAGE.md", "frontmatter route must match export-profile.json")
    for tool in tools:
        if f"`{tool}`" not in page:
            diagnostics.error("PAGE.md", f"must mention Tool `{tool}`")
    writes = [item.get("toolName") for item in capabilities.values() if item.get("sideEffect") != "read"]
    if not writes:
        boundary = "\n".join(filter(None, [markdown_section(body, "页面定位"), markdown_section(body, "Agent 使用边界"), markdown_section(body, "不属于本页面的能力")]))
        if "只读" not in boundary or not re.search(r"(?:不|不得|禁止|不会).{0,40}(?:创建|修改|更新|删除|写入)", boundary, re.DOTALL):
            diagnostics.error("PAGE.md", "read-only pages must explicitly prohibit writes")
    else:
        side_effects = markdown_section(body, "副作用|确认与写入")
        if side_effects is None or chinese_count(side_effects) < 60:
            diagnostics.error("PAGE.md", "write pages need a substantive side-effect and confirmation section")
        else:
            for tool in writes:
                block = next((line for line in side_effects.splitlines() if f"`{tool}`" in line), "")
                if not block or not re.search(r"Host|宿主", block) or not re.search(r"不得|禁止|不要", block) or "重试" not in block or not re.search(r"未知|不确定", block):
                    diagnostics.error("PAGE.md", f"write Tool `{tool}` needs Host confirmation, no-retry, and unknown-outcome guidance")

    required_skill = ["定位与适用范围", "能力目录", "输入与来源", "状态与交接", "意图路由", "推荐组合", "自由组合边界", "输出组织", "失败分类与恢复", "安全与副作用", "完整调用示例", "Agent 自检清单"]
    if len(skill) < 4000 or chinese_count(skill) < 1500:
        diagnostics.error("SKILL.md", "must contain at least 4000 characters and 1500 Chinese characters")
    for heading in required_skill:
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", skill, re.MULTILINE):
            diagnostics.error("SKILL.md", f"missing canonical section: {heading}")
    if not re.search(r"dry[- ]run|试运行", skill, re.IGNORECASE):
        diagnostics.error("SKILL.md", "must document dry-run")
    for capability in capabilities.values():
        tool = capability.get("toolName")
        block = markdown_section(skill, rf"`{re.escape(tool)}`", level=3) if tool else None
        if tool and block is None:
            diagnostics.error("SKILL.md", f"missing Tool guidance heading for `{tool}`")
        elif block is not None:
            required_topics = [
                r"适用|调用时机|当用户|用于",
                r"输入|入参|无入参|空对象",
                r"输出|返回",
                r"交接|下游|传给|直接回答|独立结束|结束任务",
                r"跳过|不要|不得|无需|停止|不适用",
            ]
            if chinese_count(block) < 70 or any(not re.search(pattern, block) for pattern in required_topics):
                diagnostics.error("SKILL.md", f"Tool guidance is incomplete for `{tool}`")
            if capability.get("sideEffect") == "read" and "只读" not in block:
                diagnostics.error("SKILL.md", f"Tool guidance must classify `{tool}` as read-only")
            for path in capability.get("successRule", {}).get("requiredOutputPaths", []):
                if isinstance(path, list) and path and f"`{path[-1]}`" not in block:
                    diagnostics.error("SKILL.md", f"Tool guidance for `{tool}` must document output leaf `{path[-1]}`")
        for item in capability.get("inputs", []):
            if isinstance(item, dict):
                name = item.get("name")
                if f"`{name}`" not in skill:
                    diagnostics.error("SKILL.md", f"must document input `{name}`")
                elif block is not None and f"`{name}`" not in block:
                    diagnostics.error("SKILL.md", f"Tool guidance for `{tool}` must own input `{name}`")
                elif block is not None and not re.search(r"必填|必须|可选|条件|需要时|仅当", block):
                    diagnostics.error("SKILL.md", f"Tool guidance for `{tool}` must classify input requiredness")
    if len(re.findall(r"^###\s+示例", skill, re.MULTILINE)) < 3:
        diagnostics.error("SKILL.md", "must contain at least three complete examples")

    terms = ["MCP", "stdio", "2025-11-25", "tools/list", "tools/call", "title", "description", "inputSchema", "outputSchema", "structuredContent", "isError", "annotations", "dry-run", "入参", "出参", "错误", "示例"]
    if len(mcp) < 8000 or chinese_count(mcp) < 2000:
        diagnostics.error("MCP.zh-CN.md", "must contain at least 8000 characters and 2000 Chinese characters")
    for term in terms:
        if term not in mcp:
            diagnostics.error("MCP.zh-CN.md", f"missing required term: {term}")
    if "handoff" not in mcp and "交接" not in mcp:
        diagnostics.error("MCP.zh-CN.md", "must document handoff semantics")
    for tool in tools:
        heading = re.search(rf"^##\s+.*`{re.escape(tool)}`.*$", mcp, re.MULTILINE)
        if not heading:
            diagnostics.error("MCP.zh-CN.md", f"missing Tool section for `{tool}`")
            continue
        next_heading = re.search(r"^##\s+", mcp[heading.end():], re.MULTILINE)
        end = len(mcp) if next_heading is None else heading.end() + next_heading.start()
        block = mcp[heading.end():end]
        required_topics = [r"用途|适用|调用时机|何时调用", r"入参|无入参|空对象", r"出参|输出|structuredContent", r"HTTP|本地|0 次请求|0 HTTP", r"失败|错误|拒绝|isError", r"handoff|交接|交给|传给|独立调用|直接回答|结束", r"示例|\"name\""]
        if chinese_count(block) < 75 or any(not re.search(pattern, block, re.IGNORECASE) for pattern in required_topics):
            diagnostics.error("MCP.zh-CN.md", f"Tool call contract is incomplete for `{tool}`")
        capability = next((item for item in capabilities.values() if item.get("toolName") == tool), {})
        for item in capability.get("inputs", []):
            if isinstance(item, dict) and f"`{item.get('name')}`" not in block:
                diagnostics.error("MCP.zh-CN.md", f"Tool `{tool}` must document input `{item.get('name')}`")
        for path in capability.get("successRule", {}).get("requiredOutputPaths", []):
            if isinstance(path, list) and path and f"`{path[-1]}`" not in block:
                diagnostics.error("MCP.zh-CN.md", f"Tool `{tool}` must document output leaf `{path[-1]}`")
        if not re.search(rf'"name"\s*:\s*"{re.escape(tool)}"[\s\S]{{0,300}}"arguments"\s*:', block):
            diagnostics.error("MCP.zh-CN.md", f"Tool `{tool}` needs a literal tools/call name and arguments example")


def validate_runtime(root: Path, capabilities: dict[str, dict[str, Any]], dry_run_variable: str, diagnostics: Diagnostics) -> None:
    function_source = (root / "function-core/index.mjs").read_text(encoding="utf-8")
    mcp_source = (root / "mcp-tool/index.mjs").read_text(encoding="utf-8")
    runtime_source = (root / "mcp-tool/runtime.mjs").read_text(encoding="utf-8")
    import_specifiers = re.findall(r"\bfrom\s*['\"]([^'\"]+)['\"]|\bimport\s*\(\s*['\"]([^'\"]+)['\"]", function_source)
    import_specifiers += [(specifier, "") for specifier in re.findall(r"(?:^|;)\s*import\s*['\"]([^'\"]+)['\"]", function_source, re.MULTILINE)]
    for pair in import_specifiers:
        specifier = pair[0] or pair[1]
        if specifier and not specifier.startswith("node:"):
            diagnostics.error("function-core/index.mjs", f"Function core must be self-contained; unsupported import `{specifier}`")
    for capability in capabilities.values():
        function_export = capability.get("functionExport")
        tool_name = capability.get("toolName")
        if function_export and not re.search(rf"export\s+(?:async\s+function|const)\s+{re.escape(function_export)}\b", function_source):
            diagnostics.error("function-core/index.mjs", f"missing named export `{function_export}`")
        if tool_name and tool_name not in mcp_source:
            diagnostics.error("mcp-tool/index.mjs", f"missing Tool registration `{tool_name}`")
        if tool_name:
            registration = re.search(
                rf"\.registerTool\s*\(\s*['\"]{re.escape(tool_name)}['\"]\s*,\s*\{{([\s\S]*?)\}}\s*,\s*async\b",
                mcp_source,
            )
            if registration is None:
                diagnostics.error("mcp-tool/index.mjs", f"Tool `{tool_name}` must use a direct object config and async callback")
            else:
                config = registration.group(1)
                title_match = re.search(r"\btitle\s*:\s*['\"]([^'\"]+)['\"]", config)
                description_match = re.search(r"\bdescription\s*:\s*['\"]([^'\"]+)['\"]", config)
                title = title_match.group(1) if title_match else ""
                description = description_match.group(1) if description_match else ""
                title_parts = re.split(r"[：:]", title)
                if len(title_parts) != 2 or chinese_count(title_parts[0]) < 2 or chinese_count(title_parts[1]) < 4 or not re.search(r"列出|查询|读取|获取|搜索|检索|创建|提交|上传|校验|验证|生成|更新|删除|组合", title_parts[1]):
                    diagnostics.error("mcp-tool/index.mjs", f"Tool `{tool_name}` needs a discoverable Chinese `领域：动作对象` title")
                description_topics = [r"用于|面向", r"调用|检索前|需要|查看|构造|仅当|仅在", r"无入参|输入|入参", r"返回|输出", r"交给|传给|写入|作为|可用于|来自", r"HTTP|GET|POST|本地", r"副作用|只读|写入|创建|非幂等"]
                if len(description) < 110 or chinese_count(description) < 60 or any(not re.search(pattern, description) for pattern in description_topics):
                    diagnostics.error("mcp-tool/index.mjs", f"Tool `{tool_name}` description must cover discovery, input, output, handoff, execution, and side effects")
    http_capabilities = [
        capability for capability in capabilities.values()
        if isinstance(capability.get("implementation"), dict)
        and capability["implementation"].get("kind") == "http"
    ]
    if http_capabilities:
        if re.search(r"\b[A-Za-z_$][\w$]*\.ok\b", function_source):
            diagnostics.error("function-core/index.mjs", "HTTP Functions must compare exact declared success status codes; response.ok is too broad")
        if not re.search(r"\b[A-Za-z_$][\w$]*\.status\b", function_source):
            diagnostics.error("function-core/index.mjs", "HTTP Functions must inspect the observed response.status")
    if "structuredContent" not in mcp_source or "isError" not in mcp_source:
        diagnostics.error("mcp-tool/index.mjs", "must implement structured success and Tool execution errors")
    runtime_import = re.search(
        r"import\s*\{([^}]+)\}\s*from\s*['\"]\./runtime\.mjs['\"]",
        mcp_source,
        re.DOTALL,
    )
    imported_runtime_names = set(re.findall(r"\b(?:McpServer|StdioServerTransport|z)\b", runtime_import.group(1))) if runtime_import else set()
    if imported_runtime_names != {"McpServer", "StdioServerTransport", "z"}:
        diagnostics.error(
            "mcp-tool/index.mjs",
            "must import McpServer, StdioServerTransport, and z from the self-contained ./runtime.mjs",
        )
    if "McpServer" not in runtime_source or "StdioServerTransport" not in runtime_source or not re.search(r"\bz\b", runtime_source):
        diagnostics.error("mcp-tool/runtime.mjs", "must bundle and export the official MCP SDK and Zod runtime")
    runtime_imports = re.findall(r"\bfrom\s*['\"]([^'\"]+)['\"]|\bimport\s*['\"]([^'\"]+)['\"]", runtime_source)
    for pair in runtime_imports:
        specifier = pair[0] or pair[1]
        if specifier and not specifier.startswith("node:") and not specifier.startswith("./"):
            diagnostics.error("mcp-tool/runtime.mjs", f"bundled runtime has unresolved third-party import `{specifier}`")
    if "McpServer" not in mcp_source or "StdioServerTransport" not in mcp_source:
        diagnostics.error("mcp-tool/index.mjs", "strict-export-v1 requires McpServer and StdioServerTransport")
    literal_registrations = re.findall(r"\.registerTool\s*\(\s*['\"]([a-z][a-z0-9_]*)['\"]", mcp_source)
    expected_registrations = sorted(
        capability.get("toolName")
        for capability in capabilities.values()
        if isinstance(capability.get("toolName"), str)
    )
    if sorted(literal_registrations) != expected_registrations:
        diagnostics.error(
            "mcp-tool/index.mjs",
            "must contain exactly one literal registerTool(\"tool_name\", ...) call for every capability",
        )
    if dry_run_variable:
        dry_run_guard = rf"if\s*\(\s*process\.env\.{re.escape(dry_run_variable)}\s*===\s*['\"]1['\"]\s*\)"
        if not re.search(dry_run_guard, mcp_source):
            diagnostics.error("mcp-tool/index.mjs", "must use a literal === \"1\" guard for the configured dry-run environment variable")
        for field in ("dryRun", "validatedInput", "operationPolicy", "operationSummary"):
            if not re.search(rf"\b{field}\b", mcp_source):
                diagnostics.error("mcp-tool/index.mjs", f"dry-run result must contain `{field}`")
    if not re.search(r"process\.stdin|StdioServerTransport|stdio", mcp_source):
        diagnostics.error("mcp-tool/index.mjs", "must expose an stdio MCP runtime")


def validate_draft(
    root: Path,
    bundle: Any,
    capabilities: dict[str, dict[str, Any]],
    diagnostics: Diagnostics,
    *,
    vnext: bool = False,
) -> None:
    draft = read_json(root / "capability-draft.json", diagnostics)
    if not isinstance(draft, dict):
        return
    if draft.get("schemaVersion") != "v1":
        diagnostics.error("capability-draft.schemaVersion", "must equal v1")
    recording_id = bundle.get("recordingId") if isinstance(bundle, dict) else None
    if draft.get("recordingId") != recording_id:
        diagnostics.error("capability-draft.recordingId", "must exactly match capability-bundle.recordingId")
    allowed_statuses = {"ready", "requires-review", "blocked"} if vnext else {"ready"}
    if draft.get("status") not in allowed_statuses:
        diagnostics.error("capability-draft.status", f"must be one of {sorted(allowed_statuses)}")
    if not isinstance(draft.get("missingEvidence"), list):
        diagnostics.error("capability-draft.missingEvidence", "must be an array")
    elif not vnext and draft.get("missingEvidence") != []:
        diagnostics.error("capability-draft.missingEvidence", "must be empty; unresolved evidence blocks approval")
    for field in ("inputs", "provenance", "requestChain"):
        if not isinstance(draft.get(field), list):
            diagnostics.error(f"capability-draft.{field}", "must be an array")
    for index, item in enumerate(draft.get("inputs", [])):
        location = f"capability-draft.inputs[{index}]"
        if not isinstance(item, dict):
            diagnostics.error(location, "must be an object")
            continue
        nonempty(item.get("name"), f"{location}.name", diagnostics)
        if item.get("valueType") not in INPUT_TYPES:
            diagnostics.error(f"{location}.valueType", "must be a supported input type")
        if not isinstance(item.get("required"), bool):
            diagnostics.error(f"{location}.required", "must be boolean")
        evidence_refs(item.get("evidenceRefs"), f"{location}.evidenceRefs", diagnostics)
    for index, item in enumerate(draft.get("provenance", [])):
        location = f"capability-draft.provenance[{index}]"
        if not isinstance(item, dict):
            diagnostics.error(location, "must be an object")
            continue
        nonempty(item.get("field"), f"{location}.field", diagnostics)
        if item.get("source") not in {"provided", "context", "constant", "prior_response"}:
            diagnostics.error(f"{location}.source", "must classify provenance as provided, context, constant, or prior_response")
        nonempty(item.get("sourceDetail"), f"{location}.sourceDetail", diagnostics)
        evidence_refs(item.get("evidenceRefs"), f"{location}.evidenceRefs", diagnostics)
    for index, step in enumerate(draft.get("requestChain", [])):
        location = f"capability-draft.requestChain[{index}]"
        if not isinstance(step, dict):
            diagnostics.error(location, "must be an object")
            continue
        nonempty(step.get("stepId"), f"{location}.stepId", diagnostics)
        if not isinstance(step.get("order"), int) or step.get("order") < 0:
            diagnostics.error(f"{location}.order", "must be a non-negative integer")
        if step.get("method") not in METHODS | {"OPTIONS"}:
            diagnostics.error(f"{location}.method", "must be an HTTP method")
        evidence_refs(step.get("evidenceRefs"), f"{location}.evidenceRefs", diagnostics)
        for mapping_index, mapping in enumerate(array(step.get("inputMappings"), f"{location}.inputMappings", diagnostics)):
            mapping_location = f"{location}.inputMappings[{mapping_index}]"
            if not isinstance(mapping, dict):
                diagnostics.error(mapping_location, "must be an object")
                continue
            nonempty(mapping.get("inputName"), f"{mapping_location}.inputName", diagnostics)
            if mapping.get("target") not in {"path", "query", "header", "body", "multipart", "context"}:
                diagnostics.error(f"{mapping_location}.target", "invalid mapping target")
            nonempty(mapping.get("targetPath"), f"{mapping_location}.targetPath", diagnostics)
            evidence_refs(mapping.get("evidenceRefs"), f"{mapping_location}.evidenceRefs", diagnostics)

    # vNext provenance and rich input metadata are derived from the Canonical
    # Contract and are compared exactly by validate_vnext_artifacts().  The
    # legacy inference below intentionally knows only authentication + handoff
    # and would misclassify mixed user/Host inputs on authenticated Tools.
    if vnext:
        return

    handoffs = bundle.get("handoffs", []) if isinstance(bundle, dict) else []
    expected_inputs: list[dict[str, Any]] = []
    expected_provenance: list[dict[str, Any]] = []
    expected_steps: list[dict[str, Any]] = []
    global_order = 0
    for capability_id, capability in capabilities.items():
        tool = capability.get("toolName")
        authentication = capability.get("authentication", "")
        for item in capability.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(tool, str):
                continue
            name = item.get("name")
            qualified = f"tools.{tool}.input.{name}"
            expected_inputs.append({"name": qualified, "valueType": item.get("type"), "required": item.get("required")})
            handoff = next((candidate for candidate in handoffs if isinstance(candidate, dict) and candidate.get("toCapabilityId") == capability_id and any(
                isinstance(mapping, dict) and mapping.get("targetInput") == name for mapping in candidate.get("mappings", [])
            )), None)
            if handoff is not None:
                mapping = next(mapping for mapping in handoff.get("mappings", []) if isinstance(mapping, dict) and mapping.get("targetInput") == name)
                source_capability = capabilities.get(handoff.get("fromCapabilityId"), {})
                source_tool = source_capability.get("toolName")
                pointer = "/" + "/".join(str(segment) for segment in mapping.get("sourcePath", []))
                source = "prior_response"
                source_detail = f"prior_response:{source_tool}:{pointer}"
            else:
                source = "context" if "runtime_context" in authentication else "provided"
                source_detail = None
            expected_provenance.append({"field": qualified, "source": source, "sourceDetail": source_detail})

        implementation = capability.get("implementation", {})
        if isinstance(implementation, dict) and implementation.get("kind") == "http" and isinstance(tool, str):
            for step in implementation.get("steps", []):
                if not isinstance(step, dict):
                    continue
                mappings = []
                for binding in step.get("bindings", []):
                    if not isinstance(binding, dict) or not isinstance(binding.get("source"), dict) or binding["source"].get("kind") != "input":
                        continue
                    mappings.append({
                        "inputName": binding["source"].get("inputName"),
                        "target": binding.get("location"),
                        "targetPath": ".".join(str(segment) for segment in binding.get("path", [])),
                    })
                expected_steps.append({
                    "stepId": f"{tool}.{step.get('stepId')}",
                    "order": global_order,
                    "method": step.get("method"),
                    "urlTemplate": step.get("url"),
                    "authentication": step.get("authentication"),
                    "inputMappings": mappings,
                })
                global_order += 1

    actual_inputs = [
        {key: item.get(key) for key in ("name", "valueType", "required")}
        for item in draft.get("inputs", []) if isinstance(item, dict)
    ]
    if sorted(actual_inputs, key=lambda item: str(item.get("name"))) != sorted(expected_inputs, key=lambda item: str(item.get("name"))):
        diagnostics.error("capability-draft.inputs", "must contain exactly one qualified tools.<tool>.input.<name> record for every bundle input")
    actual_provenance = [item for item in draft.get("provenance", []) if isinstance(item, dict)]
    if len(actual_provenance) != len(expected_provenance):
        diagnostics.error("capability-draft.provenance", "must contain exactly one record for every qualified bundle input")
    for expected in expected_provenance:
        actual = next((item for item in actual_provenance if item.get("field") == expected["field"]), None)
        if actual is None or actual.get("source") != expected["source"]:
            diagnostics.error("capability-draft.provenance", f"missing canonical provenance for `{expected['field']}`")
        elif expected["sourceDetail"] is not None and actual.get("sourceDetail") != expected["sourceDetail"]:
            diagnostics.error("capability-draft.provenance", f"invalid prior_response sourceDetail for `{expected['field']}`")
        elif expected["sourceDetail"] is None and str(actual.get("sourceDetail", "")).startswith("prior_response:"):
            diagnostics.error("capability-draft.provenance", f"non-handoff input `{expected['field']}` cannot declare prior_response")

    actual_steps = []
    for step in draft.get("requestChain", []):
        if not isinstance(step, dict):
            continue
        actual_steps.append({
            key: step.get(key) for key in ("stepId", "order", "method", "urlTemplate", "authentication")
        } | {"inputMappings": [
            {key: mapping.get(key) for key in ("inputName", "target", "targetPath")}
            for mapping in step.get("inputMappings", []) if isinstance(mapping, dict)
        ]})
    if actual_steps != expected_steps:
        diagnostics.error("capability-draft.requestChain", "must be mechanically derived from every HTTP step and direct input binding in bundle order")


def validate_workflow(root: Path, capabilities: dict[str, dict[str, Any]], diagnostics: Diagnostics) -> None:
    workflow = read_json(root / "workflow.json", diagnostics)
    if not isinstance(workflow, dict):
        return
    if workflow.get("schemaVersion") != "v1" or workflow.get("kind") != "constrained-write-subgraph":
        diagnostics.error("workflow.json", "must be a v1 constrained-write-subgraph")
    workflow_id = nonempty(workflow.get("workflowId"), "workflow.workflowId", diagnostics)
    if workflow_id and not CAPABILITY_ID.fullmatch(workflow_id):
        diagnostics.error("workflow.workflowId", "must be lower-case hyphenated")
    entry = nonempty(workflow.get("entryCondition"), "workflow.entryCondition", diagnostics)
    if entry and not re.fullmatch(r"[a-z][a-z0-9_]{2,120}", entry):
        diagnostics.error("workflow.entryCondition", "must be a stable machine condition name")
    steps = array(workflow.get("steps"), "workflow.steps", diagnostics)
    if not steps:
        diagnostics.error("workflow.steps", "must contain at least one step")
    step_ids: set[str] = set()
    for index, step in enumerate(steps):
        location = f"workflow.steps[{index}]"
        if not isinstance(step, dict):
            diagnostics.error(location, "must be an object")
            continue
        step_id = nonempty(step.get("stepId"), f"{location}.stepId", diagnostics)
        if step_id in step_ids:
            diagnostics.error(f"{location}.stepId", "duplicate step id")
        if step_id:
            step_ids.add(step_id)
        capability_id = step.get("capabilityId")
        owner = step.get("owner")
        if (capability_id is None) == (owner is None):
            diagnostics.error(location, "must name exactly one capabilityId or runtime owner")
        if capability_id is not None and capability_id not in capabilities:
            diagnostics.error(f"{location}.capabilityId", "must name a declared capability")
        if owner is not None and owner not in {"agent_host", "mcp_runtime", "mcp_session_runtime", "target_api"}:
            diagnostics.error(f"{location}.owner", "invalid runtime owner")
        requires = array(step.get("requires"), f"{location}.requires", diagnostics)
        if not requires:
            diagnostics.error(f"{location}.requires", "must declare at least one enforced condition")
        retry = step.get("retry")
        if retry not in WORKFLOW_RETRIES:
            diagnostics.error(f"{location}.retry", "invalid retry policy")
        if retry == "never" and step.get("maxAttempts") != 1:
            diagnostics.error(f"{location}.maxAttempts", "never retry requires maxAttempts=1")
        if retry != "never" and "maxAttempts" in step:
            diagnostics.error(f"{location}.maxAttempts", "only never retry may set maxAttempts")
    bindings = array(workflow.get("bindings"), "workflow.bindings", diagnostics)
    if not bindings:
        diagnostics.error("workflow.bindings", "must bind validation, confirmation, and write state")
    for index, binding in enumerate(bindings):
        location = f"workflow.bindings[{index}]"
        if not isinstance(binding, dict):
            diagnostics.error(location, "must be an object")
            continue
        nonempty(binding.get("from"), f"{location}.from", diagnostics)
        nonempty(binding.get("to"), f"{location}.to", diagnostics)
        if "constraint" in binding and binding.get("constraint") not in {"canonical_equal", "equal"}:
            diagnostics.error(f"{location}.constraint", "must be canonical_equal or equal")
    enforcement = array(workflow.get("enforcement"), "workflow.enforcement", diagnostics)
    if not enforcement:
        diagnostics.error("workflow.enforcement", "must contain runtime-owned enforcement")
    seen_constraints: set[str] = set()
    for index, item in enumerate(enforcement):
        location = f"workflow.enforcement[{index}]"
        if not isinstance(item, dict):
            diagnostics.error(location, "must be an object")
            continue
        constraint = item.get("constraint")
        if constraint not in WORKFLOW_CONSTRAINTS:
            diagnostics.error(f"{location}.constraint", "invalid constrained-workflow rule")
        if constraint in seen_constraints:
            diagnostics.error(f"{location}.constraint", "duplicate constrained-workflow rule")
        if isinstance(constraint, str):
            seen_constraints.add(constraint)
        owners = array(item.get("owners"), f"{location}.owners", diagnostics)
        if not owners:
            diagnostics.error(f"{location}.owners", "must name an enforcement owner")
        for owner_value in owners:
            if owner_value not in WORKFLOW_OWNERS and not (isinstance(owner_value, str) and re.fullmatch(r"function:[a-z][a-z0-9-]{2,80}", owner_value)):
                diagnostics.error(f"{location}.owners", f"invalid enforcement owner: {owner_value}")
    nonempty(workflow.get("unknownOutcomePolicy"), "workflow.unknownOutcomePolicy", diagnostics)


def _validate_preflight_checks(
    value: Any,
    *,
    vnext: bool,
    diagnostics: Diagnostics,
) -> bool:
    if not isinstance(value, list) or not value:
        return False
    valid = True
    for index, item in enumerate(value):
        location = f"preflight-report.checks[{index}]"
        if not isinstance(item, dict):
            diagnostics.error(location, "must be an executed check object")
            valid = False
            continue
        if item.get("status") != "passed":
            diagnostics.error(f"{location}.status", "must be passed")
            valid = False
        if not isinstance(item.get("command"), str) or not item["command"].strip():
            diagnostics.error(f"{location}.command", "must record a non-empty executed command")
            valid = False
        if vnext:
            exit_code = item.get("exitCode")
            if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0:
                diagnostics.error(f"{location}.exitCode", "a passed vNext check must have exitCode=0")
                valid = False
            evidence_digest = item.get("evidenceHash", item.get("sha256"))
            if not isinstance(evidence_digest, str) or not HEX64.fullmatch(evidence_digest):
                diagnostics.error(
                    f"{location}.evidenceHash",
                    "must contain a SHA-256 evidenceHash or sha256 digest",
                )
                valid = False
    return valid


def _validate_vnext_live_matrix(
    canonical: dict[str, Any],
    matrix: dict[str, Any],
    live: Any,
    diagnostics: Diagnostics,
) -> None:
    if (
        not isinstance(live, dict)
        or live.get("schemaVersion") != "vNext"
        or live.get("status") not in {"passed", "partial"}
        or not HEX64.fullmatch(str(live.get("inputHash", "")))
        or not HEX64.fullmatch(str(live.get("resultHash", "")))
        or not isinstance(live.get("capabilities"), list)
    ):
        diagnostics.error(
            "live-verification.json",
            "must record capability-scoped vNext live evidence with SHA-256 hashes",
        )
        return

    canonical_ids = {
        item.get("capabilityId")
        for item in canonical.get("capabilities", [])
        if isinstance(item, dict)
    }
    canonical_by_id = {
        item.get("capabilityId"): item
        for item in canonical.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    seen_ids: set[str] = set()
    successful_ids: set[str] = set()
    live_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(live["capabilities"]):
        location = f"live-verification.capabilities[{index}]"
        if not isinstance(item, dict):
            diagnostics.error(location, "must be an object")
            continue
        capability_id = item.get("capabilityId")
        unique_canonical_id = capability_id in canonical_ids and capability_id not in seen_ids
        if not unique_canonical_id:
            diagnostics.error(f"{location}.capabilityId", "must uniquely name a canonical capability")
        if isinstance(capability_id, str):
            seen_ids.add(capability_id)
        status = item.get("status")
        if status not in {"passed", "failed"}:
            diagnostics.error(f"{location}.status", "must be passed or failed")
        if not HEX64.fullmatch(str(item.get("inputHash", ""))) or not HEX64.fullmatch(str(item.get("resultHash", ""))):
            diagnostics.error(location, "must contain SHA-256 input and result hashes")
        if status == "passed":
            if item.get("isError") is not False:
                diagnostics.error(f"{location}.isError", "passed live evidence must record isError=false")
            elif unique_canonical_id and isinstance(capability_id, str):
                successful_ids.add(capability_id)
        if unique_canonical_id and isinstance(capability_id, str):
            live_by_id[capability_id] = item

    expected_live_status = "passed" if successful_ids == canonical_ids else "partial"
    if live.get("status") != expected_live_status:
        diagnostics.error(
            "live-verification.status",
            "must be derived from successful live coverage of every canonical capability",
        )

    rows = matrix.get("capabilities", [])
    if not isinstance(rows, list):
        return
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if (
            isinstance(status, dict)
            and status.get("runtimeVerified") is True
        ):
            capability_id = row.get("capabilityId")
            location = f"verification-matrix.capabilities[{index}]"
            if capability_id not in successful_ids:
                diagnostics.error(
                    f"{location}.status.runtimeVerified",
                    "requires successful live evidence for the same capabilityId",
                )
                continue
            canonical_capability = canonical_by_id.get(capability_id, {})
            tool_name = canonical_capability.get("toolName")
            live_item = live_by_id.get(capability_id, {})
            checks = row.get("checks") if isinstance(row.get("checks"), list) else []
            if not any(
                isinstance(check, dict)
                and check.get("phase") == "runtime"
                and check.get("status") == "passed"
                and check.get("toolName") == tool_name
                and check.get("inputHash") == live_item.get("inputHash")
                and check.get("resultHash") == live_item.get("resultHash")
                for check in checks
            ):
                diagnostics.error(
                    f"{location}.checks",
                    "runtime verification needs an executed runtime check bound to this Tool's live input/result hashes",
                )

    workflow_rows = matrix.get("workflows", [])
    workflows = {
        item.get("workflowId"): item
        for item in canonical.get("workflows", [])
        if isinstance(item, dict) and isinstance(item.get("workflowId"), str)
    }
    if not isinstance(workflow_rows, list):
        return
    for index, row in enumerate(workflow_rows):
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if not isinstance(status, dict) or status.get("runtimeVerified") is not True:
            continue
        location = f"verification-matrix.workflows[{index}]"
        workflow = workflows.get(row.get("workflowId"), {})
        entry_id = workflow.get("entryCapabilityId")
        live_item = live_by_id.get(entry_id, {})
        tool_name = canonical_by_id.get(entry_id, {}).get("toolName")
        checks = row.get("checks") if isinstance(row.get("checks"), list) else []
        if entry_id not in successful_ids or not any(
            isinstance(check, dict)
            and check.get("phase") == "runtime"
            and check.get("status") == "passed"
            and check.get("toolName") == tool_name
            and check.get("inputHash") == live_item.get("inputHash")
            and check.get("resultHash") == live_item.get("resultHash")
            for check in checks
        ):
            diagnostics.error(
                f"{location}.checks",
                "workflow runtime verification needs a runtime check bound to its entry Tool's live evidence",
            )


def validate_finalization(root: Path, diagnostics: Diagnostics) -> None:
    receipt = read_json(root / "function-core/validation-receipt.json", diagnostics)
    preflight = read_json(root / "preflight-report.json", diagnostics)
    approval = read_json(root / "approval-audit.json", diagnostics)
    live = read_json(root / "live-verification.json", diagnostics)
    manifest = read_json(root / "export-manifest.json", diagnostics)
    bundle_hash = sha256(root / "capability-bundle.json")
    draft_hash = sha256(root / "capability-draft.json")
    vnext = (root / "canonical-contract.json").is_file()
    canonical = read_json(root / "canonical-contract.json", diagnostics) if vnext else None
    if isinstance(receipt, dict):
        if receipt.get("bundleHash") != bundle_hash or receipt.get("capabilityDraftHash") != draft_hash:
            diagnostics.error("function-core/validation-receipt.json", "bundle and draft hashes must match current files")
        if isinstance(canonical, dict):
            if receipt.get("contractId") != canonical.get("contractId"):
                diagnostics.error("function-core/validation-receipt.json", "contractId must match canonical-contract.json")
            if receipt.get("canonicalContractHash") != sha256(root / "canonical-contract.json"):
                diagnostics.error("function-core/validation-receipt.json", "canonical contract hash must match current file")
    preflight_checks_valid = isinstance(preflight, dict) and _validate_preflight_checks(
        preflight.get("checks"),
        vnext=vnext,
        diagnostics=diagnostics,
    )
    if not isinstance(preflight, dict) or preflight.get("status") != "passed" or not preflight_checks_valid:
        diagnostics.error("preflight-report.json", "must record a fully passed preflight")
    elif preflight.get("bundleHash") != bundle_hash or preflight.get("capabilityDraftHash") != draft_hash:
        diagnostics.error("preflight-report.json", "bundle and draft hashes must match current files")
    if vnext:
        allowed_decisions = {"approved", "partially-approved", "requires-review", "blocked"}
        if (
            not isinstance(approval, dict)
            or approval.get("decision") not in allowed_decisions
            or approval.get("preflightStatus") != "passed"
            or not approval.get("artifacts")
        ):
            diagnostics.error(
                "approval-audit.json",
                "must honestly summarize a passed vNext preflight and enumerate artifacts",
            )
        matrix = read_json(root / "verification-matrix.json", diagnostics)
        if isinstance(approval, dict) and isinstance(matrix, dict):
            def item_decision(item: Any) -> str:
                status = item.get("status", {}) if isinstance(item, dict) else {}
                if status.get("blocked") is True:
                    return "blocked"
                if status.get("requiresReview") is True:
                    return "requires-review"
                return "approved"

            expected_capabilities = [
                {"capabilityId": item.get("capabilityId"), "decision": item_decision(item)}
                for item in matrix.get("capabilities", [])
                if isinstance(item, dict)
            ]
            expected_workflows = [
                {"workflowId": item.get("workflowId"), "decision": item_decision(item)}
                for item in matrix.get("workflows", [])
                if isinstance(item, dict)
            ]
            decisions = [item["decision"] for item in expected_capabilities + expected_workflows]
            if decisions and all(item == "approved" for item in decisions):
                expected_overall = "approved"
            elif "approved" in decisions:
                expected_overall = "partially-approved"
            elif "requires-review" in decisions:
                expected_overall = "requires-review"
            else:
                expected_overall = "blocked"
            if approval.get("capabilities") != expected_capabilities:
                diagnostics.error("approval-audit.capabilities", "must be derived exactly from capability verification states")
            if approval.get("workflows") != expected_workflows:
                diagnostics.error("approval-audit.workflows", "must be derived exactly from workflow verification states")
            if approval.get("decision") != expected_overall:
                diagnostics.error("approval-audit.decision", "must be derived from every capability and workflow decision")
        if isinstance(canonical, dict):
            _validate_vnext_live_matrix(
                canonical,
                matrix if isinstance(matrix, dict) else {},
                live,
                diagnostics,
            )
    else:
        if not isinstance(approval, dict) or approval.get("decision") != "approved" or approval.get("preflightStatus") != "passed" or not approval.get("artifacts"):
            diagnostics.error("approval-audit.json", "must approve a passed preflight and enumerate artifacts")
        if not isinstance(live, dict) or live.get("status") != "passed" or live.get("isError") is not False or not HEX64.fullmatch(str(live.get("inputHash", ""))) or not HEX64.fullmatch(str(live.get("resultHash", ""))):
            diagnostics.error("live-verification.json", "must record a real successful invocation with SHA-256 input/result hashes")
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != "v0" or not isinstance(manifest.get("files"), list):
        diagnostics.error("export-manifest.json", "must be a v0 file manifest")
        return
    declared: set[str] = set()
    for index, item in enumerate(manifest["files"]):
        location = f"export-manifest.files[{index}]"
        if not isinstance(item, dict):
            diagnostics.error(location, "must be an object")
            continue
        relative = item.get("relativePath")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
            diagnostics.error(f"{location}.relativePath", "unsafe relative path")
            continue
        path = root / relative
        if relative in declared or not path.is_file() or item.get("sha256") != sha256(path) or item.get("sanitized") is not True:
            diagnostics.error(location, "must uniquely describe the current sanitized file")
        declared.add(relative)
    expected = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path.name != "export-manifest.json"}
    if declared != expected:
        diagnostics.error("export-manifest.files", "must cover every candidate file except export-manifest.json exactly once")


def validate(
    root: Path,
    source_root: Path,
    pre_finalize: bool,
    diagnostics: Diagnostics,
    source_maps: dict[str, Path] | None = None,
) -> dict[str, Any] | None:
    required = BASE_FILES if pre_finalize else BASE_FILES | FINAL_FILES
    for relative in sorted(required):
        if not (root / relative).is_file():
            diagnostics.error(relative, "required strict-export-v1 artifact is missing")
    if diagnostics.errors:
        return None
    profile = read_json(root / "export-profile.json", diagnostics)
    allowed_origins, dry_run, _ = validate_profile(profile, diagnostics)
    bundle = read_json(root / "capability-bundle.json", diagnostics)
    mirrored = read_json(root / "function-core/capability-bundle.json", diagnostics)
    if bundle != mirrored:
        diagnostics.error("function-core/capability-bundle.json", "must exactly mirror capability-bundle.json")
    capabilities = validate_bundle(bundle, allowed_origins, diagnostics)
    vnext = (root / "canonical-contract.json").is_file()
    validate_draft(root, bundle, capabilities, diagnostics, vnext=vnext)
    validate_runtime(root, capabilities, dry_run, diagnostics)
    validate_documents(root, profile, capabilities, diagnostics)
    has_writes = any(capability.get("sideEffect") != "read" for capability in capabilities.values())
    if vnext:
        if (root / "workflow.json").exists():
            diagnostics.error(
                "workflow.json",
                "vNext hard workflows live only in canonical-contract.json; a second hand-maintained workflow is forbidden",
            )
    elif has_writes:
        if not (root / "workflow.json").is_file():
            diagnostics.error("workflow.json", "required when any capability has a write side effect")
        else:
            validate_workflow(root, capabilities, diagnostics)
    elif (root / "workflow.json").exists():
        diagnostics.warn("workflow.json", "read-only bundles usually do not need a constrained write workflow")
    if vnext:
        validate_vnext_artifacts(
            root,
            source_root,
            source_maps or {},
            pre_finalize,
            diagnostics,
        )
    if not pre_finalize:
        validate_finalization(root, diagnostics)
    return bundle if isinstance(bundle, dict) else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--source-map",
        action="append",
        default=[],
        metavar="SOURCE_ID=PATH",
        help="repeat for each explicitly authorized vNext source root",
    )
    parser.add_argument("--pre-finalize", action="store_true", help="validate generation before audit files are finalized")
    return parser.parse_args()


def parse_source_maps(values: list[str], diagnostics: Diagnostics) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for index, value in enumerate(values):
        if "=" not in value:
            diagnostics.error(f"--source-map[{index}]", "must use SOURCE_ID=PATH")
            continue
        source_id, raw_path = value.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,80}", source_id):
            diagnostics.error(f"--source-map[{index}]", "has an invalid source ID")
            continue
        if not raw_path:
            diagnostics.error(f"--source-map[{index}]", "must include a path")
            continue
        if not Path(raw_path).is_absolute():
            diagnostics.error(f"--source-map[{index}]", "path must be absolute")
            continue
        if source_id in result:
            diagnostics.error(f"--source-map[{index}]", f"duplicate source ID `{source_id}`")
            continue
        result[source_id] = Path(raw_path).resolve()
    return result


def main() -> int:
    args = parse_args()
    diagnostics = Diagnostics()
    source_maps = parse_source_maps(args.source_map, diagnostics)
    bundle = validate(
        args.artifact_root.resolve(),
        args.source_root.resolve(),
        args.pre_finalize,
        diagnostics,
        source_maps,
    )
    for warning in diagnostics.warnings:
        print(f"WARNING {warning}")
    for error in diagnostics.errors:
        print(f"ERROR {error}", file=sys.stderr)
    if diagnostics.errors:
        print(f"Code2Skill strict export is invalid: {len(diagnostics.errors)} error(s).", file=sys.stderr)
        return 1
    count = len(bundle.get("capabilities", [])) if isinstance(bundle, dict) else 0
    phase = "pre-finalization" if args.pre_finalize else "final"
    print(f"Code2Skill strict export is valid ({phase}): {count} capability/capabilities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
