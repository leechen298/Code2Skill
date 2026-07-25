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

from contract_model import operation_summary_for_capability
from validate_vnext import validate_vnext_artifacts


COMMON_BASE_FILES = {
    "capability-bundle.json",
    "function-core/capability-bundle.json",
    "function-core/index.mjs",
    "mcp-tool/index.mjs",
    "mcp-tool/runtime.mjs",
    "MCP.zh-CN.md",
    "SKILL.md",
    "capability-draft.json",
    "export-profile.json",
}
LEGACY_BASE_FILES = COMMON_BASE_FILES | {"PAGE.md"}
VNEXT_BASE_FILES = COMMON_BASE_FILES | {
    "MCP-SETUP.md",
    "references/feature-context.md",
    "function-core/schema-contract.json",
    "mcp-tool/schema-contract.json",
    "references/capability-contracts.json",
    "portable-error-normalizer.mjs",
}
# Public compatibility alias: new callers should treat vNext as the default
# strict-export shape.  Legacy validation selects LEGACY_BASE_FILES explicitly.
BASE_FILES = VNEXT_BASE_FILES
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
FEATURE_SURFACE_KINDS = {"route", "backend-api", "rpc", "message", "worker", "other"}
AGENT_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_REVIEWED_NORMALIZER_SHA256 = (
    "e131b01caeae3f32fe4fabead64652a156c9aa8fbcdf2bdddf01de22611a4e23"
)


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


def _parse_http_origin(value: str, *, origin_only: bool = False) -> tuple[str | None, str | None]:
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        # Accessing port also rejects malformed or out-of-range ports.
        _ = parsed.port
    except ValueError:
        return None, "must be a valid HTTP(S) URL"
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not hostname:
        return None, "must be a valid HTTP(S) URL"
    if parsed.username is not None or parsed.password is not None:
        return None, "must not contain embedded credentials"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin_only and value != origin:
        return None, "must be an HTTP(S) origin without path, query, fragment, or credentials"
    return origin, None


def validate_profile(
    profile: Any,
    diagnostics: Diagnostics,
    *,
    vnext: bool = False,
) -> tuple[set[str], str, str | None]:
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
    route: str | None = None
    if vnext:
        if "pageRoute" in profile:
            diagnostics.error(
                "export-profile.pageRoute",
                "is a legacy-only field and must not be reintroduced into a vNext export",
            )
        surface = profile.get("featureSurface")
        if not isinstance(surface, dict):
            diagnostics.error("export-profile.featureSurface", "must be an object for vNext exports")
        else:
            if surface.get("kind") not in FEATURE_SURFACE_KINDS:
                diagnostics.error(
                    "export-profile.featureSurface.kind",
                    f"must be one of {sorted(FEATURE_SURFACE_KINDS)}",
                )
            identifier = nonempty(
                surface.get("identifier"),
                "export-profile.featureSurface.identifier",
                diagnostics,
            )
            if identifier and (len(identifier) > 256 or "\n" in identifier or "\r" in identifier):
                diagnostics.error(
                    "export-profile.featureSurface.identifier",
                    "must be a stable single-line identifier of at most 256 characters",
                )
            if surface.get("kind") == "route" and identifier and not identifier.startswith("/"):
                diagnostics.error(
                    "export-profile.featureSurface.identifier",
                    "route feature surfaces must use an absolute application route",
                )
    else:
        route = nonempty(profile.get("pageRoute"), "export-profile.pageRoute", diagnostics)
        if route and not re.fullmatch(r"/[A-Za-z0-9/_-]*", route):
            diagnostics.error("export-profile.pageRoute", "must be an absolute application route")
    origins: set[str] = set()
    for index, origin in enumerate(array(profile.get("allowedRuntimeOrigins"), "export-profile.allowedRuntimeOrigins", diagnostics)):
        text = nonempty(origin, f"export-profile.allowedRuntimeOrigins[{index}]", diagnostics)
        if not text:
            continue
        _, origin_error = _parse_http_origin(text, origin_only=True)
        if origin_error:
            diagnostics.error(
                f"export-profile.allowedRuntimeOrigins[{index}]",
                "must be an HTTP(S) origin without path, query, or credentials",
            )
        origins.add(text)
    if not origins and not vnext:
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
        if isinstance(implementation, dict):
            allowed_implementation_fields = (
                {"kind", "steps", "outputStepId"}
                if kind == "http"
                else {"kind"}
            )
            unexpected_implementation_fields = set(implementation) - allowed_implementation_fields
            if unexpected_implementation_fields:
                diagnostics.error(
                    f"{location}.implementation",
                    "contains unsupported Runtime/Host extension fields: "
                    + ", ".join(sorted(unexpected_implementation_fields)),
                )
        if kind == "http":
            steps = array(implementation.get("steps"), f"{location}.implementation.steps", diagnostics)
            output_step = nonempty(implementation.get("outputStepId"), f"{location}.implementation.outputStepId", diagnostics)
            seen_steps: set[str] = set()
            for step_index, step in enumerate(steps):
                step_location = f"{location}.implementation.steps[{step_index}]"
                if not isinstance(step, dict):
                    diagnostics.error(step_location, "must be an object")
                    continue
                unexpected_step_fields = set(step) - {
                    "stepId",
                    "method",
                    "authentication",
                    "url",
                    "headers",
                    "bindings",
                    "successStatusCodes",
                    "evidenceRefs",
                }
                if unexpected_step_fields:
                    diagnostics.error(
                        step_location,
                        "contains unsupported Runtime/Host extension fields: "
                        + ", ".join(sorted(unexpected_step_fields)),
                    )
                step_id = nonempty(step.get("stepId"), f"{step_location}.stepId", diagnostics)
                if step_id in seen_steps:
                    diagnostics.error(f"{step_location}.stepId", "duplicate step id")
                if step.get("method") not in METHODS:
                    diagnostics.error(f"{step_location}.method", "invalid HTTP method")
                if step.get("authentication") not in AUTHENTICATION:
                    diagnostics.error(f"{step_location}.authentication", "invalid authentication mode")
                url = nonempty(step.get("url"), f"{step_location}.url", diagnostics)
                if url:
                    origin, origin_error = _parse_http_origin(url)
                    if origin_error:
                        diagnostics.error(
                            f"{step_location}.url",
                            "must be an HTTP(S) URL without embedded credentials",
                        )
                    elif origin not in allowed_origins:
                        diagnostics.error(f"{step_location}.url", "origin is not allowlisted by export-profile.json")
                if not isinstance(step.get("headers"), dict):
                    diagnostics.error(f"{step_location}.headers", "must be an object")
                codes = array(step.get("successStatusCodes"), f"{step_location}.successStatusCodes", diagnostics)
                if not codes or any(not isinstance(code, int) or not 100 <= code <= 599 for code in codes):
                    diagnostics.error(f"{step_location}.successStatusCodes", "must contain valid HTTP status codes")
                evidence_refs(step.get("evidenceRefs"), f"{step_location}.evidenceRefs", diagnostics)
                binding_targets: list[tuple[str, tuple[str, ...], str]] = []
                for binding_index, binding in enumerate(array(step.get("bindings"), f"{step_location}.bindings", diagnostics)):
                    binding_location = f"{step_location}.bindings[{binding_index}]"
                    if not isinstance(binding, dict):
                        diagnostics.error(binding_location, "must be an object")
                        continue
                    unexpected_binding_fields = set(binding) - {
                        "source",
                        "location",
                        "path",
                        "evidenceRefs",
                    }
                    if unexpected_binding_fields:
                        diagnostics.error(
                            binding_location,
                            "contains unsupported binding fields: "
                            + ", ".join(sorted(unexpected_binding_fields)),
                        )
                    source = binding.get("source")
                    if not isinstance(source, dict) or source.get("kind") not in {
                        "input",
                        "prior_response",
                        "host_resolved_attachment",
                    }:
                        diagnostics.error(f"{binding_location}.source", "invalid source")
                    elif source["kind"] in {"input", "host_resolved_attachment"} and source.get("inputName") not in input_names:
                        diagnostics.error(f"{binding_location}.source.inputName", "unknown input")
                    elif source["kind"] == "host_resolved_attachment" and source.get("requirementId") != "attachment-resolution":
                        diagnostics.error(
                            f"{binding_location}.source.requirementId",
                            "Host-resolved attachments must use the generic attachment-resolution requirement",
                        )
                    elif source["kind"] == "prior_response" and source.get("stepId") not in seen_steps:
                        diagnostics.error(f"{binding_location}.source.stepId", "must reference an earlier step")
                    if isinstance(source, dict) and source.get("kind") in {
                        "input",
                        "prior_response",
                        "host_resolved_attachment",
                    }:
                        allowed_source_fields = {
                            "input": {"kind", "inputName"},
                            "prior_response": {"kind", "stepId", "path"},
                            "host_resolved_attachment": {"kind", "inputName", "requirementId"},
                        }[source["kind"]]
                        unexpected_source_fields = set(source) - allowed_source_fields
                        if unexpected_source_fields:
                            diagnostics.error(
                                f"{binding_location}.source",
                                "contains unsupported source fields: "
                                + ", ".join(sorted(unexpected_source_fields)),
                            )
                    if binding.get("location") not in {"path", "query", "body", "header", "multipart"}:
                        diagnostics.error(f"{binding_location}.location", "invalid binding location")
                    path = array(binding.get("path"), f"{binding_location}.path", diagnostics)
                    if not path:
                        diagnostics.error(f"{binding_location}.path", "must not be empty")
                    elif any(not isinstance(segment, str) or not segment for segment in path):
                        diagnostics.error(
                            f"{binding_location}.path",
                            "must contain only non-empty string segments",
                        )
                    elif binding.get("location") in {"path", "query", "body", "header", "multipart"}:
                        location_name = binding["location"]
                        target_path = tuple(path)
                        for previous_location, previous_path, previous_binding_location in binding_targets:
                            paths_overlap = (
                                previous_path[: len(target_path)] == target_path
                                or target_path[: len(previous_path)] == previous_path
                            )
                            if previous_location == location_name and paths_overlap:
                                diagnostics.error(
                                    binding_location,
                                    "request binding target must not equal, contain, or be contained by another binding target "
                                    f"in the same step ({previous_binding_location})",
                                )
                        binding_targets.append((location_name, target_path, binding_location))
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


