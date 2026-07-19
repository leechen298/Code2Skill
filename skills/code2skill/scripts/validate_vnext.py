#!/usr/bin/env python3
"""Deep validation for Code2Skill vNext portable contracts.

The legacy strict-export validator remains responsible for the node-stdio
runtime profile.  This module validates the portable, host-neutral contract
layer and proves that every derived view still agrees with its canonical
source.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from contract_model import (
    ContractError,
    derive_bundle,
    derive_consumer_requirements,
    derive_goal_contract,
    derive_host_compatibility,
    validate_canonical_contract,
    validate_source_topology,
    write_evidence_complete,
)
from derive_artifacts import derive_draft


VNEXT_FILES = {
    "source-topology.json",
    "canonical-contract.json",
    "goal-contract.json",
    "consumer-requirements.json",
    "host-profile.json",
    "host-compatibility-report.json",
    "verification-matrix.json",
}
CRITICAL_WRITE_ROLES = {
    "data-contract",
    "validation",
    "business-rule",
    "authorization",
    "identity",
    "tenant",
    "persistence",
    "idempotency",
    "unknown-outcome",
}
INFORMATION_CLASSES = {
    "required",
    "optional",
    "requiredWhen",
    "derived",
    "dynamic",
    "attachment",
}
SOURCE_KINDS = {
    "user",
    "trusted-host-context",
    "upstream-tool",
    "derived-calculation",
    "host-approved-attachment",
    "bounded-content",
}
CONDITION_OPERATORS = {
    "equals",
    "not-equals",
    "in",
    "not-in",
    "present",
    "absent",
    "non-empty",
    "empty",
    "gt",
    "gte",
    "lt",
    "lte",
    "and",
    "or",
    "not",
}
BRAND_TOKENS = {
    "codex",
    "kimi",
    "claude",
    "openclaw",
    "hermes-agent",
    "chatgpt",
}
HEX64 = re.compile(r"^[a-f0-9]{64}$")
TRANSIENT_VERIFICATION_REASONS = {
    "behavior-verification-pending",
    "runtime-verification-pending",
    "host-verification-pending",
    "canonical-verification-checks-pending",
    "workflow-bypass-verification-pending",
}
LOCAL_PATH_NAMES = re.compile(r"(?:^|_)(?:local_?)?(?:file_?)?path(?:$|_)", re.IGNORECASE)


def _read_json(path: Path, diagnostics: Any) -> dict[str, Any] | None:
    if not path.is_file():
        diagnostics.error(path.name, "required vNext artifact is missing")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        diagnostics.error(path.name, f"invalid JSON: {error}")
        return None
    if not isinstance(value, dict):
        diagnostics.error(path.name, "must contain a JSON object")
        return None
    return value


def _json_equal(actual: Any, expected: Any, location: str, diagnostics: Any) -> None:
    if actual != expected:
        diagnostics.error(location, "must be deterministically derived from canonical-contract.json")


def _safe_relative_path(value: Any, location: str, diagnostics: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.error(location, "must be a non-empty portable relative path")
        return None
    if "\\" in value or "\x00" in value or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        diagnostics.error(location, "must not contain a URI, backslash, or NUL")
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        diagnostics.error(location, "must be relative and must not traverse outside its declared source root")
        return None
    return path


def _locator_path(locator: str) -> str:
    """Return the root-relative file portion of a portable evidence locator."""

    return locator.split("#", 1)[0].split(":", 1)[0]


def _known_evidence(contract: dict[str, Any]) -> set[str]:
    return {
        item.get("evidenceId")
        for item in contract.get("evidenceCatalog", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    }


def _validate_evidence_refs(
    value: Any,
    known: set[str],
    location: str,
    diagnostics: Any,
    *,
    required: bool = True,
) -> list[str]:
    if not isinstance(value, list):
        diagnostics.error(location, "must be an array of canonical evidence IDs")
        return []
    if required and not value:
        diagnostics.error(location, "must contain at least one evidence ID")
    refs: list[str] = []
    for index, ref in enumerate(value):
        if not isinstance(ref, str) or not ref:
            diagnostics.error(f"{location}[{index}]", "must be a non-empty evidence ID")
        elif ref not in known:
            diagnostics.error(f"{location}[{index}]", f"references unknown evidence `{ref}`")
        else:
            refs.append(ref)
    return refs


def _condition_fields(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    result: set[str] = set()
    field = value.get("field")
    if isinstance(field, str):
        result.add(field)
    path = value.get("path")
    if isinstance(path, list) and path and isinstance(path[0], str):
        result.add(path[0])
    for key in ("conditions", "operands"):
        children = value.get(key)
        if isinstance(children, list):
            for child in children:
                result.update(_condition_fields(child))
    operand = value.get("condition")
    if isinstance(operand, dict):
        result.update(_condition_fields(operand))
    return result


def _validate_condition(
    value: Any,
    input_names: set[str],
    known_evidence: set[str],
    location: str,
    diagnostics: Any,
) -> None:
    if not isinstance(value, dict):
        diagnostics.error(location, "must contain machine-readable condition objects")
        return
    operator = value.get("operator")
    if operator not in CONDITION_OPERATORS:
        diagnostics.error(f"{location}.operator", f"must be one of {sorted(CONDITION_OPERATORS)}")
    fields = _condition_fields(value)
    if not fields:
        diagnostics.error(location, "must reference at least one input field")
    for field in fields:
        if field not in input_names:
            diagnostics.error(location, f"references unknown input `{field}`")
    if "evidenceRefs" in value:
        _validate_evidence_refs(value.get("evidenceRefs"), known_evidence, f"{location}.evidenceRefs", diagnostics)


def _validate_input_path(value: Any, input_names: set[str], location: str, diagnostics: Any) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        diagnostics.error(location, "must be a non-empty input path")
    elif value[0] not in input_names:
        diagnostics.error(location, f"references unknown input `{value[0]}`")


def _validate_constraint_shape(
    constraint: dict[str, Any],
    input_names: set[str],
    location: str,
    diagnostics: Any,
) -> None:
    kind = constraint.get("kind")
    if kind == "forbidden-shape":
        _validate_input_path(constraint.get("path"), input_names, f"{location}.path", diagnostics)
        predicate = constraint.get("predicate")
        if not isinstance(predicate, dict) or predicate.get("operator") not in {"absent", "empty"}:
            diagnostics.error(f"{location}.predicate", "forbidden shapes need an absent or empty predicate")
    elif kind == "cross-field":
        if "if" in constraint or "then" in constraint:
            for key in ("if", "then"):
                condition = constraint.get(key)
                if not isinstance(condition, dict):
                    diagnostics.error(f"{location}.{key}", "must be a machine-readable condition")
                    continue
                _validate_input_path(condition.get("path"), input_names, f"{location}.{key}.path", diagnostics)
                if condition.get("operator") not in CONDITION_OPERATORS:
                    diagnostics.error(f"{location}.{key}.operator", "has an invalid condition operator")
        else:
            for key in ("left", "right"):
                operand = constraint.get(key)
                if not isinstance(operand, dict):
                    diagnostics.error(f"{location}.{key}", "must be an operand object")
                    continue
                source = operand.get("source")
                path = operand.get("path")
                if source in {"input", "canonicalDigest"}:
                    _validate_input_path(path, input_names, f"{location}.{key}.path", diagnostics)
                elif source not in {"validationGrant", "confirmationGrant", "attachmentGrant", "trustedContext"}:
                    diagnostics.error(f"{location}.{key}.source", "has an invalid protected source")
                elif not isinstance(path, list) or not path:
                    diagnostics.error(f"{location}.{key}.path", "must be a non-empty protected value path")
            if constraint.get("operator") not in {"equals", "not-equals"}:
                diagnostics.error(f"{location}.operator", "cross-field comparison must be equals or not-equals")
    elif kind == "grant-binding":
        fields = constraint.get("fields")
        required = {"subject", "session", "target", "payloadDigest"}
        if not isinstance(fields, list) or not required <= set(fields):
            diagnostics.error(f"{location}.fields", "grant bindings must include subject, session, target, and payloadDigest")
    else:
        diagnostics.error(f"{location}.kind", "must be forbidden-shape, cross-field, or grant-binding")


def _validate_source_topology_and_evidence(
    topology: dict[str, Any],
    contract: dict[str, Any],
    source_root: Path,
    source_maps: dict[str, Path],
    diagnostics: Any,
) -> None:
    topology_id = topology.get("topologyId")
    if contract.get("sourceTopologyRef") not in {"source-topology.json", topology_id}:
        diagnostics.error(
            "canonical-contract.sourceTopologyRef",
            "must reference source-topology.json or its topologyId",
        )

    sources: dict[str, dict[str, Any]] = {}
    resolved_roots: dict[str, Path] = {}
    for index, source in enumerate(topology.get("sources", [])):
        if not isinstance(source, dict) or not isinstance(source.get("sourceId"), str):
            continue
        source_id = source["sourceId"]
        sources[source_id] = source
        relative_root = _safe_relative_path(
            source.get("root"),
            f"source-topology.sources[{index}].root",
            diagnostics,
        )
        if relative_root is None:
            continue
        available = source.get("availability") in {"available", "partially-available"}
        if source_maps and available:
            mapped = source_maps.get(source_id)
            if mapped is None:
                diagnostics.error(
                    f"source-topology.sources[{index}].sourceId",
                    "every available source needs an explicit --source-map sourceId=/authorized/root mapping",
                )
                continue
            resolved = mapped.resolve()
        elif source_maps:
            continue
        else:
            resolved = (source_root / relative_root).resolve()
        resolved_roots[source_id] = resolved
        if available:
            if source.get("searched") is not True:
                diagnostics.error(
                    f"source-topology.sources[{index}].searched",
                    "an available source must be searched before it can support canonical facts",
                )
            if not resolved.is_dir():
                diagnostics.error(
                    f"source-topology.sources[{index}].root",
                    "declared available source root does not exist in its authorized mapping",
                )

    for index, evidence in enumerate(contract.get("evidenceCatalog", [])):
        if not isinstance(evidence, dict):
            continue
        source_id = evidence.get("sourceId")
        location = f"canonical-contract.evidenceCatalog[{index}]"
        source = sources.get(source_id)
        if source is None:
            continue
        locator = evidence.get("locator")
        relative = _safe_relative_path(
            _locator_path(locator) if isinstance(locator, str) else locator,
            f"{location}.locator",
            diagnostics,
        )
        if relative is None:
            continue
        if source.get("availability") not in {"available", "partially-available"}:
            if evidence.get("assertionLevel") == "fact":
                diagnostics.error(location, "fact evidence cannot come from an unavailable source")
            continue
        source_path = resolved_roots.get(str(source_id))
        if source_path is not None:
            authorized_root = source_path.resolve()
            candidate = (authorized_root / relative).resolve()
            try:
                candidate.relative_to(authorized_root)
            except ValueError:
                diagnostics.error(
                    f"{location}.locator",
                    "resolves through a symlink outside the declared authorized source root",
                )
                continue
            if not candidate.is_file():
                diagnostics.error(
                    f"{location}.locator",
                    "does not resolve to a file inside the declared authorized source root",
                )


def _validate_information_model(contract: dict[str, Any], diagnostics: Any) -> None:
    known_evidence = _known_evidence(contract)
    capabilities = {
        item.get("capabilityId"): item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    for capability_index, capability in enumerate(contract.get("capabilities", [])):
        if not isinstance(capability, dict):
            continue
        capability_id = capability.get("capabilityId", f"index-{capability_index}")
        location = f"canonical-contract.capabilities[{capability_index}]"
        inputs = [item for item in capability.get("inputs", []) if isinstance(item, dict)]
        input_names = {item.get("name") for item in inputs if isinstance(item.get("name"), str)}
        if len(input_names) != len(inputs):
            diagnostics.error(f"{location}.inputs", "input names must be unique non-empty strings")
        for input_index, item in enumerate(inputs):
            input_location = f"{location}.inputs[{input_index}]"
            name = item.get("name")
            information_class = item.get("informationClass")
            if information_class not in INFORMATION_CLASSES:
                diagnostics.error(
                    f"{input_location}.informationClass",
                    f"must be one of {sorted(INFORMATION_CLASSES)}",
                )
            strategies = item.get("sourceStrategies")
            if not isinstance(strategies, list) or not strategies:
                diagnostics.error(f"{input_location}.sourceStrategies", "must contain at least one acquisition strategy")
                strategies = []
            for strategy_index, strategy in enumerate(strategies):
                strategy_location = f"{input_location}.sourceStrategies[{strategy_index}]"
                strategy_kind = strategy if isinstance(strategy, str) else strategy.get("kind") if isinstance(strategy, dict) else None
                if strategy_kind not in SOURCE_KINDS:
                    diagnostics.error(strategy_location, f"must be one of {sorted(SOURCE_KINDS)}")
                    continue
                provider = strategy.get("capabilityId") if isinstance(strategy, dict) else None
                if strategy_kind == "upstream-tool" and isinstance(strategy, dict):
                    if provider not in capabilities:
                        diagnostics.error(strategy_location, "must reference a declared provider capability")
                    if not isinstance(strategy.get("outputPath"), list) or not strategy.get("outputPath"):
                        diagnostics.error(strategy_location, "capability-output needs a non-empty outputPath")
            if information_class == "derived" and any(
                strategy == "user" or (isinstance(strategy, dict) and strategy.get("kind") == "user")
                for strategy in strategies
            ):
                diagnostics.error(input_location, "derived information cannot be accepted as arbitrary user input")
            if information_class == "attachment" and any(
                (strategy if isinstance(strategy, str) else strategy.get("kind") if isinstance(strategy, dict) else None)
                not in {"host-approved-attachment", "bounded-content", "upstream-tool", "trusted-host-context"}
                for strategy in strategies
            ):
                diagnostics.error(input_location, "attachment inputs require approved references, bounded content, or upload output")
            if isinstance(name, str) and LOCAL_PATH_NAMES.search(name):
                diagnostics.error(f"{input_location}.name", "public inputs must not accept arbitrary local file paths")

            required_when = item.get("requiredWhen", [])
            forbidden_when = item.get("forbiddenWhen", [])
            if not isinstance(required_when, list):
                diagnostics.error(f"{input_location}.requiredWhen", "must be an array")
                required_when = []
            if not isinstance(forbidden_when, list):
                diagnostics.error(f"{input_location}.forbiddenWhen", "must be an array")
                forbidden_when = []
            if required_when:
                if item.get("required") is True:
                    diagnostics.error(input_location, "a conditionally required input cannot also be unconditionally required")
                if information_class != "requiredWhen":
                    diagnostics.error(f"{input_location}.informationClass", "conditional requiredness must be classified as requiredWhen")
                for condition_index, condition in enumerate(required_when):
                    _validate_condition(
                        condition,
                        input_names,
                        known_evidence,
                        f"{input_location}.requiredWhen[{condition_index}]",
                        diagnostics,
                    )
            elif information_class == "requiredWhen":
                diagnostics.error(f"{input_location}.requiredWhen", "requiredWhen information must declare at least one activation condition")
            if forbidden_when:
                if item.get("required") is True:
                    diagnostics.error(input_location, "an unconditionally required input cannot also be conditionally forbidden")
                for condition_index, condition in enumerate(forbidden_when):
                    _validate_condition(
                        condition,
                        input_names,
                        known_evidence,
                        f"{input_location}.forbiddenWhen[{condition_index}]",
                        diagnostics,
                    )
            if item.get("required") is True and information_class not in {"required", "dynamic", "derived", "attachment"}:
                diagnostics.error(f"{input_location}.informationClass", "unconditionally required inputs need a matching information classification")

            value_domain = item.get("valueDomain")
            if not isinstance(value_domain, dict):
                diagnostics.error(f"{input_location}.valueDomain", "must be an object")
                continue
            domain_kind = value_domain.get("kind")
            if domain_kind == "dynamic":
                provider = value_domain.get("sourceCapabilityId")
                if provider not in capabilities:
                    diagnostics.error(f"{input_location}.valueDomain", "dynamic domain must name a provider capability")
                elif information_class == "dynamic" and capabilities[provider].get("sideEffect") != "read":
                    diagnostics.error(f"{input_location}.valueDomain", "dynamic domains must come from a read capability")
                if any(key in value_domain for key in ("values", "enum", "options")):
                    diagnostics.error(
                        f"{input_location}.valueDomain",
                        "must not freeze one observed dynamic response into static values",
                    )
                freshness = value_domain.get("freshness") or item.get("freshness")
                if not isinstance(freshness, dict):
                    diagnostics.error(f"{input_location}.valueDomain.freshness", "dynamic values need scope and invalidation rules")
                else:
                    refresh = freshness.get("refreshWhen") or freshness.get("invalidatedBy")
                    if not isinstance(refresh, list) or not refresh or any(not isinstance(reason, str) or not reason for reason in refresh):
                        diagnostics.error(f"{input_location}.valueDomain.freshness.refreshWhen", "must name identity/session/tenant/version invalidation events")
                    if not refresh and not freshness.get("ttlSeconds"):
                        diagnostics.error(
                            f"{input_location}.valueDomain.freshness",
                            "must declare expiry or invalidation conditions",
                        )
            elif domain_kind == "static":
                values = value_domain.get("values")
                if not isinstance(values, list) or not values:
                    diagnostics.error(f"{input_location}.valueDomain.values", "a static domain must contain source-proven values")
                _validate_evidence_refs(
                    value_domain.get("evidenceRefs"),
                    known_evidence,
                    f"{input_location}.valueDomain.evidenceRefs",
                    diagnostics,
                )
            elif domain_kind != "unconstrained":
                diagnostics.error(f"{input_location}.valueDomain.kind", "must be static, dynamic, or unconstrained")

        for constraint_index, constraint in enumerate(capability.get("constraints", [])):
            constraint_location = f"{location}.constraints[{constraint_index}]"
            if not isinstance(constraint, dict):
                diagnostics.error(constraint_location, "must be an object")
                continue
            if not isinstance(constraint.get("constraintId"), str) or not constraint.get("constraintId"):
                diagnostics.error(f"{constraint_location}.constraintId", "must be a stable identifier")
            if constraint.get("enforcement") not in {
                "runtime",
                "function-and-runtime",
                "runtime-before-dispatch",
                "schema",
                "function",
            }:
                diagnostics.error(f"{constraint_location}.enforcement", "must name an executable enforcement boundary")
            _validate_evidence_refs(
                constraint.get("evidenceRefs"),
                known_evidence,
                f"{constraint_location}.evidenceRefs",
                diagnostics,
            )
            _validate_constraint_shape(constraint, input_names, constraint_location, diagnostics)

        _validate_attachments(capability, location, diagnostics)
        _validate_operation_policy(capability, location, diagnostics)
        _validate_evidence_refs(capability.get("evidenceRefs"), known_evidence, f"{location}.evidenceRefs", diagnostics)
        if capability.get("missingEvidence") and capability.get("readiness") == "ready":
            diagnostics.error(location, "a capability with missing evidence cannot be ready")
        if capability.get("sideEffect") != "read" and not write_evidence_complete(capability):
            if capability.get("readiness") == "ready":
                diagnostics.error(location, "a write capability without complete fact-level evidence cannot be ready")
        if not isinstance(capability_id, str):
            diagnostics.error(f"{location}.capabilityId", "must be a string")


def _validate_attachments(capability: dict[str, Any], location: str, diagnostics: Any) -> None:
    attachments = capability.get("attachments")
    if not isinstance(attachments, dict):
        diagnostics.error(f"{location}.attachments", "must be an object")
        return
    mode = attachments.get("mode")
    if mode not in {"none", "host-approved-reference", "opaque-upload-results"}:
        diagnostics.error(f"{location}.attachments.mode", "must classify the attachment boundary")
        return
    if mode == "none":
        return
    forbidden = attachments.get("forbiddenInputs")
    if not isinstance(forbidden, list) or not {"local-path", "unverified-url"}.issubset(set(forbidden)):
        diagnostics.error(
            f"{location}.attachments.forbiddenInputs",
            "must forbid local paths and unverified URLs",
        )
    if mode == "host-approved-reference":
        accepted = attachments.get("acceptedInputs")
        if not isinstance(accepted, list) or not accepted or not set(accepted) <= {"opaque-host-grant", "bounded-content"}:
            diagnostics.error(
                f"{location}.attachments.acceptedInputs",
                "may accept only opaque Host grants or bounded content",
            )
        metadata = attachments.get("metadata")
        required_metadata = {"fileName", "mediaType", "sizeBytes", "sha256"}
        if (
            not isinstance(metadata, dict)
            or not required_metadata.issubset(set(metadata.get("required", [])))
            or not isinstance(metadata.get("maxSizeBytes"), int)
            or metadata.get("maxSizeBytes", 0) <= 0
        ):
            diagnostics.error(
                f"{location}.attachments.metadata",
                "must bind name, media type, size, SHA-256, and a positive size limit",
            )
        result = attachments.get("resultBinding")
        if (
            not isinstance(result, dict)
            or result.get("kind") != "opaque-token"
            or result.get("subjectScoped") is not True
            or result.get("sessionScoped") is not True
            or result.get("singleUse") is not True
        ):
            diagnostics.error(
                f"{location}.attachments.resultBinding",
                "upload results must be opaque, subject/session-bound, and single use",
            )


def _validate_operation_policy(capability: dict[str, Any], location: str, diagnostics: Any) -> None:
    policy = capability.get("operationPolicy")
    if not isinstance(policy, dict):
        diagnostics.error(f"{location}.operationPolicy", "must be an object")
        return
    side_effect = capability.get("sideEffect")
    if policy.get("sideEffect") != side_effect:
        diagnostics.error(f"{location}.operationPolicy.sideEffect", "must match capability.sideEffect")
    if side_effect == "read":
        if policy.get("confirmation") != "not-required":
            diagnostics.error(f"{location}.operationPolicy.confirmation", "read capabilities must not require trusted write confirmation")
        if policy.get("automaticRetry") != "read-only-bounded":
            diagnostics.error(f"{location}.operationPolicy.retry", "read retry policy must be bounded or never")
        if policy.get("unknownOutcome") != "not-applicable":
            diagnostics.error(f"{location}.operationPolicy.unknownOutcome", "read capabilities do not use write outcome reconciliation")
        return
    if policy.get("confirmation") not in {"trusted-confirmation-required", "upload-confirmation-required"}:
        diagnostics.error(f"{location}.operationPolicy.confirmation", "writes require trusted Host confirmation")
    if policy.get("automaticRetry") != "never":
        diagnostics.error(f"{location}.operationPolicy.retry", "writes must never retry automatically")
    if policy.get("unknownOutcome") not in {"stop-and-reconcile", "reconcile-before-any-retry"}:
        diagnostics.error(f"{location}.operationPolicy.unknownOutcome", "writes need an explicit unknown-outcome reconciliation policy")
    if not isinstance(policy.get("idempotency"), str) or not policy.get("idempotency"):
        diagnostics.error(f"{location}.operationPolicy.idempotency", "writes must declare idempotency or at-most-once behavior")


def _validate_outputs_and_evidence(contract: dict[str, Any], diagnostics: Any) -> None:
    known = _known_evidence(contract)
    for capability_index, capability in enumerate(contract.get("capabilities", [])):
        if not isinstance(capability, dict):
            continue
        location = f"canonical-contract.capabilities[{capability_index}]"
        outputs = capability.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            diagnostics.error(f"{location}.outputs", "must describe at least one independently useful result")
            continue
        seen_paths: set[tuple[str, ...]] = set()
        for output_index, output in enumerate(outputs):
            output_location = f"{location}.outputs[{output_index}]"
            if not isinstance(output, dict):
                diagnostics.error(output_location, "must be an object")
                continue
            path = output.get("path")
            if not isinstance(path, list) or not path or any(not isinstance(item, str) or not item for item in path):
                diagnostics.error(f"{output_location}.path", "must be a non-empty output path")
            else:
                key = tuple(path)
                if key in seen_paths:
                    diagnostics.error(f"{output_location}.path", "must be unique within the capability")
                seen_paths.add(key)
            _validate_evidence_refs(output.get("evidenceRefs"), known, f"{output_location}.evidenceRefs", diagnostics)
            domain = output.get("valueDomain")
            if isinstance(domain, dict) and domain.get("kind") == "dynamic":
                if any(key in domain for key in ("values", "enum", "options")):
                    diagnostics.error(output_location, "dynamic output domains must not freeze observed values")
                freshness = domain.get("freshness")
                if not isinstance(freshness, dict) or not freshness.get("refreshWhen"):
                    diagnostics.error(output_location, "dynamic output domains need freshness and invalidation rules")
        coverage = capability.get("evidenceCoverage")
        if not isinstance(coverage, dict):
            diagnostics.error(f"{location}.evidenceCoverage", "must be an object")
        else:
            for category, record in coverage.items():
                record_location = f"{location}.evidenceCoverage.{category}"
                if not isinstance(record, dict):
                    diagnostics.error(record_location, "must be an object")
                    continue
                if record.get("assertionLevel") not in {"fact", "inference", "unknown"}:
                    diagnostics.error(f"{record_location}.assertionLevel", "must classify confidence")
                _validate_evidence_refs(record.get("evidenceRefs"), known, f"{record_location}.evidenceRefs", diagnostics)


def _validate_conflicts_and_missing_sources(
    topology: dict[str, Any],
    contract: dict[str, Any],
    diagnostics: Any,
) -> None:
    conflicts = contract.get("conflicts")
    if not isinstance(conflicts, list):
        diagnostics.error(
            "canonical-contract.conflicts",
            "must be an array, including an empty array when the cross-source conflict audit found none",
        )
        conflicts = []
    known = _known_evidence(contract)
    capability_ids = {
        item.get("capabilityId")
        for item in contract.get("capabilities", [])
        if isinstance(item, dict)
    }
    unresolved_write_ids: set[str] = set()
    conflict_ids: set[str] = set()
    for index, conflict in enumerate(conflicts):
        location = f"canonical-contract.conflicts[{index}]"
        if not isinstance(conflict, dict):
            diagnostics.error(location, "must be an object")
            continue
        conflict_id = conflict.get("conflictId")
        if not isinstance(conflict_id, str) or not conflict_id:
            diagnostics.error(f"{location}.conflictId", "must be a stable identifier")
        elif conflict_id in conflict_ids:
            diagnostics.error(f"{location}.conflictId", "must be unique")
        else:
            conflict_ids.add(conflict_id)
        refs = _validate_evidence_refs(conflict.get("evidenceRefs"), known, f"{location}.evidenceRefs", diagnostics)
        if len(refs) < 2:
            diagnostics.error(f"{location}.evidenceRefs", "a source conflict must retain at least two disagreeing evidence records")
        affected = conflict.get("affectedCapabilityIds")
        if not isinstance(affected, list) or not affected:
            diagnostics.error(f"{location}.affectedCapabilityIds", "must identify affected capabilities")
            affected = []
        for capability_id in affected:
            if capability_id not in capability_ids:
                diagnostics.error(f"{location}.affectedCapabilityIds", f"references unknown capability `{capability_id}`")
        status = conflict.get("status")
        if status not in {"resolved", "unresolved"}:
            diagnostics.error(f"{location}.status", "must be resolved or unresolved")
        if status == "resolved":
            resolution = conflict.get("resolution")
            if not (
                isinstance(resolution, str) and resolution.strip()
                or isinstance(resolution, dict) and resolution.get("authoritativeEvidenceRefs")
            ):
                diagnostics.error(f"{location}.resolution", "resolved conflicts need an evidence-backed authority decision")
        elif status == "unresolved":
            unresolved_write_ids.update(str(item) for item in affected)

    critical_missing = False
    missing_sources = topology.get("missingSources", [])
    if isinstance(missing_sources, list):
        for missing in missing_sources:
            if not isinstance(missing, dict):
                continue
            roles = {str(item) for item in missing.get("semanticRoles", [])}
            if roles & (CRITICAL_WRITE_ROLES | {"side-effect", "transport-contract", "error-contract"}):
                critical_missing = True
    for source in topology.get("sources", []):
        if not isinstance(source, dict) or source.get("availability") in {"available", "partially-available"}:
            continue
        roles = {str(item) for item in source.get("semanticRoles", [])}
        if roles & (CRITICAL_WRITE_ROLES | {"side-effect", "transport-contract", "error-contract"}):
            critical_missing = True

    for index, capability in enumerate(contract.get("capabilities", [])):
        if not isinstance(capability, dict) or capability.get("sideEffect") == "read":
            continue
        capability_id = capability.get("capabilityId")
        if capability_id in unresolved_write_ids and capability.get("readiness") == "ready":
            diagnostics.error(
                f"canonical-contract.capabilities[{index}].readiness",
                "a write affected by an unresolved source conflict cannot be ready",
            )
        if critical_missing and capability.get("readiness") == "ready":
            diagnostics.error(
                f"canonical-contract.capabilities[{index}].readiness",
                "a write cannot be ready while critical authorized source roles are unavailable",
            )


def _validate_graph_and_goals(contract: dict[str, Any], diagnostics: Any) -> None:
    capability_ids = {
        item.get("capabilityId")
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    graph = contract.get("capabilityGraph")
    if not isinstance(graph, dict):
        return
    graph_ids = {
        item.get("capabilityId")
        for item in graph.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    graph_nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    if graph_ids != capability_ids or len(graph_nodes) != len(capability_ids):
        diagnostics.error("canonical-contract.capabilityGraph.nodes", "must cover every capability exactly once")
    workflow_entries = {
        item.get("entryCapabilityId")
        for item in contract.get("workflows", [])
        if isinstance(item, dict)
    }
    edge_keys: set[tuple[Any, ...]] = set()
    for edge_index, edge in enumerate(graph.get("edges", [])):
        if not isinstance(edge, dict):
            continue
        location = f"canonical-contract.capabilityGraph.edges[{edge_index}]"
        edge_key = (
            edge.get("fromCapabilityId"),
            edge.get("toCapabilityId"),
            edge.get("kind"),
            edge.get("composition"),
        )
        if edge_key in edge_keys:
            diagnostics.error(location, "duplicates an existing capability graph edge")
        edge_keys.add(edge_key)
        if edge.get("kind") == "hard-precondition" and edge.get("toCapabilityId") not in workflow_entries:
            diagnostics.error(location, "hard preconditions must terminate in a runtime-guarded write workflow")
        if edge.get("composition") == "derived":
            target = next(
                (item for item in contract.get("capabilities", []) if isinstance(item, dict) and item.get("capabilityId") == edge.get("toCapabilityId")),
                None,
            )
            if isinstance(target, dict) and target.get("sideEffect") != "read" and target.get("capabilityId") not in workflow_entries:
                diagnostics.error(location, "derived write compositions require the same deterministic guard as observed writes")

    goal_ids: set[str] = set()
    workflow_ids = {
        item.get("workflowId")
        for item in contract.get("workflows", [])
        if isinstance(item, dict)
    }
    for goal_index, goal in enumerate(contract.get("goals", [])):
        location = f"canonical-contract.goals[{goal_index}]"
        if not isinstance(goal, dict):
            diagnostics.error(location, "must be an object")
            continue
        goal_id = goal.get("goalId")
        if not isinstance(goal_id, str) or not goal_id:
            diagnostics.error(f"{location}.goalId", "must be a stable identifier")
        elif goal_id in goal_ids:
            diagnostics.error(f"{location}.goalId", "must be unique")
        else:
            goal_ids.add(goal_id)
        if any(key in goal for key in ("fixedSequence", "orderedSteps", "mandatoryTranscript")):
            diagnostics.error(location, "a Goal Contract must describe information and completion, not a rigid transcript")
        need_ids: set[str] = set()
        needs = goal.get("informationNeeds")
        if not isinstance(needs, list) or not needs:
            diagnostics.error(f"{location}.informationNeeds", "must contain information requirements")
            needs = []
        for need_index, need in enumerate(needs):
            need_location = f"{location}.informationNeeds[{need_index}]"
            if not isinstance(need, dict):
                diagnostics.error(need_location, "must be an object")
                continue
            information_id = need.get("informationId")
            if not isinstance(information_id, str) or not information_id:
                diagnostics.error(f"{need_location}.informationId", "must be a stable identifier")
            elif information_id in need_ids:
                diagnostics.error(f"{need_location}.informationId", "must be unique within the goal")
            else:
                need_ids.add(information_id)
            classification = need.get("classification")
            if classification not in {"required", "optional", "requiredWhen", "derived", "dynamic"}:
                diagnostics.error(f"{need_location}.classification", "must classify how the information is needed")
            if classification == "requiredWhen" and not isinstance(need.get("condition"), dict):
                diagnostics.error(f"{need_location}.condition", "conditional information needs an activation condition")
            sources = need.get("satisfiedBy")
            if not isinstance(sources, list) or not sources:
                diagnostics.error(f"{need_location}.satisfiedBy", "must declare how the information can be acquired")
                sources = []
            for source_index, source in enumerate(sources):
                source_location = f"{need_location}.satisfiedBy[{source_index}]"
                if not isinstance(source, dict) or source.get("kind") not in {"user", "trusted-host-context", "capability", "derived"}:
                    diagnostics.error(source_location, "has an invalid acquisition kind")
                elif source.get("kind") == "capability":
                    if source.get("capabilityId") not in capability_ids:
                        diagnostics.error(source_location, "references an unknown capability")
                    if not isinstance(source.get("outputPath"), list) or not source.get("outputPath"):
                        diagnostics.error(source_location, "capability acquisition needs an outputPath")
            if classification in {"dynamic", "derived", "requiredWhen"} and not isinstance(need.get("reuseWhile"), dict):
                diagnostics.error(f"{need_location}.reuseWhile", "must declare when acquired information remains reusable")
        for need_index, need in enumerate(needs):
            if not isinstance(need, dict) or need.get("classification") != "requiredWhen":
                continue
            condition = need.get("condition")
            condition_location = f"{location}.informationNeeds[{need_index}].condition"
            if not isinstance(condition, dict):
                continue
            path = condition.get("path")
            if not isinstance(path, list) or not path or path[0] not in need_ids:
                diagnostics.error(f"{condition_location}.path", "must reference a declared information need")
            if condition.get("operator") not in CONDITION_OPERATORS:
                diagnostics.error(f"{condition_location}.operator", "has an invalid operator")
        predicate = goal.get("completionPredicate")
        if not isinstance(predicate, dict) or not predicate.get("operator"):
            diagnostics.error(f"{location}.completionPredicate", "must be machine readable")
        elif predicate.get("operator") == "all-satisfied":
            ids = predicate.get("informationIds")
            if not isinstance(ids, list) or set(ids) != need_ids:
                diagnostics.error(f"{location}.completionPredicate.informationIds", "must cover the goal's information needs")
        elif predicate.get("operator") == "workflow-completed" and predicate.get("workflowId") not in workflow_ids:
            diagnostics.error(f"{location}.completionPredicate.workflowId", "must reference a declared workflow")
        elif predicate.get("operator") == "any-satisfied":
            ids = predicate.get("informationIds")
            if not isinstance(ids, list) or not ids or not set(ids) <= need_ids:
                diagnostics.error(f"{location}.completionPredicate.informationIds", "must name declared information needs")
        elif predicate.get("operator") not in {"all-satisfied", "workflow-completed", "any-satisfied"}:
            diagnostics.error(f"{location}.completionPredicate.operator", "is not an allowed completion predicate")
        policy = goal.get("agentPolicy")
        required_policy = {
            "acceptInformationInAnyOrder",
            "reuseFreshInformation",
            "askOnlyCurrentlyMissing",
            "skipUnnecessaryCapabilities",
            "stopWhenPredicateSatisfied",
        }
        if not isinstance(policy, dict) or any(policy.get(key) is not True for key in required_policy):
            diagnostics.error(
                f"{location}.agentPolicy",
                "must support information in any order, freshness reuse, minimal questions/calls, and explicit stopping",
            )
        required_ids = goal.get("requiredCapabilityIds", [])
        optional_ids = goal.get("optionalCapabilityIds", [])
        required_id_set: set[str] = set()
        optional_id_set: set[str] = set()
        if not isinstance(required_ids, list) or not isinstance(optional_ids, list):
            diagnostics.error(location, "requiredCapabilityIds and optionalCapabilityIds must be arrays")
        else:
            for field, values, seen in (
                ("requiredCapabilityIds", required_ids, required_id_set),
                ("optionalCapabilityIds", optional_ids, optional_id_set),
            ):
                for value_index, capability_id in enumerate(values):
                    value_location = f"{location}.{field}[{value_index}]"
                    if not isinstance(capability_id, str) or not capability_id:
                        diagnostics.error(value_location, "must be a non-empty capability ID")
                        continue
                    if capability_id in seen:
                        diagnostics.error(value_location, "duplicates a capability in the same goal field")
                    else:
                        seen.add(capability_id)
                    if capability_id not in capability_ids:
                        diagnostics.error(value_location, "references an unknown capability")
            overlap = required_id_set & optional_id_set
            if overlap:
                diagnostics.error(
                    location,
                    "a capability cannot be both required and optional for the same goal: "
                    + ", ".join(sorted(overlap)),
                )

        inferred_conditional_ids = {
            source.get("capabilityId")
            for need in needs
            if isinstance(need, dict) and need.get("classification") == "requiredWhen"
            for source in need.get("satisfiedBy", [])
            if isinstance(source, dict)
            and source.get("kind") == "capability"
            and source.get("capabilityId") in optional_id_set
        }
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict) or "conditional" not in str(edge.get("kind", "")):
                continue
            inferred_conditional_ids.update(
                capability_id
                for capability_id in (edge.get("fromCapabilityId"), edge.get("toCapabilityId"))
                if capability_id in optional_id_set
            )

        conditional_values = goal.get("conditionalCapabilityIds")
        if conditional_values is None:
            if inferred_conditional_ids:
                diagnostics.error(
                    f"{location}.conditionalCapabilityIds",
                    "must be declared for conditionally activated capabilities: "
                    + ", ".join(sorted(inferred_conditional_ids)),
                )
            conditional_values = []
        elif not isinstance(conditional_values, list):
            diagnostics.error(f"{location}.conditionalCapabilityIds", "must be an array")
            conditional_values = []

        seen_conditional: set[str] = set()
        for conditional_index, conditional in enumerate(conditional_values):
            conditional_location = f"{location}.conditionalCapabilityIds[{conditional_index}]"
            capability_id = (
                conditional
                if isinstance(conditional, str)
                else conditional.get("capabilityId") if isinstance(conditional, dict) else None
            )
            if not isinstance(capability_id, str) or not capability_id:
                diagnostics.error(conditional_location, "must name a non-empty capability ID")
                continue
            if capability_id not in capability_ids:
                diagnostics.error(conditional_location, "references an unknown capability")
            if capability_id in seen_conditional:
                diagnostics.error(conditional_location, "duplicates a conditional capability")
            else:
                seen_conditional.add(capability_id)
            if capability_id in required_id_set:
                diagnostics.error(conditional_location, "conditional capabilities cannot also be required")
            if capability_id not in optional_id_set:
                diagnostics.error(conditional_location, "conditional capabilities must also be optional")

            if isinstance(conditional, dict):
                condition = conditional.get("condition")
                if not isinstance(condition, dict):
                    diagnostics.error(f"{conditional_location}.condition", "must be machine readable")
                    continue
                condition_path = condition.get("path")
                if (
                    not isinstance(condition_path, list)
                    or not condition_path
                    or condition_path[0] not in need_ids
                ):
                    diagnostics.error(
                        f"{conditional_location}.condition.path",
                        "must reference a declared information need",
                    )
                if condition.get("operator") not in CONDITION_OPERATORS:
                    diagnostics.error(f"{conditional_location}.condition.operator", "has an invalid operator")
                continue

            if capability_id not in inferred_conditional_ids:
                diagnostics.error(
                    conditional_location,
                    "must be linked to a conditional information need or capability-graph edge",
                )

        undeclared_conditional_ids = inferred_conditional_ids - seen_conditional
        if undeclared_conditional_ids:
            diagnostics.error(
                f"{location}.conditionalCapabilityIds",
                "must declare conditionally activated capabilities: "
                + ", ".join(sorted(undeclared_conditional_ids)),
            )


def _validate_host_contracts(
    contract: dict[str, Any],
    consumer: dict[str, Any],
    host: dict[str, Any],
    compatibility: dict[str, Any],
    diagnostics: Any,
) -> None:
    expected_consumer = derive_consumer_requirements(contract)
    _json_equal(consumer, expected_consumer, "consumer-requirements.json", diagnostics)
    try:
        expected_compatibility = derive_host_compatibility(contract, expected_consumer, host)
    except ContractError as error:
        diagnostics.error("host-profile.json", str(error))
        return
    _json_equal(compatibility, expected_compatibility, "host-compatibility-report.json", diagnostics)
    if host.get("schemaVersion") != "vNext" or not isinstance(host.get("profileId"), str):
        diagnostics.error("host-profile.json", "must be a vNext generic capability profile")
    serialized = json.dumps(host, ensure_ascii=False).lower()
    for brand in BRAND_TOKENS:
        if brand in serialized:
            diagnostics.error("host-profile.json", "must describe generic Host facilities rather than bind to an Agent brand")
            break
    requirements = contract.get("consumerRequirements", {}).get("requirements", [])
    required_host_capabilities = {
        item.get("hostCapability")
        for item in requirements
        if isinstance(item, dict) and isinstance(item.get("hostCapability"), str)
    }
    host_capabilities = host.get("capabilities")
    if not isinstance(host_capabilities, dict):
        diagnostics.error("host-profile.capabilities", "must be an object")
        return
    if not required_host_capabilities <= set(host_capabilities):
        diagnostics.error("host-profile.capabilities", "must explicitly classify every required generic Host facility")
    for name, support in host_capabilities.items():
        if not isinstance(support, dict) or support.get("status") not in {"supported", "external-integration", "unsupported"}:
            diagnostics.error(f"host-profile.capabilities.{name}", "must declare supported, external-integration, or unsupported")


def _validate_workflows_and_runtime(root: Path, contract: dict[str, Any], diagnostics: Any) -> None:
    writes = {
        item.get("capabilityId"): item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and item.get("sideEffect") != "read"
    }
    workflows = [item for item in contract.get("workflows", []) if isinstance(item, dict)]
    workflow_by_entry = {item.get("entryCapabilityId"): item for item in workflows}
    if set(workflow_by_entry) != set(writes) or len(workflows) != len(writes):
        diagnostics.error(
            "canonical-contract.workflows",
            "must contain exactly one deterministic guard workflow for every write capability",
        )
    workflow_ids: set[str] = set()
    for index, workflow in enumerate(workflows):
        location = f"canonical-contract.workflows[{index}]"
        workflow_id = workflow.get("workflowId")
        if not isinstance(workflow_id, str) or not workflow_id:
            diagnostics.error(f"{location}.workflowId", "must be a stable identifier")
        elif workflow_id in workflow_ids:
            diagnostics.error(f"{location}.workflowId", "must be unique")
        else:
            workflow_ids.add(workflow_id)
        if workflow.get("kind") != "deterministic-write-guard":
            diagnostics.error(f"{location}.kind", "must be deterministic-write-guard")
        guard_asset = workflow.get("guardAsset")
        if not isinstance(guard_asset, str) or not guard_asset.startswith("portable-workflow-guard.mjs"):
            diagnostics.error(f"{location}.guardAsset", "must use the portable workflow guard contract")
        bindings = workflow.get("bindings")
        common_bindings = {"subject", "session", "target", "expiresAt", "singleUse"}
        if not isinstance(bindings, list) or not common_bindings <= set(bindings):
            diagnostics.error(f"{location}.bindings", "must bind subject, session, target, expiry, and single use")
        capability = writes.get(workflow.get("entryCapabilityId"), {})
        confirmation = capability.get("operationPolicy", {}).get("confirmation") if isinstance(capability, dict) else None
        if confirmation == "trusted-confirmation-required":
            required = {"payloadDigest", "validationGrantId", "confirmationGrantId"}
            if not isinstance(bindings, list) or not required <= set(bindings):
                diagnostics.error(f"{location}.bindings", "final writes must bind payload, validation, and confirmation grants")
        if confirmation == "upload-confirmation-required":
            required = {
                "attachmentGrantId",
                "confirmationGrantId",
                "fileName",
                "mediaType",
                "sizeBytes",
                "sha256",
            }
            if not isinstance(bindings, list) or not required <= set(bindings):
                diagnostics.error(
                    f"{location}.bindings",
                    "uploads must bind approved attachment metadata, Hash, grant, and confirmation",
                )
        if (
            isinstance(capability, dict)
            and capability.get("attachments", {}).get("mode") == "opaque-upload-results"
            and (not isinstance(bindings, list) or "attachmentGrantIds" not in bindings)
        ):
            diagnostics.error(f"{location}.bindings", "attachment-consuming writes must bind uploaded attachment grants")
        enforcement = workflow.get("enforcement")
        if (
            not isinstance(enforcement, dict)
            or enforcement.get("owner") != "mcp-session-runtime"
            or enforcement.get("mustCompleteBeforeDispatch") is not True
            or enforcement.get("rejectWithoutDispatch") is not True
        ):
            diagnostics.error(f"{location}.enforcement", "must be runtime-owned and reject before dispatch")
        if workflow.get("unknownOutcomePolicy") not in {
            "stop-and-reconcile-before-any-new-attempt",
            "reconcile-before-any-retry",
        }:
            diagnostics.error(f"{location}.unknownOutcomePolicy", "must prohibit automatic retries after uncertain writes")
        checks = workflow.get("verificationChecks")
        if not isinstance(checks, list) or not checks or not any("zero-dispatch" in str(item) for item in checks):
            diagnostics.error(f"{location}.verificationChecks", "must include executable zero-dispatch bypass checks")

    if not writes:
        return
    guard_path = root / "portable-workflow-guard.mjs"
    if not guard_path.is_file():
        diagnostics.error("portable-workflow-guard.mjs", "is required by every vNext write workflow")
        return
    guard_source = guard_path.read_text(encoding="utf-8")
    required_guard_tokens = {
        "canonicalPayloadDigest",
        "issueAttachmentGrant",
        "issueUploadConfirmationGrant",
        "issueValidationGrant",
        "issueConfirmationGrant",
        "dispatchOnce",
        "dispatchUploadOnce",
        "GRANT_ALREADY_USED",
        "EXPIRED_GRANT",
        "GRANT_BINDING_MISMATCH",
        "LOCAL_PATH_FORBIDDEN",
        "UNKNOWN_DISPATCH_OUTCOME",
        "automaticRetryAllowed = false",
    }
    for token in sorted(required_guard_tokens):
        if token not in guard_source:
            diagnostics.error("portable-workflow-guard.mjs", f"missing required enforcement behavior `{token}`")
    function_path = root / "function-core" / "index.mjs"
    mcp_path = root / "mcp-tool" / "index.mjs"
    function_source = function_path.read_text(encoding="utf-8") if function_path.is_file() else ""
    mcp_source = mcp_path.read_text(encoding="utf-8") if mcp_path.is_file() else ""
    runtime_sources = function_source + "\n" + mcp_source
    if "portable-workflow-guard.mjs" not in runtime_sources:
        diagnostics.error(
            "function-core/index.mjs",
            "write runtime must import and use portable-workflow-guard.mjs before dispatch",
        )
    if "PortableWorkflowGuard" not in runtime_sources:
        diagnostics.error(
            "function-core/index.mjs",
            "write runtime must use the portable workflow guard contract",
        )
    if re.search(r"new\s+PortableWorkflowGuard\s*\(", function_source):
        diagnostics.error(
            "function-core/index.mjs",
            "Function core must receive a session-isolated Guard from protected runtime context, not create per-call or shared state",
        )
    if re.search(
        r"(?:^|\n)\s*(?:const|let|var)\s+\w*[Gg]uard\w*\s*=\s*new\s+PortableWorkflowGuard\s*\(",
        runtime_sources,
    ):
        diagnostics.error(
            "function-core/index.mjs",
            "must not create one module-global Guard for unrelated subjects or sessions",
        )
    for capability_id, capability in writes.items():
        function_export = capability.get("functionExport")
        if not isinstance(function_export, str):
            continue
        function_match = re.search(
            rf"export\s+(?:async\s+function|const)\s+{re.escape(function_export)}\b([\s\S]*?)(?=\nexport\s+(?:async\s+function|const)|\Z)",
            function_source,
        )
        if function_match is None:
            continue
        function_body = function_match.group(1)
        dispatch_matches = list(re.finditer(r"\.\s*dispatch(?:Upload)?Once\s*\(", function_body))
        if len(dispatch_matches) != 1:
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must contain exactly one guarded dispatch",
            )
            continue
        dispatch_start = dispatch_matches[0].start()
        before_dispatch = function_body[:dispatch_start]
        side_effect_before_guard = re.search(
            r"(?:\bfetch\s*\(|\.fetch\s*\(|\.request\s*\(|\baxios\b|\bwriteFile\s*\(|\bunlink\s*\(|\bexec\s*\(|\bspawn\s*\()",
            before_dispatch,
        )
        if side_effect_before_guard:
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` performs a possible external side effect before its Guard",
            )
        statement_prefix = before_dispatch.rstrip()
        if not re.search(r"return\s+[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\s*$", statement_prefix):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must return the Guard dispatch as its write boundary",
            )


def _validate_executed_checks(
    value: Any,
    location: str,
    diagnostics: Any,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        diagnostics.error(location, "must be an array")
        return []
    valid: list[dict[str, Any]] = []
    for index, check in enumerate(value):
        check_location = f"{location}[{index}]"
        if not isinstance(check, dict):
            diagnostics.error(check_location, "must be an executed check object")
            continue
        check_valid = True
        if check.get("status") not in {"passed", "failed"}:
            diagnostics.error(f"{check_location}.status", "must be passed or failed")
            check_valid = False
        command = check.get("command")
        if not isinstance(command, str) or not command.strip():
            diagnostics.error(f"{check_location}.command", "must record a non-empty executed command")
            check_valid = False
        exit_code = check.get("exitCode")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code < 0:
            diagnostics.error(f"{check_location}.exitCode", "must be a non-negative integer")
            check_valid = False
        elif check.get("status") == "passed" and exit_code != 0:
            diagnostics.error(check_location, "a passed check must have exitCode=0")
            check_valid = False
        evidence_digest = check.get("evidenceHash", check.get("sha256"))
        if not isinstance(evidence_digest, str) or not HEX64.fullmatch(evidence_digest):
            diagnostics.error(
                f"{check_location}.evidenceHash",
                "must contain a SHA-256 evidenceHash or sha256 digest",
            )
            check_valid = False
        if check_valid:
            valid.append(check)
    return valid


def _declared_verification_reasons(value: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("reasons", "blockingReasons"):
        reasons = value.get(key, [])
        if isinstance(reasons, list):
            result.extend(reason for reason in reasons if isinstance(reason, str) and reason)
    return result


def _row_verification_reasons(
    row: dict[str, Any],
    location: str,
    diagnostics: Any,
) -> list[str]:
    if "reasons" not in row:
        return []
    reasons = row.get("reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) or not reason for reason in reasons
    ):
        diagnostics.error(f"{location}.reasons", "must contain non-empty reason strings")
        return []
    return reasons


def _validate_verification_matrix(
    contract: dict[str, Any],
    compatibility: dict[str, Any],
    matrix: dict[str, Any],
    pre_finalize: bool,
    diagnostics: Any,
) -> None:
    if matrix.get("schemaVersion") != "vNext" or matrix.get("contractId") != contract.get("contractId"):
        diagnostics.error("verification-matrix.json", "must identify the current vNext canonical contract")
    capability_ids = {
        item.get("capabilityId")
        for item in contract.get("capabilities", [])
        if isinstance(item, dict)
    }
    workflow_ids = {
        item.get("workflowId")
        for item in contract.get("workflows", [])
        if isinstance(item, dict)
    }
    rows = matrix.get("capabilities")
    workflow_rows = matrix.get("workflows")
    if (
        not isinstance(rows, list)
        or {item.get("capabilityId") for item in rows if isinstance(item, dict)} != capability_ids
        or len([item for item in rows if isinstance(item, dict)]) != len(capability_ids)
    ):
        diagnostics.error("verification-matrix.capabilities", "must cover every capability exactly once")
        rows = []
    if (
        not isinstance(workflow_rows, list)
        or {item.get("workflowId") for item in workflow_rows if isinstance(item, dict)} != workflow_ids
        or len([item for item in workflow_rows if isinstance(item, dict)]) != len(workflow_ids)
    ):
        diagnostics.error("verification-matrix.workflows", "must cover every hard workflow exactly once")
        workflow_rows = []
    compatibility_by_id = {
        item.get("capabilityId"): item.get("status")
        for item in compatibility.get("capabilityAssessments", [])
        if isinstance(item, dict)
    }
    contract_by_id = {
        item.get("capabilityId"): item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict)
    }
    workflow_by_id = {
        item.get("workflowId"): item
        for item in contract.get("workflows", [])
        if isinstance(item, dict)
    }
    workflow_row_by_id = {
        item.get("workflowId"): item for item in workflow_rows if isinstance(item, dict)
    }
    unresolved_by_capability: set[str] = set()
    for conflict in contract.get("conflicts", []):
        if isinstance(conflict, dict) and conflict.get("status") == "unresolved":
            affected = conflict.get("affectedCapabilityIds", [])
            if isinstance(affected, list):
                unresolved_by_capability.update(
                    item for item in affected if isinstance(item, str)
                )

    for row_index, row in enumerate(workflow_rows):
        if not isinstance(row, dict):
            continue
        location = f"verification-matrix.workflows[{row_index}]"
        status = row.get("status")
        if not isinstance(status, dict) or any(
            not isinstance(status.get(field), bool)
            for field in (
                "generated",
                "behaviorVerified",
                "runtimeVerified",
                "hostVerified",
                "bypassVerified",
                "requiresReview",
                "blocked",
            )
        ):
            diagnostics.error(f"{location}.status", "must contain boolean per-workflow verification states")
            continue
        if status.get("generated") is not True:
            diagnostics.error(f"{location}.status.generated", "an emitted workflow must be generated")
        if status.get("bypassVerified") != status.get("behaviorVerified"):
            diagnostics.error(f"{location}.status", "workflow behavior verification must be the zero-dispatch bypass verification")
        if status.get("runtimeVerified") and not status.get("bypassVerified"):
            diagnostics.error(f"{location}.status.runtimeVerified", "workflow runtime verification requires passed bypass behavior")
        if status.get("blocked") and any(
            status.get(field) for field in ("behaviorVerified", "runtimeVerified", "hostVerified", "bypassVerified")
        ):
            diagnostics.error(f"{location}.status", "blocked workflows cannot be marked verified")
        workflow = workflow_by_id.get(row.get("workflowId"), {})
        entry_id = workflow.get("entryCapabilityId") if isinstance(workflow, dict) else None
        if status.get("hostVerified") and compatibility_by_id.get(entry_id) != "enabled":
            diagnostics.error(f"{location}.status.hostVerified", "workflow Host verification requires an enabled entry capability")
        checks = row.get("checks")
        valid_checks: list[dict[str, Any]] = []
        if not isinstance(checks, list):
            diagnostics.error(f"{location}.checks", "must be an array")
        elif not pre_finalize:
            valid_checks = _validate_executed_checks(checks, f"{location}.checks", diagnostics)
        if not pre_finalize and (status.get("behaviorVerified") or status.get("runtimeVerified")):
            if not any(
                check.get("status") == "passed"
                and (
                    check.get("layer") == "bypass"
                    or check.get("zeroDispatch") is True
                    or check.get("zeroExternalWrites") is True
                )
                for check in valid_checks
            ):
                diagnostics.error(f"{location}.checks", "verified workflows require passed zero-dispatch bypass evidence")

        reasons = _row_verification_reasons(row, location, diagnostics)
        persistent_reasons = [
            reason
            for reason in reasons + _declared_verification_reasons(workflow)
            if reason not in TRANSIENT_VERIFICATION_REASONS
        ]
        workflow_approved = (
            status.get("generated") is True
            and status.get("behaviorVerified") is True
            and status.get("bypassVerified") is True
            and status.get("runtimeVerified") is True
            and status.get("hostVerified") is True
            and compatibility_by_id.get(entry_id) == "enabled"
            and not persistent_reasons
            and status.get("blocked") is False
        )
        expected_review = status.get("blocked") is False and not workflow_approved
        if status.get("requiresReview") is not expected_review:
            diagnostics.error(
                f"{location}.status.requiresReview",
                "must be derived from workflow bypass, runtime, Host, blocking reasons, and blocked state",
            )

    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        location = f"verification-matrix.capabilities[{row_index}]"
        status = row.get("status")
        if not isinstance(status, dict):
            diagnostics.error(f"{location}.status", "must be an object")
            continue
        fields = ("generated", "behaviorVerified", "runtimeVerified", "hostVerified", "requiresReview", "blocked")
        if any(not isinstance(status.get(field), bool) for field in fields):
            diagnostics.error(f"{location}.status", "all verification states must be boolean")
            continue
        capability_id = row.get("capabilityId")
        capability = contract_by_id.get(capability_id, {})
        if status.get("generated") is not True:
            diagnostics.error(f"{location}.status.generated", "a matrix row for an emitted capability must be generated")
        if status.get("blocked") and any(status.get(field) for field in ("behaviorVerified", "runtimeVerified", "hostVerified")):
            diagnostics.error(f"{location}.status", "blocked capabilities cannot be marked verified")
        if status.get("hostVerified") and compatibility_by_id.get(capability_id) != "enabled":
            diagnostics.error(f"{location}.status.hostVerified", "Host verification requires an enabled compatibility assessment")
        if status.get("runtimeVerified") and not status.get("behaviorVerified"):
            diagnostics.error(f"{location}.status.runtimeVerified", "runtime verification cannot precede behavior verification")
        checks = row.get("checks")
        valid_checks: list[dict[str, Any]] = []
        if not isinstance(checks, list):
            diagnostics.error(f"{location}.checks", "must be an array")
        elif not pre_finalize:
            valid_checks = _validate_executed_checks(checks, f"{location}.checks", diagnostics)
        if not pre_finalize and any(status.get(field) for field in ("behaviorVerified", "runtimeVerified", "hostVerified")):
            if not any(check.get("status") == "passed" for check in valid_checks):
                diagnostics.error(f"{location}.checks", "verified states require capability-specific executed check evidence")

        workflow = next(
            (
                item
                for item in contract.get("workflows", [])
                if isinstance(item, dict) and item.get("entryCapabilityId") == capability_id
            ),
            None,
        )
        workflow_status: dict[str, Any] = {}
        if isinstance(workflow, dict):
            workflow_row = workflow_row_by_id.get(workflow.get("workflowId"), {})
            if isinstance(workflow_row, dict) and isinstance(workflow_row.get("status"), dict):
                workflow_status = workflow_row["status"]
        workflow_runtime_ready = (
            workflow_status.get("behaviorVerified") is True
            and workflow_status.get("bypassVerified") is True
            and workflow_status.get("runtimeVerified") is True
            and workflow_status.get("blocked") is False
        )
        workflow_approved = (
            workflow_runtime_ready
            and workflow_status.get("hostVerified") is True
            and workflow_status.get("requiresReview") is False
        )
        if capability.get("sideEffect") != "read" and status.get("runtimeVerified") and not workflow_runtime_ready:
            diagnostics.error(location, "a write cannot be runtime-verified before its bypass workflow is verified")

        reasons = _row_verification_reasons(row, location, diagnostics)
        persistent_reasons = [
            reason
            for reason in reasons + _declared_verification_reasons(capability)
            if reason not in TRANSIENT_VERIFICATION_REASONS
        ]
        canonical_blocked = capability.get("readiness") == "blocked"
        if canonical_blocked and status.get("blocked") is not True:
            diagnostics.error(
                f"{location}.status.blocked",
                "a canonically blocked capability cannot be cleared by the verification matrix",
            )
        canonical_review = (
            capability.get("readiness") == "requires-review"
            or bool(capability.get("missingEvidence"))
            or capability_id in unresolved_by_capability
            or (capability.get("sideEffect") != "read" and not write_evidence_complete(capability))
            or bool(persistent_reasons)
        )
        requires_host = capability.get("sideEffect") != "read" or bool(
            capability.get("hostRequirements")
        )
        host_gate = not requires_host or (
            status.get("hostVerified") is True
            and compatibility_by_id.get(capability_id) == "enabled"
        )
        capability_approved = (
            status.get("generated") is True
            and status.get("behaviorVerified") is True
            and status.get("runtimeVerified") is True
            and host_gate
            and (capability.get("sideEffect") == "read" or workflow_approved)
            and not canonical_review
            and status.get("blocked") is False
        )
        expected_review = status.get("blocked") is False and not capability_approved
        if status.get("requiresReview") is not expected_review:
            diagnostics.error(
                f"{location}.status.requiresReview",
                "must be derived from verification gates, canonical readiness/evidence/conflicts, Host compatibility, workflows, and blocked state",
            )


def validate_vnext_artifacts(
    root: Path,
    source_root: Path,
    source_maps: dict[str, Path],
    pre_finalize: bool,
    diagnostics: Any,
) -> None:
    """Validate a vNext candidate and all deterministic projections."""

    for relative in sorted(VNEXT_FILES):
        if not (root / relative).is_file():
            diagnostics.error(relative, "required vNext artifact is missing")
    if any(not (root / relative).is_file() for relative in VNEXT_FILES):
        return
    topology = _read_json(root / "source-topology.json", diagnostics)
    contract = _read_json(root / "canonical-contract.json", diagnostics)
    goal = _read_json(root / "goal-contract.json", diagnostics)
    consumer = _read_json(root / "consumer-requirements.json", diagnostics)
    host = _read_json(root / "host-profile.json", diagnostics)
    compatibility = _read_json(root / "host-compatibility-report.json", diagnostics)
    matrix = _read_json(root / "verification-matrix.json", diagnostics)
    if any(value is None for value in (topology, contract, goal, consumer, host, compatibility, matrix)):
        return
    assert topology is not None and contract is not None and goal is not None
    assert consumer is not None and host is not None and compatibility is not None and matrix is not None
    try:
        source_ids = validate_source_topology(topology)
        validate_canonical_contract(contract, source_ids)
    except ContractError as error:
        diagnostics.error("canonical-contract.json", str(error))
        return
    unknown_maps = set(source_maps) - source_ids
    if unknown_maps:
        diagnostics.error("--source-map", f"contains unknown source IDs: {', '.join(sorted(unknown_maps))}")
    _validate_source_topology_and_evidence(topology, contract, source_root, source_maps, diagnostics)
    _validate_information_model(contract, diagnostics)
    _validate_outputs_and_evidence(contract, diagnostics)
    _validate_conflicts_and_missing_sources(topology, contract, diagnostics)
    _validate_graph_and_goals(contract, diagnostics)
    _validate_host_contracts(contract, consumer, host, compatibility, diagnostics)
    _validate_workflows_and_runtime(root, contract, diagnostics)
    _validate_verification_matrix(contract, compatibility, matrix, pre_finalize, diagnostics)

    _json_equal(goal, derive_goal_contract(contract), "goal-contract.json", diagnostics)
    expected_bundle = derive_bundle(contract)
    actual_bundle = _read_json(root / "capability-bundle.json", diagnostics)
    if actual_bundle is not None:
        _json_equal(actual_bundle, expected_bundle, "capability-bundle.json", diagnostics)
        actual_draft = _read_json(root / "capability-draft.json", diagnostics)
        if actual_draft is not None:
            _json_equal(actual_draft, derive_draft(expected_bundle, contract), "capability-draft.json", diagnostics)
