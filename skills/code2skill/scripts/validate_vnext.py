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
    WRITE_EVIDENCE,
    derive_bundle,
    derive_consumer_requirements,
    derive_documentation_contract,
    derive_goal_contract,
    derive_host_compatibility,
    derive_schema_contract,
    derive_verification_matrix,
    validate_canonical_contract,
    validate_source_topology,
    workflow_capability_ids,
    write_evidence_complete,
    json_schema_errors,
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
    "function-core/schema-contract.json",
    "mcp-tool/schema-contract.json",
    "references/capability-contracts.json",
}
CRITICAL_WRITE_ROLES = {
    "data-contract",
    "explicit-message-operation",
    "explicit-operation",
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
HEX64 = re.compile(r"^[a-f0-9]{64}$")
TRANSIENT_VERIFICATION_REASONS = {
    "behavior-verification-pending",
    "runtime-verification-pending",
    "host-verification-pending",
    "canonical-verification-checks-pending",
    "workflow-bypass-verification-pending",
}
LOCAL_PATH_NAMES = re.compile(r"(?:^|_)(?:local_?)?(?:file_?)?path(?:$|_)", re.IGNORECASE)
JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}
MAPPING_KINDS = {"direct", "select-one", "append-to-array"}
OBSERVED_EDGE_KINDS = {"handoff", "conditional-handoff", "hard-precondition"}
DERIVED_EDGE_KINDS = {"optional-planning"}
REQUEST_BINDING_EVIDENCE_ROLES = {
    "request-construction",
    "serialization",
    "transport-contract",
}
INPUT_CONTRACT_EVIDENCE_ROLES = {
    "attachment-contract",
    "authorization",
    "business-rule",
    "client-api-call",
    "data-contract",
    "explicit-message-operation",
    "explicit-operation",
    "identity",
    "request-construction",
    "serialization",
    "side-effect",
    "transport-contract",
    "validation",
    "workflow-test",
}
HTTP_STEP_EVIDENCE_ROLES = REQUEST_BINDING_EVIDENCE_ROLES | {"behavior-test"}
RESPONSE_EVIDENCE_ROLES = {
    "response-consumption",
    "serialization",
    "transport-contract",
    "behavior-test",
    "failure-test",
}
CONDITION_EVIDENCE_ROLES = {
    "validation",
    "business-rule",
    "transport-contract",
    "request-construction",
    "behavior-test",
}
STATIC_DOMAIN_EVIDENCE_ROLES = {
    "static-domain",
    "client-local-behavior",
    "transport-contract",
    "serialization",
    "validation",
    "business-rule",
}
DYNAMIC_POLICY_EVIDENCE_ROLES = {
    "response-consumption",
    "transport-contract",
    "validation",
    "business-rule",
    "behavior-test",
}
SIDE_EFFECT_EVIDENCE_ROLES = {
    "side-effect",
    "persistence",
    "transport-contract",
    "business-rule",
    "explicit-operation",
    "explicit-message-operation",
    "behavior-test",
}
ATTACHMENT_METADATA_EVIDENCE_ROLES = {
    "attachment-contract",
    "transport-contract",
    "serialization",
    "validation",
}
REUSE_EVIDENCE_ROLES = {
    "request-construction",
    "transport-contract",
    "validation",
    "business-rule",
    "idempotency",
    "workflow-test",
    "authorization",
    "identity",
    "attachment-contract",
}
REUSE_CLAIMS = {
    "sameSubject",
    "sameTenant",
    "sameSession",
    "samePayloadDigest",
    "sameVersion",
    "notEdited",
    "notExpired",
    "notConsumed",
}
GENERIC_HOST_REQUIREMENTS = {
    "agent-skills-discovery": "agentSkillsDiscovery",
    "mcp-tool-invocation": "mcpToolInvocation",
    "authentication-injection": "authenticationInjection",
    "trusted-confirmation": "trustedConfirmation",
    "session-state": "sessionState",
    "attachment-resolution": "attachmentResolution",
    "unknown-outcome-reconciliation": "unknownOutcomeReconciliation",
}
GENERIC_HOST_ON_MISSING = {
    "agent-skills-discovery": "requires-host-integration",
    "mcp-tool-invocation": "disable",
    "authentication-injection": "disable",
    "trusted-confirmation": "disable",
    "session-state": "disable",
    "attachment-resolution": "requires-host-integration",
    "unknown-outcome-reconciliation": "disable",
}
RUNTIME_CONTEXT_CLAIMS = {
    "subject": ("authentication-injection", ["subjectId"], {"subject"}),
    "session": ("session-state", ["sessionId"], {"session"}),
    "confirmation": ("trusted-confirmation", ["confirmationGrantId"], {"confirmationGrantId"}),
    "expiry": ("session-state", ["expiresAt"], {"expiresAt"}),
}


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


def _capabilities_by_id(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["capabilityId"]: item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }


def _declared_output(
    capability: dict[str, Any],
    path: Any,
) -> dict[str, Any] | None:
    if not isinstance(path, list) or not path:
        return None
    key = tuple(path)
    return next(
        (
            item
            for item in capability.get("outputs", [])
            if isinstance(item, dict) and tuple(item.get("path", [])) == key
        ),
        None,
    )


def _dynamic_domain_for_output(
    capability: dict[str, Any],
    path: Any,
) -> dict[str, Any] | None:
    """Return the closest dynamic domain governing an output path.

    A provider commonly declares the dynamic scope on an array/object parent
    while a consumer binds one nested field.  Treating only the leaf as the
    provenance boundary would let a consumer silently widen tenant/session
    scope or freshness while still citing the same provider.
    """

    if not isinstance(path, list) or not path:
        return None
    candidates = [
        output
        for output in capability.get("outputs", [])
        if isinstance(output, dict)
        and isinstance(output.get("path"), list)
        and path[: len(output["path"])] == output["path"]
        and isinstance(output.get("valueDomain"), dict)
        and output["valueDomain"].get("kind") == "dynamic"
    ]
    if not candidates:
        return None
    closest = max(candidates, key=lambda output: len(output["path"]))
    return closest["valueDomain"]


def _declared_input(
    capability: dict[str, Any],
    name: Any,
) -> dict[str, Any] | None:
    if not isinstance(name, str) or not name:
        return None
    return next(
        (
            item
            for item in capability.get("inputs", [])
            if isinstance(item, dict) and item.get("name") == name
        ),
        None,
    )


def _value_schema(item: dict[str, Any]) -> dict[str, Any]:
    schema = item.get("schema")
    if isinstance(schema, dict):
        return schema
    value_type = item.get("type")
    return {"type": value_type} if isinstance(value_type, str) else {}


def _schema_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _schema_structure(child)
            for key, child in value.items()
            if key not in {"description", "title", "examples", "default"}
        }
    if isinstance(value, list):
        return [_schema_structure(item) for item in value]
    return value


def _schema_at_relative_path(schema: Any, path: list[Any]) -> dict[str, Any] | None:
    current = schema
    for segment in path:
        if segment == "*":
            if not isinstance(current, dict) or current.get("type") != "array":
                return None
            current = current.get("items")
        else:
            if not isinstance(current, dict) or current.get("type") != "object":
                return None
            properties = current.get("properties")
            if not isinstance(properties, dict) or segment not in properties:
                return None
            current = properties[segment]
    return current if isinstance(current, dict) else None


def _mapping_compatible(
    output: dict[str, Any],
    target_input: dict[str, Any],
    mapping_kind: Any,
) -> bool:
    if mapping_kind not in MAPPING_KINDS:
        return False
    output_path = output.get("path", [])
    output_schema = _schema_structure(_value_schema(output))
    target_schema = _schema_structure(_value_schema(target_input))
    if mapping_kind == "select-one":
        return "*" in output_path and output_schema == target_schema
    if mapping_kind == "append-to-array":
        return (
            "*" not in output_path
            and target_input.get("type") == "array"
            and isinstance(target_schema.get("items"), dict)
            and output_schema == target_schema["items"]
        )
    return "*" not in output_path and output_schema == target_schema


def _expected_host_requirement_ids(
    contract: dict[str, Any],
    capability: dict[str, Any],
) -> set[str]:
    expected = {"agent-skills-discovery", "mcp-tool-invocation"}
    for item in capability.get("inputs", []):
        if not isinstance(item, dict):
            continue
        for strategy in item.get("sourceStrategies", []):
            if (
                isinstance(strategy, dict)
                and strategy.get("kind") == "trusted-host-context"
                and isinstance(strategy.get("requirementId"), str)
            ):
                expected.add(strategy["requirementId"])
    if capability.get("authentication") != "none":
        expected.add("authentication-injection")
    policy = capability.get("operationPolicy", {})
    if isinstance(policy, dict):
        if policy.get("confirmation") in {
            "trusted-confirmation-required",
            "upload-confirmation-required",
        }:
            expected.add("trusted-confirmation")
        if (
            capability.get("sideEffect") != "read"
            and policy.get("unknownOutcome") != "not-applicable"
        ):
            expected.add("unknown-outcome-reconciliation")
    attachments = capability.get("attachments", {})
    if isinstance(attachments, dict):
        if attachments.get("mode") == "host-approved-reference":
            expected.add("attachment-resolution")
        result = attachments.get("resultBinding")
        if (
            isinstance(result, dict)
            and (
                result.get("reuse") == "single-use"
                or isinstance(result.get("scoping"), dict)
                and result["scoping"].get("session") is True
            )
        ):
            expected.add("session-state")
    for item in [*capability.get("inputs", []), *capability.get("outputs", [])]:
        if not isinstance(item, dict):
            continue
        domain = item.get("valueDomain", {})
        freshness = item.get("freshness", {})
        if isinstance(domain, dict):
            freshness = domain.get("freshness", freshness)
            if domain.get("sessionScoped") is True:
                expected.add("session-state")
        if isinstance(freshness, dict) and any(
            isinstance(reason, str) and "session" in reason
            for reason in freshness.get("refreshWhen", [])
        ):
            expected.add("session-state")
    workflow = next(
        (
            item
            for item in contract.get("workflows", [])
            if isinstance(item, dict)
            and item.get("entryCapabilityId") == capability.get("capabilityId")
        ),
        None,
    )
    if isinstance(workflow, dict) and any(
        isinstance(binding, dict)
        and str(binding.get("name", "")).lower()
        in {"session", "sessionid", "singleuse", "expiresat"}
        for binding in workflow.get("bindings", [])
    ):
        expected.add("session-state")
    return expected