def validate_vnext_runtime_contract(
    canonical: Any,
    allowed_origins: set[str],
    diagnostics: Diagnostics,
) -> set[str]:
    """Validate runtime properties that must be derived from the Canonical Contract."""
    if not isinstance(canonical, dict):
        return set()
    expected_origins: set[str] = set()
    capabilities = canonical.get("capabilities")
    if not isinstance(capabilities, list):
        return expected_origins
    for capability_index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            continue
        location = f"canonical-contract.capabilities[{capability_index}]"
        implementation = capability.get("implementation")
        kind = implementation.get("kind") if isinstance(implementation, dict) else None
        annotations = capability.get("annotations")
        open_world = annotations.get("openWorldHint") if isinstance(annotations, dict) else None
        if kind in {"http", "local"} and open_world is not (kind == "http"):
            diagnostics.error(
                f"{location}.annotations.openWorldHint",
                f"must be {'true' if kind == 'http' else 'false'} for {kind} capabilities",
            )
        if kind != "http" or not isinstance(implementation, dict):
            continue
        steps = implementation.get("steps")
        if not isinstance(steps, list):
            continue
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("url"), str):
                continue
            url = step["url"]
            step_location = f"{location}.implementation.steps[{step_index}].url"
            origin, origin_error = _parse_http_origin(url)
            if origin_error:
                diagnostics.error(
                    step_location,
                    "must be an HTTP(S) URL without embedded credentials",
                )
                continue
            if origin is not None:
                expected_origins.add(origin)
    if allowed_origins != expected_origins:
        diagnostics.error(
            "export-profile.allowedRuntimeOrigins",
            "must exactly equal all HTTP(S) origins used by Canonical HTTP steps; "
            f"expected {sorted(expected_origins)}",
        )
    return expected_origins


def chinese_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def markdown_section(text: str, heading_pattern: str, level: int = 2) -> str | None:
    match = re.search(rf"^{'#' * level}\s+.*{heading_pattern}.*$", text, re.MULTILINE)
    if not match:
        return None
    next_heading = re.search(rf"^{'#' * level}\s+", text[match.end():], re.MULTILINE)
    end = len(text) if next_heading is None else match.end() + next_heading.start()
    return text[match.end():end].strip()


def markdown_frontmatter(text: str, location: str, diagnostics: Diagnostics) -> tuple[dict[str, str], str]:
    match = re.match(r"\A---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|\Z)", text)
    if match is None:
        diagnostics.error(location, "must start with YAML frontmatter")
        return {}, text
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values, text[match.end():]


def _path_label(value: Any) -> str | None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        return None
    return ".".join(value)


def _validate_document_contract_binding(root: Path, diagnostics: Diagnostics) -> None:
    relative = "references/capability-contracts.json"
    contract_path = root / relative
    if not contract_path.is_file():
        diagnostics.error(relative, "is required as the Canonical-derived documentation fact surface")
        return
    digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    marker = f"<!-- code2skill-capability-contract-sha256:{digest} -->"
    for document in ("SKILL.md", "MCP.zh-CN.md", "references/feature-context.md"):
        path = root / document
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            diagnostics.error(
                document,
                "must carry the exact SHA-256 marker for the current Canonical-derived capability contract",
            )
        if relative not in text:
            diagnostics.error(
                document,
                f"must name `{relative}` as the authoritative machine-readable business contract",
            )


def _validate_document_contract_restatements(
    text: str,
    capabilities: dict[str, dict[str, Any]],
    location: str,
    diagnostics: Diagnostics,
) -> None:
    """Reject common prose claims that invert Canonical requiredness/policy.

    Full types, domains, sources, freshness, policies, and evidence remain exact
    in references/capability-contracts.json. Prose may explain why information
    is needed but must not restate a contradictory contract.
    """

    for capability in capabilities.values():
        tool_name = capability.get("toolName")
        for item in capability.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            input_name = item["name"]
            relevant_lines = [
                line
                for line in text.splitlines()
                if re.search(
                    rf"(?<![A-Za-z0-9_$]){re.escape(input_name)}(?![A-Za-z0-9_$])",
                    line,
                )
            ]
            for line in relevant_lines:
                if item.get("required") is True and re.search(
                    r"可选|非必填|无需提供|optional",
                    line,
                    re.IGNORECASE,
                ):
                    diagnostics.error(
                        location,
                        f"input `{input_name}` is Canonically required and must not be described as optional",
                    )
                if (
                    item.get("required") is not True
                    and not item.get("requiredWhen")
                    and re.search(r"必填|必须提供|\brequired\b", line, re.IGNORECASE)
                ):
                    diagnostics.error(
                        location,
                        f"input `{input_name}` is not unconditionally required and must not be described as required",
                    )
                if item.get("requiredWhen") and re.search(
                    r"无条件.{0,8}必填|始终.{0,8}必填|always.{0,8}required",
                    line,
                    re.IGNORECASE,
                ):
                    diagnostics.error(
                        location,
                        f"input `{input_name}` is conditional and must not be described as always required",
                    )
        if capability.get("sideEffect") != "read" and isinstance(tool_name, str):
            if re.search(
                rf"(?<![A-Za-z0-9_$]){re.escape(tool_name)}(?![A-Za-z0-9_$])"
                rf"[^\r\n]{{0,100}}(?:是|属于|为).{{0,8}}只读|"
                rf"只读[^\r\n]{{0,100}}(?<![A-Za-z0-9_$]){re.escape(tool_name)}(?![A-Za-z0-9_$])",
                text,
                re.IGNORECASE,
            ):
                diagnostics.error(
                    location,
                    f"write Tool `{tool_name}` must not be described as read-only",
                )
        policy = capability.get("operationPolicy", {})
        if isinstance(policy, dict) and policy.get("automaticRetry") == "never":
            if re.search(
                rf"(?<![A-Za-z0-9_$]){re.escape(str(tool_name))}(?![A-Za-z0-9_$])"
                rf"[^\r\n]{{0,120}}(?:可以|允许|会).{{0,8}}自动重试",
                text,
            ):
                diagnostics.error(
                    location,
                    f"Tool `{tool_name}` forbids automatic retries and prose must not allow them",
                )