def _validate_feature_boundary_and_exposure(
    contract: dict[str, Any],
    diagnostics: Any,
) -> None:
    boundary = contract.get("featureBoundary")
    if not isinstance(boundary, dict):
        diagnostics.error("canonical-contract.featureBoundary", "must be an object")
        return
    role = boundary.get("primaryEvidenceRole")
    expected = {
        "client-feature": ("client-observed-only", "clientSourceIds", {"client-request", "client-local-behavior"}),
        "explicitly-scoped-service-feature": (
            "explicitly-scoped-surface",
            "serviceSourceIds",
            {"explicitly-scoped-operation"},
        ),
    }
    if role not in expected:
        diagnostics.error(
            "canonical-contract.featureBoundary.primaryEvidenceRole",
            "must classify a client feature or explicitly scoped service feature",
        )
        return
    inclusion_rule, source_field, allowed_exposures = expected[role]
    if boundary.get("scopeKind") != "business-feature":
        diagnostics.error(
            "canonical-contract.featureBoundary.scopeKind",
            "must describe one business feature rather than one file, page, or whole repository",
        )
    if boundary.get("inclusionRule") != inclusion_rule:
        diagnostics.error(
            "canonical-contract.featureBoundary.inclusionRule",
            "must match the declared primary evidence role",
        )
    if boundary.get("backendEvidenceRole") != "supplement-and-verify":
        diagnostics.error(
            "canonical-contract.featureBoundary.backendEvidenceRole",
            "backend evidence may supplement and verify the exposed feature surface, not create it",
        )
    source_ids = boundary.get(source_field)
    if not isinstance(source_ids, list) or not source_ids or any(
        not isinstance(source_id, str) or not source_id for source_id in source_ids
    ):
        diagnostics.error(
            f"canonical-contract.featureBoundary.{source_field}",
            "must name the explicit primary evidence roots",
        )
        source_ids = []
    evidence_by_id = {
        item.get("evidenceId"): item
        for item in contract.get("evidenceCatalog", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    }
    exposure_evidence_roles = {
        "client-request": {"client-api-call"},
        "client-local-behavior": {"client-local-behavior"},
        "explicitly-scoped-operation": {
            "explicit-operation",
            "explicit-message-operation",
        },
    }
    for index, capability in enumerate(contract.get("capabilities", [])):
        if not isinstance(capability, dict):
            continue
        location = f"canonical-contract.capabilities[{index}].exposure"
        exposure = capability.get("exposure")
        if not isinstance(exposure, dict):
            diagnostics.error(location, "must be an object")
            continue
        if exposure.get("kind") not in allowed_exposures:
            diagnostics.error(
                f"{location}.kind",
                "must be a primary-surface request, local behavior, or explicitly scoped operation",
            )
        refs = _validate_evidence_refs(
            exposure.get("evidenceRefs"),
            set(evidence_by_id),
            f"{location}.evidenceRefs",
            diagnostics,
        )
        for ref in refs:
            evidence = evidence_by_id[ref]
            if evidence.get("sourceId") not in source_ids:
                diagnostics.error(
                    f"{location}.evidenceRefs",
                    "primary exposure must be proven by the declared feature surface; supplemental backend evidence cannot create a Tool",
                )
            if evidence.get("assertionLevel") != "fact":
                diagnostics.error(
                    f"{location}.evidenceRefs",
                    "primary exposure must be fact-level",
                )
            allowed_roles = exposure_evidence_roles.get(exposure.get("kind"), set())
            if evidence.get("semanticRole") not in allowed_roles:
                diagnostics.error(
                    f"{location}.evidenceRefs",
                    "primary exposure evidence semanticRole must prove the declared client API invocation, client-local behavior, or explicitly scoped service operation",
                )
        supplemental = _validate_evidence_refs(
            exposure.get("supplementalEvidenceRefs", []),
            set(evidence_by_id),
            f"{location}.supplementalEvidenceRefs",
            diagnostics,
            required=False,
        )
        if set(refs) & set(supplemental):
            diagnostics.error(location, "primary and supplemental evidence must be disjoint")


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


def _validate_fact_evidence_refs(
    value: Any,
    known: set[str],
    evidence_by_id: dict[str, dict[str, Any]],
    allowed_roles: set[str],
    location: str,
    diagnostics: Any,
    *,
    purpose: str,
) -> list[str]:
    refs = _validate_evidence_refs(value, known, location, diagnostics)
    if not any(
        evidence_by_id.get(ref, {}).get("assertionLevel") == "fact"
        and evidence_by_id.get(ref, {}).get("semanticRole") in allowed_roles
        for ref in refs
    ):
        diagnostics.error(
            location,
            f"must cite at least one fact-level {purpose} evidence item with an appropriate semanticRole",
        )
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


def _condition_semantics(
    value: Any,
    root_mapping: dict[str, str] | None = None,
) -> Any:
    """Return condition semantics without duplicating its evidence metadata."""

    mapping = root_mapping or {}
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key == "evidenceRefs":
                continue
            if key == "path" and isinstance(child, list) and child:
                result[key] = [mapping.get(child[0], child[0]), *child[1:]]
            elif key == "field" and isinstance(child, str):
                result[key] = mapping.get(child, child)
            else:
                result[key] = _condition_semantics(child, mapping)
        return result
    if isinstance(value, list):
        return [_condition_semantics(item, mapping) for item in value]
    return value


def _goal_source_matches_strategy(
    source: dict[str, Any],
    strategy: Any,
    mapping_kind: Any,
) -> bool:
    strategy_kind = (
        strategy
        if isinstance(strategy, str)
        else strategy.get("kind") if isinstance(strategy, dict) else None
    )
    source_kind = source.get("kind")
    if source_kind == "user":
        return strategy_kind == "user"
    if source_kind == "trusted-host-context":
        requirement_id = source.get("requirementId")
        if strategy_kind == "host-approved-attachment":
            return requirement_id == "attachment-resolution"
        return (
            strategy_kind == "trusted-host-context"
            and isinstance(strategy, dict)
            and strategy.get("requirementId") == requirement_id
        )
    if source_kind == "capability":
        return (
            strategy_kind == "upstream-tool"
            and isinstance(strategy, dict)
            and strategy.get("capabilityId") == source.get("capabilityId")
            and strategy.get("outputPath") == source.get("outputPath")
        )
    return False


def _validate_condition(
    value: Any,
    input_names: set[str],
    known_evidence: set[str],
    location: str,
    diagnostics: Any,
    schemas_by_name: dict[str, dict[str, Any]] | None = None,
) -> None:
    if not isinstance(value, dict):
        diagnostics.error(location, "must contain machine-readable condition objects")
        return
    operator = value.get("operator")
    if operator not in CONDITION_OPERATORS:
        diagnostics.error(f"{location}.operator", f"must be one of {sorted(CONDITION_OPERATORS)}")
        return
    if operator in {"and", "or"}:
        children = value.get("conditions", value.get("operands"))
        if not isinstance(children, list) or not children:
            diagnostics.error(location, f"{operator} conditions need a non-empty conditions array")
        else:
            for index, child in enumerate(children):
                _validate_condition(
                    child,
                    input_names,
                    known_evidence,
                    f"{location}.conditions[{index}]",
                    diagnostics,
                    schemas_by_name,
                )
    elif operator == "not":
        child = value.get("condition")
        if not isinstance(child, dict):
            diagnostics.error(f"{location}.condition", "not needs one nested condition")
        else:
            _validate_condition(
                child,
                input_names,
                known_evidence,
                f"{location}.condition",
                diagnostics,
                schemas_by_name,
            )
    else:
        path = value.get("path")
        if not isinstance(path, list) or not path or not isinstance(path[0], str):
            diagnostics.error(f"{location}.path", "must reference a declared input path")
        elif path[0] not in input_names:
            diagnostics.error(location, f"references unknown input `{path[0]}`")
        elif schemas_by_name is not None:
            root_schema = schemas_by_name.get(path[0])
            resolved_schema = (
                _schema_at_relative_path(root_schema, path[1:])
                if isinstance(root_schema, dict)
                else None
            )
            if resolved_schema is None:
                diagnostics.error(
                    f"{location}.path",
                    "must resolve to a field declared by the referenced information Schema",
                )
            else:
                schema_type = resolved_schema.get("type")
                if operator in {"gt", "gte", "lt", "lte"} and schema_type not in {"integer", "number"}:
                    diagnostics.error(
                        f"{location}.operator",
                        "numeric comparisons require an integer or number Schema",
                    )
                if operator in {"empty", "non-empty"} and schema_type not in {"string", "array", "object"}:
                    diagnostics.error(
                        f"{location}.operator",
                        "empty checks require a string, array, or object Schema",
                    )
                if operator in {"equals", "not-equals", "gt", "gte", "lt", "lte"}:
                    if "value" not in value or json_schema_errors(value.get("value"), resolved_schema):
                        diagnostics.error(
                            f"{location}.value",
                            "must match the referenced field Schema",
                        )
                if operator in {"in", "not-in"}:
                    candidates = value.get("value")
                    if (
                        not isinstance(candidates, list)
                        or not candidates
                        or any(json_schema_errors(candidate, resolved_schema) for candidate in candidates)
                    ):
                        diagnostics.error(
                            f"{location}.value",
                            "must be a non-empty array whose values match the referenced field Schema",
                        )
    if "evidenceRefs" in value:
        _validate_evidence_refs(value.get("evidenceRefs"), known_evidence, f"{location}.evidenceRefs", diagnostics)


def _validate_input_path(value: Any, input_names: set[str], location: str, diagnostics: Any) -> None:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        diagnostics.error(location, "must be a non-empty input path")
    elif value[0] not in input_names:
        diagnostics.error(location, f"references unknown input `{value[0]}`")


def _validate_schema_shape(schema: Any, location: str, diagnostics: Any) -> None:
    if not isinstance(schema, dict):
        diagnostics.error(location, "must be a JSON Schema object")
        return
    schema_type = schema.get("type")
    if schema_type not in JSON_TYPES:
        diagnostics.error(f"{location}.type", "must be a portable JSON type")
        return
    common_keywords = {
        "type",
        "enum",
        "const",
        "description",
        "title",
        "default",
        "examples",
    }
    type_keywords = {
        "object": {"properties", "required", "additionalProperties"},
        "array": {"items", "minItems", "maxItems", "uniqueItems"},
        "string": {"pattern", "minLength", "maxLength", "format"},
        "integer": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
        "number": {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
        "boolean": set(),
        "null": set(),
    }
    unsupported_keywords = set(schema) - common_keywords - type_keywords[schema_type]
    if unsupported_keywords:
        diagnostics.error(
            location,
            "contains unsupported or unenforced JSON Schema keywords: "
            + ", ".join(sorted(unsupported_keywords)),
        )
    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            diagnostics.error(f"{location}.enum", "must be a non-empty array")
        else:
            for index, item in enumerate(enum):
                if json_schema_errors(item, {"type": schema_type}):
                    diagnostics.error(
                        f"{location}.enum[{index}]",
                        "must match the declared schema type",
                    )
    if "const" in schema and json_schema_errors(schema.get("const"), {"type": schema_type}):
        diagnostics.error(f"{location}.const", "must match the declared schema type")
    if "format" in schema and schema.get("format") != "uri":
        diagnostics.error(
            f"{location}.format",
            "must equal the standard JSON Schema format `uri` when declared on a string Schema",
        )
    for keyword in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if keyword in schema and (
            schema_type not in {"integer", "number"}
            or not isinstance(schema.get(keyword), (int, float))
            or isinstance(schema.get(keyword), bool)
        ):
            diagnostics.error(
                f"{location}.{keyword}",
                "must be a numeric bound on an integer or number Schema",
            )
    lower = schema.get("minimum", schema.get("exclusiveMinimum"))
    upper = schema.get("maximum", schema.get("exclusiveMaximum"))
    if (
        isinstance(lower, (int, float))
        and not isinstance(lower, bool)
        and isinstance(upper, (int, float))
        and not isinstance(upper, bool)
        and lower > upper
    ):
        diagnostics.error(location, "lower numeric bounds must not exceed upper bounds")
    for keyword in ("minLength", "maxLength"):
        if keyword in schema and (
            schema_type != "string"
            or not isinstance(schema.get(keyword), int)
            or isinstance(schema.get(keyword), bool)
            or schema.get(keyword) < 0
        ):
            diagnostics.error(
                f"{location}.{keyword}",
                "must be a non-negative integer on a string Schema",
            )
    if (
        isinstance(schema.get("minLength"), int)
        and isinstance(schema.get("maxLength"), int)
        and schema["minLength"] > schema["maxLength"]
    ):
        diagnostics.error(location, "minLength must not exceed maxLength")
    if schema_type == "object":
        properties = schema.get("properties")
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            diagnostics.error(f"{location}.properties", "must be an object")
            properties = {}
        if schema.get("additionalProperties") is not False:
            diagnostics.error(
                f"{location}.additionalProperties",
                "object contracts must be closed with additionalProperties=false",
            )
        if not isinstance(required, list) or any(
            not isinstance(name, str) or name not in properties for name in required
        ):
            diagnostics.error(
                f"{location}.required",
                "must name only declared object properties",
            )
        for name, child in properties.items():
            _validate_schema_shape(child, f"{location}.properties.{name}", diagnostics)
    elif schema_type == "array":
        if not isinstance(schema.get("items"), dict):
            diagnostics.error(f"{location}.items", "array contracts must declare an item schema")
        else:
            _validate_schema_shape(schema["items"], f"{location}.items", diagnostics)
        for keyword in ("minItems", "maxItems"):
            if keyword in schema and (
                not isinstance(schema.get(keyword), int)
                or isinstance(schema.get(keyword), bool)
                or schema.get(keyword) < 0
            ):
                diagnostics.error(
                    f"{location}.{keyword}",
                    "must be a non-negative integer on an array Schema",
                )
        if (
            isinstance(schema.get("minItems"), int)
            and isinstance(schema.get("maxItems"), int)
            and schema["minItems"] > schema["maxItems"]
        ):
            diagnostics.error(location, "minItems must not exceed maxItems")
        if "uniqueItems" in schema and not isinstance(schema.get("uniqueItems"), bool):
            diagnostics.error(f"{location}.uniqueItems", "must be boolean")
    if isinstance(schema.get("pattern"), str):
        try:
            re.compile(schema["pattern"])
        except re.error:
            diagnostics.error(f"{location}.pattern", "must be a valid regular expression")


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

    source_ids_by_root: dict[Path, list[str]] = {}
    for source_id, resolved_root in resolved_roots.items():
        source = sources.get(source_id, {})
        if source.get("availability") not in {"available", "partially-available"}:
            continue
        source_ids_by_root.setdefault(resolved_root.resolve(), []).append(source_id)
    for resolved_root, aliased_source_ids in source_ids_by_root.items():
        if len(aliased_source_ids) > 1:
            diagnostics.error(
                "source-topology.sources",
                "distinct sourceId values must resolve to distinct authorized roots; "
                f"{', '.join(sorted(aliased_source_ids))} all resolve to {resolved_root}",
            )

    for index, evidence in enumerate(contract.get("evidenceCatalog", [])):
        if not isinstance(evidence, dict):
            continue
        source_id = evidence.get("sourceId")
        location = f"canonical-contract.evidenceCatalog[{index}]"
        source = sources.get(source_id)
        if source is None:
            continue
        semantic_roles = source.get("semanticRoles", [])
        if (
            not isinstance(semantic_roles, list)
            or evidence.get("semanticRole") not in semantic_roles
        ):
            diagnostics.error(
                f"{location}.semanticRole",
                "must be one of the semanticRoles declared by its source topology entry",
            )
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
    evidence_by_id = {
        item.get("evidenceId"): item
        for item in contract.get("evidenceCatalog", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    }
    requirement_host_capability = {
        item.get("requirementId"): item.get("hostCapability")
        for item in contract.get("consumerRequirements", {}).get("requirements", [])
        if isinstance(item, dict)
        and isinstance(item.get("requirementId"), str)
        and isinstance(item.get("hostCapability"), str)
    }
    capabilities = {
        item.get("capabilityId"): item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    known_requirement_ids = {
        item.get("requirementId")
        for item in contract.get("consumerRequirements", {}).get("requirements", [])
        if isinstance(item, dict) and isinstance(item.get("requirementId"), str)
    }
    for capability_index, capability in enumerate(contract.get("capabilities", [])):
        if not isinstance(capability, dict):
            continue
        capability_id = capability.get("capabilityId", f"index-{capability_index}")
        location = f"canonical-contract.capabilities[{capability_index}]"
        inputs = [item for item in capability.get("inputs", []) if isinstance(item, dict)]
        input_names = {item.get("name") for item in inputs if isinstance(item.get("name"), str)}
        input_schemas = {
            item["name"]: _value_schema(item)
            for item in inputs
            if isinstance(item.get("name"), str)
        }
        if len(input_names) != len(inputs):
            diagnostics.error(f"{location}.inputs", "input names must be unique non-empty strings")
        for input_index, item in enumerate(inputs):
            input_location = f"{location}.inputs[{input_index}]"
            name = item.get("name")
            if item.get("type") not in JSON_TYPES - {"null"}:
                diagnostics.error(
                    f"{input_location}.type",
                    "must use a portable JSON input type",
                )
            declared_schema = item.get("schema")
            if item.get("type") in {"object", "array"} and not isinstance(declared_schema, dict):
                diagnostics.error(
                    f"{input_location}.schema",
                    "object and array inputs need a complete closed JSON Schema",
                )
            if isinstance(declared_schema, dict):
                _validate_schema_shape(declared_schema, f"{input_location}.schema", diagnostics)
                if declared_schema.get("type") != item.get("type"):
                    diagnostics.error(
                        f"{input_location}.schema.type",
                        "must match the input type",
                    )
            _validate_fact_evidence_refs(
                item.get("evidenceRefs"),
                known_evidence,
                evidence_by_id,
                INPUT_CONTRACT_EVIDENCE_ROLES,
                f"{input_location}.evidenceRefs",
                diagnostics,
                purpose="public input and data-contract",
            )
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
                if strategy_kind == "trusted-host-context" and isinstance(strategy, dict):
                    if strategy.get("requirementId") not in known_requirement_ids:
                        diagnostics.error(
                            f"{strategy_location}.requirementId",
                            "must name the generic Host requirement that supplies this trusted value",
                        )
                provider = strategy.get("capabilityId") if isinstance(strategy, dict) else None
                if strategy_kind == "upstream-tool":
                    if not isinstance(strategy, dict):
                        diagnostics.error(
                            strategy_location,
                            "upstream-tool must be an object naming its provider, output path, and mapping kind",
                        )
                        continue
                    if provider == capability_id:
                        diagnostics.error(strategy_location, "must not reference the consuming capability itself")
                    provider_capability = capabilities.get(provider)
                    if provider_capability is None:
                        diagnostics.error(strategy_location, "must reference a declared provider capability")
                        continue
                    provider_output = _declared_output(
                        provider_capability,
                        strategy.get("outputPath"),
                    )
                    if provider_output is None:
                        diagnostics.error(
                            f"{strategy_location}.outputPath",
                            "must resolve to one exactly declared provider output",
                        )
                    elif not _mapping_compatible(
                        provider_output,
                        item,
                        strategy.get("mappingKind"),
                    ):
                        diagnostics.error(
                            strategy_location,
                            "mappingKind and provider output schema/cardinality must match the target input",
                        )
            if (
                strategies
                and all(
                    (strategy if isinstance(strategy, str) else strategy.get("kind") if isinstance(strategy, dict) else None)
                    == "trusted-host-context"
                    for strategy in strategies
                )
                and any(not isinstance(strategy, dict) for strategy in strategies)
            ):
                diagnostics.error(
                    f"{input_location}.sourceStrategies",
                    "a sole trusted Host source must explicitly name its generic requirementId",
                )
            if information_class in {"derived", "dynamic"} and any(
                strategy == "user" or (isinstance(strategy, dict) and strategy.get("kind") == "user")
                for strategy in strategies
            ):
                diagnostics.error(
                    input_location,
                    f"{information_class} information cannot be accepted as arbitrary user input; users may select a provider-issued value but cannot construct it",
                )
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
                        input_schemas,
                    )
                    _validate_fact_evidence_refs(
                        condition.get("evidenceRefs") if isinstance(condition, dict) else None,
                        known_evidence,
                        evidence_by_id,
                        CONDITION_EVIDENCE_ROLES,
                        f"{input_location}.requiredWhen[{condition_index}].evidenceRefs",
                        diagnostics,
                        purpose="conditional business rule",
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
                        input_schemas,
                    )
                    _validate_fact_evidence_refs(
                        condition.get("evidenceRefs") if isinstance(condition, dict) else None,
                        known_evidence,
                        evidence_by_id,
                        CONDITION_EVIDENCE_ROLES,
                        f"{input_location}.forbiddenWhen[{condition_index}].evidenceRefs",
                        diagnostics,
                        purpose="conditional business rule",
                    )
            if item.get("required") is True and information_class not in {"required", "dynamic", "derived", "attachment"}:
                diagnostics.error(f"{input_location}.informationClass", "unconditionally required inputs need a matching information classification")

            value_domain = item.get("valueDomain")
            if not isinstance(value_domain, dict):
                diagnostics.error(f"{input_location}.valueDomain", "must be an object")
                continue
            domain_kind = value_domain.get("kind")
            has_upstream_strategy = any(
                isinstance(strategy, dict)
                and strategy.get("kind") == "upstream-tool"
                for strategy in strategies
            )
            if has_upstream_strategy and domain_kind != "dynamic":
                diagnostics.error(
                    f"{input_location}.valueDomain.kind",
                    "every upstream Tool value must retain its provider-backed dynamic domain",
                )
            if information_class == "dynamic" and domain_kind != "dynamic":
                diagnostics.error(
                    f"{input_location}.valueDomain.kind",
                    "dynamic information must retain a dynamic provider domain and cannot be frozen or made unconstrained",
                )
            if (
                information_class == "derived"
                and any(
                    isinstance(strategy, dict)
                    and strategy.get("kind") == "upstream-tool"
                    for strategy in strategies
                )
                and domain_kind != "dynamic"
            ):
                diagnostics.error(
                    f"{input_location}.valueDomain.kind",
                    "an upstream-derived input must retain the provider-backed dynamic domain",
                )
            if domain_kind == "dynamic":
                allowed_dynamic_fields = {
                    "kind",
                    "sourceCapabilityId",
                    "sourcePath",
                    "mappingKind",
                    "identityScoped",
                    "tenantScoped",
                    "sessionScoped",
                    "freshness",
                    "evidenceRefs",
                }
                if set(value_domain) - allowed_dynamic_fields:
                    diagnostics.error(
                        f"{input_location}.valueDomain",
                        "contains unsupported dynamic-domain fields",
                    )
                _validate_fact_evidence_refs(
                    value_domain.get("evidenceRefs"),
                    known_evidence,
                    evidence_by_id,
                    DYNAMIC_POLICY_EVIDENCE_ROLES,
                    f"{input_location}.valueDomain.evidenceRefs",
                    diagnostics,
                    purpose="dynamic scope, provenance, and freshness",
                )
                for scope_field in ("identityScoped", "tenantScoped", "sessionScoped"):
                    if not isinstance(value_domain.get(scope_field), bool):
                        diagnostics.error(
                            f"{input_location}.valueDomain.{scope_field}",
                            "must explicitly declare a boolean dynamic scope",
                        )
                provider = value_domain.get("sourceCapabilityId")
                provider_capability = capabilities.get(provider)
                if provider_capability is None:
                    diagnostics.error(f"{input_location}.valueDomain", "dynamic domain must name a provider capability")
                elif information_class == "dynamic" and provider_capability.get("sideEffect") != "read":
                    diagnostics.error(f"{input_location}.valueDomain", "dynamic domains must come from a read capability")
                else:
                    provider_output = _declared_output(
                        provider_capability,
                        value_domain.get("sourcePath"),
                    )
                    if provider_output is None:
                        diagnostics.error(
                            f"{input_location}.valueDomain.sourcePath",
                            "must resolve to one exactly declared provider output",
                        )
                    elif not _mapping_compatible(
                        provider_output,
                        item,
                        value_domain.get("mappingKind"),
                    ):
                        diagnostics.error(
                            f"{input_location}.valueDomain",
                            "mappingKind and provider output schema/cardinality must match the input",
                        )
                    provider_domain = _dynamic_domain_for_output(
                        provider_capability,
                        value_domain.get("sourcePath"),
                    )
                    if provider_domain is None:
                        diagnostics.error(
                            f"{input_location}.valueDomain",
                            "must inherit a dynamic scope and freshness domain declared by the provider output",
                        )
                    else:
                        for inherited_field in (
                            "identityScoped",
                            "tenantScoped",
                            "sessionScoped",
                            "freshness",
                        ):
                            if value_domain.get(inherited_field) != provider_domain.get(inherited_field):
                                diagnostics.error(
                                    f"{input_location}.valueDomain.{inherited_field}",
                                    "must exactly match the governing provider output dynamic domain",
                                )
                    matching_strategy = any(
                        isinstance(strategy, dict)
                        and strategy.get("kind") == "upstream-tool"
                        and strategy.get("capabilityId") == provider
                        and strategy.get("outputPath") == value_domain.get("sourcePath")
                        and strategy.get("mappingKind") == value_domain.get("mappingKind")
                        for strategy in strategies
                    )
                    if not matching_strategy:
                        diagnostics.error(
                            f"{input_location}.valueDomain",
                            "must exactly match one declared upstream-tool acquisition strategy",
                        )
                if any(key in value_domain for key in ("values", "enum", "options")):
                    diagnostics.error(
                        f"{input_location}.valueDomain",
                        "must not freeze one observed dynamic response into static values",
                    )
                freshness = value_domain.get("freshness") or item.get("freshness")
                if not isinstance(freshness, dict):
                    diagnostics.error(f"{input_location}.valueDomain.freshness", "dynamic values need scope and invalidation rules")
                else:
                    if set(freshness) - {"ttlSeconds", "refreshWhen"}:
                        diagnostics.error(
                            f"{input_location}.valueDomain.freshness",
                            "may contain only ttlSeconds and refreshWhen",
                        )
                    ttl_seconds = freshness.get("ttlSeconds")
                    if ttl_seconds is not None and (
                        not isinstance(ttl_seconds, int)
                        or isinstance(ttl_seconds, bool)
                        or not 1 <= ttl_seconds <= 31_536_000
                    ):
                        diagnostics.error(
                            f"{input_location}.valueDomain.freshness.ttlSeconds",
                            "must be a positive bounded lifetime no longer than one year",
                        )
                    refresh = freshness.get("refreshWhen") or freshness.get("invalidatedBy")
                    if not isinstance(refresh, list) or not refresh or any(not isinstance(reason, str) or not reason for reason in refresh):
                        diagnostics.error(f"{input_location}.valueDomain.freshness.refreshWhen", "must name identity/session/tenant/version invalidation events")
                    elif any(
                        not re.search(
                            r"subject|identity|user|tenant|session|version|catalog|source|policy|config|payload|selection|resource|record|data|expir|ttl|consum|revok|chang|updat|invalid|edit",
                            reason,
                            re.IGNORECASE,
                        )
                        for reason in refresh
                    ):
                        diagnostics.error(
                            f"{input_location}.valueDomain.freshness.refreshWhen",
                            "must use source-derived semantic invalidation events rather than an opaque or never-refresh marker",
                        )
                    if not refresh and not ttl_seconds:
                        diagnostics.error(
                            f"{input_location}.valueDomain.freshness",
                            "must declare expiry or invalidation conditions",
                        )
            elif domain_kind == "static":
                if set(value_domain) != {"kind", "values", "evidenceRefs"}:
                    diagnostics.error(
                        f"{input_location}.valueDomain",
                        "static domains must contain exactly kind, values, and evidenceRefs",
                    )
                values = value_domain.get("values")
                if not isinstance(values, list) or not values:
                    diagnostics.error(f"{input_location}.valueDomain.values", "a static domain must contain source-proven values")
                _validate_fact_evidence_refs(
                    value_domain.get("evidenceRefs"),
                    known_evidence,
                    evidence_by_id,
                    STATIC_DOMAIN_EVIDENCE_ROLES,
                    f"{input_location}.valueDomain.evidenceRefs",
                    diagnostics,
                    purpose="stable closed-domain",
                )
                if isinstance(values, list):
                    for value_index, value in enumerate(values):
                        if json_schema_errors(
                            value,
                            declared_schema
                            if isinstance(declared_schema, dict)
                            else {"type": item.get("type")},
                        ):
                            diagnostics.error(
                                f"{input_location}.valueDomain.values[{value_index}]",
                                "must match the input type",
                            )
            elif domain_kind == "unconstrained":
                if set(value_domain) != {"kind"}:
                    diagnostics.error(
                        f"{input_location}.valueDomain",
                        "unconstrained domains may contain only kind",
                    )
            else:
                diagnostics.error(f"{input_location}.valueDomain.kind", "must be static, dynamic, or unconstrained")

        conditional_input_names = {
            item.get("name")
            for item in inputs
            if isinstance(item.get("name"), str) and item.get("requiredWhen")
        }
        conditional_dependencies: dict[str, set[str]] = {}
        for input_index, item in enumerate(inputs):
            input_name = item.get("name")
            if not isinstance(input_name, str):
                continue
            required_conditions = [
                condition
                for condition in item.get("requiredWhen", [])
                if isinstance(condition, dict)
            ]
            forbidden_conditions = [
                condition
                for condition in item.get("forbiddenWhen", [])
                if isinstance(condition, dict)
            ]
            required_semantics = {
                json.dumps(_condition_semantics(condition), sort_keys=True)
                for condition in required_conditions
            }
            forbidden_semantics = {
                json.dumps(_condition_semantics(condition), sort_keys=True)
                for condition in forbidden_conditions
            }
            if required_semantics & forbidden_semantics:
                diagnostics.error(
                    f"{location}.inputs[{input_index}]",
                    "the same condition cannot both require and forbid one input",
                )
            dependencies = {
                dependency
                for condition in required_conditions
                for dependency in _condition_fields(condition)
                if dependency in conditional_input_names
            }
            if input_name in dependencies:
                diagnostics.error(
                    f"{location}.inputs[{input_index}].requiredWhen",
                    "a conditional Capability input cannot activate itself",
                )
            conditional_dependencies[input_name] = dependencies

        visiting_inputs: set[str] = set()
        visited_inputs: set[str] = set()

        def visit_conditional_input(input_name: str) -> bool:
            if input_name in visiting_inputs:
                return True
            if input_name in visited_inputs:
                return False
            visiting_inputs.add(input_name)
            cycle = any(
                visit_conditional_input(dependency)
                for dependency in conditional_dependencies.get(input_name, set())
            )
            visiting_inputs.remove(input_name)
            visited_inputs.add(input_name)
            return cycle

        if any(
            visit_conditional_input(input_name)
            for input_name in conditional_input_names
        ):
            diagnostics.error(
                f"{location}.inputs",
                "requiredWhen Capability input dependencies must be acyclic",
            )

        implementation = capability.get("implementation", {})
        if isinstance(implementation, dict) and implementation.get("kind") == "http":
            for step_index, step in enumerate(implementation.get("steps", [])):
                if not isinstance(step, dict):
                    continue
                step_location = f"{location}.implementation.steps[{step_index}]"
                _validate_fact_evidence_refs(
                    step.get("evidenceRefs"),
                    known_evidence,
                    evidence_by_id,
                    HTTP_STEP_EVIDENCE_ROLES,
                    f"{step_location}.evidenceRefs",
                    diagnostics,
                    purpose="HTTP operation, method, status, and serialization",
                )
                for binding_index, binding in enumerate(step.get("bindings", [])):
                    if not isinstance(binding, dict):
                        continue
                    _validate_fact_evidence_refs(
                        binding.get("evidenceRefs"),
                        known_evidence,
                        evidence_by_id,
                        REQUEST_BINDING_EVIDENCE_ROLES,
                        f"{step_location}.bindings[{binding_index}].evidenceRefs",
                        diagnostics,
                        purpose="request binding",
                    )

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

        implementation_bound_inputs = {
            binding.get("source", {}).get("inputName")
            for step in capability.get("implementation", {}).get("steps", [])
            if isinstance(step, dict)
            for binding in step.get("bindings", [])
            if isinstance(binding, dict)
            and isinstance(binding.get("source"), dict)
            and binding["source"].get("kind") in {"input", "host_resolved_attachment"}
        }
        workflow_bound_inputs = {
            source.get("inputName")
            for workflow in contract.get("workflows", [])
            if isinstance(workflow, dict)
            and workflow.get("entryCapabilityId") == capability_id
            for binding in workflow.get("bindings", [])
            if isinstance(binding, dict)
            for source in [binding.get("actualSource")]
            if isinstance(source, dict)
            and source.get("kind") in {"capability-input", "derived-calculation"}
        }
        for input_index, item in enumerate(inputs):
            consumed = item.get("name") in implementation_bound_inputs | workflow_bound_inputs
            if not any(
                isinstance(strategy, dict) and strategy.get("kind") == "upstream-tool"
                for strategy in item.get("sourceStrategies", [])
            ) and not (
                isinstance(capability.get("implementation"), dict)
                and capability["implementation"].get("kind") == "http"
            ):
                continue
            if not consumed:
                diagnostics.error(
                    f"{location}.inputs[{input_index}]",
                    "every declared HTTP or upstream-derived input must be consumed by an implementation binding or the declared hard Workflow",
                )

        host_resolved_sources = [
            binding.get("source")
            for step in capability.get("implementation", {}).get("steps", [])
            if isinstance(step, dict)
            for binding in step.get("bindings", [])
            if isinstance(binding, dict)
            and isinstance(binding.get("source"), dict)
            and binding["source"].get("kind") == "host_resolved_attachment"
        ]
        attachment_mode = capability.get("attachments", {}).get("mode")
        if host_resolved_sources and attachment_mode != "host-approved-reference":
            diagnostics.error(
                f"{location}.implementation",
                "host_resolved_attachment is valid only for a declared Host-approved business upload capability",
            )

        _validate_attachments(contract, capability, known_evidence, location, diagnostics)
        _validate_error_contract(capability, known_evidence, location, diagnostics)
        _validate_operation_policy(capability, location, diagnostics)
        annotations = capability.get("annotations")
        if not isinstance(annotations, dict) or set(annotations) != {
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
        } or any(not isinstance(value, bool) for value in annotations.values()):
            diagnostics.error(
                f"{location}.annotations",
                "must explicitly declare the four portable MCP Tool hint booleans",
            )
        else:
            if annotations["readOnlyHint"] != (capability.get("sideEffect") == "read"):
                diagnostics.error(
                    f"{location}.annotations.readOnlyHint",
                    "must match sideEffect",
                )
            if annotations["readOnlyHint"] and annotations["destructiveHint"]:
                diagnostics.error(
                    f"{location}.annotations.destructiveHint",
                    "a read-only Tool cannot simultaneously claim destructive behavior",
                )
            if capability.get("sideEffect") == "delete" and not annotations["destructiveHint"]:
                diagnostics.error(
                    f"{location}.annotations.destructiveHint",
                    "delete capabilities must declare destructiveHint=true",
                )
            idempotency = capability.get("operationPolicy", {}).get("idempotency")
            expected_idempotent = idempotency in {
                "safe",
                "idempotent",
                "content-hash-deduplicated",
            }
            if annotations["idempotentHint"] != expected_idempotent:
                diagnostics.error(
                    f"{location}.annotations.idempotentHint",
                    "must match the Canonical idempotency policy",
                )
        _validate_runtime_protection(capability, known_evidence, location, diagnostics)
        operation_policy = capability.get("operationPolicy", {})
        confirmation_policy = (
            operation_policy.get("confirmation")
            if isinstance(operation_policy, dict)
            else None
        )
        protection = capability.get("runtimeProtection")
        host_capabilities = {
            requirement_host_capability.get(requirement_id)
            for requirement_id in capability.get("hostRequirements", [])
            if isinstance(requirement_id, str)
        }
        if confirmation_policy in {
            "trusted-confirmation-required",
            "upload-confirmation-required",
        }:
            if (
                not isinstance(protection, dict)
                or protection.get("mode") != "deterministic-workflow"
            ):
                diagnostics.error(
                    f"{location}.runtimeProtection",
                    "trusted confirmation must be enforced by a deterministic runtime workflow",
                )
            if "trustedConfirmation" not in host_capabilities:
                diagnostics.error(
                    f"{location}.hostRequirements",
                    "trusted confirmation needs a generic trustedConfirmation Host requirement",
                )
            for input_index, input_item in enumerate(inputs):
                input_name = str(input_item.get("name", ""))
                strategies = input_item.get("sourceStrategies", [])
                accepts_user = any(
                    strategy == "user"
                    or (
                        isinstance(strategy, dict)
                        and strategy.get("kind") == "user"
                    )
                    for strategy in strategies
                ) if isinstance(strategies, list) else False
                if accepts_user and input_item.get("type") == "boolean" and re.search(
                    r"confirm|approv",
                    input_name,
                    re.IGNORECASE,
                ):
                    diagnostics.error(
                        f"{location}.inputs[{input_index}]",
                        "a public Tool argument cannot self-attest trusted user confirmation",
                    )
        attachment_mode = capability.get("attachments", {}).get("mode")
        if attachment_mode == "host-approved-reference" and "attachmentResolution" not in host_capabilities:
            diagnostics.error(
                f"{location}.hostRequirements",
                "Host-provided attachments need a generic attachmentResolution requirement",
            )
        declared_host_requirements = capability.get("hostRequirements")
        expected_host_requirements = _expected_host_requirement_ids(contract, capability)
        if (
            not isinstance(declared_host_requirements, list)
            or len(declared_host_requirements) != len(set(declared_host_requirements))
            or set(declared_host_requirements) != expected_host_requirements
        ):
            diagnostics.error(
                f"{location}.hostRequirements",
                "must exactly equal the generic Host facilities mechanically required by authentication, MCP exposure, confirmation, session state, attachments, and unknown outcomes: "
                + ", ".join(sorted(expected_host_requirements)),
            )
        _validate_evidence_refs(capability.get("evidenceRefs"), known_evidence, f"{location}.evidenceRefs", diagnostics)
        if capability.get("missingEvidence") and capability.get("readiness") == "ready":
            diagnostics.error(location, "a capability with missing evidence cannot be ready")
        if not write_evidence_complete(capability, contract) and capability.get("readiness") == "ready":
            diagnostics.error(
                location,
                "a capability without complete operation-bound fact-level side-effect evidence cannot be ready",
            )
        if not isinstance(capability_id, str):
            diagnostics.error(f"{location}.capabilityId", "must be a string")


def _validate_attachments(
    contract: dict[str, Any],
    capability: dict[str, Any],
    known_evidence: set[str],
    location: str,
    diagnostics: Any,
) -> None:
    evidence_by_id = {
        item.get("evidenceId"): item
        for item in contract.get("evidenceCatalog", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    }
    attachments = capability.get("attachments")
    if not isinstance(attachments, dict):
        diagnostics.error(f"{location}.attachments", "must be an object")
        return
    mode = attachments.get("mode")
    if mode not in {"none", "host-approved-reference", "business-upload-results"}:
        diagnostics.error(f"{location}.attachments.mode", "must classify the attachment boundary")
        return
    if mode == "none":
        if set(attachments) != {"mode"}:
            diagnostics.error(
                f"{location}.attachments",
                "mode none must not carry undeclared attachment or Host-adapter fields",
            )
        return
    protection = capability.get("runtimeProtection")
    workflow_enforced = (
        isinstance(protection, dict)
        and protection.get("mode") == "deterministic-workflow"
    )
    common_attachment_fields = {"mode", "forbiddenInputs"}
    if mode == "host-approved-reference":
        expected_attachment_fields = common_attachment_fields | {
            "hostInputRole",
            "uploadOwner",
            "acceptedInputs",
            "metadata",
            "contentBindings",
            "resultBinding",
        }
    else:
        expected_attachment_fields = common_attachment_fields | {"consumerBindings"}
    if workflow_enforced:
        expected_attachment_fields.add("enforcedByWorkflow")
    if set(attachments) != expected_attachment_fields:
        diagnostics.error(
            f"{location}.attachments",
            "must contain exactly the portable fields defined for its mode and runtime protection; Host- or platform-specific extension fields are forbidden",
        )
    forbidden = attachments.get("forbiddenInputs")
    if not isinstance(forbidden, list) or not {"local-path", "unverified-url"}.issubset(set(forbidden)):
        diagnostics.error(
            f"{location}.attachments.forbiddenInputs",
            "must forbid local paths and unverified URLs",
        )
    if mode == "host-approved-reference":
        if attachments.get("hostInputRole") != "approved-reference-or-bounded-content":
            diagnostics.error(
                f"{location}.attachments.hostInputRole",
                "the Host may provide only an approved reference or bounded content",
            )
        if attachments.get("uploadOwner") != "business-tool":
            diagnostics.error(
                f"{location}.attachments.uploadOwner",
                "the generated business Tool, not the Host, must own the business upload",
            )
        if capability.get("sideEffect") not in {"create", "update"}:
            diagnostics.error(
                f"{location}.attachments.mode",
                "a business upload capability must declare its write side effect",
            )
        implementation = capability.get("implementation")
        if not isinstance(implementation, dict) or not isinstance(implementation.get("kind"), str):
            diagnostics.error(
                f"{location}.implementation",
                "a business upload Tool needs an executable implementation boundary",
            )
        accepted = attachments.get("acceptedInputs")
        if not isinstance(accepted, list) or not accepted or not set(accepted) <= {"opaque-host-grant", "bounded-content"}:
            diagnostics.error(
                f"{location}.attachments.acceptedInputs",
                "may accept only opaque Host grants or bounded content",
            )
            accepted = []
        attachment_inputs = [
            item
            for item in capability.get("inputs", [])
            if isinstance(item, dict) and item.get("informationClass") == "attachment"
        ]
        attachment_source_kinds = {
            strategy if isinstance(strategy, str) else strategy.get("kind")
            for item in attachment_inputs
            for strategy in item.get("sourceStrategies", [])
            if isinstance(strategy, (str, dict))
        }
        if "opaque-host-grant" in accepted and "host-approved-attachment" not in attachment_source_kinds:
            diagnostics.error(
                f"{location}.attachments.acceptedInputs",
                "opaque Host grants need a host-approved-attachment input strategy",
            )
        if "opaque-host-grant" in accepted:
            opaque_attachment_inputs = [
                item
                for item in attachment_inputs
                if any(
                    (strategy if isinstance(strategy, str) else strategy.get("kind") if isinstance(strategy, dict) else None)
                    == "host-approved-attachment"
                    for strategy in item.get("sourceStrategies", [])
                )
            ]
            if len(opaque_attachment_inputs) != 1:
                diagnostics.error(
                    f"{location}.attachments.acceptedInputs",
                    "the portable opaque-grant upload boundary accepts exactly one approved attachment per Tool invocation; upload multiple attachments with separate calls",
                )
            resolved_binding_records = [
                (step.get("stepId"), binding)
                for step in capability.get("implementation", {}).get("steps", [])
                if isinstance(step, dict)
                for binding in step.get("bindings", [])
                if isinstance(binding, dict)
                and isinstance(binding.get("source"), dict)
                and binding["source"].get("kind") == "host_resolved_attachment"
                and binding["source"].get("inputName") in {
                    item.get("name") for item in attachment_inputs
                }
                and binding["source"].get("requirementId") == "attachment-resolution"
            ]
            resolved_bindings = [binding for _, binding in resolved_binding_records]
            if len(resolved_bindings) != len(opaque_attachment_inputs) or not resolved_bindings:
                diagnostics.error(
                    f"{location}.implementation",
                    "each opaque Host attachment input must be resolved exactly once through the generic attachment-resolution facility before the business upload request",
                )
            content_bindings = attachments.get("contentBindings")
            content_bindings_location = f"{location}.attachments.contentBindings"
            expected_content_binding_fields = {
                "inputName",
                "stepId",
                "location",
                "path",
                "requirementId",
                "evidenceRefs",
            }
            if not isinstance(content_bindings, list) or not content_bindings:
                diagnostics.error(
                    content_bindings_location,
                    "must explicitly identify every opaque attachment input, generic resolver, final upload request step, and source-proven body or multipart field",
                )
                content_bindings = []
            implementation_output_step_id = (
                implementation.get("outputStepId")
                if isinstance(implementation, dict)
                else None
            )
            declared_content_signatures: list[tuple[Any, Any, Any, tuple[Any, ...], Any]] = []
            opaque_input_names = {item.get("name") for item in opaque_attachment_inputs}
            for content_index, content_binding in enumerate(content_bindings):
                content_binding_location = f"{content_bindings_location}[{content_index}]"
                if (
                    not isinstance(content_binding, dict)
                    or set(content_binding) != expected_content_binding_fields
                ):
                    diagnostics.error(
                        content_binding_location,
                        "must contain exclusively the portable resolved-content binding fields",
                    )
                    continue
                content_evidence_refs = _validate_evidence_refs(
                    content_binding.get("evidenceRefs"),
                    known_evidence,
                    f"{content_binding_location}.evidenceRefs",
                    diagnostics,
                )
                content_path = content_binding.get("path")
                if (
                    not isinstance(content_path, list)
                    or not content_path
                    or any(not isinstance(segment, str) or not segment for segment in content_path)
                ):
                    diagnostics.error(
                        f"{content_binding_location}.path",
                        "must be a non-empty source-proven request field path",
                    )
                    content_path = []
                if content_binding.get("stepId") != implementation_output_step_id:
                    diagnostics.error(
                        f"{content_binding_location}.stepId",
                        "must equal implementation.outputStepId so resolved content reaches the actual business upload request",
                    )
                signature = (
                    content_binding.get("stepId"),
                    content_binding.get("location"),
                    content_binding.get("inputName"),
                    tuple(content_path),
                    content_binding.get("requirementId"),
                )
                declared_content_signatures.append(signature)
                qualifying_binding_evidence = {
                    ref
                    for ref in content_evidence_refs
                    if evidence_by_id.get(ref, {}).get("assertionLevel") == "fact"
                    and evidence_by_id.get(ref, {}).get("semanticRole")
                    in REQUEST_BINDING_EVIDENCE_ROLES
                }
                if not qualifying_binding_evidence:
                    diagnostics.error(
                        f"{content_binding_location}.evidenceRefs",
                        "the exact attachment upload step, location, and path must cite fact-level request-construction, serialization, or transport-contract evidence",
                    )
                matching_resolved_bindings = [
                    binding
                    for step_id, binding in resolved_binding_records
                    if (
                        step_id,
                        binding.get("location"),
                        binding.get("source", {}).get("inputName"),
                        tuple(binding.get("path", [])),
                        binding.get("source", {}).get("requirementId"),
                    )
                    == signature
                ]
                if matching_resolved_bindings and not any(
                    qualifying_binding_evidence
                    & set(binding.get("evidenceRefs", []))
                    for binding in matching_resolved_bindings
                ):
                    diagnostics.error(
                        f"{content_binding_location}.evidenceRefs",
                        "must share its qualifying request-binding evidence with the matching host_resolved_attachment implementation binding",
                    )
                if (
                    content_binding.get("requirementId") != "attachment-resolution"
                    or content_binding.get("location") not in {"multipart", "body"}
                    or content_binding.get("inputName") not in opaque_input_names
                ):
                    diagnostics.error(
                        content_binding_location,
                        "must use the generic attachment-resolution requirement for one declared opaque attachment input",
                    )
            resolved_content_signatures = [
                (
                    step_id,
                    binding.get("location"),
                    binding.get("source", {}).get("inputName"),
                    tuple(binding.get("path", [])),
                    binding.get("source", {}).get("requirementId"),
                )
                for step_id, binding in resolved_binding_records
            ]
            if (
                len(declared_content_signatures) != len(set(declared_content_signatures))
                or sorted(declared_content_signatures, key=repr)
                != sorted(resolved_content_signatures, key=repr)
                or {signature[2] for signature in declared_content_signatures}
                != opaque_input_names
            ):
                diagnostics.error(
                    content_bindings_location,
                    "must uniquely and exactly cover every host_resolved_attachment implementation binding into the final business upload request",
                )
            if any(
                step_id != implementation_output_step_id
                for step_id, _ in resolved_binding_records
            ):
                diagnostics.error(
                    f"{location}.implementation.outputStepId",
                    "resolved attachment content must be bound directly into the actual business upload request step",
                )
            implementation_steps = (
                implementation.get("steps", [])
                if isinstance(implementation, dict)
                else []
            )
            for resolved_step_id, resolved_binding in resolved_binding_records:
                resolved_location = resolved_binding.get("location")
                resolved_path = tuple(resolved_binding.get("path", []))
                resolved_step = next(
                    (
                        step
                        for step in implementation_steps
                        if isinstance(step, dict)
                        and step.get("stepId") == resolved_step_id
                    ),
                    None,
                )
                if not isinstance(resolved_step, dict):
                    continue
                for other_binding in resolved_step.get("bindings", []):
                    if other_binding is resolved_binding or not isinstance(other_binding, dict):
                        continue
                    other_path = tuple(other_binding.get("path", []))
                    paths_overlap = (
                        resolved_path[: len(other_path)] == other_path
                        or other_path[: len(resolved_path)] == resolved_path
                    )
                    if (
                        other_binding.get("location") == resolved_location
                        and resolved_path
                        and other_path
                        and paths_overlap
                    ):
                        diagnostics.error(
                            f"{location}.implementation",
                            "a resolved attachment request binding target must not be equal to, contain, or be contained by another binding target in the same step",
                        )
            resolved_input_names: set[str] = set()
            required_metadata = (
                set(attachments.get("metadata", {}).get("required", []))
                if isinstance(attachments.get("metadata"), dict)
                else set()
            ) | {"grantId"}
            for resolved_binding in resolved_bindings:
                source = resolved_binding.get("source", {})
                input_name = source.get("inputName") if isinstance(source, dict) else None
                resolved_input_names.add(str(input_name))
                resolved_input = _declared_input(capability, input_name)
                resolved_schema = _value_schema(resolved_input) if isinstance(resolved_input, dict) else {}
                properties = resolved_schema.get("properties", {})
                required_fields = set(resolved_schema.get("required", []))
                source_kinds = {
                    strategy if isinstance(strategy, str) else strategy.get("kind")
                    for strategy in resolved_input.get("sourceStrategies", [])
                    if isinstance(strategy, (str, dict))
                } if isinstance(resolved_input, dict) else set()
                if (
                    not isinstance(resolved_input, dict)
                    or resolved_input.get("informationClass") != "attachment"
                    or resolved_input.get("type") != "object"
                    or not isinstance(properties, dict)
                    or not required_metadata <= set(properties)
                    or not required_metadata <= required_fields
                    or source_kinds != {"host-approved-attachment"}
                ):
                    diagnostics.error(
                        f"{location}.implementation",
                        "host_resolved_attachment must reference a dedicated opaque attachment object with approved-grant provenance and all declared metadata",
                    )
                if resolved_binding.get("location") not in {"multipart", "body"}:
                    diagnostics.error(
                        f"{location}.implementation",
                        "resolved attachment content must bind to the source-proven HTTP body or multipart location",
                    )
            raw_attachment_bindings = [
                binding
                for step in capability.get("implementation", {}).get("steps", [])
                if isinstance(step, dict)
                for binding in step.get("bindings", [])
                if isinstance(binding, dict)
                and isinstance(binding.get("source"), dict)
                and binding["source"].get("kind") == "input"
                and binding["source"].get("inputName") in resolved_input_names
            ]
            if raw_attachment_bindings:
                diagnostics.error(
                    f"{location}.implementation",
                    "an opaque Host grant is metadata, not file content, and must not be sent directly to the business upload API",
                )
        if "bounded-content" in accepted and "bounded-content" not in attachment_source_kinds:
            diagnostics.error(
                f"{location}.attachments.acceptedInputs",
                "bounded content needs a bounded-content input strategy",
            )
        metadata = attachments.get("metadata")
        if (
            not isinstance(metadata, dict)
            or set(metadata) != {"required", "maxSizeBytes", "evidenceRefs"}
            or not isinstance(metadata.get("required"), list)
        ):
            diagnostics.error(
                f"{location}.attachments.metadata",
                "must contain exactly required, maxSizeBytes, and evidenceRefs for the source-proven attachment boundary",
            )
        else:
            _validate_fact_evidence_refs(
                metadata.get("evidenceRefs"),
                known_evidence,
                evidence_by_id,
                ATTACHMENT_METADATA_EVIDENCE_ROLES,
                f"{location}.attachments.metadata.evidenceRefs",
                diagnostics,
                purpose="attachment metadata, media, digest, and size limit",
            )
        if isinstance(metadata, dict) and (
            not isinstance(metadata.get("maxSizeBytes"), int)
            or isinstance(metadata.get("maxSizeBytes"), bool)
            or metadata.get("maxSizeBytes", 0) <= 0
        ):
            diagnostics.error(
                f"{location}.attachments.metadata.maxSizeBytes",
                "attachments need a positive source- or deployment-proven size limit",
            )
        if isinstance(metadata, dict) and isinstance(metadata.get("required"), list):
            attachment_properties = {
                name: schema
                for item in attachment_inputs
                for name, schema in (
                    item.get("schema", {}).get("properties", {}).items()
                    if isinstance(item.get("schema"), dict)
                    and isinstance(item["schema"].get("properties"), dict)
                    else []
                )
            }
            missing_metadata = set(metadata["required"]) - set(attachment_properties)
            if missing_metadata:
                diagnostics.error(
                    f"{location}.attachments.metadata.required",
                    "must name fields present in the public attachment input Schema: "
                    + ", ".join(sorted(missing_metadata)),
                )
            max_size = metadata.get("maxSizeBytes")
            size_schema = attachment_properties.get("sizeBytes")
            if isinstance(max_size, int) and max_size > 0 and (
                not isinstance(size_schema, dict)
                or size_schema.get("maximum") != max_size
            ):
                diagnostics.error(
                    f"{location}.attachments.metadata.maxSizeBytes",
                    "must exactly match the attachment input Schema sizeBytes.maximum",
                )
        result = attachments.get("resultBinding")
        if (
            not isinstance(result, dict)
            or set(result) != {
                "kind",
                "valueKind",
                "outputPath",
                "scoping",
                "reuse",
                "evidenceRefs",
            }
            or result.get("kind") != "source-defined"
        ):
            diagnostics.error(
                f"{location}.attachments.resultBinding",
                "must contain exactly the closed source-defined business upload result fields",
            )
        else:
            if result.get("valueKind") not in {
                "opaque-token",
                "url",
                "file-id",
                "object-key",
                "object",
            }:
                diagnostics.error(
                    f"{location}.attachments.resultBinding.valueKind",
                    "must preserve the source result as an opaque token, URL, file ID, object key, or object",
                )
            output_path = result.get("outputPath")
            declared_output_paths = {
                tuple(item.get("path", []))
                for item in capability.get("outputs", [])
                if isinstance(item, dict) and isinstance(item.get("path"), list)
            }
            if not isinstance(output_path, list) or tuple(output_path) not in declared_output_paths:
                diagnostics.error(
                    f"{location}.attachments.resultBinding.outputPath",
                    "must name one declared business Tool output path",
                )
            else:
                declared_output = _declared_output(capability, output_path)
                expected_type = (
                    "object"
                    if result.get("valueKind") == "object"
                    else "string"
                )
                if (
                    isinstance(declared_output, dict)
                    and result.get("valueKind") in {
                        "opaque-token",
                        "url",
                        "file-id",
                        "object-key",
                        "object",
                    }
                    and declared_output.get("type") != expected_type
                ):
                    diagnostics.error(
                        f"{location}.attachments.resultBinding.valueKind",
                        f"requires a declared {expected_type} output",
                    )
                declared_schema = (
                    _value_schema(declared_output)
                    if isinstance(declared_output, dict)
                    else {}
                )
                declared_format = declared_schema.get("format")
                if result.get("valueKind") == "url" and declared_format != "uri":
                    diagnostics.error(
                        f"{location}.attachments.resultBinding.valueKind",
                        "url results require a string output Schema with format=uri",
                    )
                if (
                    result.get("valueKind") in {
                        "opaque-token",
                        "file-id",
                        "object-key",
                    }
                    and declared_format in {"uri", "uri-reference", "url"}
                ):
                    diagnostics.error(
                        f"{location}.attachments.resultBinding.valueKind",
                        "non-URL upload results must not use a URL-formatted output Schema",
                    )
                required_success_paths = capability.get("successRule", {}).get(
                    "requiredOutputPaths", []
                )
                if output_path not in required_success_paths:
                    diagnostics.error(
                        f"{location}.successRule.requiredOutputPaths",
                        "must require the source-defined upload result path before treating the business upload as successful",
                    )
            scoping = result.get("scoping")
            if not isinstance(scoping, dict) or set(scoping) != {"subject", "session"} or any(
                not isinstance(scoping.get(key), bool) for key in ("subject", "session")
            ):
                diagnostics.error(
                    f"{location}.attachments.resultBinding.scoping",
                    "must explicitly preserve the source-proven subject and session scoping booleans",
                )
            if result.get("reuse") not in {"single-use", "reusable", "unknown"}:
                diagnostics.error(
                    f"{location}.attachments.resultBinding.reuse",
                    "must classify the source-proven reuse boundary",
                )
            _validate_fact_evidence_refs(
                result.get("evidenceRefs"),
                known_evidence,
                evidence_by_id,
                RESPONSE_EVIDENCE_ROLES,
                f"{location}.attachments.resultBinding.evidenceRefs",
                diagnostics,
                purpose="business upload response and result binding",
            )
        if workflow_enforced:
            if attachments.get("enforcedByWorkflow") != protection.get("workflowId"):
                diagnostics.error(
                    f"{location}.attachments.enforcedByWorkflow",
                    "must name the deterministic workflow that protects the business upload",
                )
        return

    consumer_bindings = attachments.get("consumerBindings")
    if not isinstance(consumer_bindings, list) or not consumer_bindings:
        diagnostics.error(
            f"{location}.attachments.consumerBindings",
            "business upload results need at least one mechanically bound provider output",
        )
        return
    capabilities = _capabilities_by_id(contract)
    implementation = capability.get("implementation", {})
    implementation_steps = (
        implementation.get("steps", []) if isinstance(implementation, dict) else []
    )
    implementation_bindings = {
        binding.get("source", {}).get("inputName")
        for step in implementation_steps
        if isinstance(step, dict)
        for binding in step.get("bindings", [])
        if isinstance(binding, dict)
        and isinstance(binding.get("source"), dict)
        and binding["source"].get("kind") in {"input", "host_resolved_attachment"}
    }
    output_step_id = implementation.get("outputStepId") if isinstance(implementation, dict) else None
    output_step_bindings = {
        binding.get("source", {}).get("inputName")
        for step in implementation_steps
        if isinstance(step, dict) and step.get("stepId") == output_step_id
        for binding in step.get("bindings", [])
        if isinstance(binding, dict)
        and isinstance(binding.get("source"), dict)
        and binding["source"].get("kind") in {"input", "host_resolved_attachment"}
    }
    for binding_index, binding in enumerate(consumer_bindings):
        binding_location = f"{location}.attachments.consumerBindings[{binding_index}]"
        if not isinstance(binding, dict):
            diagnostics.error(binding_location, "must be an object")
            continue
        target_input = _declared_input(capability, binding.get("inputName"))
        if target_input is None:
            diagnostics.error(f"{binding_location}.inputName", "must name one declared consumer input")
            continue
        strategies = target_input.get("sourceStrategies", [])
        if any(
            not isinstance(strategy, dict)
            or strategy.get("kind") != "upstream-tool"
            for strategy in strategies
        ):
            diagnostics.error(
                f"{binding_location}.inputName",
                "business upload results may come only from declared upstream business-upload Tools",
            )
        provider_id = binding.get("providerCapabilityId")
        provider = capabilities.get(provider_id)
        if provider is None or provider_id == capability.get("capabilityId"):
            diagnostics.error(
                f"{binding_location}.providerCapabilityId",
                "must name a distinct declared business upload capability",
            )
            continue
        provider_attachments = provider.get("attachments", {})
        if not isinstance(provider_attachments, dict) or provider_attachments.get("mode") != "host-approved-reference":
            diagnostics.error(
                f"{binding_location}.providerCapabilityId",
                "must name a capability that owns the business upload",
            )
        provider_output = _declared_output(provider, binding.get("providerOutputPath"))
        if provider_output is None:
            diagnostics.error(
                f"{binding_location}.providerOutputPath",
                "must resolve to one declared upload output",
            )
            continue
        result_binding = provider_attachments.get("resultBinding", {})
        if not isinstance(result_binding, dict) or result_binding.get("outputPath") != binding.get("providerOutputPath"):
            diagnostics.error(
                f"{binding_location}.providerOutputPath",
                "must equal the provider's source-defined upload result path",
            )
        if not _mapping_compatible(provider_output, target_input, binding.get("mappingKind")):
            diagnostics.error(
                binding_location,
                "mappingKind and upload output schema/cardinality must match the consumer input",
            )
        if not any(
            isinstance(strategy, dict)
            and strategy.get("kind") == "upstream-tool"
            and strategy.get("capabilityId") == provider_id
            and strategy.get("outputPath") == binding.get("providerOutputPath")
            and strategy.get("mappingKind") == binding.get("mappingKind")
            for strategy in strategies
        ):
            diagnostics.error(
                binding_location,
                "must exactly match one upstream-tool source strategy on the target input",
            )
        matching_handoff = any(
            isinstance(handoff, dict)
            and handoff.get("fromCapabilityId") == provider_id
            and handoff.get("toCapabilityId") == capability.get("capabilityId")
            and any(
                isinstance(mapping, dict)
                and mapping.get("sourcePath") == binding.get("providerOutputPath")
                and mapping.get("targetInput") == binding.get("inputName")
                and mapping.get("mappingKind") == binding.get("mappingKind")
                for mapping in handoff.get("mappings", [])
            )
            for handoff in contract.get("handoffs", [])
        )
        if not matching_handoff:
            diagnostics.error(binding_location, "needs a matching Canonical handoff mapping")
        if binding.get("inputName") not in implementation_bindings:
            diagnostics.error(
                f"{location}.implementation",
                f"must bind attachment input `{binding.get('inputName')}` into the business request",
            )
        if binding.get("inputName") not in output_step_bindings:
            diagnostics.error(
                f"{location}.implementation.outputStepId",
                f"final business request must directly bind attachment input `{binding.get('inputName')}`; an unused or noop step is insufficient",
            )
        _validate_evidence_refs(
            binding.get("evidenceRefs"),
            known_evidence,
            f"{binding_location}.evidenceRefs",
            diagnostics,
        )
    if workflow_enforced:
        if attachments.get("enforcedByWorkflow") != protection.get("workflowId"):
            diagnostics.error(
                f"{location}.attachments.enforcedByWorkflow",
                "must name the deterministic workflow that binds upload results before dispatch",
            )


def _validate_error_contract(
    capability: dict[str, Any],
    known_evidence: set[str],
    location: str,
    diagnostics: Any,
) -> None:
    contract = capability.get("errorContract")
    error_location = f"{location}.errorContract"
    if not isinstance(contract, dict):
        diagnostics.error(error_location, "must be a structured actionable error contract")
        return
    if contract.get("format") != "structured":
        diagnostics.error(f"{error_location}.format", "must equal structured")
    if contract.get("preservesRecoveryContext") is not True:
        diagnostics.error(
            f"{error_location}.preservesRecoveryContext",
            "must preserve enough structured information for the Agent to explain, recover, or stop safely",
        )
    for name in ("codePath", "messagePath", "detailsPath"):
        path = contract.get(name)
        if not isinstance(path, list) or not path or any(
            not isinstance(segment, str) or not segment for segment in path
        ):
            diagnostics.error(f"{error_location}.{name}", "must be a non-empty structured result path")
    retryability_path = contract.get("retryabilityPath")
    if retryability_path is not None and (
        not isinstance(retryability_path, list)
        or not retryability_path
        or any(not isinstance(segment, str) or not segment for segment in retryability_path)
    ):
        diagnostics.error(
            f"{error_location}.retryabilityPath",
            "must be null/absent or a non-empty structured result path",
        )
    if not isinstance(contract.get("defaultRetryable"), bool):
        diagnostics.error(f"{error_location}.defaultRetryable", "must be boolean")
    elif retryability_path is None and contract.get("defaultRetryable") is not False:
        diagnostics.error(
            f"{error_location}.defaultRetryable",
            "must be false when no retryabilityPath is declared",
        )
    _validate_evidence_refs(
        contract.get("evidenceRefs"),
        known_evidence,
        f"{error_location}.evidenceRefs",
        diagnostics,
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
    if policy.get("confirmation") not in {
        "not-required",
        "trusted-confirmation-required",
        "upload-confirmation-required",
    }:
        diagnostics.error(
            f"{location}.operationPolicy.confirmation",
            "must explicitly classify whether this evidenced write needs trusted confirmation",
        )
    if policy.get("automaticRetry") != "never":
        diagnostics.error(f"{location}.operationPolicy.retry", "writes must never retry automatically")
    if policy.get("unknownOutcome") not in {"stop-and-reconcile", "reconcile-before-any-retry"}:
        diagnostics.error(f"{location}.operationPolicy.unknownOutcome", "writes need an explicit unknown-outcome reconciliation policy")
    if not isinstance(policy.get("idempotency"), str) or not policy.get("idempotency"):
        diagnostics.error(f"{location}.operationPolicy.idempotency", "writes must declare idempotency or at-most-once behavior")


def _validate_runtime_protection(
    capability: dict[str, Any],
    known_evidence: set[str],
    location: str,
    diagnostics: Any,
) -> None:
    protection = capability.get("runtimeProtection")
    side_effect = capability.get("sideEffect")
    protection_location = f"{location}.runtimeProtection"
    if side_effect == "read":
        if protection is not None:
            diagnostics.error(protection_location, "read capabilities must not declare write runtime protection")
        return
    if not isinstance(protection, dict):
        diagnostics.error(
            protection_location,
            "writes must select backend-authoritative, deterministic-workflow, or unresolved protection",
        )
        return
    mode = protection.get("mode")
    if mode not in {"backend-authoritative", "deterministic-workflow", "unresolved"}:
        diagnostics.error(
            f"{protection_location}.mode",
            "must be backend-authoritative, deterministic-workflow, or unresolved",
        )
        return
    refs = _validate_evidence_refs(
        protection.get("evidenceRefs"),
        known_evidence,
        f"{protection_location}.evidenceRefs",
        diagnostics,
    )
    if not refs:
        diagnostics.error(
            f"{protection_location}.evidenceRefs",
            "must prove which runtime owns the non-bypassable rules",
        )
    if mode == "unresolved":
        if capability.get("readiness") not in {"requires-review", "blocked"}:
            diagnostics.error(
                f"{location}.readiness",
                "unresolved runtime protection cannot be ready",
            )
        missing_evidence = capability.get("missingEvidence")
        if not isinstance(missing_evidence, list) or not missing_evidence:
            diagnostics.error(
                f"{location}.missingEvidence",
                "unresolved runtime protection must record the missing backend proof",
            )
        if "owner" in protection or "workflowId" in protection or "workflowId" in capability:
            diagnostics.error(
                protection_location,
                "unresolved runtime protection must not guess an owner or workflow",
            )
    elif mode == "backend-authoritative":
        if protection.get("owner") != "target-api":
            diagnostics.error(f"{protection_location}.owner", "must equal target-api")
        if "workflowId" in protection or "workflowId" in capability:
            diagnostics.error(
                protection_location,
                "backend-authoritative writes must not invent a local workflow or Guard",
            )
    else:
        workflow_id = protection.get("workflowId")
        if not isinstance(workflow_id, str) or not workflow_id:
            diagnostics.error(
                f"{protection_location}.workflowId",
                "deterministic-workflow protection must name its hard workflow",
            )
        if "owner" in protection and protection.get("owner") != "portable-runtime":
            diagnostics.error(
                f"{protection_location}.owner",
                "must equal portable-runtime when explicitly declared",
            )
        if capability.get("workflowId") not in {None, workflow_id}:
            diagnostics.error(
                f"{location}.workflowId",
                "must match runtimeProtection.workflowId",
            )


def _validate_outputs_and_evidence(contract: dict[str, Any], diagnostics: Any) -> None:
    known = _known_evidence(contract)
    evidence_by_id = {
        item.get("evidenceId"): item
        for item in contract.get("evidenceCatalog", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    }
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
            if output.get("type") not in JSON_TYPES:
                diagnostics.error(
                    f"{output_location}.type",
                    "must declare the portable JSON type exposed by the MCP output schema",
                )
            if output.get("type") in {"object", "array"} and not isinstance(output.get("schema"), dict):
                diagnostics.error(
                    f"{output_location}.schema",
                    "object and array outputs need a complete closed JSON Schema",
                )
            if isinstance(output.get("schema"), dict):
                _validate_schema_shape(
                    output["schema"],
                    f"{output_location}.schema",
                    diagnostics,
                )
                if output["schema"].get("type") != output.get("type"):
                    diagnostics.error(
                        f"{output_location}.schema.type",
                        "must match the output type",
                    )
            _validate_fact_evidence_refs(
                output.get("evidenceRefs"),
                known,
                evidence_by_id,
                RESPONSE_EVIDENCE_ROLES,
                f"{output_location}.evidenceRefs",
                diagnostics,
                purpose="response field and output Schema",
            )
            domain = output.get("valueDomain")
            inherited_domains = [
                parent.get("valueDomain")
                for parent in outputs
                if isinstance(parent, dict)
                and isinstance(parent.get("path"), list)
                and isinstance(path, list)
                and len(parent["path"]) < len(path)
                and path[: len(parent["path"])] == parent["path"]
                and isinstance(parent.get("valueDomain"), dict)
            ]
            if not isinstance(domain, dict) and not inherited_domains:
                diagnostics.error(
                    f"{output_location}.valueDomain",
                    "must declare static, dynamic, or unconstrained output provenance unless inherited from a parent output",
                )
            if isinstance(domain, dict) and domain.get("kind") == "dynamic":
                allowed_output_domain_fields = {
                    "kind",
                    "identityScoped",
                    "tenantScoped",
                    "sessionScoped",
                    "freshness",
                    "evidenceRefs",
                }
                if set(domain) - allowed_output_domain_fields:
                    diagnostics.error(
                        f"{output_location}.valueDomain",
                        "contains unsupported dynamic output-domain fields",
                    )
                _validate_fact_evidence_refs(
                    domain.get("evidenceRefs"),
                    known,
                    evidence_by_id,
                    DYNAMIC_POLICY_EVIDENCE_ROLES,
                    f"{output_location}.valueDomain.evidenceRefs",
                    diagnostics,
                    purpose="dynamic output scope and freshness",
                )
                for scope_field in ("identityScoped", "tenantScoped", "sessionScoped"):
                    if not isinstance(domain.get(scope_field), bool):
                        diagnostics.error(
                            f"{output_location}.valueDomain.{scope_field}",
                            "must explicitly declare a boolean dynamic scope",
                        )
                if any(key in domain for key in ("values", "enum", "options")):
                    diagnostics.error(output_location, "dynamic output domains must not freeze observed values")
                freshness = domain.get("freshness")
                if not isinstance(freshness, dict) or not freshness.get("refreshWhen"):
                    diagnostics.error(output_location, "dynamic output domains need freshness and invalidation rules")
                else:
                    if set(freshness) - {"ttlSeconds", "refreshWhen"}:
                        diagnostics.error(
                            f"{output_location}.valueDomain.freshness",
                            "may contain only ttlSeconds and refreshWhen",
                        )
                    ttl_seconds = freshness.get("ttlSeconds")
                    if ttl_seconds is not None and (
                        not isinstance(ttl_seconds, int)
                        or isinstance(ttl_seconds, bool)
                        or not 1 <= ttl_seconds <= 31_536_000
                    ):
                        diagnostics.error(
                            f"{output_location}.valueDomain.freshness.ttlSeconds",
                            "must be a positive bounded lifetime no longer than one year",
                        )
                    refresh = freshness.get("refreshWhen")
                    if any(
                        not isinstance(reason, str)
                        or not re.search(
                            r"subject|identity|user|tenant|session|version|catalog|source|policy|config|payload|selection|resource|record|data|expir|ttl|consum|revok|chang|updat|invalid|edit",
                            reason,
                            re.IGNORECASE,
                        )
                        for reason in refresh
                    ):
                        diagnostics.error(
                            f"{output_location}.valueDomain.freshness.refreshWhen",
                            "must use source-derived semantic invalidation events",
                        )
            elif isinstance(domain, dict) and domain.get("kind") == "static":
                if set(domain) != {"kind", "values", "evidenceRefs"}:
                    diagnostics.error(
                        f"{output_location}.valueDomain",
                        "static output domains must contain exactly kind, values, and evidenceRefs",
                    )
                values = domain.get("values")
                if not isinstance(values, list) or not values:
                    diagnostics.error(
                        f"{output_location}.valueDomain.values",
                        "a static output domain must contain source-proven values",
                    )
                _validate_fact_evidence_refs(
                    domain.get("evidenceRefs"),
                    known,
                    evidence_by_id,
                    STATIC_DOMAIN_EVIDENCE_ROLES,
                    f"{output_location}.valueDomain.evidenceRefs",
                    diagnostics,
                    purpose="stable closed output-domain",
                )
                if isinstance(values, list):
                    for value_index, value in enumerate(values):
                        if json_schema_errors(value, _value_schema(output)):
                            diagnostics.error(
                                f"{output_location}.valueDomain.values[{value_index}]",
                                "must match the output Schema",
                            )
            elif isinstance(domain, dict) and domain.get("kind") == "unconstrained":
                if set(domain) != {"kind"}:
                    diagnostics.error(
                        f"{output_location}.valueDomain",
                        "unconstrained output domains may contain only kind",
                    )
            elif isinstance(domain, dict):
                diagnostics.error(
                    f"{output_location}.valueDomain.kind",
                    "must be static, dynamic, or unconstrained",
                )
        declared_outputs = [item for item in outputs if isinstance(item, dict)]
        for child_index, child in enumerate(declared_outputs):
            child_path = child.get("path")
            if not isinstance(child_path, list):
                continue
            for parent in declared_outputs:
                parent_path = parent.get("path")
                if (
                    not isinstance(parent_path, list)
                    or len(parent_path) >= len(child_path)
                    or child_path[: len(parent_path)] != parent_path
                ):
                    continue
                parent_schema = _value_schema(parent)
                nested_schema = _schema_at_relative_path(
                    parent_schema,
                    child_path[len(parent_path):],
                )
                if nested_schema is None or _schema_structure(nested_schema) != _schema_structure(_value_schema(child)):
                    diagnostics.error(
                        f"{location}.outputs[{child_index}].schema",
                        "must agree with the same nested path already declared by its parent output Schema",
                    )
        success_rule = capability.get("successRule")
        if isinstance(success_rule, dict):
            _validate_fact_evidence_refs(
                success_rule.get("evidenceRefs"),
                known,
                evidence_by_id,
                RESPONSE_EVIDENCE_ROLES,
                f"{location}.successRule.evidenceRefs",
                diagnostics,
                purpose="minimum successful response and required output",
            )
        coverage = capability.get("evidenceCoverage")
        if not isinstance(coverage, dict):
            diagnostics.error(f"{location}.evidenceCoverage", "must be an object")
        else:
            expected_coverage_categories = (
                {"sideEffect"}
                if capability.get("sideEffect") == "read"
                else set(WRITE_EVIDENCE)
            )
            if set(coverage) != expected_coverage_categories:
                diagnostics.error(
                    f"{location}.evidenceCoverage",
                    "must contain exactly the evidence categories required by the declared side effect: "
                    + ", ".join(sorted(expected_coverage_categories)),
                )
            for category, record in coverage.items():
                record_location = f"{location}.evidenceCoverage.{category}"
                if not isinstance(record, dict):
                    diagnostics.error(record_location, "must be an object")
                    continue
                if record.get("assertionLevel") not in {"fact", "inference", "unknown"}:
                    diagnostics.error(f"{record_location}.assertionLevel", "must classify confidence")
                if category == "sideEffect":
                    if set(record) != {
                        "declaredSideEffect",
                        "assertionLevel",
                        "evidenceRefs",
                    }:
                        diagnostics.error(
                            record_location,
                            "must contain exactly declaredSideEffect, assertionLevel, and evidenceRefs",
                        )
                    if record.get("declaredSideEffect") != capability.get("sideEffect"):
                        diagnostics.error(
                            f"{record_location}.declaredSideEffect",
                            "must match the capability sideEffect",
                        )
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
    known_evidence = _known_evidence(contract)
    evidence_by_id = {
        item.get("evidenceId"): item
        for item in contract.get("evidenceCatalog", [])
        if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
    }
    known_requirement_ids = {
        item.get("requirementId")
        for item in contract.get("consumerRequirements", {}).get("requirements", [])
        if isinstance(item, dict) and isinstance(item.get("requirementId"), str)
    }
    capabilities = _capabilities_by_id(contract)
    capability_ids = set(capabilities)
    handoff_pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for handoff_index, handoff in enumerate(contract.get("handoffs", [])):
        location = f"canonical-contract.handoffs[{handoff_index}]"
        if not isinstance(handoff, dict):
            diagnostics.error(location, "must be an object")
            continue
        source_id = handoff.get("fromCapabilityId")
        target_id = handoff.get("toCapabilityId")
        source = capabilities.get(source_id)
        target = capabilities.get(target_id)
        if source is None or target is None or source_id == target_id:
            diagnostics.error(location, "must connect two distinct declared capabilities")
            continue
        pair = (source_id, target_id)
        if pair in handoff_pairs:
            diagnostics.error(location, "duplicates an existing handoff pair")
        else:
            handoff_pairs[pair] = handoff
        if not isinstance(handoff.get("required"), bool):
            diagnostics.error(f"{location}.required", "must be boolean")
        mappings = handoff.get("mappings")
        if not isinstance(mappings, list) or not mappings:
            diagnostics.error(f"{location}.mappings", "must contain at least one typed mapping")
            mappings = []
        seen_mappings: set[tuple[Any, ...]] = set()
        for mapping_index, mapping in enumerate(mappings):
            mapping_location = f"{location}.mappings[{mapping_index}]"
            if not isinstance(mapping, dict):
                diagnostics.error(mapping_location, "must be an object")
                continue
            mapping_key = (
                tuple(mapping.get("sourcePath", [])),
                mapping.get("targetInput"),
                mapping.get("mappingKind"),
            )
            if mapping_key in seen_mappings:
                diagnostics.error(mapping_location, "duplicates a mapping in this handoff")
            seen_mappings.add(mapping_key)
            output = _declared_output(source, mapping.get("sourcePath"))
            target_input = _declared_input(target, mapping.get("targetInput"))
            if output is None:
                diagnostics.error(
                    f"{mapping_location}.sourcePath",
                    "must resolve to one exactly declared source output",
                )
            if target_input is None:
                diagnostics.error(
                    f"{mapping_location}.targetInput",
                    "must name one declared target input",
                )
            if (
                output is not None
                and target_input is not None
                and not _mapping_compatible(output, target_input, mapping.get("mappingKind"))
            ):
                diagnostics.error(
                    mapping_location,
                    "mappingKind and source output schema/cardinality must match the target input",
                )
            if target_input is not None and not any(
                isinstance(strategy, dict)
                and strategy.get("kind") == "upstream-tool"
                and strategy.get("capabilityId") == source_id
                and strategy.get("outputPath") == mapping.get("sourcePath")
                and strategy.get("mappingKind") == mapping.get("mappingKind")
                for strategy in target_input.get("sourceStrategies", [])
            ):
                diagnostics.error(
                    mapping_location,
                    "must exactly match one upstream-tool source strategy on the target input",
                )
        _validate_evidence_refs(
            handoff.get("evidenceRefs"),
            known_evidence,
            f"{location}.evidenceRefs",
            diagnostics,
        )
    for target_id, target in capabilities.items():
        for input_index, target_input in enumerate(target.get("inputs", [])):
            if not isinstance(target_input, dict):
                continue
            for strategy_index, strategy in enumerate(target_input.get("sourceStrategies", [])):
                if not isinstance(strategy, dict) or strategy.get("kind") != "upstream-tool":
                    continue
                source_id = strategy.get("capabilityId")
                handoff = handoff_pairs.get((source_id, target_id))
                matches = (
                    isinstance(handoff, dict)
                    and any(
                        isinstance(mapping, dict)
                        and mapping.get("sourcePath") == strategy.get("outputPath")
                        and mapping.get("targetInput") == target_input.get("name")
                        and mapping.get("mappingKind") == strategy.get("mappingKind")
                        for mapping in handoff.get("mappings", [])
                    )
                )
                if not matches:
                    diagnostics.error(
                        f"canonical-contract.capabilities[{target_id}].inputs[{input_index}].sourceStrategies[{strategy_index}]",
                        "upstream-tool acquisition needs one matching typed Canonical handoff",
                    )
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
    for node_index, node in enumerate(graph_nodes):
        if not isinstance(node.get("independentValue"), str) or not node.get("independentValue", "").strip():
            diagnostics.error(
                f"canonical-contract.capabilityGraph.nodes[{node_index}].independentValue",
                "must explain the independently selectable business value",
            )
    workflow_entries = {
        item.get("entryCapabilityId")
        for item in contract.get("workflows", [])
        if isinstance(item, dict)
    }
    edge_keys: set[tuple[Any, ...]] = set()
    observed_pair_counts: dict[tuple[str, str], int] = {}
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
        source_id = edge.get("fromCapabilityId")
        target_id = edge.get("toCapabilityId")
        if source_id not in capability_ids or target_id not in capability_ids or source_id == target_id:
            diagnostics.error(location, "must connect two distinct declared capabilities")
        composition = edge.get("composition")
        kind = edge.get("kind")
        if composition == "observed":
            if kind not in OBSERVED_EDGE_KINDS:
                diagnostics.error(location, "observed edges must use a declared handoff kind")
            pair = (source_id, target_id)
            handoff = handoff_pairs.get(pair)
            if handoff is None:
                diagnostics.error(location, "observed handoff edges need one matching Canonical handoff")
            else:
                observed_pair_counts[pair] = observed_pair_counts.get(pair, 0) + 1
                if observed_pair_counts[pair] > 1:
                    diagnostics.error(location, "duplicates the observed edge for one Canonical handoff")
                if edge.get("required") is not handoff.get("required"):
                    diagnostics.error(f"{location}.required", "must match the Canonical handoff")
            if kind == "conditional-handoff" and edge.get("required") is not False:
                diagnostics.error(f"{location}.required", "conditional handoffs must be optional")
            if kind == "hard-precondition" and edge.get("required") is not True:
                diagnostics.error(f"{location}.required", "hard preconditions must be required")
        elif composition == "derived":
            if kind not in DERIVED_EDGE_KINDS:
                diagnostics.error(location, "derived planning edges must use an allowed derived kind")
            if kind == "optional-planning" and edge.get("required") is not False:
                diagnostics.error(
                    f"{location}.required",
                    "optional planning edges must not become mandatory execution dependencies",
                )
        else:
            diagnostics.error(f"{location}.composition", "must be observed or derived")
        if not isinstance(edge.get("required"), bool):
            diagnostics.error(f"{location}.required", "must be boolean")
        if edge.get("kind") == "hard-precondition" and edge.get("toCapabilityId") not in workflow_entries:
            diagnostics.error(location, "hard preconditions must terminate in a runtime-guarded write workflow")
        if edge.get("composition") == "derived":
            target = next(
                (item for item in contract.get("capabilities", []) if isinstance(item, dict) and item.get("capabilityId") == edge.get("toCapabilityId")),
                None,
            )
            protection = target.get("runtimeProtection") if isinstance(target, dict) else None
            if (
                isinstance(protection, dict)
                and protection.get("mode") == "deterministic-workflow"
                and target.get("capabilityId") not in workflow_entries
            ):
                diagnostics.error(
                    location,
                    "derived composition must retain the target's declared deterministic guard",
                )

    missing_observed_pairs = set(handoff_pairs) - set(observed_pair_counts)
    if missing_observed_pairs:
        diagnostics.error(
            "canonical-contract.capabilityGraph.edges",
            "must contain one observed edge for every handoff: "
            + ", ".join(f"{source}->{target}" for source, target in sorted(missing_observed_pairs)),
        )

    goal_ids: set[str] = set()
    goal_covered_capability_ids: set[str] = set()
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
        if not isinstance(goal.get("intent"), str) or not goal.get("intent", "").strip():
            diagnostics.error(f"{location}.intent", "must describe the user-visible outcome")
        if any(key in goal for key in ("fixedSequence", "orderedSteps", "mandatoryTranscript")):
            diagnostics.error(location, "a Goal Contract must describe information and completion, not a rigid transcript")
        if "hardConstraints" in goal:
            diagnostics.error(
                f"{location}.hardConstraints",
                "free-text hard constraints are forbidden; use capability constraints and deterministic workflow references",
            )
        need_ids: set[str] = set()
        supplied_pairs: dict[tuple[str, str], list[str]] = {}
        needs = goal.get("informationNeeds")
        if not isinstance(needs, list) or not needs:
            diagnostics.error(f"{location}.informationNeeds", "must contain information requirements")
            needs = []
        for need_index, need in enumerate(needs):
            need_location = f"{location}.informationNeeds[{need_index}]"
            if not isinstance(need, dict):
                diagnostics.error(need_location, "must be an object")
                continue
            allowed_need_fields = {
                "informationId",
                "description",
                "classification",
                "type",
                "schema",
                "condition",
                "satisfiedBy",
                "supplies",
                "reuseWhile",
            }
            unexpected_need_fields = set(need) - allowed_need_fields
            if unexpected_need_fields:
                diagnostics.error(
                    need_location,
                    "contains unsupported information-need fields: "
                    + ", ".join(sorted(unexpected_need_fields)),
                )
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
            if need.get("type") not in JSON_TYPES - {"null"}:
                diagnostics.error(
                    f"{need_location}.type",
                    "must declare the portable JSON type of the information need",
                )
            need_schema = need.get("schema")
            if "schema" in need and not isinstance(need_schema, dict):
                diagnostics.error(
                    f"{need_location}.schema",
                    "must be a portable JSON Schema object when declared",
                )
            if need.get("type") in {"object", "array"} and not isinstance(need_schema, dict):
                diagnostics.error(
                    f"{need_location}.schema",
                    "object and array information needs require a complete closed JSON Schema",
                )
            if isinstance(need_schema, dict):
                _validate_schema_shape(need_schema, f"{need_location}.schema", diagnostics)
                if need_schema.get("type") != need.get("type"):
                    diagnostics.error(
                        f"{need_location}.schema.type",
                        "must match the information need type",
                    )
            supplies = need.get("supplies", [])
            if not isinstance(supplies, list):
                diagnostics.error(f"{need_location}.supplies", "must be an array")
                supplies = []
            for supply_index, supply in enumerate(supplies):
                supply_location = f"{need_location}.supplies[{supply_index}]"
                if (
                    not isinstance(supply, dict)
                    or set(supply) != {"capabilityId", "inputName", "mappingKind"}
                ):
                    diagnostics.error(
                        supply_location,
                        "must contain exactly capabilityId, inputName, and mappingKind",
                    )
                    continue
                target_capability = capabilities.get(supply.get("capabilityId"))
                target_input = (
                    _declared_input(target_capability, supply.get("inputName"))
                    if isinstance(target_capability, dict)
                    else None
                )
                if not isinstance(target_input, dict):
                    diagnostics.error(
                        supply_location,
                        "must reference one exact declared public Capability input",
                    )
                    continue
                if not _mapping_compatible(
                    need,
                    target_input,
                    supply.get("mappingKind"),
                ):
                    diagnostics.error(
                        supply_location,
                        "Goal information Schema/cardinality and mappingKind must match the supplied Capability input",
                    )
                pair = (str(supply.get("capabilityId")), str(supply.get("inputName")))
                if pair in supplied_pairs:
                    diagnostics.error(
                        supply_location,
                        "duplicates a Capability input already supplied by another information mapping",
                    )
                supplied_pairs.setdefault(pair, []).append(str(information_id))
            if classification == "requiredWhen" and not isinstance(need.get("condition"), dict):
                diagnostics.error(f"{need_location}.condition", "conditional information needs an activation condition")
            sources = need.get("satisfiedBy")
            if not isinstance(sources, list) or not sources:
                diagnostics.error(f"{need_location}.satisfiedBy", "must declare how the information can be acquired")
                sources = []
            seen_sources: set[str] = set()
            for source_index, source in enumerate(sources):
                source_location = f"{need_location}.satisfiedBy[{source_index}]"
                if isinstance(source, dict):
                    source_identity = json.dumps(source, ensure_ascii=False, sort_keys=True)
                    if source_identity in seen_sources:
                        diagnostics.error(source_location, "duplicates an acquisition source")
                    seen_sources.add(source_identity)
                if not isinstance(source, dict) or source.get("kind") not in {"user", "trusted-host-context", "capability"}:
                    diagnostics.error(source_location, "has an invalid acquisition kind")
                elif source.get("kind") == "capability":
                    provider = capabilities.get(source.get("capabilityId"))
                    if provider is None:
                        diagnostics.error(source_location, "references an unknown capability")
                    else:
                        provider_output = _declared_output(provider, source.get("outputPath"))
                        if provider_output is None:
                            diagnostics.error(
                                f"{source_location}.outputPath",
                                "must resolve to one exactly declared provider output",
                            )
                        elif _schema_structure(_value_schema(provider_output)) != _schema_structure(_value_schema(need)):
                            diagnostics.error(
                                source_location,
                                "provider output Schema must match the information need Schema",
                            )
                elif source.get("kind") == "trusted-host-context" and "requirementId" in source:
                    if source.get("requirementId") not in known_requirement_ids:
                        diagnostics.error(
                            f"{source_location}.requirementId",
                            "must name a declared generic Host requirement",
                        )
            if classification in {"derived", "dynamic"}:
                for source_index, source in enumerate(sources):
                    if not isinstance(source, dict):
                        continue
                    source_location = f"{need_location}.satisfiedBy[{source_index}]"
                    if source.get("kind") == "user":
                        diagnostics.error(
                            source_location,
                            f"classification `{classification}` is trusted system-produced information and cannot be satisfied by user input; use an exact capability output or declared trusted Host requirement",
                        )
                    if (
                        source.get("kind") == "trusted-host-context"
                        and not isinstance(source.get("requirementId"), str)
                    ):
                        diagnostics.error(
                            f"{source_location}.requirementId",
                            f"classification `{classification}` requires an assessable declared trusted Host requirement",
                        )
            for supply_index, supply in enumerate(supplies):
                if not isinstance(supply, dict):
                    continue
                target_capability = capabilities.get(supply.get("capabilityId"))
                target_input = (
                    _declared_input(target_capability, supply.get("inputName"))
                    if isinstance(target_capability, dict)
                    else None
                )
                if not isinstance(target_input, dict):
                    continue
                strategies = [
                    strategy
                    for strategy in target_input.get("sourceStrategies", [])
                    if isinstance(strategy, (str, dict))
                ]
                incompatible_sources = [
                    source
                    for source in sources
                    if isinstance(source, dict)
                    and not any(
                        _goal_source_matches_strategy(
                            source,
                            strategy,
                            supply.get("mappingKind"),
                        )
                        for strategy in strategies
                    )
                ]
                if incompatible_sources:
                    diagnostics.error(
                        f"{need_location}.supplies[{supply_index}]",
                        "every advertised Goal acquisition source must exactly align with the supplied Capability input source strategy and Host requirement",
                    )
                if (
                    classification == "optional"
                    and target_input.get("required") is True
                ):
                    diagnostics.error(
                        f"{need_location}.classification",
                        "optional Goal information cannot supply an unconditionally required Capability input",
                    )
            if (
                sources
                and all(source.get("kind") == "trusted-host-context" for source in sources if isinstance(source, dict))
                and any(not isinstance(source.get("requirementId"), str) for source in sources if isinstance(source, dict))
            ):
                diagnostics.error(
                    f"{need_location}.satisfiedBy",
                    "a sole trusted Host acquisition path must explicitly name its generic requirementId",
                )
            if classification in {"dynamic", "derived", "requiredWhen"} and not isinstance(need.get("reuseWhile"), dict):
                diagnostics.error(f"{need_location}.reuseWhile", "must declare when acquired information remains reusable")
            reuse_while = need.get("reuseWhile")
            if isinstance(reuse_while, dict):
                if (
                    not set(reuse_while) <= REUSE_CLAIMS | {"evidenceRefs"}
                    or not (set(reuse_while) & REUSE_CLAIMS)
                    or any(reuse_while.get(claim) is not True for claim in set(reuse_while) & REUSE_CLAIMS)
                ):
                    diagnostics.error(
                        f"{need_location}.reuseWhile",
                        "must use only executable true-valued reuse claims plus evidenceRefs",
                    )
                _validate_fact_evidence_refs(
                    reuse_while.get("evidenceRefs"),
                    known_evidence,
                    evidence_by_id,
                    REUSE_EVIDENCE_ROLES,
                    f"{need_location}.reuseWhile.evidenceRefs",
                    diagnostics,
                    purpose="information freshness and reuse boundary",
                )
                for source in sources:
                    if source.get("kind") != "capability":
                        continue
                    provider = capabilities.get(source.get("capabilityId"))
                    provider_output = (
                        _declared_output(provider, source.get("outputPath"))
                        if isinstance(provider, dict)
                        else None
                    )
                    expected_reuse_claims: set[str] = set()
                    output_domain = (
                        provider_output.get("valueDomain")
                        if isinstance(provider_output, dict)
                        else None
                    )
                    if not (
                        isinstance(output_domain, dict)
                        and output_domain.get("kind") == "dynamic"
                    ) and isinstance(provider, dict):
                        source_path = source.get("outputPath")
                        parent_domains = [
                            output.get("valueDomain")
                            for output in sorted(
                                provider.get("outputs", []),
                                key=lambda item: len(item.get("path", []))
                                if isinstance(item, dict)
                                and isinstance(item.get("path"), list)
                                else -1,
                                reverse=True,
                            )
                            if isinstance(output, dict)
                            and isinstance(output.get("path"), list)
                            and isinstance(source_path, list)
                            and source_path[: len(output["path"])] == output["path"]
                            and isinstance(output.get("valueDomain"), dict)
                            and output["valueDomain"].get("kind") == "dynamic"
                        ]
                        output_domain = parent_domains[0] if parent_domains else None
                    if isinstance(output_domain, dict) and output_domain.get("kind") == "dynamic":
                        if output_domain.get("identityScoped") is True:
                            expected_reuse_claims.add("sameSubject")
                        if output_domain.get("tenantScoped") is True:
                            expected_reuse_claims.add("sameTenant")
                        if output_domain.get("sessionScoped") is True:
                            expected_reuse_claims.add("sameSession")
                        freshness = output_domain.get("freshness", {})
                        if isinstance(freshness, dict) and (
                            freshness.get("ttlSeconds")
                            or any(
                                isinstance(reason, str) and "expir" in reason.lower()
                                for reason in freshness.get("refreshWhen", [])
                            )
                        ):
                            expected_reuse_claims.add("notExpired")
                    provider_attachments = provider.get("attachments", {}) if isinstance(provider, dict) else {}
                    result_binding = (
                        provider_attachments.get("resultBinding")
                        if isinstance(provider_attachments, dict)
                        else None
                    )
                    if (
                        isinstance(result_binding, dict)
                        and source.get("outputPath") == result_binding.get("outputPath")
                    ):
                        scoping = result_binding.get("scoping", {})
                        if isinstance(scoping, dict) and scoping.get("subject") is True:
                            expected_reuse_claims.add("sameSubject")
                        if isinstance(scoping, dict) and scoping.get("session") is True:
                            expected_reuse_claims.add("sameSession")
                        if result_binding.get("reuse") == "single-use":
                            expected_reuse_claims.add("notConsumed")
                    missing_reuse_claims = expected_reuse_claims - set(reuse_while)
                    if missing_reuse_claims:
                        diagnostics.error(
                            f"{need_location}.reuseWhile",
                            "must preserve provider scope and freshness claims: "
                            + ", ".join(sorted(missing_reuse_claims)),
                        )
        need_classifications = {
            need.get("informationId"): need.get("classification")
            for need in needs
            if isinstance(need, dict) and isinstance(need.get("informationId"), str)
        }
        need_schemas = {
            need["informationId"]: _value_schema(need)
            for need in needs
            if isinstance(need, dict) and isinstance(need.get("informationId"), str)
        }
        need_by_id = {
            need.get("informationId"): need
            for need in needs
            if isinstance(need, dict) and isinstance(need.get("informationId"), str)
        }
        supply_roots_by_capability: dict[str, dict[str, str]] = {}
        for need in needs:
            if not isinstance(need, dict) or not isinstance(need.get("informationId"), str):
                continue
            for supply in need.get("supplies", []):
                if (
                    isinstance(supply, dict)
                    and isinstance(supply.get("capabilityId"), str)
                    and isinstance(supply.get("inputName"), str)
                ):
                    supply_roots_by_capability.setdefault(
                        supply["capabilityId"], {}
                    )[need["informationId"]] = supply["inputName"]

        for (capability_id, input_name), supplier_ids in supplied_pairs.items():
            target_capability = capabilities.get(capability_id)
            target_input = (
                _declared_input(target_capability, input_name)
                if isinstance(target_capability, dict)
                else None
            )
            if not isinstance(target_input, dict) or not target_input.get("requiredWhen"):
                continue
            supplier = need_by_id.get(supplier_ids[0]) if supplier_ids else None
            if not isinstance(supplier, dict) or supplier.get("classification") != "requiredWhen":
                diagnostics.error(
                    f"{location}.informationNeeds",
                    f"Capability input `{capability_id}.{input_name}` is conditional and must be supplied by a requiredWhen Goal need",
                )
                continue
            goal_condition = _condition_semantics(
                supplier.get("condition"),
                supply_roots_by_capability.get(capability_id, {}),
            )
            capability_conditions = {
                json.dumps(_condition_semantics(condition), sort_keys=True)
                for condition in target_input.get("requiredWhen", [])
                if isinstance(condition, dict)
            }
            if json.dumps(goal_condition, sort_keys=True) not in capability_conditions:
                diagnostics.error(
                    f"{location}.informationNeeds",
                    f"Goal condition supplying `{capability_id}.{input_name}` must match the Capability requiredWhen rule after input mapping",
                )
        for need_index, need in enumerate(needs):
            if not isinstance(need, dict) or need.get("classification") != "requiredWhen":
                continue
            condition = need.get("condition")
            condition_location = f"{location}.informationNeeds[{need_index}].condition"
            if not isinstance(condition, dict):
                continue
            _validate_condition(
                condition,
                need_ids,
                known_evidence,
                condition_location,
                diagnostics,
                need_schemas,
            )
            _validate_fact_evidence_refs(
                condition.get("evidenceRefs"),
                known_evidence,
                evidence_by_id,
                CONDITION_EVIDENCE_ROLES,
                f"{condition_location}.evidenceRefs",
                diagnostics,
                purpose="Goal conditional business rule",
            )
            for dependency_id in _condition_fields(condition):
                if dependency_id == need.get("informationId"):
                    diagnostics.error(
                        condition_location,
                        "a conditional information need cannot activate itself",
                    )
                if need_classifications.get(dependency_id) == "optional":
                    diagnostics.error(
                        condition_location,
                        "a requiredWhen activation dependency cannot be optional because the goal must resolve the condition before completion",
                    )
        conditional_dependencies = {
            str(need.get("informationId")): {
                dependency
                for dependency in _condition_fields(need.get("condition"))
                if need_classifications.get(dependency) == "requiredWhen"
            }
            for need in needs
            if isinstance(need, dict)
            and need.get("classification") == "requiredWhen"
            and isinstance(need.get("informationId"), str)
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit_conditional(information_id: str) -> bool:
            if information_id in visiting:
                return True
            if information_id in visited:
                return False
            visiting.add(information_id)
            has_cycle = any(
                visit_conditional(dependency)
                for dependency in conditional_dependencies.get(information_id, set())
            )
            visiting.remove(information_id)
            visited.add(information_id)
            return has_cycle

        if any(visit_conditional(information_id) for information_id in conditional_dependencies):
            diagnostics.error(
                f"{location}.informationNeeds",
                "requiredWhen information dependencies must be acyclic so activation can be resolved",
            )

        execution_dependencies: dict[str, set[str]] = {}
        for need in needs:
            if not isinstance(need, dict) or not isinstance(need.get("informationId"), str):
                continue
            need_node = f"need:{need['informationId']}"
            execution_dependencies.setdefault(need_node, set())
            for source in need.get("satisfiedBy", []):
                if (
                    isinstance(source, dict)
                    and source.get("kind") == "capability"
                    and isinstance(source.get("capabilityId"), str)
                ):
                    execution_dependencies.setdefault(
                        f"capability:{source['capabilityId']}", set()
                    ).add(need_node)
            for supply in need.get("supplies", []):
                if isinstance(supply, dict) and isinstance(supply.get("capabilityId"), str):
                    execution_dependencies[need_node].add(
                        f"capability:{supply['capabilityId']}"
                    )
            if need.get("classification") == "requiredWhen":
                for dependency in _condition_fields(need.get("condition")):
                    if dependency in need_ids:
                        execution_dependencies.setdefault(
                            f"need:{dependency}", set()
                        ).add(need_node)

        visiting_execution: set[str] = set()
        visited_execution: set[str] = set()

        def visit_execution(node: str) -> bool:
            if node in visiting_execution:
                return True
            if node in visited_execution:
                return False
            visiting_execution.add(node)
            cycle = any(
                visit_execution(dependency)
                for dependency in execution_dependencies.get(node, set())
            )
            visiting_execution.remove(node)
            visited_execution.add(node)
            return cycle

        if any(visit_execution(node) for node in execution_dependencies):
            diagnostics.error(
                f"{location}.informationNeeds",
                "Goal acquisition, supplies, and activation dependencies must be acyclic",
            )
        predicate = goal.get("completionPredicate")
        if not isinstance(predicate, dict) or not predicate.get("operator"):
            diagnostics.error(f"{location}.completionPredicate", "must be machine readable")
        elif predicate.get("operator") == "all-satisfied":
            ids = predicate.get("informationIds")
            if (
                not isinstance(ids, list)
                or len(ids) != len(set(ids))
                or set(ids) != need_ids
            ):
                diagnostics.error(f"{location}.completionPredicate.informationIds", "must cover the goal's information needs")
        elif predicate.get("operator") == "workflow-completed" and predicate.get("workflowId") not in workflow_ids:
            diagnostics.error(f"{location}.completionPredicate.workflowId", "must reference a declared workflow")
        elif predicate.get("operator") == "any-satisfied":
            ids = predicate.get("informationIds")
            if (
                not isinstance(ids, list)
                or not ids
                or len(ids) != len(set(ids))
                or not set(ids) <= need_ids
            ):
                diagnostics.error(f"{location}.completionPredicate.informationIds", "must name declared information needs")
            else:
                for need_index, need in enumerate(needs):
                    if (
                        isinstance(need, dict)
                        and need.get("informationId") not in set(ids)
                        and need.get("classification") != "optional"
                    ):
                        diagnostics.error(
                            f"{location}.informationNeeds[{need_index}].classification",
                            "information outside an any-satisfied predicate must be optional",
                        )
        elif predicate.get("operator") not in {"all-satisfied", "workflow-completed", "any-satisfied"}:
            diagnostics.error(f"{location}.completionPredicate.operator", "is not an allowed completion predicate")
        if isinstance(predicate, dict) and "conditionalNeedsOnlyWhenActive" in predicate and predicate.get(
            "conditionalNeedsOnlyWhenActive"
        ) is not True:
            diagnostics.error(
                f"{location}.completionPredicate.conditionalNeedsOnlyWhenActive",
                "must be true when explicitly declared because inactive conditional needs never block completion",
            )
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
            capability_id
            for need in needs
            if isinstance(need, dict) and need.get("classification") == "requiredWhen"
            for capability_id in {
                *{
                    source.get("capabilityId")
                    for source in need.get("satisfiedBy", [])
                    if isinstance(source, dict)
                    and source.get("kind") == "capability"
                },
                *{
                    supply.get("capabilityId")
                    for supply in need.get("supplies", [])
                    if isinstance(supply, dict)
                },
            }
            if capability_id in optional_id_set
        }
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
                _validate_condition(
                    condition,
                    need_ids,
                    known_evidence,
                    f"{conditional_location}.condition",
                    diagnostics,
                    need_schemas,
                )
                _validate_fact_evidence_refs(
                    condition.get("evidenceRefs"),
                    known_evidence,
                    evidence_by_id,
                    CONDITION_EVIDENCE_ROLES,
                    f"{conditional_location}.condition.evidenceRefs",
                    diagnostics,
                    purpose="conditional Capability activation rule",
                )
                linked_conditions = [
                    need.get("condition")
                    for need in needs
                    if isinstance(need, dict)
                    and need.get("classification") == "requiredWhen"
                    and (
                        any(
                            isinstance(source, dict)
                            and source.get("kind") == "capability"
                            and source.get("capabilityId") == capability_id
                            for source in need.get("satisfiedBy", [])
                        )
                        or any(
                            isinstance(supply, dict)
                            and supply.get("capabilityId") == capability_id
                            for supply in need.get("supplies", [])
                        )
                    )
                    and isinstance(need.get("condition"), dict)
                ]
                if capability_id not in inferred_conditional_ids or not any(
                    _condition_semantics(condition)
                    == _condition_semantics(linked_condition)
                    for linked_condition in linked_conditions
                ):
                    diagnostics.error(
                        conditional_location,
                        "object-form conditional capability must use the same condition as its linked requiredWhen information need",
                    )
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

        provider_ids: set[str] = set()
        expected_required_ids: set[str] = set()
        expected_optional_ids: set[str] = set()
        expected_conditional_ids: set[str] = set()
        predicate = goal.get("completionPredicate", {})
        alternative_information_ids = {
            item
            for item in predicate.get("informationIds", [])
            if isinstance(item, str)
        } if isinstance(predicate, dict) and predicate.get("operator") == "any-satisfied" else set()
        for need_index, need in enumerate(needs):
            if not isinstance(need, dict):
                continue
            classification = need.get("classification")
            sources = [
                source
                for source in need.get("satisfiedBy", [])
                if isinstance(source, dict)
            ]
            need_provider_ids = {
                source.get("capabilityId")
                for source in sources
                if source.get("kind") == "capability"
                and isinstance(source.get("capabilityId"), str)
            }
            provider_ids.update(need_provider_ids)
            non_capability_alternative = any(
                source.get("kind") in {"user", "trusted-host-context", "derived"}
                for source in sources
            )
            for provider_id in need_provider_ids:
                provider_ids.add(provider_id)
                if need.get("informationId") in alternative_information_ids:
                    expected_optional_ids.add(provider_id)
                elif classification == "requiredWhen":
                    expected_optional_ids.add(provider_id)
                    expected_conditional_ids.add(provider_id)
                elif classification == "optional":
                    expected_optional_ids.add(provider_id)
                elif len(need_provider_ids) > 1 or non_capability_alternative:
                    expected_optional_ids.add(provider_id)
                else:
                    expected_required_ids.add(provider_id)
        predicate = goal.get("completionPredicate", {})
        workflow_entry_id = None
        if isinstance(predicate, dict) and predicate.get("operator") == "workflow-completed":
            workflow = next(
                (
                    item
                    for item in contract.get("workflows", [])
                    if isinstance(item, dict)
                    and item.get("workflowId") == predicate.get("workflowId")
                ),
                None,
            )
            if isinstance(workflow, dict):
                workflow_entry_id = workflow.get("entryCapabilityId")
                if isinstance(workflow_entry_id, str):
                    expected_required_ids.add(workflow_entry_id)
        if required_id_set != expected_required_ids:
            diagnostics.error(
                f"{location}.requiredCapabilityIds",
                "must be derived exactly from non-conditional capability information sources plus the completion workflow entry: "
                + ", ".join(sorted(expected_required_ids)),
            )
        if optional_id_set != expected_optional_ids:
            diagnostics.error(
                f"{location}.optionalCapabilityIds",
                "must be derived exactly from optional and requiredWhen capability information sources: "
                + ", ".join(sorted(expected_optional_ids)),
            )
        if seen_conditional != expected_conditional_ids:
            diagnostics.error(
                f"{location}.conditionalCapabilityIds",
                "must be derived exactly from requiredWhen capability information sources: "
                + ", ".join(sorted(expected_conditional_ids)),
            )

        goal_capability_ids = required_id_set | optional_id_set | provider_ids
        goal_covered_capability_ids.update(goal_capability_ids)
        for capability_id, input_name in supplied_pairs:
            if capability_id not in goal_capability_ids:
                diagnostics.error(
                    f"{location}.informationNeeds",
                    f"supplies `{capability_id}.{input_name}` even though that Capability is not part of the Goal",
                )
        for capability_id in sorted(goal_capability_ids):
            target_capability = capabilities.get(capability_id)
            if not isinstance(target_capability, dict):
                continue
            for target_input in target_capability.get("inputs", []):
                if not isinstance(target_input, dict):
                    continue
                input_name = target_input.get("name")
                needs_supply = target_input.get("required") is True or bool(
                    target_input.get("requiredWhen")
                )
                if (
                    needs_supply
                    and isinstance(input_name, str)
                    and (capability_id, input_name) not in supplied_pairs
                ):
                    diagnostics.error(
                        f"{location}.informationNeeds",
                        f"must collect or acquire the required Capability input `{capability_id}.{input_name}` through one exact supplies mapping",
                    )

    graph_node_ids = {
        node.get("capabilityId")
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("capabilityId"), str)
    }
    uncovered_goal_nodes = graph_node_ids - goal_covered_capability_ids
    if uncovered_goal_nodes:
        diagnostics.error(
            "canonical-contract.goals",
            "every independently valuable capabilityGraph node must belong to at least one partial or complete Goal: "
            + ", ".join(sorted(uncovered_goal_nodes)),
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
    requirements = contract.get("consumerRequirements", {}).get("requirements", [])
    required_host_capabilities: set[str] = set()
    requirement_ids: set[str] = set()
    if not isinstance(requirements, list):
        diagnostics.error("canonical-contract.consumerRequirements.requirements", "must be an array")
        requirements = []
    for index, requirement in enumerate(requirements):
        location = f"canonical-contract.consumerRequirements.requirements[{index}]"
        if not isinstance(requirement, dict):
            diagnostics.error(location, "must be an object")
            continue
        requirement_id = requirement.get("requirementId")
        host_capability = requirement.get("hostCapability")
        if not isinstance(requirement_id, str) or not requirement_id:
            diagnostics.error(f"{location}.requirementId", "must be a non-empty portable identifier")
        elif requirement_id in requirement_ids:
            diagnostics.error(f"{location}.requirementId", "must be unique")
        else:
            requirement_ids.add(requirement_id)
        if not isinstance(host_capability, str) or not host_capability:
            diagnostics.error(f"{location}.hostCapability", "must name a generic facility key")
        else:
            required_host_capabilities.add(host_capability)
            expected_host_capability = GENERIC_HOST_REQUIREMENTS.get(requirement_id)
            if (
                expected_host_capability is not None
                and host_capability != expected_host_capability
            ):
                diagnostics.error(
                    f"{location}.hostCapability",
                    f"generic requirement `{requirement_id}` must map to `{expected_host_capability}`",
                )
        if not isinstance(requirement.get("description"), str) or not requirement.get("description", "").strip():
            diagnostics.error(f"{location}.description", "must describe the facility without assuming a Producer")
        if requirement.get("onMissing") not in {"disable", "requires-host-integration"}:
            diagnostics.error(
                f"{location}.onMissing",
                "must deterministically disable the dependent capability or require Host integration",
            )
        expected_on_missing = GENERIC_HOST_ON_MISSING.get(requirement_id)
        if expected_on_missing is not None and requirement.get("onMissing") != expected_on_missing:
            diagnostics.error(
                f"{location}.onMissing",
                f"generic requirement `{requirement_id}` must use `{expected_on_missing}`",
            )
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
    known_evidence = _known_evidence(contract)
    writes = {
        item.get("capabilityId"): item
        for item in contract.get("capabilities", [])
        if isinstance(item, dict) and item.get("sideEffect") != "read"
    }
    protected_writes = {
        capability_id: capability
        for capability_id, capability in writes.items()
        if isinstance(capability.get("runtimeProtection"), dict)
        and capability["runtimeProtection"].get("mode") == "deterministic-workflow"
    }
    workflows = [item for item in contract.get("workflows", []) if isinstance(item, dict)]
    workflow_by_entry = {item.get("entryCapabilityId"): item for item in workflows}
    if set(workflow_by_entry) != set(protected_writes) or len(workflows) != len(protected_writes):
        diagnostics.error(
            "canonical-contract.workflows",
            "must contain exactly one hard workflow for every deterministic-workflow capability and none for backend-authoritative writes",
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
        if guard_asset != "portable-workflow-guard.mjs#dispatchWithPolicy":
            diagnostics.error(
                f"{location}.guardAsset",
                "must use the generic portable dispatchWithPolicy boundary",
            )
        bindings = workflow.get("bindings")
        if not isinstance(bindings, list) or not bindings:
            diagnostics.error(
                f"{location}.bindings",
                "must describe source-proven actual and protected expected values",
            )
            bindings = []
        capability = protected_writes.get(workflow.get("entryCapabilityId"), {})
        capability_inputs = {
            item.get("name")
            for item in capability.get("inputs", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        } if isinstance(capability, dict) else set()
        capability_inputs_by_name = {
            item["name"]: item
            for item in capability.get("inputs", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        } if isinstance(capability, dict) else {}
        binding_names: set[str] = set()
        for binding_index, binding in enumerate(bindings):
            binding_location = f"{location}.bindings[{binding_index}]"
            if not isinstance(binding, dict):
                diagnostics.error(binding_location, "must be an object")
                continue
            name = binding.get("name")
            if not isinstance(name, str) or not name:
                diagnostics.error(f"{binding_location}.name", "must be a stable non-empty name")
            elif name in binding_names:
                diagnostics.error(f"{binding_location}.name", "must be unique within the workflow")
            else:
                binding_names.add(name)
            actual_source = binding.get("actualSource")
            if not isinstance(actual_source, dict) or actual_source.get("kind") not in {
                "capability-input",
                "runtime-context",
                "derived-calculation",
                "constant",
            }:
                diagnostics.error(
                    f"{binding_location}.actualSource",
                    "must name a capability input, runtime context value, deterministic calculation, or constant",
                )
            elif actual_source.get("kind") == "capability-input" and actual_source.get("inputName") not in capability_inputs:
                diagnostics.error(
                    f"{binding_location}.actualSource.inputName",
                    "must name an entry capability input",
                )
            elif actual_source.get("kind") == "capability-input":
                relative_path = actual_source.get("path", [])
                input_item = capability_inputs_by_name.get(actual_source.get("inputName"))
                if (
                    not isinstance(relative_path, list)
                    or any(not isinstance(segment, str) or not segment for segment in relative_path)
                    or not isinstance(input_item, dict)
                    or _schema_at_relative_path(_value_schema(input_item), relative_path) is None
                ):
                    diagnostics.error(
                        f"{binding_location}.actualSource.path",
                        "must resolve inside the declared entry capability input Schema",
                    )
            elif actual_source.get("kind") == "runtime-context" and (
                not isinstance(actual_source.get("path"), list)
                or not actual_source.get("path")
                or any(not isinstance(segment, str) or not segment for segment in actual_source.get("path", []))
            ):
                diagnostics.error(
                    f"{binding_location}.actualSource.path",
                    "runtime context sources must declare a non-empty protected Host path",
                )
            elif actual_source.get("kind") == "derived-calculation" and actual_source.get("algorithm") not in {
                "canonical-json-sha256",
                "ordered-id-list",
            }:
                diagnostics.error(
                    f"{binding_location}.actualSource.algorithm",
                    "must name an allowed deterministic calculation",
                )
            elif (
                actual_source.get("kind") == "derived-calculation"
                and actual_source.get("inputName") not in capability_inputs
            ):
                diagnostics.error(
                    f"{binding_location}.actualSource.inputName",
                    "must name an entry capability input",
                )
            elif actual_source.get("kind") == "derived-calculation":
                relative_path = actual_source.get("path", [])
                input_item = capability_inputs_by_name.get(actual_source.get("inputName"))
                if (
                    not isinstance(relative_path, list)
                    or any(not isinstance(segment, str) or not segment for segment in relative_path)
                    or not isinstance(input_item, dict)
                    or _schema_at_relative_path(_value_schema(input_item), relative_path) is None
                ):
                    diagnostics.error(
                        f"{binding_location}.actualSource.path",
                        "must resolve inside the deterministic calculation input Schema",
                    )
            elif actual_source.get("kind") == "constant" and "value" not in actual_source:
                diagnostics.error(
                    f"{binding_location}.actualSource.value",
                    "constant sources must declare their immutable value",
                )
            if isinstance(actual_source, dict) and actual_source.get("kind") in {
                "capability-input",
                "runtime-context",
                "derived-calculation",
                "constant",
            }:
                allowed_actual_fields = {
                    "capability-input": {"kind", "inputName", "path"},
                    "runtime-context": {"kind", "claim", "requirementId", "path"},
                    "derived-calculation": {"kind", "algorithm", "inputName", "path"},
                    "constant": {"kind", "value"},
                }[actual_source["kind"]]
                unexpected_actual_fields = set(actual_source) - allowed_actual_fields
                if unexpected_actual_fields:
                    diagnostics.error(
                        f"{binding_location}.actualSource",
                        "contains unsupported source fields: "
                        + ", ".join(sorted(unexpected_actual_fields)),
                    )
            if isinstance(actual_source, dict) and actual_source.get("kind") == "runtime-context":
                claim = actual_source.get("claim")
                requirement_id = actual_source.get("requirementId")
                claim_contract = RUNTIME_CONTEXT_CLAIMS.get(claim)
                if not isinstance(claim, str) or not claim:
                    diagnostics.error(
                        f"{binding_location}.actualSource.claim",
                        "runtime context sources must name a semantic claim",
                    )
                if requirement_id not in {
                    item.get("requirementId")
                    for item in contract.get("consumerRequirements", {}).get("requirements", [])
                    if isinstance(item, dict)
                }:
                    diagnostics.error(
                        f"{binding_location}.actualSource.requirementId",
                        "must name a declared generic Host requirement",
                    )
                if requirement_id not in capability.get("hostRequirements", []):
                    diagnostics.error(
                        f"{binding_location}.actualSource.requirementId",
                        "the entry capability must declare the Host requirement used by this runtime claim",
                    )
                if claim_contract is not None:
                    expected_requirement, expected_path, expected_binding_names = claim_contract
                    if requirement_id != expected_requirement or actual_source.get("path") != expected_path:
                        diagnostics.error(
                            f"{binding_location}.actualSource",
                            f"runtime claim `{claim}` must use {expected_requirement} at path {expected_path}",
                        )
                    if name not in expected_binding_names:
                        diagnostics.error(
                            f"{binding_location}.name",
                            f"runtime claim `{claim}` cannot satisfy binding `{name}`",
                        )
            expected_source = binding.get("expectedSource")
            if not isinstance(expected_source, dict) or expected_source.get("kind") not in {
                "protected-runtime-state",
                "constant",
            }:
                diagnostics.error(
                    f"{binding_location}.expectedSource",
                    "must come from protected runtime state or an immutable constant, never a public Tool argument",
                )
            elif expected_source.get("kind") == "protected-runtime-state" and (
                not isinstance(expected_source.get("path"), list)
                or not expected_source.get("path")
                or any(not isinstance(segment, str) or not segment for segment in expected_source.get("path", []))
            ):
                diagnostics.error(
                    f"{binding_location}.expectedSource.path",
                    "protected runtime sources must declare a non-empty state path",
                )
            elif expected_source.get("kind") == "constant" and (
                "value" not in expected_source
                or actual_source.get("kind") != "constant"
                or expected_source.get("value") != actual_source.get("value")
            ):
                diagnostics.error(
                    f"{binding_location}.expectedSource.value",
                    "constant expected values must exactly match an immutable actual constant",
                )
            if isinstance(expected_source, dict) and expected_source.get("kind") in {
                "protected-runtime-state",
                "constant",
            }:
                allowed_expected_fields = {
                    "protected-runtime-state": {"kind", "path"},
                    "constant": {"kind", "value"},
                }[expected_source["kind"]]
                unexpected_expected_fields = set(expected_source) - allowed_expected_fields
                if unexpected_expected_fields:
                    diagnostics.error(
                        f"{binding_location}.expectedSource",
                        "contains unsupported source fields: "
                        + ", ".join(sorted(unexpected_expected_fields)),
                    )
            if (
                isinstance(expected_source, dict)
                and expected_source.get("kind") == "protected-runtime-state"
                and expected_source.get("path") != [name]
            ):
                diagnostics.error(
                    f"{binding_location}.expectedSource.path",
                    "protected operation state is keyed by the exact workflow binding name",
                )
            if binding.get("comparator") != "json-equals":
                diagnostics.error(
                    f"{binding_location}.comparator",
                    "must use deterministic json-equals comparison",
                )
            _validate_evidence_refs(
                binding.get("evidenceRefs"),
                known_evidence,
                f"{binding_location}.evidenceRefs",
                diagnostics,
            )
        for constraint in capability.get("constraints", []) if isinstance(capability, dict) else []:
            if not isinstance(constraint, dict) or constraint.get("kind") != "grant-binding":
                continue
            fields = constraint.get("fields", [])
            if not isinstance(fields, list) or not set(fields) <= binding_names:
                diagnostics.error(
                    f"{location}.bindings",
                    "must cover every field in the entry capability's grant-binding constraints",
                )
        protection = capability.get("runtimeProtection", {}) if isinstance(capability, dict) else {}
        if protection.get("workflowId") != workflow_id:
            diagnostics.error(
                f"{location}.workflowId",
                "must match the entry capability runtimeProtection.workflowId",
            )
        enforcement = workflow.get("enforcement")
        if (
            not isinstance(enforcement, dict)
            or not isinstance(enforcement.get("owner"), str)
            or not enforcement.get("owner", "").strip()
            or enforcement.get("mustCompleteBeforeDispatch") is not True
            or enforcement.get("rejectWithoutDispatch") is not True
        ):
            diagnostics.error(
                f"{location}.enforcement",
                "must name the generated executable runtime boundary and reject before dispatch",
            )
        if workflow.get("unknownOutcomePolicy") not in {
            "stop-and-reconcile-before-any-new-attempt",
            "reconcile-before-any-retry",
        }:
            diagnostics.error(f"{location}.unknownOutcomePolicy", "must prohibit automatic retries after uncertain writes")
        checks = workflow.get("verificationChecks")
        if not isinstance(checks, list) or not checks or not any("zero-dispatch" in str(item) for item in checks):
            diagnostics.error(f"{location}.verificationChecks", "must include executable zero-dispatch bypass checks")

    if not protected_writes:
        return
    guard_path = root / "portable-workflow-guard.mjs"
    if not guard_path.is_file():
        diagnostics.error("portable-workflow-guard.mjs", "is required by deterministic-workflow capabilities")
        return
    guard_source = guard_path.read_text(encoding="utf-8")
    reference_guard_path = (
        Path(__file__).resolve().parent.parent
        / "assets"
        / "portable-workflow-guard.mjs"
    )
    if (
        not reference_guard_path.is_file()
        or guard_path.read_bytes() != reference_guard_path.read_bytes()
    ):
        diagnostics.error(
            "portable-workflow-guard.mjs",
            "must be the byte-exact reviewed Code2Skill Guard asset; source-specific policy belongs in protected operation data, not custom Guard code",
        )
    required_guard_tokens = {
        "GuardViolation",
        "UnknownDispatchOutcomeError",
        "PortableWorkflowGuard",
        "dispatchWithPolicy",
        "bindingSources",
        "runtimeContext",
        "safeInput",
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
    for capability_id, capability in protected_writes.items():
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
        if not re.match(r"\s*\(\s*input\s*,\s*context\s*\)", function_body):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must receive exactly (input, context) at the guarded boundary",
            )
        dispatch_matches = list(re.finditer(r"\.\s*dispatchWithPolicy\s*\(", function_body))
        if len(dispatch_matches) != 1:
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must contain exactly one guarded dispatch",
            )
            continue
        workflow = workflow_by_entry.get(capability_id, {})
        workflow_id = workflow.get("workflowId") if isinstance(workflow, dict) else None
        if "verify" in function_body:
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must not execute an arbitrary verifier before dispatch",
            )
        if not isinstance(workflow_id, str) or not re.search(
            rf"workflowId\s*:\s*['\"]{re.escape(workflow_id)}['\"]",
            function_body,
        ):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must bind its exact Canonical workflowId",
            )
        if not isinstance(workflow_id, str) or not re.search(
            rf"const\s+protectedWorkflowState\s*=\s*protectedWorkflowStateFor\s*\(\s*context\s*,\s*['\"]{re.escape(workflow_id)}['\"]\s*\)",
            function_body,
        ):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must resolve protected workflow state from runtime context",
            )
        if any(token in function_body for token in ("expectedBindings", "requiredBindings", "bindings:")):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must not receive or pass caller-projected workflow bindings",
            )
        if not re.search(r"(?:^|[,\n])\s*input\s*(?:,|\n)", function_body):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must pass its exact public input into the Guard",
            )
        if not re.search(r"runtimeContext\s*:\s*context\b", function_body):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must let the Guard project trusted runtime-context bindings",
            )
        if not re.search(
            r"operationKey\s*:\s*protectedWorkflowState\.operationKey\b",
            function_body,
        ):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` operation key must come from protected runtime state",
            )
        if not re.search(r"\}\s*,\s*context\.dispatch\s*\)", function_body):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must dispatch the same Guard-frozen input through context.dispatch",
            )
        dispatch_start = dispatch_matches[0].start()
        dispatch_end_match = re.search(
            r"\}\s*,\s*context\.dispatch\s*\)",
            function_body[dispatch_start:],
        )
        dispatch_policy = (
            function_body[dispatch_start:dispatch_start + dispatch_end_match.end()]
            if dispatch_end_match is not None
            else function_body[dispatch_start:]
        )
        if re.search(r"\binput\s*:", dispatch_policy):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must not substitute another value for the exact input shorthand passed to the Guard",
            )
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
        side_effect_aliases: set[str] = set()
        side_effect_names = (
            r"fetch|request|axios|writeFile|writeFileSync|appendFile|appendFileSync|"
            r"unlink|unlinkSync|rename|renameSync|rm|rmSync|exec|execFile|spawn|"
            r"spawnSync|upload|publish|send|dispatch"
        )
        for assignment in re.finditer(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\r\n]+)",
            before_dispatch,
        ):
            if re.search(rf"\b(?:{side_effect_names})\b", assignment.group(2)):
                side_effect_aliases.add(assignment.group(1))
        for destructuring in re.finditer(
            r"\b(?:const|let|var)\s*\{([^}]+)\}\s*=\s*[^;\r\n]+",
            before_dispatch,
        ):
            for entry in destructuring.group(1).split(","):
                match = re.fullmatch(
                    rf"\s*(?:{side_effect_names})\s*(?::\s*([A-Za-z_$][\w$]*))?\s*",
                    entry,
                )
                if match:
                    side_effect_aliases.add(match.group(1) or entry.strip())
        if any(
            re.search(rf"\b{re.escape(alias)}\s*\(", before_dispatch)
            for alias in side_effect_aliases
        ):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` performs an aliased external side effect before its Guard",
            )
        body_opening = function_body.find("{")
        guarded_body = function_body[body_opening + 1:] if body_opening >= 0 else function_body
        if re.search(r"(?:^|[;{}])\s*(?:input|context)\s*=", guarded_body):
            diagnostics.error(
                "function-core/index.mjs",
                f"write Function `{function_export}` must not reassign its exact input or trusted context",
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
    delivery = matrix.get("delivery")
    delivery_statuses = {
        "functionCore": {"pending", "generated"},
        "mcpServer": {"pending", "generated"},
        "skill": {"pending", "generated"},
        "runtime": {"not-run", "partially-verified", "verified"},
        "deployment": {"not-deployed", "deployed"},
    }
    if not isinstance(delivery, dict):
        diagnostics.error(
            "verification-matrix.delivery",
            "must report Function, MCP, Skill, runtime, and deployment separately",
        )
    else:
        if set(delivery) != set(delivery_statuses):
            diagnostics.error(
                "verification-matrix.delivery",
                "must contain exactly functionCore, mcpServer, skill, runtime, and deployment",
            )
        for surface, allowed_statuses in delivery_statuses.items():
            record = delivery.get(surface)
            if not isinstance(record, dict) or record.get("status") not in allowed_statuses:
                diagnostics.error(
                    f"verification-matrix.delivery.{surface}.status",
                    f"must be one of {sorted(allowed_statuses)}",
                )
    expected_delivery = derive_verification_matrix(contract, compatibility).get("delivery")
    if pre_finalize and delivery != expected_delivery:
        diagnostics.error(
            "verification-matrix.delivery",
            "pre-finalization delivery states must retain the canonical pending/not-run/not-deployed baseline",
        )
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
        member_ids = workflow_capability_ids(workflow) if isinstance(workflow, dict) else []
        all_members_host_compatible = bool(member_ids) and all(
            compatibility_by_id.get(capability_id) == "enabled"
            for capability_id in member_ids
        )
        if status.get("hostVerified") and not all_members_host_compatible:
            diagnostics.error(
                f"{location}.status.hostVerified",
                "workflow Host verification requires every covered capability to be enabled",
            )
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
            and all_members_host_compatible
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
        protection = capability.get("runtimeProtection")
        requires_workflow = (
            isinstance(protection, dict)
            and protection.get("mode") == "deterministic-workflow"
        )
        if (
            isinstance(protection, dict)
            and protection.get("mode") == "unresolved"
            and status.get("runtimeVerified")
        ):
            diagnostics.error(
                location,
                "an unresolved write cannot be runtime-verified before its backend protection boundary is proven",
            )
        if requires_workflow and status.get("runtimeVerified") and not workflow_runtime_ready:
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
            or (capability.get("sideEffect") != "read" and not write_evidence_complete(capability, contract))
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
            and (not requires_workflow or workflow_approved)
            and not canonical_review
            and status.get("blocked") is False
        )
        expected_review = status.get("blocked") is False and not capability_approved
        if status.get("requiresReview") is not expected_review:
            diagnostics.error(
                f"{location}.status.requiresReview",
                "must be derived from verification gates, canonical readiness/evidence/conflicts, Host compatibility, workflows, and blocked state",
            )

    if not pre_finalize and isinstance(delivery, dict):
        verified_count = sum(
            1
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("status"), dict)
            and row["status"].get("runtimeVerified") is True
        )
        if rows and verified_count == len(rows):
            expected_runtime = "verified"
        elif verified_count:
            expected_runtime = "partially-verified"
        else:
            expected_runtime = "not-run"
        expected_final_delivery = {
            "functionCore": {"status": "generated"},
            "mcpServer": {"status": "generated"},
            "skill": {"status": "generated"},
            "runtime": {"status": expected_runtime},
            "deployment": {"status": "not-deployed"},
        }
        if delivery != expected_final_delivery:
            diagnostics.error(
                "verification-matrix.delivery",
                "final delivery states must be derived from emitted artifacts and per-capability runtime verification; deployment remains not-deployed until an external deployment system records separate evidence",
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
    _validate_feature_boundary_and_exposure(contract, diagnostics)
    _validate_information_model(contract, diagnostics)
    _validate_outputs_and_evidence(contract, diagnostics)
    _validate_conflicts_and_missing_sources(topology, contract, diagnostics)
    _validate_graph_and_goals(contract, diagnostics)
    _validate_host_contracts(contract, consumer, host, compatibility, diagnostics)
    _validate_workflows_and_runtime(root, contract, diagnostics)
    _validate_verification_matrix(contract, compatibility, matrix, pre_finalize, diagnostics)

    _json_equal(goal, derive_goal_contract(contract), "goal-contract.json", diagnostics)
    expected_schema_contract = derive_schema_contract(contract)
    expected_documentation_contract = derive_documentation_contract(contract)
    function_schema_contract = _read_json(
        root / "function-core" / "schema-contract.json",
        diagnostics,
    )
    mcp_schema_contract = _read_json(
        root / "mcp-tool" / "schema-contract.json",
        diagnostics,
    )
    if function_schema_contract is not None:
        _json_equal(
            function_schema_contract,
            expected_schema_contract,
            "function-core/schema-contract.json",
            diagnostics,
        )
    if mcp_schema_contract is not None:
        _json_equal(
            mcp_schema_contract,
            expected_schema_contract,
            "mcp-tool/schema-contract.json",
            diagnostics,
        )
    actual_documentation_contract = _read_json(
        root / "references" / "capability-contracts.json",
        diagnostics,
    )
    if actual_documentation_contract is not None:
        _json_equal(
            actual_documentation_contract,
            expected_documentation_contract,
            "references/capability-contracts.json",
            diagnostics,
        )
    expected_bundle = derive_bundle(contract)
    actual_bundle = _read_json(root / "capability-bundle.json", diagnostics)
    if actual_bundle is not None:
        _json_equal(actual_bundle, expected_bundle, "capability-bundle.json", diagnostics)
        actual_draft = _read_json(root / "capability-draft.json", diagnostics)
        if actual_draft is not None:
            _json_equal(actual_draft, derive_draft(expected_bundle, contract), "capability-draft.json", diagnostics)