def _validate_optional_upstream_guidance(
    text: str,
    capabilities: dict[str, dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Keep an observed provider recommendation distinct from API requiredness.

    An optional input may still have a normal acquisition path through another
    Tool.  The generated Skill must preserve that useful path without turning
    it into a hard prerequisite: it names a compatible provider and leaves the
    final omission decision to the target API.
    """

    capabilities_by_id = {
        capability.get("capabilityId"): capability
        for capability in capabilities.values()
        if isinstance(capability, dict)
        and isinstance(capability.get("capabilityId"), str)
    }
    paragraphs = [
        paragraph
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]
    for capability in capabilities.values():
        if not isinstance(capability, dict):
            continue
        target_tool = capability.get("toolName")
        for input_item in capability.get("inputs", []):
            target_requiredness = (
                input_item.get("targetRequiredness")
                if isinstance(input_item, dict)
                else None
            )
            if (
                not isinstance(input_item, dict)
                or not isinstance(input_item.get("name"), str)
                or not isinstance(target_requiredness, dict)
                or target_requiredness.get("status") != "unproven"
            ):
                continue
            normal_provider = target_requiredness.get("normalProvider", {})
            provider = capabilities_by_id.get(normal_provider.get("capabilityId"))
            provider_tools = {
                provider.get("toolName")
            } if isinstance(provider, dict) and isinstance(provider.get("toolName"), str) else set()
            if not provider_tools:
                continue
            input_name = input_item["name"]
            relevant = [
                paragraph
                for paragraph in paragraphs
                if re.search(
                    rf"(?<![A-Za-z0-9_$]){re.escape(input_name)}(?![A-Za-z0-9_$])",
                    paragraph,
                )
                and any(
                    re.search(
                        rf"(?<![A-Za-z0-9_$]){re.escape(provider_tool)}(?![A-Za-z0-9_$])",
                        paragraph,
                    )
                    for provider_tool in provider_tools
                )
            ]
            if not any(
                re.search(r"建议|正常流程|通常|优先", paragraph)
                and not re.search(
                    r"(?<!不)(?<!不是)(?<!并非)(?:必须|务必|需要|应当|须|只能)(?:先|优先)?调用|"
                    r"只有.{0,30}调用.{0,30}(?:才|才能)|硬前置|不可跳过|前置条件|"
                    r"\bmust\s+call\b|\brequired\s+precondition\b",
                    paragraph,
                    re.DOTALL | re.IGNORECASE,
                )
                and re.search(r"缺省|缺失|省略|未提供|不提供|不传|缺少", paragraph)
                and re.search(r"是否", paragraph)
                and re.search(r"接受|拒绝", paragraph)
                and re.search(
                    r"(?:目标\s*API|目标接口|后端|服务端).{0,40}(?:决定|判断|校验)",
                    paragraph,
                    re.DOTALL | re.IGNORECASE,
                )
                for paragraph in relevant
            ):
                diagnostics.error(
                    "SKILL.md",
                    f"optional upstream-provided input `{input_name}` for Tool `{target_tool}` must name a compatible provider Tool, recommend the observed acquisition path, and state that the target API decides whether omission is accepted",
                )


def _validate_vnext_feature_context(
    root: Path,
    capabilities: dict[str, dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    location = "references/feature-context.md"
    context = (root / location).read_text(encoding="utf-8")
    if re.search(r"<[A-Za-z][^>\r\n]*>", context) or "业务背景模板" in context:
        diagnostics.error(
            location,
            "must replace every template placeholder and template instruction with source-derived feature facts",
        )
    if len(context) < 800 or chinese_count(context) < 250:
        diagnostics.error(location, "must contain at least 800 characters and 250 Chinese characters")
    if not re.search(r"^#\s+.+$", context, re.MULTILINE):
        diagnostics.error(location, "must contain a Feature Context title")
    required_sections = {
        "purpose": r"功能定位|业务目的|Purpose",
        "actors and permissions": r"参与者与权限|角色与权限|Actors? and permissions",
        "domain concepts and field semantics": r"领域概念与字段语义|业务概念与字段(?:语义)?|Domain concepts and field semantics",
        "states and business rules": r"状态与业务规则|状态(?:[、，,与和]*)规则(?:与结果)?|业务状态与规则|States and business rules",
        "original client behavior": r"原(?:始)?客户端行为|客户端行为|前端调用行为|Original client behavior",
        "results and failures": r"结果与失败|结果和失败|失败与恢复|状态(?:[、，,与和]*)规则与结果|Results and failures",
        "related capabilities": r"相关能力|可用能力|Related capabilities",
        "unknowns": r"未知项|未知信息|未知与边界|Unknowns",
    }
    for label, pattern in required_sections.items():
        section = markdown_section(context, rf"(?i:{pattern})")
        if section is None:
            diagnostics.error(location, f"missing general Feature Context section: {label}")
        elif len(section) < 30:
            diagnostics.error(location, f"Feature Context section is too short: {label}")
    for capability in capabilities.values():
        tool = capability.get("toolName")
        if isinstance(tool, str) and f"`{tool}`" not in context:
            diagnostics.error(location, f"must mention Tool `{tool}`")
    canonical_path = root / "canonical-contract.json"
    if canonical_path.is_file():
        try:
            canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            canonical = {}
        for capability in canonical.get("capabilities", []) if isinstance(canonical, dict) else []:
            if not isinstance(capability, dict):
                continue
            exposure = capability.get("exposure", {})
            for evidence_id in exposure.get("evidenceRefs", []) if isinstance(exposure, dict) else []:
                if isinstance(evidence_id, str) and f"`{evidence_id}`" not in context:
                    diagnostics.error(
                        location,
                        f"must cite primary exposure evidence `{evidence_id}` from the Canonical evidence index",
                    )

    writes = [item.get("toolName") for item in capabilities.values() if item.get("sideEffect") != "read"]
    if not writes:
        if "只读" not in context or not re.search(
            r"(?:不|不得|禁止|不会).{0,40}(?:创建|修改|更新|删除|写入)",
            context,
            re.DOTALL,
        ):
            diagnostics.error(location, "read-only features must explicitly prohibit writes")
    else:
        side_effects = markdown_section(context, r"副作用|确认与写入|Side effects")
        if side_effects is None or chinese_count(side_effects) < 60:
            diagnostics.error(location, "write features need substantive side-effect and confirmation context")


def _validate_vnext_skill_metadata(root: Path, skill: str, diagnostics: Diagnostics) -> None:
    values, _ = markdown_frontmatter(skill, "SKILL.md", diagnostics)
    name = values.get("name", "")
    description = values.get("description", "")
    if not 1 <= len(name) <= 64 or not AGENT_SKILL_NAME.fullmatch(name):
        diagnostics.error("SKILL.md", "frontmatter name must be 1-64 lower-case letters, digits, and hyphen-separated segments")
    elif name != root.name:
        diagnostics.error("SKILL.md", f"frontmatter name must match candidate directory `{root.name}`")
    if not 1 <= len(description) <= 1024:
        diagnostics.error("SKILL.md", "frontmatter description must contain 1-1024 characters")
    if "references/feature-context.md" not in skill:
        diagnostics.error("SKILL.md", "must reference `references/feature-context.md` as on-demand Feature Context")


def _validate_vnext_mcp_setup(
    root: Path,
    profile: Any,
    capabilities: dict[str, dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    location = "MCP-SETUP.md"
    setup = (root / location).read_text(encoding="utf-8")
    if re.search(r"<[A-Za-z][^>\r\n]*>", setup):
        diagnostics.error(location, "generated setup must not retain angle-bracket template placeholders")
    command = re.search(r"npx\s+skills\s+add\b[^\r\n]+", setup)
    if command is None:
        diagnostics.error(location, "must contain a generic `npx skills add` command")
    else:
        command_text = command.group(0)
        required_options = {
            "Agent selector": r"(?:^|\s)(?:-a|--agent)(?:\s|=)",
            "global install": r"(?:^|\s)(?:-g|--global)(?:\s|$)",
            "non-interactive confirmation": r"(?:^|\s)(?:-y|--yes)(?:\s|$)",
        }
        for label, pattern in required_options.items():
            if not re.search(pattern, command_text):
                diagnostics.error(location, f"generic Skill install command is missing {label}")
        if root.name not in command_text:
            diagnostics.error(
                location,
                f"Skill install command must identify the generated package `{root.name}`",
            )
    if not re.search(r"(?:只|仅).{0,16}(?:安装|负责安装).{0,12}Skill", setup, re.IGNORECASE | re.DOTALL):
        diagnostics.error(location, "must state that `npx skills add` only installs the Skill")
    if not re.search(
        r"(?:不等于|不能视为|并不代表|不代表).{0,20}MCP|不会.{0,20}(?:启动|注册).{0,12}MCP",
        setup,
        re.IGNORECASE | re.DOTALL,
    ):
        diagnostics.error(location, "must not equate Skill installation with an operational MCP runtime")
    for label, pattern in {
        "MCP startup": r"MCP.{0,20}(?:启动|运行)|(?:启动|运行).{0,20}MCP",
        "MCP registration": r"MCP.{0,20}注册|注册.{0,20}MCP",
        "authentication": r"认证|鉴权|authentication",
        "environment variables": r"环境变量|environment variable",
    }.items():
        if not re.search(pattern, setup, re.IGNORECASE | re.DOTALL):
            diagnostics.error(location, f"must document {label} separately from Skill installation")
    if any(
        "attachment-resolution" in capability.get("hostRequirements", [])
        for capability in capabilities.values()
    ) and not (
        "attachment-resolution" in setup
        and re.search(r"requires-host-integration", setup, re.IGNORECASE)
    ):
        diagnostics.error(
            location,
            "attachment-dependent packages must document the generic attachment-resolution integration and unavailable status",
        )
    if isinstance(profile, dict):
        dry_run_variable = profile.get("dryRunEnvironmentVariable")
        if isinstance(dry_run_variable, str) and dry_run_variable not in setup:
            diagnostics.error(
                location,
                "must document the exact export-profile dry-run environment variable",
            )
        if profile.get("transport") == "stdio" and not re.search(
            r"node\s+[^\r\n]*mcp-tool/index\.mjs",
            setup,
        ):
            diagnostics.error(
                location,
                "stdio Runtime Profile must document the generated mcp-tool/index.mjs startup command",
            )


def validate_documents(
    root: Path,
    profile: Any,
    capabilities: dict[str, dict[str, Any]],
    diagnostics: Diagnostics,
    *,
    vnext: bool = False,
) -> None:
    tools = [item.get("toolName") for item in capabilities.values() if isinstance(item.get("toolName"), str)]
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    mcp = (root / "MCP.zh-CN.md").read_text(encoding="utf-8")
    if vnext:
        _validate_document_contract_binding(root, diagnostics)
        _validate_vnext_feature_context(root, capabilities, diagnostics)
        _validate_vnext_skill_metadata(root, skill, diagnostics)
        _validate_vnext_mcp_setup(root, profile, capabilities, diagnostics)
        _validate_document_contract_restatements(skill, capabilities, "SKILL.md", diagnostics)
        _validate_optional_upstream_guidance(skill, capabilities, diagnostics)
        _validate_document_contract_restatements(mcp, capabilities, "MCP.zh-CN.md", diagnostics)
        _validate_document_contract_restatements(
            (root / "references/feature-context.md").read_text(encoding="utf-8"),
            capabilities,
            "references/feature-context.md",
            diagnostics,
        )
    else:
        page = (root / "PAGE.md").read_text(encoding="utf-8")
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
        if vnext:
            error_contract = capability.get("errorContract")
            if isinstance(error_contract, dict) and error_contract.get("format") == "structured":
                for path_name in ("codePath", "messagePath", "detailsPath", "retryabilityPath"):
                    path_label = _path_label(error_contract.get(path_name))
                    if path_label and f"`{path_label}`" not in block:
                        diagnostics.error(
                            "MCP.zh-CN.md",
                            f"Tool `{tool}` must document structured error path `{path_label}`",
                        )
                if not re.search(r'"isError"\s*:\s*true', block) or not re.search(
                    r'"structuredContent"\s*:',
                    block,
                ):
                    diagnostics.error(
                        "MCP.zh-CN.md",
                        f"Tool `{tool}` needs an isError=true example with structuredContent",
                    )
                if not _path_label(error_contract.get("retryabilityPath")) and not re.search(
                    r"默认.{0,8}(?:不可|不应|禁止).{0,8}重试|default.{0,8}(?:false|not retryable)",
                    block,
                    re.IGNORECASE,
                ):
                    diagnostics.error(
                        "MCP.zh-CN.md",
                        f"Tool `{tool}` must document default non-retryability when retryabilityPath is absent",
                    )


def _mask_javascript(source: str, *, mask_strings: bool) -> str:
    """Replace JavaScript comments, and optionally strings, while preserving offsets."""
    output = list(source)
    index = 0
    length = len(source)
    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
            for offset in range(index, end):
                output[offset] = " "
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = length if end < 0 else end + 2
            for offset in range(index, end):
                if output[offset] not in {"\n", "\r"}:
                    output[offset] = " "
            index = end
            continue
        quote = source[index]
        if quote in {"'", '"', "`"}:
            start = index
            index += 1
            while index < length:
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == quote:
                    index += 1
                    break
                index += 1
            if mask_strings:
                for offset in range(start, min(index, length)):
                    if output[offset] not in {"\n", "\r"}:
                        output[offset] = " "
            continue
        index += 1
    return "".join(output)


def _matching_delimiter(masked_source: str, start: int, opening: str, closing: str) -> int | None:
    if start < 0 or start >= len(masked_source) or masked_source[start] != opening:
        return None
    depth = 0
    for index in range(start, len(masked_source)):
        character = masked_source[index]
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_javascript_arguments(source: str) -> list[str]:
    masked = _mask_javascript(source, mask_strings=True)
    arguments: list[str] = []
    start = 0
    round_depth = square_depth = brace_depth = 0
    for index, character in enumerate(masked):
        if character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif character == "," and round_depth == square_depth == brace_depth == 0:
            arguments.append(source[start:index].strip())
            start = index + 1
    arguments.append(source[start:].strip())
    return arguments


def _literal_tool_registrations(source: str) -> list[tuple[str, str, str | None, str | None]]:
    """Return literal Tool name, config, async callback parameters, and body."""
    commentless = _mask_javascript(source, mask_strings=False)
    code = _mask_javascript(source, mask_strings=True)
    registrations: list[tuple[str, str, str | None, str | None]] = []
    pattern = re.compile(r"\.\s*registerTool\s*\(\s*(['\"])([a-z][a-z0-9_]*)\1")
    for match in pattern.finditer(commentless):
        open_parenthesis = code.find("(", match.start())
        close_parenthesis = _matching_delimiter(code, open_parenthesis, "(", ")")
        if close_parenthesis is None:
            registrations.append((match.group(2), "", None, None))
            continue
        arguments = _split_javascript_arguments(commentless[open_parenthesis + 1:close_parenthesis])
        if len(arguments) != 3:
            registrations.append((match.group(2), "", None, None))
            continue
        tool_literal = re.fullmatch(r"\s*(['\"])([a-z][a-z0-9_]*)\1\s*", arguments[0])
        if tool_literal is None:
            continue
        config = arguments[1]
        callback = arguments[2]
        callback_code = _mask_javascript(callback, mask_strings=True)
        arrow = re.search(
            r"\basync\s*(?:\(([^)]*)\)|([A-Za-z_$][\w$]*))\s*=>\s*\{",
            callback_code,
        )
        callback_body: str | None = None
        callback_parameters: str | None = None
        if arrow is not None:
            callback_parameters = arrow.group(1) if arrow.group(1) is not None else arrow.group(2)
            body_start = callback_code.find("{", arrow.start())
            body_end = _matching_delimiter(callback_code, body_start, "{", "}")
            if body_end is not None and not callback_code[body_end + 1:].strip():
                callback_body = callback[body_start + 1:body_end]
        registrations.append((tool_literal.group(2), config, callback_parameters, callback_body))
    return registrations


def _javascript_excluded_ranges(masked_source: str) -> list[tuple[int, int]]:
    """Find statically dead blocks and nested function bodies in a callback."""
    ranges: list[tuple[int, int]] = []
    patterns = (
        r"\b(?:if|while)\s*\(\s*(?:false|0|null|undefined)\s*\)\s*\{",
        r"\b(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\([^)]*\)\s*\{",
        r"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, masked_source):
            opening = masked_source.rfind("{", match.start(), match.end())
            closing = _matching_delimiter(masked_source, opening, "{", "}")
            if closing is not None:
                ranges.append((match.start(), closing + 1))
    return ranges


def _inside_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _exported_function_region(source: str, function_export: str) -> str | None:
    declaration = re.search(
        rf"\bexport\s+(?:async\s+function|const)\s+{re.escape(function_export)}\b",
        _mask_javascript(source, mask_strings=True),
    )
    if declaration is None:
        return None
    next_export = re.search(
        r"\bexport\s+(?:async\s+function|const)\s+[A-Za-z_$][\w$]*\b",
        _mask_javascript(source[declaration.end():], mask_strings=True),
    )
    end = len(source) if next_export is None else declaration.end() + next_export.start()
    return source[declaration.start():end]


NETWORK_CALL_PATTERN = re.compile(
    r"(?:\bfetch\s*\(|\brequest\s*\(|\.\s*request\s*\(|"
    r"\baxios(?:\s*\.[A-Za-z_$][\w$]*)?\s*\(|"
    r"\bhttps?\s*\.\s*(?:request|get)\s*\(|\bXMLHttpRequest\s*\(|"
    r"\bnew\s+(?:WebSocket|EventSource)\s*\()"
)
COMPUTED_NETWORK_CALL_PATTERN = re.compile(
    r"\[\s*(['\"])(?:fetch|request)\1\s*\]\s*\(",
    re.IGNORECASE,
)
EXTERNAL_CALLBACK_CALL_PATTERN = re.compile(
    NETWORK_CALL_PATTERN.pattern
    + r"|(?:\b(?:writeFile|writeFileSync|appendFile|appendFileSync|unlink|unlinkSync|"
    r"rename|renameSync|rm|rmSync|spawn|spawnSync|exec|execFile|upload|publish|send|"
    r"connect|dispatch)\s*\(|\bprocess\s*\.\s*(?:exit|kill)\s*\()"
)
RUNTIME_EFFECTFUL_NODE_MODULES = {
    "node:child_process",
    "node:dgram",
    "node:fs",
    "node:fs/promises",
    "node:http",
    "node:http2",
    "node:https",
    "node:module",
    "node:net",
    "node:tls",
    "node:vm",
    "node:worker_threads",
}


def _exported_function_body_ranges(
    source: str,
    function_exports: set[str],
) -> list[tuple[int, int]]:
    code = _mask_javascript(source, mask_strings=True)
    ranges: list[tuple[int, int]] = []
    for function_export in function_exports:
        patterns = (
            rf"\bexport\s+async\s+function\s+{re.escape(function_export)}\s*\([^)]*\)\s*\{{",
            rf"\bexport\s+const\s+{re.escape(function_export)}\s*=\s*async\s*\([^)]*\)\s*=>\s*\{{",
        )
        for pattern in patterns:
            match = re.search(pattern, code)
            if match is None:
                continue
            opening = code.rfind("{", match.start(), match.end())
            closing = _matching_delimiter(code, opening, "{", "}")
            if closing is not None:
                ranges.append((match.start(), closing + 1))
            break
    return ranges


def _masked_out_ranges(source: str, ranges: list[tuple[int, int]]) -> tuple[str, str]:
    code = list(_mask_javascript(source, mask_strings=True))
    commentless = list(_mask_javascript(source, mask_strings=False))
    for start, end in ranges:
        for index in range(max(0, start), min(len(code), end)):
            if code[index] not in {"\n", "\r"}:
                code[index] = " "
            if commentless[index] not in {"\n", "\r"}:
                commentless[index] = " "
    return "".join(code), "".join(commentless)


def _module_has_external_effect(code: str, commentless: str) -> bool:
    if (
        EXTERNAL_CALLBACK_CALL_PATTERN.search(code)
        or COMPUTED_NETWORK_CALL_PATTERN.search(commentless)
        or re.search(
            r"\[\s*(['\"])(?:writeFile|writeFileSync|appendFile|unlink|rename|rm|"
            r"spawn|exec|upload|publish|send|connect|dispatch)\1\s*\]\s*\(",
            commentless,
        )
    ):
        return True
    effect_names = (
        r"fetch|request|axios|writeFile|writeFileSync|appendFile|appendFileSync|"
        r"unlink|unlinkSync|rename|renameSync|rm|rmSync|spawn|spawnSync|exec|"
        r"execFile|upload|publish|send|connect|dispatch"
    )
    aliases: set[str] = set()
    for assignment in re.finditer(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\r\n]+)",
        commentless,
    ):
        if re.search(rf"\b(?:{effect_names})\b", assignment.group(2)):
            aliases.add(assignment.group(1))
    for destructuring in re.finditer(
        r"\b(?:const|let|var)\s*\{([^}]+)\}\s*=\s*[^;\r\n]+",
        commentless,
    ):
        for entry in destructuring.group(1).split(","):
            match = re.fullmatch(
                rf"\s*(?:{effect_names})\s*(?::\s*([A-Za-z_$][\w$]*))?\s*",
                entry,
            )
            if match:
                aliases.add(match.group(1) or entry.strip())
    return any(re.search(rf"\b{re.escape(alias)}\s*\(", code) for alias in aliases)


def _literal_http_origins(source: str) -> list[tuple[str, str | None, str | None]]:
    commentless = _mask_javascript(source, mask_strings=False)
    result: list[tuple[str, str | None, str | None]] = []
    for match in re.finditer(r"(['\"`])(https?://[^'\"`\s]+)\1", commentless):
        url = match.group(2)
        origin, error = _parse_http_origin(url)
        result.append((url, origin, error))
    return result


def _validate_vnext_function_runtime(
    function_source: str,
    capabilities: dict[str, dict[str, Any]],
    allowed_origins: set[str],
    diagnostics: Diagnostics,
) -> None:
    has_http_capability = any(
        isinstance(capability.get("implementation"), dict)
        and capability["implementation"].get("kind") == "http"
        for capability in capabilities.values()
    )
    if has_http_capability:
        expected_urls = {
            step.get("url")
            for capability in capabilities.values()
            if isinstance(capability.get("implementation"), dict)
            and capability["implementation"].get("kind") == "http"
            for step in capability["implementation"].get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("url"), str)
        }
        observed_urls: set[str] = set()
        for url, origin, origin_error in _literal_http_origins(function_source):
            observed_urls.add(url)
            if origin_error:
                diagnostics.error(
                    "function-core/index.mjs",
                    f"HTTP Function runtime literal must be a valid URL without credentials: `{url}`",
                )
            elif origin not in allowed_origins:
                diagnostics.error(
                    "function-core/index.mjs",
                    f"HTTP Function runtime literal origin `{origin}` is not declared by Canonical HTTP steps",
                )
        if observed_urls != expected_urls:
            diagnostics.error(
                "function-core/index.mjs",
                "HTTP Function runtime URL literals must exactly equal Canonical HTTP step URLs; "
                f"expected {sorted(expected_urls)}",
            )
        global_code = _mask_javascript(function_source, mask_strings=True)
        global_commentless = _mask_javascript(function_source, mask_strings=False)
        for network_call in NETWORK_CALL_PATTERN.finditer(global_code):
            opening = network_call.end() - 1
            closing = _matching_delimiter(global_code, opening, "(", ")")
            arguments = (
                _split_javascript_arguments(global_commentless[opening + 1:closing])
                if closing is not None
                else []
            )
            first_argument = arguments[0].strip() if arguments else ""
            literal_match = re.fullmatch(
                r"(['\"`])(https?://[^'\"`\s]+)\1",
                first_argument,
            )
            if literal_match is None or literal_match.group(2) not in expected_urls:
                diagnostics.error(
                    "function-core/index.mjs",
                    "every HTTP network call, including helper code, must use one exact Canonical URL literal",
                )
        global_network_aliases: set[str] = set()
        for assignment in re.finditer(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\r\n]+)",
            global_commentless,
        ):
            if re.search(r"\b(?:fetch|request|axios)\b", assignment.group(2), re.IGNORECASE):
                global_network_aliases.add(assignment.group(1))
        for destructuring in re.finditer(
            r"\b(?:const|let|var)\s*\{([^}]+)\}\s*=\s*[^;\r\n]*\b(?:context|globalThis|window)\b",
            global_commentless,
        ):
            for entry in destructuring.group(1).split(","):
                match = re.fullmatch(
                    r"\s*(?:fetch|request|axios)\s*(?::\s*([A-Za-z_$][\w$]*))?\s*",
                    entry,
                    re.IGNORECASE,
                )
                if match:
                    global_network_aliases.add(match.group(1) or entry.strip())
        if COMPUTED_NETWORK_CALL_PATTERN.search(global_commentless) or any(
            re.search(rf"\b{re.escape(alias)}\s*\(", global_code)
            for alias in global_network_aliases
        ):
            diagnostics.error(
                "function-core/index.mjs",
                "HTTP network calls must remain directly inspectable and cannot use computed properties or aliases",
            )
    for capability in capabilities.values():
        implementation = capability.get("implementation")
        kind = implementation.get("kind") if isinstance(implementation, dict) else None
        function_export = capability.get("functionExport")
        if kind not in {"local", "http"} or not isinstance(function_export, str):
            continue
        region = _exported_function_region(function_source, function_export)
        if region is None:
            continue
        code = _mask_javascript(region, mask_strings=True)
        commentless = _mask_javascript(region, mask_strings=False)
        network_aliases: set[str] = set()
        for assignment in re.finditer(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\r\n]+)",
            commentless,
        ):
            right_hand_side = assignment.group(2)
            if re.search(r"\b(?:fetch|request|axios)\b", right_hand_side, re.IGNORECASE):
                network_aliases.add(assignment.group(1))
        for destructuring in re.finditer(
            r"\b(?:const|let|var)\s*\{([^}]+)\}\s*=\s*[^;\r\n]*\b(?:context|globalThis|window)\b",
            commentless,
        ):
            for entry in destructuring.group(1).split(","):
                match = re.fullmatch(
                    r"\s*(?:fetch|request|axios)\s*(?::\s*([A-Za-z_$][\w$]*))?\s*",
                    entry,
                    re.IGNORECASE,
                )
                if match:
                    network_aliases.add(match.group(1) or entry.strip())
        alias_call = any(
            re.search(rf"\b{re.escape(alias)}\s*\(", code)
            for alias in network_aliases
        )
        if kind == "local" and (
            NETWORK_CALL_PATTERN.search(code)
            or COMPUTED_NETWORK_CALL_PATTERN.search(commentless)
            or alias_call
        ):
            diagnostics.error(
                "function-core/index.mjs",
                f"local Function `{function_export}` must not perform fetch/request/axios network calls",
            )
        if kind == "http":
            if COMPUTED_NETWORK_CALL_PATTERN.search(commentless) or alias_call:
                diagnostics.error(
                    "function-core/index.mjs",
                    f"HTTP Function `{function_export}` must call its Canonical URL directly, not through a computed property or network alias",
                )
            for network_call in NETWORK_CALL_PATTERN.finditer(code):
                opening = network_call.end() - 1
                closing = _matching_delimiter(code, opening, "(", ")")
                arguments = (
                    _split_javascript_arguments(commentless[opening + 1:closing])
                    if closing is not None
                    else []
                )
                first_argument = arguments[0].strip() if arguments else ""
                literal_match = re.fullmatch(
                    r"(['\"`])(https?://[^'\"`\s]+)\1",
                    first_argument,
                )
                if literal_match is None or literal_match.group(2) not in expected_urls:
                    diagnostics.error(
                        "function-core/index.mjs",
                        f"HTTP Function `{function_export}` must call one exact Canonical URL literal without a dynamic suffix",
                    )
        body_opening = code.find("{")
        function_body = code[body_opening + 1:] if body_opening >= 0 else code
        if re.search(r"(?:^|[;{}])\s*(?:input|context)\s*=", function_body):
            diagnostics.error(
                "function-core/index.mjs",
                f"Function `{function_export}` must not reassign its validated input or trusted context",
            )


def _callback_direct_result_return(
    callback_body: str,
    result_name: str,
    excluded: list[tuple[int, int]],
) -> int | None:
    code = _mask_javascript(callback_body, mask_strings=True)
    commentless = _mask_javascript(callback_body, mask_strings=False)
    for match in re.finditer(r"\breturn\s*\{", code):
        if _inside_ranges(match.start(), excluded):
            continue
        opening = code.find("{", match.start(), match.end())
        closing = _matching_delimiter(code, opening, "{", "}")
        if closing is None:
            continue
        result_object = code[opening + 1:closing]
        raw_result_object = commentless[opening + 1:closing]
        properties = _split_javascript_arguments(raw_result_object)
        patterns = (
            rf"structuredContent\s*:\s*{re.escape(result_name)}",
            (
                r"content\s*:\s*\[\s*\{\s*type\s*:\s*(['\"])text\1\s*,\s*"
                rf"text\s*:\s*JSON\s*\.\s*stringify\s*\(\s*{re.escape(result_name)}\s*\)\s*\}}\s*\]"
            ),
            r"isError\s*:\s*false",
        )
        if (
            "..." not in result_object
            and len(properties) == len(patterns)
            and all(
                any(re.fullmatch(pattern, item.strip()) for item in properties)
                for pattern in patterns
            )
        ):
            return match.start()
    return None


def _callback_error_result_return(
    callback_body: str,
    result_name: str,
    excluded: list[tuple[int, int]],
) -> tuple[int, int] | None:
    code = _mask_javascript(callback_body, mask_strings=True)
    commentless = _mask_javascript(callback_body, mask_strings=False)
    for match in re.finditer(r"\breturn\s*\{", code):
        if _inside_ranges(match.start(), excluded):
            continue
        opening = code.find("{", match.start(), match.end())
        closing = _matching_delimiter(code, opening, "{", "}")
        if closing is None:
            continue
        result_object = code[opening + 1:closing]
        raw_result_object = commentless[opening + 1:closing]
        properties = _split_javascript_arguments(raw_result_object)
        patterns = (
            rf"structuredContent\s*:\s*{re.escape(result_name)}",
            (
                r"content\s*:\s*\[\s*\{\s*type\s*:\s*(['\"])text\1\s*,\s*"
                rf"text\s*:\s*JSON\s*\.\s*stringify\s*\(\s*{re.escape(result_name)}\s*\)\s*\}}\s*\]"
            ),
            r"isError\s*:\s*true",
        )
        if (
            "..." not in result_object
            and len(properties) == len(patterns)
            and all(
                any(re.fullmatch(pattern, item.strip()) for item in properties)
                for pattern in patterns
            )
        ):
            return match.start(), closing + 1
    return None


def _has_unconditional_termination_before(code: str, position: int) -> bool:
    # Generated callbacks use a direct top-level return/throw for unconditional
    # termination. Conditional returns have an `if (...)` token after the most
    # recent statement boundary and therefore do not match this normal form.
    return re.search(r"(?:\A|[;}])\s*(?:return|throw)\b", code[:position]) is not None


def _javascript_brace_depth(code: str, position: int) -> int:
    depth = 0
    for character in code[:position]:
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
    return depth


def _callback_dry_run_guard(
    callback_body: str,
    dry_run_variable: str,
    excluded: list[tuple[int, int]],
    expected_operation_policy: dict[str, Any] | None,
    expected_operation_summary: dict[str, Any] | None,
) -> tuple[int, int] | None:
    """Return the exact reviewed dry-run guard range, if present.

    A dry-run response is still an MCP Tool result.  Requiring one local result
    object and a direct text projection prevents the static adapter contract
    from accepting an envelope that the detached protocol probe will reject.
    """

    if not dry_run_variable:
        return None
    code = _mask_javascript(callback_body, mask_strings=True)
    commentless = _mask_javascript(callback_body, mask_strings=False)
    guard_pattern = re.compile(
        rf"if\s*\(\s*process\.env\.{re.escape(dry_run_variable)}\s*===\s*(['\"])1\1\s*\)"
    )
    for guard in guard_pattern.finditer(commentless):
        if _inside_ranges(guard.start(), excluded):
            continue
        block_open = guard.end()
        while block_open < len(code) and code[block_open].isspace():
            block_open += 1
        if block_open >= len(code) or code[block_open] != "{":
            continue
        block_close = _matching_delimiter(code, block_open, "{", "}")
        if block_close is None:
            continue

        body_code = code[block_open + 1:block_close]
        declaration = re.match(
            r"\s*const\s+dryRunResult\s*=\s*\{",
            body_code,
        )
        if declaration is None:
            continue
        object_open = block_open + 1 + body_code.find(
            "{",
            declaration.start(),
            declaration.end(),
        )
        object_close = _matching_delimiter(code, object_open, "{", "}")
        if object_close is None or object_close >= block_close:
            continue
        result_properties = _split_javascript_arguments(
            commentless[object_open + 1:object_close]
        )
        parsed_properties: dict[str, str] = {}
        for item in result_properties:
            property_match = re.fullmatch(
                r"(dryRun|validatedInput|operationPolicy|operationSummary)\s*:\s*([\s\S]+)",
                item.strip(),
            )
            if property_match is None or property_match.group(1) in parsed_properties:
                parsed_properties = {}
                break
            parsed_properties[property_match.group(1)] = property_match.group(2).strip()
        if (
            set(parsed_properties)
            != {"dryRun", "validatedInput", "operationPolicy", "operationSummary"}
            or parsed_properties.get("dryRun") != "true"
            or parsed_properties.get("validatedInput") != "input"
        ):
            continue
        try:
            observed_operation_policy = json.loads(parsed_properties["operationPolicy"])
            observed_operation_summary = json.loads(parsed_properties["operationSummary"])
        except (KeyError, json.JSONDecodeError):
            continue
        if not isinstance(observed_operation_policy, dict) or not isinstance(
            observed_operation_summary, dict
        ):
            continue
        if (
            expected_operation_policy is not None
            and observed_operation_policy != expected_operation_policy
        ):
            continue
        if (
            expected_operation_summary is not None
            and observed_operation_summary != expected_operation_summary
        ):
            continue

        after_result = commentless[object_close + 1:block_close]
        return_match = re.match(r"\s*;\s*return\s*\{", after_result)
        if return_match is None:
            continue
        return_open = object_close + 1 + after_result.find(
            "{",
            return_match.start(),
            return_match.end(),
        )
        return_close = _matching_delimiter(code, return_open, "{", "}")
        if return_close is None or return_close >= block_close:
            continue
        envelope_properties = _split_javascript_arguments(
            commentless[return_open + 1:return_close]
        )
        envelope_patterns = (
            r"structuredContent\s*:\s*dryRunResult",
            (
                r"content\s*:\s*\[\s*\{\s*type\s*:\s*(['\"])text\1\s*,\s*"
                r"text\s*:\s*JSON\s*\.\s*stringify\s*\(\s*dryRunResult\s*\)\s*\}\s*\]"
            ),
            r"isError\s*:\s*false",
        )
        if len(envelope_properties) != len(envelope_patterns) or not all(
            any(re.fullmatch(pattern, item.strip()) for item in envelope_properties)
            for pattern in envelope_patterns
        ):
            continue
        if re.fullmatch(
            r"\s*;?\s*",
            commentless[return_close + 1:block_close],
        ) is None:
            continue
        return guard.start(), block_close + 1
    return None


def _validate_vnext_tool_callback(
    tool_name: str,
    callback_parameters: str,
    callback_body: str,
    expected_export: str,
    function_exports: set[str],
    dry_run_variable: str,
    expected_operation_policy: dict[str, Any] | None,
    expected_operation_summary: dict[str, Any] | None,
    diagnostics: Diagnostics,
) -> None:
    code = _mask_javascript(callback_body, mask_strings=True)
    commentless = _mask_javascript(callback_body, mask_strings=False)
    excluded = _javascript_excluded_ranges(code)
    parameters = [item.strip() for item in callback_parameters.split(",")]
    if parameters != ["input", "runtimeContext"]:
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must receive exactly `(input, runtimeContext)` from the MCP runtime",
        )
    shadows_expected_export = re.search(
        rf"(?:\b(?:const|let|var|function|class)\s+{re.escape(expected_export)}\b|"
        rf"\b{re.escape(expected_export)}\s*=)",
        code,
    ) is not None
    called_exports: dict[str, list[int]] = {}
    for function_export in function_exports:
        called_exports[function_export] = [
            match.start()
            for match in re.finditer(rf"\b{re.escape(function_export)}\s*\(", code)
        ]
    template_export_calls = {
        function_export
        for function_export in function_exports
        if re.search(
            rf"\$\{{[^`]*\b{re.escape(function_export)}\s*\(",
            commentless,
            re.DOTALL,
        )
    }
    other_exports = {
        function_export
        for function_export, positions in called_exports.items()
        if function_export != expected_export and positions
    } | (template_export_calls - {expected_export})
    assignments = [
        match
        for match in re.finditer(
            rf"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*await\s+{re.escape(expected_export)}\s*\(",
            code,
        )
        if not _inside_ranges(match.start(), excluded)
    ]
    if (
        other_exports
        or shadows_expected_export
        or template_export_calls
        or len(called_exports.get(expected_export, [])) != 1
        or len(assignments) != 1
    ):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must call exactly its Canonical Function export `{expected_export}`",
        )
        return
    result_name = assignments[0].group(1)
    result_return = _callback_direct_result_return(callback_body, result_name, excluded)
    error_result_return = _callback_error_result_return(
        callback_body,
        "toolError",
        excluded,
    )
    try_match = re.search(r"\btry\s*\{", code)
    try_open = code.find("{", try_match.start(), try_match.end()) if try_match else -1
    try_close = _matching_delimiter(code, try_open, "{", "}") if try_open >= 0 else None
    catch_match = (
        re.match(
            r"\s*catch\s*\(\s*error\s*\)\s*\{",
            code[try_close + 1:],
        )
        if try_close is not None
        else None
    )
    catch_open = (
        code.find(
            "{",
            try_close + 1,
            try_close + 1 + catch_match.end(),
        )
        if try_close is not None and catch_match is not None
        else -1
    )
    catch_close = (
        _matching_delimiter(code, catch_open, "{", "}")
        if catch_open >= 0
        else None
    )
    success_return_end: int | None = None
    if result_return is not None:
        success_open = code.find("{", result_return)
        success_close = _matching_delimiter(code, success_open, "{", "}")
        success_return_end = success_close + 1 if success_close is not None else None
    normalizer_prefix = (
        re.match(
            r"\s*const\s+toolError\s*=\s*normalizeToolError\s*\(",
            code[catch_open + 1:catch_close],
        )
        if catch_close is not None
        else None
    )
    normalizer_call_open = (
        code.find(
            "(",
            catch_open + 1,
            catch_open + 1 + normalizer_prefix.end(),
        )
        if normalizer_prefix is not None
        else -1
    )
    normalizer_call_close = (
        _matching_delimiter(code, normalizer_call_open, "(", ")")
        if normalizer_call_open >= 0
        else None
    )
    normalizer_arguments = (
        _split_javascript_arguments(
            commentless[normalizer_call_open + 1:normalizer_call_close]
        )
        if normalizer_call_close is not None
        else []
    )
    try:
        normalizer_policy = (
            json.loads(normalizer_arguments[1])
            if len(normalizer_arguments) == 2
            else None
        )
    except json.JSONDecodeError:
        normalizer_policy = None
    normalizer_terminator = (
        re.match(r"\s*;", code[normalizer_call_close + 1:catch_close])
        if normalizer_call_close is not None and catch_close is not None
        else None
    )
    normalizer_valid = (
        len(normalizer_arguments) == 2
        and normalizer_arguments[0].strip() == "error"
        and isinstance(normalizer_policy, dict)
        and (
            expected_operation_policy is None
            or normalizer_policy == expected_operation_policy
        )
        and normalizer_terminator is not None
    )
    normalizer_end = (
        normalizer_call_close + 1 + normalizer_terminator.end()
        if normalizer_valid
        and normalizer_call_close is not None
        and normalizer_terminator is not None
        else None
    )
    strict_error_wrapper = (
        try_open >= 0
        and try_close is not None
        and catch_open >= 0
        and catch_close is not None
        and code[catch_close + 1:].strip() == ""
        and try_open < assignments[0].start() < try_close
        and result_return is not None
        and try_open < result_return < try_close
        and success_return_end is not None
        and re.fullmatch(r"\s*;?\s*", code[success_return_end:try_close]) is not None
        and normalizer_end is not None
        and error_result_return is not None
        and catch_open < error_result_return[0] < error_result_return[1] < catch_close
        and re.fullmatch(
            r"\s*",
            code[normalizer_end:error_result_return[0]],
        )
        is not None
        and re.fullmatch(
            r"\s*;?\s*",
            code[error_result_return[1]:catch_close],
        )
        is not None
        and len(re.findall(r"\bnormalizeToolError\s*\(", code)) == 1
    )
    if not strict_error_wrapper:
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must use the exact try/success projection/catch/normalizeToolError/error projection wrapper",
        )
    call_opening = code.rfind("(", assignments[0].start(), assignments[0].end())
    call_closing = _matching_delimiter(code, call_opening, "(", ")")
    call_arguments = (
        _split_javascript_arguments(commentless[call_opening + 1:call_closing])
        if call_closing is not None
        else []
    )
    if (
        len(call_arguments) != 2
        or call_arguments[0].strip() != "input"
        or call_arguments[1].strip() != "runtimeContext"
    ):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must pass the exact Tool input and trusted runtimeContext to `{expected_export}`",
        )
    if re.search(r"(?:^|[;{}])\s*(?:input|runtimeContext)\s*=", code[:assignments[0].start()]):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must not replace its Tool input or trusted runtimeContext before Function execution",
        )
    if re.search(
        r"\b(?:PortableWorkflowGuard|protectedWorkflowState|expectedBindings|bindingSources|dispatchWithPolicy)\b",
        code,
    ):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must not construct or project Guard, protected-state, or binding data",
        )

    prefix_without_dry_guard = list(code[:assignments[0].start()])
    prefix_commentless = commentless[:assignments[0].start()]
    dry_guard_pattern = re.compile(
        rf"if\s*\(\s*process\.env\.{re.escape(dry_run_variable)}\s*===\s*(['\"])1\1\s*\)"
    ) if dry_run_variable else None
    if dry_guard_pattern is not None:
        for guard in dry_guard_pattern.finditer(prefix_commentless):
            end = guard.end()
            while end < len(prefix_commentless) and prefix_commentless[end].isspace():
                end += 1
            if end < len(prefix_commentless) and prefix_commentless[end] == "{":
                closing = _matching_delimiter(code, end, "{", "}")
                end = closing + 1 if closing is not None else end
            else:
                semicolon = code.find(";", end)
                end = semicolon + 1 if semicolon >= 0 else end
            prefix_without_dry_guard[guard.start():end] = " " * (end - guard.start())
    if re.search(r"\b(?:return|throw)\b", "".join(prefix_without_dry_guard)):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must not terminate before its Canonical Function call except through the exact dry-run guard",
        )
    directly_adjacent = (
        result_return is not None
        and call_closing is not None
        and re.fullmatch(r"\s*;?\s*", code[call_closing + 1:result_return]) is not None
    )
    if (
        result_return is None
        or assignments[0].end() >= result_return
        or not directly_adjacent
        or _has_unconditional_termination_before(
            "".join(prefix_without_dry_guard),
            len(prefix_without_dry_guard),
        )
        or _javascript_brace_depth(code, assignments[0].start()) != 1
        or (
            result_return is not None
            and _javascript_brace_depth(code, result_return) != 1
        )
        or not strict_error_wrapper
    ):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` successful result must directly project `{expected_export}` output",
        )
    if not dry_run_variable:
        return
    dry_guard = _callback_dry_run_guard(
        callback_body,
        dry_run_variable,
        excluded,
        expected_operation_policy,
        expected_operation_summary,
    )
    guard_position = dry_guard[0] if dry_guard is not None else None
    guard_end_position = dry_guard[1] if dry_guard is not None else None
    external_positions = [
        position
        for positions in called_exports.values()
        for position in positions
    ]
    external_positions.extend(match.start() for match in EXTERNAL_CALLBACK_CALL_PATTERN.finditer(code))
    callback_side_effect_names = (
        r"fetch|request|axios|writeFile|writeFileSync|appendFile|appendFileSync|"
        r"unlink|unlinkSync|rename|renameSync|rm|rmSync|spawn|spawnSync|exec|"
        r"execFile|upload|publish|send|connect|dispatch"
    )
    callback_aliases: set[str] = set()
    for assignment in re.finditer(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\r\n]+)",
        commentless,
    ):
        if re.search(rf"\b(?:{callback_side_effect_names})\b", assignment.group(2)):
            callback_aliases.add(assignment.group(1))
    for destructuring in re.finditer(
        r"\b(?:const|let|var)\s*\{([^}]+)\}\s*=\s*[^;\r\n]+",
        commentless,
    ):
        for entry in destructuring.group(1).split(","):
            match = re.fullmatch(
                rf"\s*(?:{callback_side_effect_names})\s*(?::\s*([A-Za-z_$][\w$]*))?\s*",
                entry,
            )
            if match:
                callback_aliases.add(match.group(1) or entry.strip())
    for alias in callback_aliases:
        external_positions.extend(
            match.start()
            for match in re.finditer(rf"\b{re.escape(alias)}\s*\(", code)
        )
    for interpolation in re.finditer(r"\$\{([^`]*)", commentless, re.DOTALL):
        external_positions.extend(
            interpolation.start(1) + match.start()
            for match in EXTERNAL_CALLBACK_CALL_PATTERN.finditer(interpolation.group(1))
        )
    if (
        guard_position is None
        or commentless[:guard_position].strip() != ""
        or (external_positions and guard_position > min(external_positions))
    ):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` dry-run guard must return before any Function or external call, be the first executable callback statement, and use the exact matching content plus structuredContent envelope",
        )
    if (
        guard_end_position is None
        or re.fullmatch(
            r"\s*try\s*\{\s*",
            code[guard_end_position:assignments[0].start()],
        )
        is None
    ):
        diagnostics.error(
            "mcp-tool/index.mjs",
            f"Tool `{tool_name}` callback must contain only the exact dry-run guard before its Canonical Function call; adapter logic and external side effects belong behind the Function boundary",
        )


def validate_runtime(
    root: Path,
    capabilities: dict[str, dict[str, Any]],
    dry_run_variable: str,
    diagnostics: Diagnostics,
    *,
    vnext: bool = False,
    allowed_runtime_origins: set[str] | None = None,
    canonical_contract: Any = None,
) -> None:
    function_source = (root / "function-core/index.mjs").read_text(encoding="utf-8")
    mcp_source = (root / "mcp-tool/index.mjs").read_text(encoding="utf-8")
    runtime_source = (root / "mcp-tool/runtime.mjs").read_text(encoding="utf-8")
    normalizer_source = ""
    if vnext:
        normalizer_path = root / "portable-error-normalizer.mjs"
        reference_normalizer = (
            Path(__file__).resolve().parent.parent
            / "assets"
            / "portable-error-normalizer.mjs"
        )
        if not normalizer_path.is_file():
            diagnostics.error(
                "portable-error-normalizer.mjs",
                "is required for structured Tool execution errors",
            )
        else:
            normalizer_source = normalizer_path.read_text(encoding="utf-8")
            candidate_bytes = normalizer_path.read_bytes()
            current_reviewed = (
                reference_normalizer.is_file()
                and candidate_bytes == reference_normalizer.read_bytes()
            )
            legacy_reviewed = (
                hashlib.sha256(candidate_bytes).hexdigest()
                == LEGACY_REVIEWED_NORMALIZER_SHA256
            )
            if not current_reviewed and not legacy_reviewed:
                diagnostics.error(
                    "portable-error-normalizer.mjs",
                    "must be one of the byte-exact reviewed Code2Skill error normalizer versions",
                )
        if not re.search(
            r"import\s*\{\s*normalizeToolError\s*\}\s*from\s*['\"]\.\./portable-error-normalizer\.mjs['\"]",
            mcp_source,
        ):
            diagnostics.error(
                "mcp-tool/index.mjs",
                "must directly import normalizeToolError from the reviewed portable error normalizer",
            )
    effective_runtime_origins = allowed_runtime_origins or set()
    if vnext and canonical_contract is not None:
        effective_runtime_origins = validate_vnext_runtime_contract(
            canonical_contract,
            effective_runtime_origins,
            diagnostics,
        )
    registrations = _literal_tool_registrations(mcp_source)
    canonical_function_exports = {
        capability.get("functionExport")
        for capability in capabilities.values()
        if isinstance(capability.get("functionExport"), str)
    }
    registrations_by_tool: dict[str, list[tuple[str, str | None, str | None]]] = {}
    for tool_name, config, callback_parameters, callback_body in registrations:
        registrations_by_tool.setdefault(tool_name, []).append(
            (config, callback_parameters, callback_body)
        )
    import_specifiers = re.findall(r"\bfrom\s*['\"]([^'\"]+)['\"]|\bimport\s*\(\s*['\"]([^'\"]+)['\"]", function_source)
    import_specifiers += [(specifier, "") for specifier in re.findall(r"(?:^|;)\s*import\s*['\"]([^'\"]+)['\"]", function_source, re.MULTILINE)]
    allows_portable_guard = vnext and any(
        isinstance(capability.get("runtimeProtection"), dict)
        and capability["runtimeProtection"].get("mode") == "deterministic-workflow"
        for capability in capabilities.values()
    )
    for pair in import_specifiers:
        specifier = pair[0] or pair[1]
        if (
            specifier
            and not specifier.startswith("node:")
            and not (
                allows_portable_guard
                and specifier == "../portable-workflow-guard.mjs"
            )
        ):
            diagnostics.error("function-core/index.mjs", f"Function core must be self-contained; unsupported import `{specifier}`")
        if vnext and specifier in RUNTIME_EFFECTFUL_NODE_MODULES:
            diagnostics.error(
                "function-core/index.mjs",
                f"Function core must not import effectful Node module `{specifier}`; use the Canonical HTTP/Host dispatch boundary",
            )
    if vnext and re.search(r"\bimport\s*\(", _mask_javascript(function_source, mask_strings=True)):
        diagnostics.error(
            "function-core/index.mjs",
            "vNext Function core must use only statically reviewed imports and cannot execute dynamic import()",
        )
    for capability in capabilities.values():
        function_export = capability.get("functionExport")
        tool_name = capability.get("toolName")
        if function_export and not re.search(rf"export\s+(?:async\s+function|const)\s+{re.escape(function_export)}\b", function_source):
            diagnostics.error("function-core/index.mjs", f"missing named export `{function_export}`")
        if tool_name and tool_name not in registrations_by_tool:
            diagnostics.error("mcp-tool/index.mjs", f"missing Tool registration `{tool_name}`")
        if tool_name:
            registration_entries = registrations_by_tool.get(tool_name, [])
            config = registration_entries[0][0] if len(registration_entries) == 1 else ""
            callback_parameters = registration_entries[0][1] if len(registration_entries) == 1 else None
            callback_body = registration_entries[0][2] if len(registration_entries) == 1 else None
            config_code = _mask_javascript(config, mask_strings=True)
            config_start = len(config_code) - len(config_code.lstrip())
            config_end = (
                _matching_delimiter(config_code, config_start, "{", "}")
                if config_start < len(config_code)
                else None
            )
            if (
                len(registration_entries) != 1
                or config_end is None
                or config_code[config_end + 1:].strip()
                or callback_body is None
            ):
                diagnostics.error("mcp-tool/index.mjs", f"Tool `{tool_name}` must use a direct object config and async callback")
            else:
                config_properties = _split_javascript_arguments(
                    config[config_start + 1:config_end]
                )
                config_property_names: list[str] = []
                for property_source in config_properties:
                    property_match = re.match(
                        r"\s*(?:(['\"])([^'\"]+)\1|([A-Za-z_$][\w$]*))\s*:",
                        property_source,
                    )
                    if property_match is not None:
                        config_property_names.append(
                            property_match.group(2) or property_match.group(3)
                        )
                expected_config_properties = {
                    "title",
                    "description",
                    "inputSchema",
                    "outputSchema",
                    "annotations",
                }
                if (
                    len(config_property_names) != len(config_properties)
                    or len(config_property_names) != len(set(config_property_names))
                    or set(config_property_names) != expected_config_properties
                ):
                    diagnostics.error(
                        "mcp-tool/index.mjs",
                        f"Tool `{tool_name}` config must contain exactly title, description, inputSchema, outputSchema, and annotations",
                    )
                inert_config_code = _mask_javascript(config, mask_strings=True)
                inert_config_commentless = _mask_javascript(config, mask_strings=False)
                forbidden_config_runtime = re.search(
                    r"\b(?:globalThis|window|document|createRequire)\s*(?:\.|\[)|"
                    r"\b(?:require|eval|Function)\s*\(|"
                    r"\bprocess\s*(?:\.|\[)|\bimport\s*\(",
                    inert_config_commentless,
                )
                if vnext and (
                    forbidden_config_runtime is not None
                    or _module_has_external_effect(
                        inert_config_code,
                        inert_config_commentless,
                    )
                    or any(
                        re.search(
                            rf"\b{re.escape(function_export)}\s*\(",
                            inert_config_code,
                        )
                        for function_export in canonical_function_exports
                    )
                ):
                    diagnostics.error(
                        "mcp-tool/index.mjs",
                        f"Tool `{tool_name}` config must be inert data and must not execute network, file, process, upload, or dispatch effects during registration",
                    )
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
                if vnext:
                    implementation = capability.get("implementation")
                    kind = implementation.get("kind") if isinstance(implementation, dict) else None
                    expected_open_world = kind == "http"
                    annotations_match = re.search(
                        r"\bannotations\s*:\s*\{([\s\S]*?)\}",
                        config,
                    )
                    open_world_match = (
                        re.search(r"\bopenWorldHint\s*:\s*(true|false)\b", annotations_match.group(1))
                        if annotations_match
                        else None
                    )
                    observed_open_world = open_world_match.group(1) == "true" if open_world_match else None
                    if observed_open_world is not expected_open_world:
                        diagnostics.error(
                            "mcp-tool/index.mjs",
                            f"Tool `{tool_name}` annotations.openWorldHint must be "
                            f"{'true' if expected_open_world else 'false'} for its {kind} Function",
                        )
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
    if vnext:
        _validate_vnext_function_runtime(
            function_source,
            capabilities,
            effective_runtime_origins,
            diagnostics,
        )
    if "structuredContent" not in mcp_source or "isError" not in mcp_source:
        diagnostics.error("mcp-tool/index.mjs", "must implement structured success and Tool execution errors")
    if vnext:
        for capability in capabilities.values():
            error_contract = capability.get("errorContract")
            if not isinstance(error_contract, dict) or error_contract.get("format") != "structured":
                continue
            tool_name = capability.get("toolName", "unknown")
            for path_name in ("codePath", "messagePath", "detailsPath", "retryabilityPath"):
                path = error_contract.get(path_name)
                if not isinstance(path, list):
                    continue
                for segment in path:
                    if isinstance(segment, str) and segment and not re.search(
                        rf"(?<![A-Za-z0-9_$]){re.escape(segment)}(?![A-Za-z0-9_$])",
                        mcp_source + "\n" + normalizer_source,
                    ):
                        diagnostics.error(
                            "mcp-tool/index.mjs",
                            f"Tool `{tool_name}` must expose structured error field `{segment}`",
                        )
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
    runtime_imports = {
        first or second or third
        for first, second, third in re.findall(
            r"\bfrom\s*['\"]([^'\"]+)['\"]|"
            r"\bimport\s*['\"]([^'\"]+)['\"]|"
            r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            runtime_source,
        )
        if first or second or third
    }
    for specifier in runtime_imports:
        if specifier and not specifier.startswith("node:") and not specifier.startswith("./"):
            diagnostics.error("mcp-tool/runtime.mjs", f"bundled runtime has unresolved third-party import `{specifier}`")
        if vnext and specifier.startswith("./"):
            diagnostics.error(
                "mcp-tool/runtime.mjs",
                f"vNext bundled runtime must be one self-contained file and cannot defer code to relative import `{specifier}`",
            )
        if vnext and specifier in RUNTIME_EFFECTFUL_NODE_MODULES:
            diagnostics.error(
                "mcp-tool/runtime.mjs",
                f"bundled runtime must not import effectful Node module `{specifier}`; business I/O belongs behind a Canonical Function dry-run boundary",
            )
    if vnext:
        runtime_code = _mask_javascript(runtime_source, mask_strings=True)
        runtime_commentless = _mask_javascript(runtime_source, mask_strings=False)
        if re.search(r"\bimport\s*\(", runtime_code):
            diagnostics.error(
                "mcp-tool/runtime.mjs",
                "vNext bundled runtime must be one self-contained file and cannot execute dynamic import()",
            )
        top_level_runtime_effects = [
            *re.finditer(r"\b(?:globalThis\s*\.\s*)?fetch\s*\(", runtime_code),
            *re.finditer(r"\bnew\s+(?:WebSocket|EventSource)\s*\(", runtime_code),
            *COMPUTED_NETWORK_CALL_PATTERN.finditer(runtime_commentless),
            *re.finditer(r"\bprocess\s*\.\s*(?:exit|kill)\s*\(", runtime_code),
            *re.finditer(r"\bprocess\s*\.\s*getBuiltinModule\s*\(", runtime_code),
        ]
        if top_level_runtime_effects:
            diagnostics.error(
                "mcp-tool/runtime.mjs",
                "the stdio-only bundled runtime must not contain client-network or process effects; business I/O belongs behind Canonical Functions",
            )
    if "McpServer" not in mcp_source or "StdioServerTransport" not in mcp_source:
        diagnostics.error("mcp-tool/index.mjs", "strict-export-v1 requires McpServer and StdioServerTransport")
    literal_registrations = [tool_name for tool_name, _, _, _ in registrations]
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
    if vnext:
        function_import = re.search(
            r"import\s*\{([^}]+)\}\s*from\s*['\"]\.\./function-core/index\.mjs['\"]",
            _mask_javascript(mcp_source, mask_strings=False),
            re.DOTALL,
        )
        directly_imported_exports = {
            item.strip()
            for item in function_import.group(1).split(",")
            if function_import and re.fullmatch(r"[A-Za-z_$][\w$]*", item.strip())
        } if function_import else set()
        for capability in capabilities.values():
            function_export = capability.get("functionExport")
            tool_name = capability.get("toolName", "unknown")
            if isinstance(function_export, str) and function_export not in directly_imported_exports:
                diagnostics.error(
                    "mcp-tool/index.mjs",
                    f"Tool `{tool_name}` must directly import Canonical Function export `{function_export}`",
                )
        function_exports = {
            capability.get("functionExport")
            for capability in capabilities.values()
            if isinstance(capability.get("functionExport"), str)
        }
        function_ranges = _exported_function_body_ranges(
            function_source,
            {item for item in function_exports if isinstance(item, str)},
        )
        function_top_code, function_top_commentless = _masked_out_ranges(
            function_source,
            function_ranges,
        )
        if _module_has_external_effect(
            function_top_code,
            function_top_commentless,
        ) or any(
            re.search(
                rf"\b{re.escape(function_export)}\s*\(",
                function_top_code,
            )
            for function_export in function_exports
        ):
            diagnostics.error(
                "function-core/index.mjs",
                "module initialization and helper definitions must not invoke a Canonical Function or perform network, file, process, upload, or dispatch side effects outside its named Function body",
            )

        mcp_import_specifiers = {
            first or second
            for first, second in re.findall(
                r"\bfrom\s*['\"]([^'\"]+)['\"]|\bimport\s*['\"]([^'\"]+)['\"]",
                mcp_source,
            )
            if first or second
        }
        allowed_mcp_imports = {
            "./runtime.mjs",
            "../function-core/index.mjs",
            "../portable-error-normalizer.mjs",
        }
        unexpected_mcp_imports = mcp_import_specifiers - allowed_mcp_imports
        if unexpected_mcp_imports:
            diagnostics.error(
                "mcp-tool/index.mjs",
                "vNext MCP adapters may import only the reviewed runtime, Canonical Functions, and error normalizer; unsupported imports: "
                + ", ".join(sorted(unexpected_mcp_imports)),
            )
        if re.search(r"\bimport\s*\(", _mask_javascript(mcp_source, mask_strings=True)):
            diagnostics.error(
                "mcp-tool/index.mjs",
                "vNext MCP adapter must use only statically reviewed imports and cannot execute dynamic import()",
            )
        mcp_commentless = _mask_javascript(mcp_source, mask_strings=False)
        mcp_code = _mask_javascript(mcp_source, mask_strings=True)
        registration_ranges: list[tuple[int, int]] = []
        for registration in re.finditer(r"\.\s*registerTool\s*\(", mcp_code):
            opening = mcp_code.find("(", registration.start(), registration.end())
            closing = _matching_delimiter(mcp_code, opening, "(", ")")
            if closing is not None:
                semicolon = closing + 1
                while semicolon < len(mcp_code) and mcp_code[semicolon].isspace():
                    semicolon += 1
                if semicolon < len(mcp_code) and mcp_code[semicolon] == ";":
                    semicolon += 1
                registration_ranges.append((registration.start(), semicolon))
        mcp_top_code, mcp_top_commentless = _masked_out_ranges(
            mcp_source,
            registration_ranges,
        )
        allowed_connect = re.search(
            r"await\s+server\s*\.\s*connect\s*\(\s*new\s+StdioServerTransport\s*\(\s*\)\s*\)\s*;?",
            mcp_top_code,
        )
        if allowed_connect is not None:
            mcp_top_code, mcp_top_commentless = _masked_out_ranges(
                mcp_source,
                registration_ranges + [(allowed_connect.start(), allowed_connect.end())],
            )
        if _module_has_external_effect(mcp_top_code, mcp_top_commentless) or any(
            re.search(
                rf"\b{re.escape(function_export)}\s*\(",
                mcp_top_code,
            )
            for function_export in function_exports
        ):
            diagnostics.error(
                "mcp-tool/index.mjs",
                "module initialization must not invoke a Canonical Function or perform network, file, process, upload, or dispatch side effects before the Tool dry-run boundary",
            )
        capability_by_tool = {
            capability.get("toolName"): capability
            for capability in capabilities.values()
            if isinstance(capability.get("toolName"), str)
        }
        for tool_name, _, callback_parameters, callback_body in registrations:
            expected_export = capability_by_tool.get(tool_name, {}).get("functionExport")
            if (
                isinstance(expected_export, str)
                and callback_parameters is not None
                and callback_body is not None
            ):
                _validate_vnext_tool_callback(
                    tool_name,
                    callback_parameters,
                    callback_body,
                    expected_export,
                    {item for item in function_exports if isinstance(item, str)},
                    dry_run_variable,
                    (
                        capability_by_tool.get(tool_name, {}).get("operationPolicy")
                        if isinstance(
                            capability_by_tool.get(tool_name, {}).get("operationPolicy"),
                            dict,
                        )
                        else None
                    ),
                    (
                        operation_summary_for_capability(
                            capability_by_tool.get(tool_name, {})
                        )
                        if isinstance(
                            capability_by_tool.get(tool_name, {}).get("operationPolicy"),
                            dict,
                        )
                        else None
                    ),
                    diagnostics,
                )
    if dry_run_variable:
        dry_run_guard = rf"if\s*\(\s*process\.env\.{re.escape(dry_run_variable)}\s*===\s*['\"]1['\"]\s*\)"
        if not re.search(dry_run_guard, _mask_javascript(mcp_source, mask_strings=False)):
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
                {
                    "capabilityId": item.get("capabilityId"),
                    "decision": item_decision(item),
                    "reasons": list(item.get("reasons", [])),
                    "issueRefs": [
                        review_item.get("issueRef")
                        for review_item in item.get("reviewItems", [])
                        if isinstance(review_item, dict)
                        and isinstance(review_item.get("issueRef"), str)
                    ],
                }
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
    vnext = (root / "canonical-contract.json").is_file()
    base_files = VNEXT_BASE_FILES if vnext else LEGACY_BASE_FILES
    required = base_files if pre_finalize else base_files | FINAL_FILES
    for relative in sorted(required):
        if not (root / relative).is_file():
            diagnostics.error(relative, "required strict-export-v1 artifact is missing")
    if diagnostics.errors:
        return None
    profile = read_json(root / "export-profile.json", diagnostics)
    allowed_origins, dry_run, _ = validate_profile(profile, diagnostics, vnext=vnext)
    canonical = read_json(root / "canonical-contract.json", diagnostics) if vnext else None
    bundle = read_json(root / "capability-bundle.json", diagnostics)
    mirrored = read_json(root / "function-core/capability-bundle.json", diagnostics)
    if bundle != mirrored:
        diagnostics.error("function-core/capability-bundle.json", "must exactly mirror capability-bundle.json")
    capabilities = validate_bundle(bundle, allowed_origins, diagnostics)
    validate_draft(root, bundle, capabilities, diagnostics, vnext=vnext)
    validate_runtime(
        root,
        capabilities,
        dry_run,
        diagnostics,
        vnext=vnext,
        allowed_runtime_origins=allowed_origins if vnext else None,
        canonical_contract=canonical if vnext else None,
    )
    validate_documents(root, profile, capabilities, diagnostics, vnext=vnext)
    has_writes = any(capability.get("sideEffect") != "read" for capability in capabilities.values())
    if vnext:
        if (root / "PAGE.md").exists():
            diagnostics.error(
                "PAGE.md",
                "is a legacy-only artifact; vNext business context belongs in references/feature-context.md",
            )
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
