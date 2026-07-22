#!/usr/bin/env python3
"""Language- and host-neutral helpers for Code2Skill vNext contracts."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Optional
from urllib.parse import urlparse


VNEXT_SCHEMA = "vNext"
SOURCE_AVAILABILITY = {
    "available",
    "partially-available",
    "unavailable",
    "not-provided",
    "not-found",
}
READINESS = {"ready", "requires-review", "blocked"}
HOST_SUPPORT = {"supported", "external-integration", "unsupported"}
COMPATIBILITY = {"enabled", "requires-host-integration", "disabled", "blocked"}
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
FEATURE_PRIMARY_ROLES = {
    "client-feature": "client-observed-only",
    "explicitly-scoped-service-feature": "explicitly-scoped-surface",
}
EXPOSURE_KINDS = {
    "client-feature": {"client-request", "client-local-behavior"},
    "explicitly-scoped-service-feature": {"explicitly-scoped-operation"},
}
RUNTIME_PROTECTION_MODES = {
    "backend-authoritative",
    "deterministic-workflow",
    "unresolved",
}
WRITE_EVIDENCE = {
    "sideEffect",
    "backendContract",
    "authorization",
    "validation",
    "idempotency",
    "unknownOutcome",
}
WRITE_EVIDENCE_ROLES = {
    "sideEffect": {
        "transport-contract",
        "business-rule",
        "side-effect",
        "persistence",
        "explicit-message-operation",
        "explicit-operation",
        "behavior-test",
    },
    "backendContract": {
        "transport-contract",
        "data-contract",
        "business-rule",
        "side-effect",
        "persistence",
        "explicit-message-operation",
        "explicit-operation",
    },
    "authorization": {"authorization", "identity", "tenant"},
    "validation": {"validation", "business-rule", "data-contract", "side-effect"},
    "idempotency": {"idempotency", "persistence", "workflow-test"},
    "unknownOutcome": {"unknown-outcome", "error-contract", "workflow-test"},
}


class ContractError(ValueError):
    """Raised when a vNext portable contract is internally inconsistent."""


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def json_schema_errors(
    value: Any,
    schema: Any,
    path: str = "$",
) -> list[str]:
    """Validate the portable JSON-Schema subset emitted by Code2Skill."""

    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]
    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _json_type_matches(value, expected_type):
        return [f"{path}: expected {expected_type}"]
    if "enum" in schema and value not in schema.get("enum", []):
        errors.append(f"{path}: value is outside enum")
    if "const" in schema and value != schema.get("const"):
        errors.append(f"{path}: value does not equal const")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            for name in required:
                if isinstance(name, str) and name not in value:
                    errors.append(f"{path}.{name}: required property is missing")
        if isinstance(properties, dict):
            for name, child in value.items():
                if name in properties:
                    errors.extend(json_schema_errors(child, properties[name], f"{path}.{name}"))
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{name}: additional property is forbidden")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(json_schema_errors(item, schema["items"], f"{path}[{index}]"))
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and not isinstance(min_items, bool) and len(value) < min_items:
            errors.append(f"{path}: array has fewer than minItems")
        if isinstance(max_items, int) and not isinstance(max_items, bool) and len(value) > max_items:
            errors.append(f"{path}: array has more than maxItems")
        if schema.get("uniqueItems") is True:
            seen_items: set[str] = set()
            for item in value:
                try:
                    identity = repr(_canonical_json_value(item))
                except (TypeError, ValueError):
                    identity = repr(item)
                if identity in seen_items:
                    errors.append(f"{path}: array items must be unique")
                    break
                seen_items.add(identity)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        exclusive_maximum = schema.get("exclusiveMaximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"{path}: value is below minimum")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"{path}: value is above maximum")
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            errors.append(f"{path}: value is not above exclusiveMinimum")
        if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
            errors.append(f"{path}: value is not below exclusiveMaximum")
    if isinstance(value, str) and isinstance(schema.get("pattern"), str):
        try:
            if re.search(schema["pattern"], value) is None:
                errors.append(f"{path}: value does not match pattern")
        except re.error:
            errors.append(f"{path}: schema pattern is invalid")
    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and not isinstance(min_length, bool) and len(value) < min_length:
            errors.append(f"{path}: string is shorter than minLength")
        if isinstance(max_length, int) and not isinstance(max_length, bool) and len(value) > max_length:
            errors.append(f"{path}: string is longer than maxLength")
        if schema.get("format") == "uri":
            parsed = urlparse(value)
            if not parsed.scheme or any(character.isspace() for character in value):
                errors.append(f"{path}: value is not an absolute URI")
    return errors


def _canonical_json_value(value: Any) -> Any:
    """Return a hashable, deterministic representation for portable JSON values."""

    if isinstance(value, dict):
        return tuple(
            (key, _canonical_json_value(child))
            for key, child in sorted(value.items())
        )
    if isinstance(value, list):
        return tuple(_canonical_json_value(child) for child in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("value is not portable JSON")


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{location} must be an object")
    return value


def _list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{location} must be an array")
    return value


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{location} must be a non-empty string")
    return value


def _string_list(value: Any, location: str) -> list[str]:
    result = _list(value, location)
    for index, item in enumerate(result):
        _string(item, f"{location}[{index}]")
    return result


def workflow_capability_ids(workflow: dict[str, Any]) -> list[str]:
    """Return the explicit Canonical members covered by one hard Workflow."""

    values = workflow.get("capabilityIds")
    if isinstance(values, list):
        return [item for item in values if isinstance(item, str)]
    return []


def _conditional_capability_id(value: Any, location: str) -> str:
    if isinstance(value, str):
        return _string(value, location)
    item = _object(value, location)
    capability_id = _string(item.get("capabilityId"), f"{location}.capabilityId")
    condition = _object(item.get("condition"), f"{location}.condition")
    _string(condition.get("operator"), f"{location}.condition.operator")
    if not _condition_information_ids(condition):
        raise ContractError(
            f"{location}.condition must reference at least one information need"
        )
    return capability_id


def _condition_information_ids(condition: Any) -> set[str]:
    if not isinstance(condition, dict):
        return set()
    result: set[str] = set()
    path = condition.get("path")
    if isinstance(path, list) and path and isinstance(path[0], str):
        result.add(path[0])
    children = condition.get("conditions", condition.get("operands"))
    if isinstance(children, list):
        for child in children:
            result.update(_condition_information_ids(child))
    child = condition.get("condition")
    if isinstance(child, dict):
        result.update(_condition_information_ids(child))
    return result


def _goal_conditional_capability_ids(
    goal: dict[str, Any],
    graph: dict[str, Any],
) -> set[str]:
    """Return optional capabilities with a machine-readable activation source."""

    optional_ids = {
        item
        for item in goal.get("optionalCapabilityIds", [])
        if isinstance(item, str)
    }
    conditional_ids: set[str] = set()
    for entry in goal.get("conditionalCapabilityIds", []):
        if not isinstance(entry, dict):
            continue
        capability_id = entry.get("capabilityId")
        condition = entry.get("condition")
        if (
            isinstance(capability_id, str)
            and capability_id in optional_ids
            and isinstance(condition, dict)
            and isinstance(condition.get("operator"), str)
            and condition.get("operator")
            and _condition_information_ids(condition)
        ):
            conditional_ids.add(capability_id)
    for need in goal.get("informationNeeds", []):
        if not isinstance(need, dict) or need.get("classification") != "requiredWhen":
            continue
        condition = need.get("condition")
        if (
            not isinstance(condition, dict)
            or not isinstance(condition.get("operator"), str)
            or not condition.get("operator")
            or not _condition_information_ids(condition)
        ):
            continue
        for source in need.get("satisfiedBy", []):
            if not isinstance(source, dict) or source.get("kind") != "capability":
                continue
            capability_id = source.get("capabilityId")
            if isinstance(capability_id, str) and capability_id in optional_ids:
                conditional_ids.add(capability_id)

    for edge in graph.get("edges", []):
        if not isinstance(edge, dict) or "conditional" not in str(edge.get("kind", "")):
            continue
        for key in ("fromCapabilityId", "toCapabilityId"):
            capability_id = edge.get(key)
            if isinstance(capability_id, str) and capability_id in optional_ids:
                conditional_ids.add(capability_id)
    return conditional_ids


def validate_source_topology(topology: dict[str, Any]) -> set[str]:
    """Validate an explicit-root topology and return its declared source IDs."""

    if topology.get("schemaVersion") != VNEXT_SCHEMA:
        raise ContractError("source-topology.schemaVersion must equal vNext")
    _string(topology.get("topologyId"), "source-topology.topologyId")
    boundary = _object(topology.get("authorizationBoundary"), "source-topology.authorizationBoundary")
    if boundary.get("discoveryPolicy") != "explicit-roots-only":
        raise ContractError("source-topology.authorizationBoundary.discoveryPolicy must equal explicit-roots-only")
    if boundary.get("machineWideDiscovery") is not False:
        raise ContractError("source-topology.authorizationBoundary.machineWideDiscovery must be false")

    source_ids: set[str] = set()
    for index, source in enumerate(_list(topology.get("sources"), "source-topology.sources")):
        item = _object(source, f"source-topology.sources[{index}]")
        source_id = _string(item.get("sourceId"), f"source-topology.sources[{index}].sourceId")
        if source_id in source_ids:
            raise ContractError(f"duplicate sourceId: {source_id}")
        source_ids.add(source_id)
        _string_list(item.get("semanticRoles"), f"source-topology.sources[{index}].semanticRoles")
        _string(item.get("root"), f"source-topology.sources[{index}].root")
        if item.get("availability") not in SOURCE_AVAILABILITY:
            raise ContractError(
                f"source-topology.sources[{index}].availability must be one of {sorted(SOURCE_AVAILABILITY)}"
            )
        if not isinstance(item.get("searched"), bool):
            raise ContractError(f"source-topology.sources[{index}].searched must be boolean")

    for index, missing in enumerate(_list(topology.get("missingSources", []), "source-topology.missingSources")):
        item = _object(missing, f"source-topology.missingSources[{index}]")
        if item.get("availability") not in SOURCE_AVAILABILITY - {"available"}:
            raise ContractError(
                f"source-topology.missingSources[{index}].availability must describe an unavailable source"
            )
        _string_list(item.get("semanticRoles"), f"source-topology.missingSources[{index}].semanticRoles")
        _string(item.get("reason"), f"source-topology.missingSources[{index}].reason")
    return source_ids


def validate_canonical_contract(contract: dict[str, Any], source_ids: set[str]) -> None:
    """Validate the portable portions needed for deterministic derivation."""

    if contract.get("schemaVersion") != VNEXT_SCHEMA:
        raise ContractError("canonical-contract.schemaVersion must equal vNext")
    _string(contract.get("contractId"), "canonical-contract.contractId")
    _string(contract.get("recordingId"), "canonical-contract.recordingId")
    _string(contract.get("sourceTopologyRef"), "canonical-contract.sourceTopologyRef")
    portable = _object(contract.get("portableCore"), "canonical-contract.portableCore")
    portable_bindings = {
        "languageBinding",
        "frameworkBinding",
        "architectureBinding",
        "hostBinding",
    }
    allowed_portable_fields = portable_bindings | {"discoveryBasis"}
    unknown_portable_fields = set(portable) - allowed_portable_fields
    if unknown_portable_fields:
        raise ContractError(
            "canonical-contract.portableCore contains unsupported runtime or Producer assumptions: "
            + ", ".join(sorted(unknown_portable_fields))
        )
    if any(portable.get(name) != "none" for name in portable_bindings):
        raise ContractError(
            "canonical-contract.portableCore must not bind a source language, framework, architecture, or consumer host"
        )
    if portable.get("discoveryBasis") != "observable-semantic-evidence":
        raise ContractError(
            "canonical-contract.portableCore.discoveryBasis must equal observable-semantic-evidence"
        )

    feature_boundary = _object(
        contract.get("featureBoundary"),
        "canonical-contract.featureBoundary",
    )
    if feature_boundary.get("scopeKind") != "business-feature":
        raise ContractError("canonical-contract.featureBoundary.scopeKind must equal business-feature")
    primary_role = feature_boundary.get("primaryEvidenceRole")
    if primary_role not in FEATURE_PRIMARY_ROLES:
        raise ContractError(
            "canonical-contract.featureBoundary.primaryEvidenceRole must be client-feature "
            "or explicitly-scoped-service-feature"
        )
    expected_inclusion = FEATURE_PRIMARY_ROLES[primary_role]
    if feature_boundary.get("inclusionRule") != expected_inclusion:
        raise ContractError(
            "canonical-contract.featureBoundary.inclusionRule must match its primary evidence role"
        )
    if feature_boundary.get("backendEvidenceRole") != "supplement-and-verify":
        raise ContractError(
            "canonical-contract.featureBoundary.backendEvidenceRole must equal supplement-and-verify"
        )
    primary_source_field = (
        "clientSourceIds" if primary_role == "client-feature" else "serviceSourceIds"
    )
    primary_source_ids = _string_list(
        feature_boundary.get(primary_source_field),
        f"canonical-contract.featureBoundary.{primary_source_field}",
    )
    if not primary_source_ids:
        raise ContractError(
            f"canonical-contract.featureBoundary.{primary_source_field} must not be empty"
        )
    if len(set(primary_source_ids)) != len(primary_source_ids):
        raise ContractError(
            f"canonical-contract.featureBoundary.{primary_source_field} must not contain duplicates"
        )
    unknown_primary_sources = set(primary_source_ids) - source_ids
    if unknown_primary_sources:
        raise ContractError(
            f"canonical-contract.featureBoundary.{primary_source_field} references unknown sources: "
            f"{', '.join(sorted(unknown_primary_sources))}"
        )
    supplementary_source_ids = _string_list(
        feature_boundary.get("supplementarySourceIds", []),
        "canonical-contract.featureBoundary.supplementarySourceIds",
    )
    if len(set(supplementary_source_ids)) != len(supplementary_source_ids):
        raise ContractError(
            "canonical-contract.featureBoundary.supplementarySourceIds must not contain duplicates"
        )
    unknown_supplementary_sources = set(supplementary_source_ids) - source_ids
    if unknown_supplementary_sources:
        raise ContractError(
            "canonical-contract.featureBoundary.supplementarySourceIds references unknown sources: "
            f"{', '.join(sorted(unknown_supplementary_sources))}"
        )
    if set(primary_source_ids) & set(supplementary_source_ids):
        raise ContractError(
            "canonical-contract.featureBoundary primary and supplementary source IDs must be disjoint"
        )

    evidence_ids: set[str] = set()
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for index, evidence in enumerate(_list(contract.get("evidenceCatalog"), "canonical-contract.evidenceCatalog")):
        item = _object(evidence, f"canonical-contract.evidenceCatalog[{index}]")
        evidence_id = _string(item.get("evidenceId"), f"canonical-contract.evidenceCatalog[{index}].evidenceId")
        if evidence_id in evidence_ids:
            raise ContractError(f"duplicate evidenceId: {evidence_id}")
        evidence_ids.add(evidence_id)
        evidence_by_id[evidence_id] = item
        if item.get("sourceId") not in source_ids:
            raise ContractError(f"evidence {evidence_id} references an unknown sourceId")
        _string(item.get("locator"), f"canonical-contract.evidenceCatalog[{index}].locator")
        _string(item.get("semanticRole"), f"canonical-contract.evidenceCatalog[{index}].semanticRole")
        if item.get("assertionLevel") not in {"fact", "inference", "unknown"}:
            raise ContractError(f"evidence {evidence_id} has an invalid assertionLevel")

    def validate_nested_evidence(value: Any, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_location = f"{location}.{key}"
                if key == "evidenceRefs":
                    for ref in _string_list(child, child_location):
                        if ref not in evidence_ids:
                            raise ContractError(f"{child_location} references unknown evidence {ref}")
                else:
                    validate_nested_evidence(child, child_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                validate_nested_evidence(child, f"{location}[{index}]")

    validate_nested_evidence(contract, "canonical-contract")

    consumer_requirements = _object(
        contract.get("consumerRequirements"),
        "canonical-contract.consumerRequirements",
    )
    requirement_ids: set[str] = set()
    for index, requirement in enumerate(_list(
        consumer_requirements.get("requirements"),
        "canonical-contract.consumerRequirements.requirements",
    )):
        item = _object(
            requirement,
            f"canonical-contract.consumerRequirements.requirements[{index}]",
        )
        requirement_id = _string(
            item.get("requirementId"),
            f"canonical-contract.consumerRequirements.requirements[{index}].requirementId",
        )
        if requirement_id in requirement_ids:
            raise ContractError(f"duplicate Host requirementId: {requirement_id}")
        requirement_ids.add(requirement_id)
        host_capability = _string(
            item.get("hostCapability"),
            f"canonical-contract.consumerRequirements.requirements[{index}].hostCapability",
        )
        expected_host_capability = GENERIC_HOST_REQUIREMENTS.get(requirement_id)
        if expected_host_capability is not None and host_capability != expected_host_capability:
            raise ContractError(
                f"generic Host requirement {requirement_id} must map to {expected_host_capability}"
            )
        _string(
            item.get("description"),
            f"canonical-contract.consumerRequirements.requirements[{index}].description",
        )
        if item.get("onMissing") not in {"disable", "requires-host-integration"}:
            raise ContractError(
                f"canonical-contract.consumerRequirements.requirements[{index}].onMissing is invalid"
            )
        expected_on_missing = GENERIC_HOST_ON_MISSING.get(requirement_id)
        if expected_on_missing is not None and item.get("onMissing") != expected_on_missing:
            raise ContractError(
                f"generic Host requirement {requirement_id} must use onMissing={expected_on_missing}"
            )

    capability_ids: set[str] = set()
    for index, capability in enumerate(_list(contract.get("capabilities"), "canonical-contract.capabilities")):
        item = _object(capability, f"canonical-contract.capabilities[{index}]")
        capability_id = _string(item.get("capabilityId"), f"canonical-contract.capabilities[{index}].capabilityId")
        if capability_id in capability_ids:
            raise ContractError(f"duplicate capabilityId: {capability_id}")
        capability_ids.add(capability_id)
        if item.get("readiness") not in READINESS:
            raise ContractError(f"capability {capability_id} has an invalid readiness")
        missing_evidence = _string_list(item.get("missingEvidence", []), f"capability {capability_id}.missingEvidence")
        if item.get("readiness") == "ready" and missing_evidence:
            raise ContractError(f"capability {capability_id} cannot be ready while evidence is missing")
        implementation = _object(
            item.get("implementation"),
            f"capability {capability_id}.implementation",
        )
        if implementation.get("kind") not in {"local", "http"}:
            raise ContractError(
                f"capability {capability_id}.implementation.kind must be local or http"
            )
        for ref in _string_list(item.get("evidenceRefs"), f"capability {capability_id}.evidenceRefs"):
            if ref not in evidence_ids:
                raise ContractError(f"capability {capability_id} references unknown evidence {ref}")

        exposure = _object(item.get("exposure"), f"capability {capability_id}.exposure")
        if exposure.get("kind") not in EXPOSURE_KINDS[primary_role]:
            raise ContractError(
                f"capability {capability_id}.exposure.kind is invalid for {primary_role}"
            )
        exposure_refs = _string_list(
            exposure.get("evidenceRefs"),
            f"capability {capability_id}.exposure.evidenceRefs",
        )
        if not exposure_refs:
            raise ContractError(
                f"capability {capability_id}.exposure.evidenceRefs must not be empty"
            )
        for ref in exposure_refs:
            evidence = evidence_by_id.get(ref)
            if evidence is None:
                raise ContractError(
                    f"capability {capability_id}.exposure.evidenceRefs references unknown evidence {ref}"
                )
            if evidence.get("sourceId") not in primary_source_ids:
                raise ContractError(
                    f"capability {capability_id}.exposure evidence must come from "
                    f"{primary_source_field}; supplementary backend evidence cannot create a capability"
                )
            if evidence.get("assertionLevel") != "fact":
                raise ContractError(
                    f"capability {capability_id}.exposure evidence must be fact-level"
                )
        supplemental_refs = _string_list(
            exposure.get("supplementalEvidenceRefs", []),
            f"capability {capability_id}.exposure.supplementalEvidenceRefs",
        )
        if set(exposure_refs) & set(supplemental_refs):
            raise ContractError(
                f"capability {capability_id}.exposure primary and supplemental evidence must be disjoint"
            )
        for ref in supplemental_refs:
            if ref not in evidence_ids:
                raise ContractError(
                    f"capability {capability_id}.exposure.supplementalEvidenceRefs "
                    f"references unknown evidence {ref}"
                )

        error_contract = _object(
            item.get("errorContract"),
            f"capability {capability_id}.errorContract",
        )
        if error_contract.get("format") != "structured":
            raise ContractError(
                f"capability {capability_id}.errorContract.format must equal structured"
            )
        if error_contract.get("preservesRecoveryContext") is not True:
            raise ContractError(
                f"capability {capability_id}.errorContract.preservesRecoveryContext must be true"
            )
        for path_name in ("codePath", "messagePath", "detailsPath"):
            path = _string_list(
                error_contract.get(path_name),
                f"capability {capability_id}.errorContract.{path_name}",
            )
            if not path:
                raise ContractError(
                    f"capability {capability_id}.errorContract.{path_name} must not be empty"
                )
        retryability_path = error_contract.get("retryabilityPath")
        if retryability_path is not None:
            retryability_segments = _string_list(
                retryability_path,
                f"capability {capability_id}.errorContract.retryabilityPath",
            )
            if not retryability_segments:
                raise ContractError(
                    f"capability {capability_id}.errorContract.retryabilityPath must not be empty"
                )
        if not isinstance(error_contract.get("defaultRetryable"), bool):
            raise ContractError(
                f"capability {capability_id}.errorContract.defaultRetryable must be boolean"
            )
        if retryability_path is None and error_contract.get("defaultRetryable") is not False:
            raise ContractError(
                f"capability {capability_id}.errorContract.defaultRetryable must be false "
                "when retryabilityPath is absent"
            )
        error_refs = _string_list(
            error_contract.get("evidenceRefs"),
            f"capability {capability_id}.errorContract.evidenceRefs",
        )
        if not error_refs:
            raise ContractError(
                f"capability {capability_id}.errorContract.evidenceRefs must not be empty"
            )
        for ref in error_refs:
            if ref not in evidence_ids:
                raise ContractError(
                    f"capability {capability_id}.errorContract.evidenceRefs references unknown evidence {ref}"
                )

        runtime_protection = item.get("runtimeProtection")
        if item.get("sideEffect") != "read" or runtime_protection is not None:
            protection = _object(
                runtime_protection,
                f"capability {capability_id}.runtimeProtection",
            )
            mode = protection.get("mode")
            if mode not in RUNTIME_PROTECTION_MODES:
                raise ContractError(
                    f"capability {capability_id}.runtimeProtection.mode must be "
                    "backend-authoritative, deterministic-workflow, or unresolved"
                )
            if item.get("sideEffect") == "read":
                raise ContractError(
                    f"read capability {capability_id} must not declare write runtime protection"
                )
            protection_refs = _string_list(
                protection.get("evidenceRefs"),
                f"capability {capability_id}.runtimeProtection.evidenceRefs",
            )
            if not protection_refs:
                raise ContractError(
                    f"capability {capability_id}.runtimeProtection.evidenceRefs must not be empty"
                )
            if item.get("readiness") == "ready" and any(
                evidence_by_id.get(ref, {}).get("assertionLevel") != "fact"
                for ref in protection_refs
            ):
                raise ContractError(
                    f"ready capability {capability_id}.runtimeProtection must use fact-level evidence"
                )
            if mode == "unresolved":
                if item.get("readiness") not in {"requires-review", "blocked"}:
                    raise ContractError(
                        f"unresolved capability {capability_id} must be requires-review or blocked"
                    )
                if not missing_evidence:
                    raise ContractError(
                        f"unresolved capability {capability_id} must declare missingEvidence"
                    )
                if "owner" in protection or "workflowId" in protection or "workflowId" in item:
                    raise ContractError(
                        f"unresolved capability {capability_id} must not guess an owner or workflowId"
                    )
            elif mode == "backend-authoritative":
                if protection.get("owner") != "target-api":
                    raise ContractError(
                        f"capability {capability_id}.runtimeProtection.owner must equal target-api"
                    )
                if "workflowId" in protection or "workflowId" in item:
                    raise ContractError(
                        f"backend-authoritative capability {capability_id} must not declare a workflowId"
                    )
            else:
                workflow_id = _string(
                    protection.get("workflowId"),
                    f"capability {capability_id}.runtimeProtection.workflowId",
                )
                if "owner" in protection and protection.get("owner") != "portable-runtime":
                    raise ContractError(
                        f"capability {capability_id}.runtimeProtection.owner must equal portable-runtime when present"
                    )
                if item.get("workflowId") not in {None, workflow_id}:
                    raise ContractError(
                        f"capability {capability_id}.workflowId must match runtimeProtection.workflowId"
                    )
        for input_index, input_value in enumerate(_list(item.get("inputs"), f"capability {capability_id}.inputs")):
            input_item = _object(input_value, f"capability {capability_id}.inputs[{input_index}]")
            _string(input_item.get("name"), f"capability {capability_id}.inputs[{input_index}].name")
            if not isinstance(input_item.get("required"), bool):
                raise ContractError(f"capability {capability_id}.inputs[{input_index}].required must be boolean")
            value_domain = _object(
                input_item.get("valueDomain", {"kind": "unconstrained"}),
                f"capability {capability_id}.inputs[{input_index}].valueDomain",
            )
            if value_domain.get("kind") not in {"static", "dynamic", "unconstrained"}:
                raise ContractError(f"capability {capability_id} has an invalid valueDomain kind")
            if value_domain.get("kind") == "dynamic":
                _string(value_domain.get("sourceCapabilityId"), "dynamic valueDomain.sourceCapabilityId")
                _object(value_domain.get("freshness"), "dynamic valueDomain.freshness")

    for capability in contract["capabilities"]:
        for input_item in capability.get("inputs", []):
            value_domain = input_item.get("valueDomain", {})
            provider = value_domain.get("sourceCapabilityId") if isinstance(value_domain, dict) else None
            if provider is not None and provider not in capability_ids:
                raise ContractError(f"dynamic valueDomain references unknown capability {provider}")

    for index, conflict in enumerate(_list(contract.get("conflicts", []), "canonical-contract.conflicts")):
        item = _object(conflict, f"canonical-contract.conflicts[{index}]")
        _string(item.get("conflictId"), f"canonical-contract.conflicts[{index}].conflictId")
        if item.get("status") not in {"resolved", "unresolved"}:
            raise ContractError("canonical contract conflict status must be resolved or unresolved")
        for capability_id in _string_list(
            item.get("affectedCapabilityIds", []),
            f"canonical-contract.conflicts[{index}].affectedCapabilityIds",
        ):
            if capability_id not in capability_ids:
                raise ContractError(f"conflict references unknown capability {capability_id}")
        for ref in _string_list(item.get("evidenceRefs"), f"canonical-contract.conflicts[{index}].evidenceRefs"):
            if ref not in evidence_ids:
                raise ContractError(f"conflict references unknown evidence {ref}")

    graph = _object(contract.get("capabilityGraph"), "canonical-contract.capabilityGraph")
    for index, node in enumerate(_list(graph.get("nodes"), "canonical-contract.capabilityGraph.nodes")):
        node_value = _object(node, f"canonical-contract.capabilityGraph.nodes[{index}]")
        if node_value.get("capabilityId") not in capability_ids:
            raise ContractError("capabilityGraph node references an unknown capability")
    for index, edge in enumerate(_list(graph.get("edges"), "canonical-contract.capabilityGraph.edges")):
        edge_value = _object(edge, f"canonical-contract.capabilityGraph.edges[{index}]")
        if edge_value.get("fromCapabilityId") not in capability_ids or edge_value.get("toCapabilityId") not in capability_ids:
            raise ContractError("capabilityGraph edge references an unknown capability")
        if edge_value.get("composition") not in {"observed", "derived"}:
            raise ContractError("capabilityGraph edge composition must be observed or derived")

    for index, goal in enumerate(_list(contract.get("goals"), "canonical-contract.goals")):
        item = _object(goal, f"canonical-contract.goals[{index}]")
        location = f"canonical-contract.goals[{index}]"
        _string(item.get("goalId"), f"canonical-contract.goals[{index}].goalId")
        _object(item.get("completionPredicate"), f"canonical-contract.goals[{index}].completionPredicate")
        _list(item.get("informationNeeds"), f"canonical-contract.goals[{index}].informationNeeds")
        required_ids = _string_list(
            item.get("requiredCapabilityIds", []),
            f"canonical-contract.goals[{index}].requiredCapabilityIds",
        )
        optional_ids = _string_list(
            item.get("optionalCapabilityIds", []),
            f"canonical-contract.goals[{index}].optionalCapabilityIds",
        )
        for field, goal_capability_ids in (
            ("requiredCapabilityIds", required_ids),
            ("optionalCapabilityIds", optional_ids),
        ):
            if len(set(goal_capability_ids)) != len(goal_capability_ids):
                raise ContractError(f"{location}.{field} must not contain duplicates")
            for capability_id in goal_capability_ids:
                if capability_id not in capability_ids:
                    raise ContractError(
                        f"{location}.{field} references unknown capability {capability_id}"
                    )
        required_optional_overlap = set(required_ids) & set(optional_ids)
        if required_optional_overlap:
            raise ContractError(
                f"{location} cannot declare capabilities as both required and optional: "
                f"{', '.join(sorted(required_optional_overlap))}"
            )

        inferred_conditional_ids = _goal_conditional_capability_ids(item, graph)
        if "conditionalCapabilityIds" not in item:
            if inferred_conditional_ids:
                raise ContractError(
                    f"{location}.conditionalCapabilityIds must be declared for conditionally activated capabilities: "
                    f"{', '.join(sorted(inferred_conditional_ids))}"
                )
            conditional_ids: list[str] = []
        else:
            conditional_values = _list(
                item.get("conditionalCapabilityIds"),
                f"{location}.conditionalCapabilityIds",
            )
            conditional_ids = [
                _conditional_capability_id(value, f"{location}.conditionalCapabilityIds[{conditional_index}]")
                for conditional_index, value in enumerate(conditional_values)
            ]
        if len(set(conditional_ids)) != len(conditional_ids):
            raise ContractError(f"{location}.conditionalCapabilityIds must not contain duplicates")
        for conditional_index, capability_id in enumerate(conditional_ids):
            conditional_location = f"{location}.conditionalCapabilityIds[{conditional_index}]"
            if capability_id not in capability_ids:
                raise ContractError(
                    f"{conditional_location} references unknown capability {capability_id}"
                )
            if capability_id not in optional_ids:
                raise ContractError(
                    f"{conditional_location} capability {capability_id} must also be optional"
                )
            if capability_id in required_ids:
                raise ContractError(
                    f"{conditional_location} capability {capability_id} cannot also be required"
                )
            conditional_value = conditional_values[conditional_index]
            if isinstance(conditional_value, dict):
                condition_information_ids = _condition_information_ids(
                    conditional_value["condition"]
                )
                information_ids = {
                    need.get("informationId")
                    for need in item.get("informationNeeds", [])
                    if isinstance(need, dict) and isinstance(need.get("informationId"), str)
                }
                if not condition_information_ids or not condition_information_ids <= information_ids:
                    raise ContractError(
                        f"{conditional_location}.condition for {capability_id} "
                        "references an unknown information need"
                    )
            if capability_id not in inferred_conditional_ids:
                raise ContractError(
                    f"{conditional_location} capability {capability_id} must be linked to a "
                    "machine-readable requiredWhen information need or conditional capability-graph edge"
                )
        undeclared_conditional_ids = inferred_conditional_ids - set(conditional_ids)
        if undeclared_conditional_ids:
            raise ContractError(
                f"{location}.conditionalCapabilityIds must declare conditionally activated capabilities: "
                f"{', '.join(sorted(undeclared_conditional_ids))}"
            )

    workflows_by_entry: dict[str, list[dict[str, Any]]] = {}
    workflow_ids: set[str] = set()
    for index, workflow in enumerate(_list(contract.get("workflows"), "canonical-contract.workflows")):
        item = _object(workflow, f"canonical-contract.workflows[{index}]")
        workflow_id = _string(item.get("workflowId"), f"canonical-contract.workflows[{index}].workflowId")
        if workflow_id in workflow_ids:
            raise ContractError(f"duplicate workflowId: {workflow_id}")
        workflow_ids.add(workflow_id)
        entry = _string(item.get("entryCapabilityId"), f"canonical-contract.workflows[{index}].entryCapabilityId")
        if entry not in capability_ids:
            raise ContractError(f"workflow {workflow_id} references unknown entry capability {entry}")
        member_location = f"canonical-contract.workflows[{index}].capabilityIds"
        member_ids = _string_list(item.get("capabilityIds"), member_location)
        if not member_ids:
            raise ContractError(f"{member_location} must contain at least the entry capability")
        if len(member_ids) != len(set(member_ids)):
            raise ContractError(f"{member_location} must not contain duplicate capability IDs")
        if entry not in member_ids:
            raise ContractError(
                f"workflow {workflow_id} capabilityIds must include its entry capability {entry}"
            )
        unknown_members = set(member_ids) - capability_ids
        if unknown_members:
            raise ContractError(
                f"workflow {workflow_id} capabilityIds reference unknown capabilities: "
                + ", ".join(sorted(unknown_members))
            )
        _string(item.get("guardAsset"), f"canonical-contract.workflows[{index}].guardAsset")
        enforcement = _object(item.get("enforcement"), f"canonical-contract.workflows[{index}].enforcement")
        if enforcement.get("mustCompleteBeforeDispatch") is not True or enforcement.get("rejectWithoutDispatch") is not True:
            raise ContractError(f"workflow {workflow_id} must reject every bypass before dispatch")
        workflows_by_entry.setdefault(entry, []).append(item)

    for capability in contract["capabilities"]:
        capability_id = capability["capabilityId"]
        workflows = workflows_by_entry.get(capability_id, [])
        protection = capability.get("runtimeProtection")
        mode = protection.get("mode") if isinstance(protection, dict) else None
        if mode == "deterministic-workflow":
            if len(workflows) != 1:
                raise ContractError(
                    f"deterministic-workflow capability {capability_id} must map to exactly one workflow"
                )
            expected_workflow_id = protection.get("workflowId")
            if workflows[0].get("workflowId") != expected_workflow_id:
                raise ContractError(
                    f"deterministic-workflow capability {capability_id} must name its canonical workflow"
                )
        elif workflows:
            raise ContractError(
                f"capability {capability_id} may declare a workflow only when runtimeProtection.mode "
                "is deterministic-workflow"
            )


def derive_bundle(contract: dict[str, Any]) -> dict[str, Any]:
    """Project the vNext canonical contract into the strict-export-v1 view."""

    capability_keys = (
        "capabilityId",
        "toolName",
        "functionExport",
        "description",
        "authentication",
        "exposure",
        "inputs",
        "outputs",
        "constraints",
        "attachments",
        "errorContract",
        "implementation",
        "successRule",
        "sideEffect",
        "operationPolicy",
        "annotations",
        "runtimeProtection",
        "readiness",
        "evidenceCoverage",
        "missingEvidence",
        "hostRequirements",
        "verificationChecks",
        "evidenceRefs",
    )
    handoff_keys = (
        "fromCapabilityId",
        "toCapabilityId",
        "mappings",
        "required",
        "evidenceRefs",
    )
    capabilities: list[dict[str, Any]] = []
    for capability in contract["capabilities"]:
        projection = {key: deepcopy(capability[key]) for key in capability_keys if key in capability}
        capabilities.append(projection)
    handoffs = [
        {key: deepcopy(item[key]) for key in handoff_keys if key in item}
        for item in contract.get("handoffs", [])
    ]
    return {
        "schemaVersion": "v1",
        "recordingId": contract["recordingId"],
        "featureBoundary": deepcopy(contract["featureBoundary"]),
        "server": deepcopy(contract["server"]),
        "capabilities": capabilities,
        "handoffs": handoffs,
    }


def derive_goal_contract(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": VNEXT_SCHEMA,
        "contractId": contract["contractId"],
        "canonicalContractRef": "canonical-contract.json",
        "goals": deepcopy(contract.get("goals", [])),
    }


def _output_schema_from_contract(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    root: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    }
    for output in sorted(outputs, key=lambda item: len(item.get("path", []))):
        path = output.get("path")
        if not isinstance(path, list) or not path:
            continue
        current = root
        for index, segment in enumerate(path):
            last = index == len(path) - 1
            if segment == "*":
                current["type"] = "array"
                current.pop("additionalProperties", None)
                current.pop("properties", None)
                current.pop("required", None)
                if last:
                    current.setdefault("items", {})
                else:
                    if not isinstance(current.get("items"), dict):
                        current["items"] = {}
                    current["items"].setdefault("type", "object")
                    current["items"].setdefault("additionalProperties", False)
                    current["items"].setdefault("properties", {})
                    current["items"].setdefault("required", [])
                    current = current["items"]
                continue
            if not isinstance(segment, str) or not segment:
                continue
            properties = current.setdefault("properties", {})
            required = current.setdefault("required", [])
            if segment not in required:
                required.append(segment)
            if last:
                leaf = properties.get(segment)
                if not isinstance(leaf, dict):
                    leaf = {}
                    properties[segment] = leaf
                declared_schema = output.get("schema")
                if isinstance(declared_schema, dict):
                    existing_children = {
                        key: deepcopy(leaf[key])
                        for key in ("items", "properties", "required", "additionalProperties")
                        if key in leaf
                    }
                    leaf.update(deepcopy(declared_schema))
                    for key, child in existing_children.items():
                        leaf.setdefault(key, child)
                elif isinstance(output.get("type"), str):
                    leaf["type"] = output["type"]
                if isinstance(output.get("description"), str):
                    leaf["description"] = output["description"]
            else:
                child = properties.get(segment)
                if not isinstance(child, dict):
                    child = {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                        "required": [],
                    }
                    properties[segment] = child
                current = child
    return root


def operation_summary_for_capability(capability: dict[str, Any]) -> dict[str, Any]:
    implementation = capability.get("implementation", {})
    if not isinstance(implementation, dict):
        implementation = {}
    steps = [
        step
        for step in implementation.get("steps", [])
        if isinstance(step, dict)
    ]
    return {
        "implementationKind": implementation.get("kind"),
        "stepCount": len(steps),
        "methods": [step.get("method") for step in steps],
        "origins": sorted({
            f"{parsed.scheme}://{parsed.netloc}"
            for step in steps
            if isinstance(step.get("url"), str)
            for parsed in [urlparse(step["url"])]
            if parsed.scheme and parsed.netloc
        }),
        "attachmentMode": capability.get("attachments", {}).get("mode", "none"),
    }


def derive_schema_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Derive the machine-comparable Function/MCP contract surface."""

    capabilities: list[dict[str, Any]] = []
    for capability in contract.get("capabilities", []):
        if not isinstance(capability, dict):
            continue
        properties: dict[str, Any] = {}
        required: list[str] = []
        for item in capability.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            declared_schema = item.get("schema")
            schema: dict[str, Any] = (
                deepcopy(declared_schema) if isinstance(declared_schema, dict) else {}
            )
            if isinstance(item.get("type"), str):
                schema.setdefault("type", item["type"])
            if isinstance(item.get("description"), str):
                schema["description"] = item["description"]
            domain = item.get("valueDomain")
            if isinstance(domain, dict) and domain.get("kind") == "static":
                schema["enum"] = deepcopy(domain.get("values", []))
            properties[item["name"]] = schema
            if item.get("required") is True:
                required.append(item["name"])
        input_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
        data_schema = _output_schema_from_contract([
            item for item in capability.get("outputs", []) if isinstance(item, dict)
        ])
        implementation = capability.get("implementation", {})
        if not isinstance(implementation, dict):
            implementation = {}
        steps = [
            step
            for step in implementation.get("steps", [])
            if isinstance(step, dict)
        ] if isinstance(implementation, dict) else []
        output_step_id = implementation.get("outputStepId") if isinstance(implementation, dict) else None
        output_step = next(
            (step for step in steps if step.get("stepId") == output_step_id),
            None,
        )
        status_schema: dict[str, Any] = {
            "type": "integer"
            if implementation.get("kind") == "http"
            else "string"
        }
        if isinstance(output_step, dict) and isinstance(output_step.get("successStatusCodes"), list):
            status_schema["enum"] = deepcopy(output_step["successStatusCodes"])
        operation_summary = operation_summary_for_capability(capability)
        output_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": status_schema,
                "data": data_schema,
            },
            "required": ["status", "data"],
        }
        capabilities.append({
            "capabilityId": capability.get("capabilityId"),
            "toolName": capability.get("toolName"),
            "functionExport": capability.get("functionExport"),
            "inputSchema": input_schema,
            "outputSchema": output_schema,
            "annotations": deepcopy(capability.get("annotations")),
            "conditionalRules": {
                item["name"]: {
                    "requiredWhen": deepcopy(item.get("requiredWhen", [])),
                    "forbiddenWhen": deepcopy(item.get("forbiddenWhen", [])),
                }
                for item in capability.get("inputs", [])
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and (item.get("requiredWhen") or item.get("forbiddenWhen"))
            },
            "constraints": deepcopy(capability.get("constraints", [])),
            "errorContract": deepcopy(capability.get("errorContract")),
            "operationPolicy": deepcopy(capability.get("operationPolicy")),
            "operationSummary": operation_summary,
        })
    return {
        "schemaVersion": VNEXT_SCHEMA,
        "contractId": contract.get("contractId"),
        "canonicalContractRef": "canonical-contract.json",
        "capabilities": capabilities,
        "workflows": [
            {
                "workflowId": workflow.get("workflowId"),
                "entryCapabilityId": workflow.get("entryCapabilityId"),
                "capabilityIds": deepcopy(workflow.get("capabilityIds", [])),
                "guardAsset": workflow.get("guardAsset"),
                "bindings": deepcopy(workflow.get("bindings", [])),
                "operationPolicy": deepcopy(
                    next(
                        (
                            capability.get("operationPolicy")
                            for capability in contract.get("capabilities", [])
                            if isinstance(capability, dict)
                            and capability.get("capabilityId")
                            == workflow.get("entryCapabilityId")
                        ),
                        None,
                    )
                ),
            }
            for workflow in contract.get("workflows", [])
            if isinstance(workflow, dict)
        ],
    }


def derive_documentation_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Derive the exact business facts that generated prose may reference.

    Narrative Skill/MCP/Feature Context text remains useful for guidance, but
    requiredness, types, domains, provenance, freshness, goals, composition,
    Consumer requirements, hard workflows, unresolved boundaries, side
    effects, runtime policy, attachment bindings, and evidence identity come
    from this view.
    """

    capability_fields = (
        "capabilityId",
        "toolName",
        "functionExport",
        "description",
        "authentication",
        "exposure",
        "inputs",
        "outputs",
        "constraints",
        "attachments",
        "implementation",
        "successRule",
        "errorContract",
        "sideEffect",
        "operationPolicy",
        "annotations",
        "runtimeProtection",
        "hostRequirements",
        "readiness",
        "missingEvidence",
        "evidenceRefs",
    )
    evidence_fields = (
        "evidenceId",
        "sourceId",
        "locator",
        "semanticRole",
        "assertionLevel",
    )
    return {
        "schemaVersion": VNEXT_SCHEMA,
        "contractId": contract.get("contractId"),
        "canonicalContractRef": "canonical-contract.json",
        "featureBoundary": deepcopy(contract.get("featureBoundary")),
        "goals": deepcopy(contract.get("goals", [])),
        "capabilityGraph": deepcopy(contract.get("capabilityGraph")),
        "handoffs": deepcopy(contract.get("handoffs", [])),
        "consumerRequirements": deepcopy(contract.get("consumerRequirements")),
        "workflows": deepcopy(contract.get("workflows", [])),
        "conflicts": deepcopy(contract.get("conflicts", [])),
        "capabilities": [
            {
                key: deepcopy(capability[key])
                for key in capability_fields
                if key in capability
            }
            for capability in contract.get("capabilities", [])
            if isinstance(capability, dict)
        ],
        "evidenceIndex": [
            {
                key: deepcopy(evidence[key])
                for key in evidence_fields
                if key in evidence
            }
            for evidence in contract.get("evidenceCatalog", [])
            if isinstance(evidence, dict)
        ],
    }


_MISSING = object()


def _value_schema(item: dict[str, Any]) -> dict[str, Any]:
    """Return the portable value Schema declared by an input, output, or need."""

    schema = item.get("schema")
    if isinstance(schema, dict):
        return schema
    value_type = item.get("type")
    return {"type": value_type} if isinstance(value_type, str) else {}


def _goal_state_entry(
    value: Any,
    reuse_while: dict[str, Any] | None = None,
) -> tuple[bool, bool, Any]:
    """Normalize one known-information entry for deterministic goal tests.

    Direct JSON values remain untouched, including business objects with fields
    named value, present, or fresh. Callers opt into state metadata with
    ``{"__goalState": true, "value": ..., "acquiredNow": true}`` for a
    newly acquired value, or provide a claim-by-claim ``reuseProof`` for a
    cached value. A bare ``fresh: true`` assertion cannot bypass Canonical
    reuse rules.
    """

    if isinstance(value, dict) and value.get("__goalState") is True:
        explicit_present = value.get("present")
        wrapped_value = value.get("value")
        meaningful_value = wrapped_value is not None and not (
            isinstance(wrapped_value, str) and not wrapped_value.strip()
        )
        present = (
            explicit_present is True and meaningful_value
            if isinstance(explicit_present, bool)
            else "value" in value and meaningful_value
        )
        reuse_claims = {
            key
            for key, enabled in (reuse_while or {}).items()
            if key != "evidenceRefs" and enabled is True
        }
        if value.get("fresh") is False:
            fresh = False
        elif value.get("acquiredNow") is True:
            fresh = True
        elif reuse_claims:
            proof = value.get("reuseProof")
            fresh = isinstance(proof, dict) and all(
                proof.get(claim) is True for claim in reuse_claims
            )
        else:
            fresh = value.get("fresh", True) is True
        return present, fresh, wrapped_value
    present = value is not None and not (
        isinstance(value, str) and not value.strip()
    )
    return present, True, value


def _goal_condition_value(
    condition: dict[str, Any],
    information: dict[str, Any],
) -> Any:
    path = condition.get("path")
    if not isinstance(path, list) or not path or not isinstance(path[0], str):
        return _MISSING
    if path[0] not in information:
        return _MISSING
    present, fresh, current = _goal_state_entry(information[path[0]])
    if not present or not fresh:
        return _MISSING
    for segment in path[1:]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and isinstance(segment, int) and 0 <= segment < len(current):
            current = current[segment]
        else:
            return _MISSING
    return current


def _goal_condition_matches(
    condition: dict[str, Any],
    information: dict[str, Any],
) -> Optional[bool]:
    operator = condition.get("operator")
    if operator in {"and", "or"}:
        children = condition.get("conditions", condition.get("operands"))
        if not isinstance(children, list) or not children:
            return None
        results = [
            _goal_condition_matches(child, information)
            for child in children
            if isinstance(child, dict)
        ]
        if len(results) != len(children):
            return None
        if operator == "and":
            return False if False in results else True if all(item is True for item in results) else None
        return True if True in results else False if all(item is False for item in results) else None
    if operator == "not":
        child = condition.get("condition")
        result = _goal_condition_matches(child, information) if isinstance(child, dict) else None
        return None if result is None else not result

    value = _goal_condition_value(condition, information)
    expected = condition.get("value")
    if operator == "present":
        return value is not _MISSING
    if operator == "absent":
        return value is _MISSING
    if value is _MISSING:
        return None
    if operator == "equals":
        return value == expected
    if operator == "not-equals":
        return value != expected
    if operator == "in":
        return isinstance(expected, list) and value in expected
    if operator == "not-in":
        return isinstance(expected, list) and value not in expected
    if operator == "non-empty":
        return value is not None and hasattr(value, "__len__") and len(value) > 0
    if operator == "empty":
        return value is None or (hasattr(value, "__len__") and len(value) == 0)
    comparisons = {
        "gt": lambda left, right: left > right,
        "gte": lambda left, right: left >= right,
        "lt": lambda left, right: left < right,
        "lte": lambda left, right: left <= right,
    }
    comparator = comparisons.get(str(operator))
    if comparator is None:
        return None
    try:
        return comparator(value, expected)
    except TypeError:
        return False


def evaluate_goal_state(
    goal: dict[str, Any],
    information: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate progressive goal completion without imposing a fixed transcript.

    `information` is keyed by Canonical `informationId`. A value may be passed
    directly or explicitly wrapped as
    `{__goalState: true, value, acquiredNow}` or with a Canonical
    `reuseProof`. Normal business objects may
    contain `value`, `present`, or `fresh` fields and remain direct values. This helper is intended
    for generated goal test vectors and Producer verification; a Consumer Host
    remains responsible for the actual conversation and Tool selection.
    """

    predicate = goal.get("completionPredicate", {})
    predicate_operator = predicate.get("operator") if isinstance(predicate, dict) else None
    predicate_ids = {
        item
        for item in predicate.get("informationIds", [])
        if isinstance(item, str)
    } if isinstance(predicate, dict) and predicate_operator == "any-satisfied" else set()
    active_ids: list[str] = []
    inactive_conditional_ids: list[str] = []
    pending_conditional_ids: list[str] = []
    missing_ids: list[str] = []
    satisfied_ids: list[str] = []
    capability_ids: list[str] = []
    ask_ids: list[str] = []
    trusted_context_ids: list[str] = []
    acquisition_options: list[dict[str, Any]] = []
    needs = [item for item in goal.get("informationNeeds", []) if isinstance(item, dict)]
    invalid_ids: list[str] = []
    normalized_information: dict[str, Any] = {}
    for need in needs:
        information_id = need.get("informationId")
        if not isinstance(information_id, str) or information_id not in information:
            continue
        present, fresh, current_value = _goal_state_entry(
            information[information_id],
            need.get("reuseWhile") if isinstance(need.get("reuseWhile"), dict) else None,
        )
        schema_errors = (
            json_schema_errors(current_value, _value_schema(need))
            if present
            else []
        )
        if schema_errors:
            invalid_ids.append(information_id)
            continue
        if present and fresh:
            normalized_information[information_id] = current_value
    condition_states: dict[str, Optional[bool]] = {}
    unresolved_condition_dependencies: set[str] = set()
    for need in needs:
        information_id = need.get("informationId")
        if not isinstance(information_id, str) or need.get("classification") != "requiredWhen":
            continue
        condition = need.get("condition")
        state = (
            _goal_condition_matches(condition, normalized_information)
            if isinstance(condition, dict)
            else None
        )
        condition_states[information_id] = state
        if state is None:
            unresolved_condition_dependencies.update(
                _condition_information_ids(condition)
            )
    for need in needs:
        information_id = need.get("informationId")
        if not isinstance(information_id, str):
            continue
        classification = need.get("classification")
        if predicate_operator == "any-satisfied" and information_id not in predicate_ids:
            continue
        if classification == "optional" and information_id not in unresolved_condition_dependencies:
            continue
        if classification == "requiredWhen":
            condition_state = condition_states.get(information_id)
            if condition_state is False:
                inactive_conditional_ids.append(information_id)
                continue
            if condition_state is not True:
                pending_conditional_ids.append(information_id)
                continue
        active_ids.append(information_id)
        if information_id in unresolved_condition_dependencies:
            present, fresh = False, False
        elif information_id in normalized_information:
            present, fresh = True, True
        else:
            present, fresh = False, False
        if present and fresh:
            satisfied_ids.append(information_id)
            continue
        if information_id not in missing_ids:
            missing_ids.append(information_id)
        sources = [source for source in need.get("satisfiedBy", []) if isinstance(source, dict)]
        providers = [
            source.get("capabilityId")
            for source in sources
            if source.get("kind") == "capability" and isinstance(source.get("capabilityId"), str)
        ]
        if providers:
            acquisition_options.append({
                "informationId": information_id,
                "capabilityIds": providers,
                "selection": "one-compatible-provider"
                if len(providers) > 1
                else "single-provider",
            })
        for capability_id in providers:
            if capability_id not in capability_ids:
                capability_ids.append(capability_id)
        has_trusted_context = any(
            source.get("kind") == "trusted-host-context" for source in sources
        )
        has_user_source = (
            classification not in {"derived", "dynamic"}
            and any(source.get("kind") == "user" for source in sources)
        )
        if has_trusted_context and information_id not in trusted_context_ids:
            trusted_context_ids.append(information_id)
        if has_user_source:
            if information_id not in ask_ids:
                ask_ids.append(information_id)

    operator = predicate.get("operator") if isinstance(predicate, dict) else None
    if operator == "any-satisfied":
        predicate_ids = predicate.get("informationIds", [])
        complete = (
            isinstance(predicate_ids, list)
            and any(
                isinstance(information_id, str)
                and information_id in satisfied_ids
                for information_id in predicate_ids
            )
        )
    elif operator == "workflow-completed":
        workflow_id = predicate.get("workflowId")
        workflow_key = f"workflow:{workflow_id}"
        if workflow_key in information:
            present, fresh, marker = _goal_state_entry(information[workflow_key])
            if isinstance(marker, dict):
                marker = marker.get("status")
            complete = present and fresh and marker in {True, "completed", "succeeded"}
        else:
            complete = False
    else:
        complete = not missing_ids and not pending_conditional_ids
    if complete and goal.get("agentPolicy", {}).get("stopWhenPredicateSatisfied", True) is True:
        missing_ids = []
        pending_conditional_ids = []
        capability_ids = []
        acquisition_options = []
        ask_ids = []
        trusted_context_ids = []
    return {
        "goalId": goal.get("goalId"),
        "activeInformationIds": active_ids,
        "inactiveConditionalInformationIds": inactive_conditional_ids,
        "pendingConditionalInformationIds": pending_conditional_ids,
        "satisfiedInformationIds": satisfied_ids,
        "invalidInformationIds": invalid_ids,
        "missingInformationIds": missing_ids,
        "acquisitionCapabilityIds": capability_ids,
        "acquisitionOptions": acquisition_options,
        "askInformationIds": ask_ids,
        "trustedContextInformationIds": trusted_context_ids,
        "complete": complete,
    }


def derive_consumer_requirements(contract: dict[str, Any]) -> dict[str, Any]:
    definitions = deepcopy(_object(contract.get("consumerRequirements"), "canonical-contract.consumerRequirements"))
    requirements = _list(definitions.get("requirements"), "canonical-contract.consumerRequirements.requirements")
    known = {item.get("requirementId") for item in requirements if isinstance(item, dict)}
    capability_requirements = []
    for capability in contract["capabilities"]:
        requirement_ids = list(capability.get("hostRequirements", []))
        unknown = [item for item in requirement_ids if item not in known]
        if unknown:
            raise ContractError(
                f"capability {capability['capabilityId']} references unknown host requirements: {', '.join(unknown)}"
            )
        capability_requirements.append({
            "capabilityId": capability["capabilityId"],
            "requirementIds": requirement_ids,
        })
    return {
        "schemaVersion": VNEXT_SCHEMA,
        "contractId": contract["contractId"],
        "canonicalContractRef": "canonical-contract.json",
        "requirements": deepcopy(requirements),
        "capabilityRequirements": capability_requirements,
    }


def derive_host_compatibility(
    contract: dict[str, Any],
    consumer_requirements: dict[str, Any],
    host_profile: dict[str, Any],
) -> dict[str, Any]:
    """Compare host abilities to requirements without recognizing host brands."""

    if host_profile.get("schemaVersion") != VNEXT_SCHEMA:
        raise ContractError("host-profile.schemaVersion must equal vNext")
    profile_id = _string(host_profile.get("profileId"), "host-profile.profileId")
    host_capabilities = _object(host_profile.get("capabilities"), "host-profile.capabilities")
    definitions = {
        item["requirementId"]: item
        for item in consumer_requirements["requirements"]
        if isinstance(item, dict) and isinstance(item.get("requirementId"), str)
    }
    requirement_sets = {
        item["capabilityId"]: item.get("requirementIds", [])
        for item in consumer_requirements["capabilityRequirements"]
    }
    assessments: list[dict[str, Any]] = []
    status_by_id: dict[str, str] = {}
    for capability in contract["capabilities"]:
        capability_id = capability["capabilityId"]
        missing: list[str] = []
        external: list[str] = []
        disable = False
        for requirement_id in requirement_sets.get(capability_id, []):
            requirement = definitions[requirement_id]
            host_capability = requirement["hostCapability"]
            support = host_capabilities.get(host_capability, {"status": "unsupported"})
            support_status = support.get("status") if isinstance(support, dict) else None
            if support_status not in HOST_SUPPORT:
                raise ContractError(f"host capability {host_capability} has an invalid status")
            if support_status == "unsupported":
                missing.append(requirement_id)
                disable = disable or requirement.get("onMissing") == "disable"
            elif support_status == "external-integration":
                external.append(requirement_id)
        if capability.get("readiness") == "blocked":
            status = "blocked"
        elif missing and disable:
            status = "disabled"
        elif missing or external:
            status = "requires-host-integration"
        else:
            status = "enabled"
        status_by_id[capability_id] = status
        assessments.append({
            "capabilityId": capability_id,
            "status": status,
            "canonicalReadiness": capability.get("readiness"),
            "missingRequirementIds": missing,
            "externalIntegrationRequirementIds": external,
        })

    goal_assessments = []

    def requirement_source_status(source: dict[str, Any]) -> str:
        kind = source.get("kind")
        if kind == "user":
            return "enabled"
        if kind == "capability":
            capability_id = source.get("capabilityId")
            return status_by_id.get(capability_id, "blocked")
        if kind == "trusted-host-context":
            requirement_id = source.get("requirementId")
            if not isinstance(requirement_id, str):
                return "requires-host-integration"
            definition = definitions.get(requirement_id)
            if not isinstance(definition, dict):
                return "blocked"
            support = host_capabilities.get(
                definition.get("hostCapability"),
                {"status": "unsupported"},
            )
            support_status = support.get("status") if isinstance(support, dict) else None
            if support_status == "supported":
                return "enabled"
            if support_status == "external-integration":
                return "requires-host-integration"
            return (
                "disabled"
                if definition.get("onMissing") == "disable"
                else "requires-host-integration"
            )
        return "blocked"

    def alternatives_status(sources: list[dict[str, Any]]) -> str:
        statuses = [requirement_source_status(source) for source in sources]
        if "enabled" in statuses:
            return "enabled"
        if "requires-host-integration" in statuses:
            return "requires-host-integration"
        if "blocked" in statuses:
            return "blocked"
        return "disabled"

    def aggregate_required_status(statuses: list[str]) -> str:
        if "blocked" in statuses:
            return "blocked"
        if "disabled" in statuses:
            return "disabled"
        if "requires-host-integration" in statuses:
            return "requires-host-integration"
        return "enabled"

    def choose_alternative_status(statuses: list[str]) -> str:
        if "enabled" in statuses:
            return "enabled"
        if "requires-host-integration" in statuses:
            return "requires-host-integration"
        if "blocked" in statuses:
            return "blocked"
        return "disabled"

    for goal_index, goal in enumerate(contract.get("goals", [])):
        goal_location = f"canonical-contract.goals[{goal_index}]"
        required_ids = _string_list(
            goal.get("requiredCapabilityIds", []),
            f"{goal_location}.requiredCapabilityIds",
        )
        conditional_values = _list(
            goal.get("conditionalCapabilityIds", []),
            f"{goal_location}.conditionalCapabilityIds",
        )
        conditional_ids = [
            _conditional_capability_id(
                item,
                f"{goal_location}.conditionalCapabilityIds[{conditional_index}]",
            )
            for conditional_index, item in enumerate(conditional_values)
        ]
        for field, capability_ids in (
            ("requiredCapabilityIds", required_ids),
            ("conditionalCapabilityIds", conditional_ids),
        ):
            for capability_id in capability_ids:
                if capability_id not in status_by_id:
                    raise ContractError(
                        f"{goal_location}.{field} references unknown capability {capability_id}"
                    )
        statuses = [status_by_id[item] for item in required_ids]
        needs = [
            need
            for need in goal.get("informationNeeds", [])
            if isinstance(need, dict)
        ]
        predicate = goal.get("completionPredicate", {})
        predicate_operator = predicate.get("operator") if isinstance(predicate, dict) else None
        predicate_ids = {
            item
            for item in predicate.get("informationIds", [])
            if isinstance(item, str)
        } if isinstance(predicate, dict) else set()
        need_statuses = {
            need.get("informationId"): alternatives_status([
                source
                for source in need.get("satisfiedBy", [])
                if isinstance(source, dict)
            ])
            for need in needs
            if isinstance(need.get("informationId"), str)
        }
        if predicate_operator == "any-satisfied":
            statuses.append(choose_alternative_status([
                need_statuses[information_id]
                for information_id in predicate_ids
                if information_id in need_statuses
            ]))
        else:
            statuses.extend(
                need_statuses[need["informationId"]]
                for need in needs
                if need.get("classification") not in {"optional", "requiredWhen"}
                and need.get("informationId") in need_statuses
            )
        if predicate_operator == "workflow-completed":
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
                statuses.extend(
                    status_by_id.get(capability_id, "blocked")
                    for capability_id in workflow_capability_ids(workflow)
                )
        status = aggregate_required_status(statuses)
        conditional_restrictions = [
            {"capabilityId": item, "status": status_by_id[item]}
            for item in conditional_ids
            if status_by_id.get(item) != "enabled"
        ]
        conditional_restrictions.extend(
            {
                "informationId": need.get("informationId"),
                "status": need_statuses.get(need.get("informationId"), "blocked"),
                "requirementIds": sorted({
                    source.get("requirementId")
                    for source in need.get("satisfiedBy", [])
                    if isinstance(source, dict)
                    and source.get("kind") == "trusted-host-context"
                    and isinstance(source.get("requirementId"), str)
                }),
                "capabilityIds": sorted({
                    source.get("capabilityId")
                    for source in need.get("satisfiedBy", [])
                    if isinstance(source, dict)
                    and source.get("kind") == "capability"
                    and isinstance(source.get("capabilityId"), str)
                }),
            }
            for need in needs
            if need.get("classification") == "requiredWhen"
            and need_statuses.get(need.get("informationId")) != "enabled"
        )
        goal_assessments.append({
            "goalId": goal["goalId"],
            "status": status,
            "conditionalRestrictions": conditional_restrictions,
        })

    statuses = set(status_by_id.values())
    overall = "compatible"
    if statuses & {"requires-host-integration", "disabled", "blocked"}:
        overall = "compatible-with-restrictions"
    if statuses and statuses <= {"disabled", "blocked"}:
        overall = "incompatible"
    return {
        "schemaVersion": VNEXT_SCHEMA,
        "contractId": contract["contractId"],
        "consumerRequirementsRef": "consumer-requirements.json",
        "hostProfileRef": "host-profile.json",
        "profileId": profile_id,
        "overallStatus": overall,
        "capabilityAssessments": assessments,
        "goalAssessments": goal_assessments,
    }


def write_evidence_complete(
    capability: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> bool:
    coverage = capability.get("evidenceCoverage")
    if not isinstance(coverage, dict):
        return False
    required_categories = (
        {"sideEffect"}
        if capability.get("sideEffect") == "read"
        else WRITE_EVIDENCE
    )
    for category in required_categories:
        item = coverage.get(category)
        if not isinstance(item, dict) or item.get("assertionLevel") != "fact" or not item.get("evidenceRefs"):
            return False
        if (
            category == "sideEffect"
            and item.get("declaredSideEffect") != capability.get("sideEffect")
        ):
            return False
    if contract is not None:
        boundary = contract.get("featureBoundary")
        catalog = contract.get("evidenceCatalog")
        if not isinstance(boundary, dict) or not isinstance(catalog, list):
            return False
        if boundary.get("primaryEvidenceRole") == "client-feature":
            authoritative_sources = set(boundary.get("supplementarySourceIds", []))
        else:
            authoritative_sources = set(boundary.get("serviceSourceIds", [])) | set(
                boundary.get("supplementarySourceIds", [])
            )
        if not authoritative_sources:
            return False
        evidence_by_id = {
            item.get("evidenceId"): item
            for item in catalog
            if isinstance(item, dict) and isinstance(item.get("evidenceId"), str)
        }
        operation_refs = {
            ref
            for value in (
                capability.get("evidenceRefs", []),
                capability.get("exposure", {}).get("evidenceRefs", []),
                capability.get("exposure", {}).get("supplementalEvidenceRefs", []),
            )
            if isinstance(value, list)
            for ref in value
            if isinstance(ref, str)
        }
        for category in required_categories:
            refs = coverage[category].get("evidenceRefs", [])
            if not isinstance(refs, list) or not refs:
                return False
            for ref in refs:
                evidence = evidence_by_id.get(ref)
                if (
                    not isinstance(evidence, dict)
                    or ref not in operation_refs
                    or evidence.get("assertionLevel") != "fact"
                    or evidence.get("sourceId") not in authoritative_sources
                    or evidence.get("semanticRole") not in WRITE_EVIDENCE_ROLES[category]
                ):
                    return False
    return True


def required_capability_verification_checks(
    capability: dict[str, Any],
    contract: dict[str, Any],
) -> list[dict[str, str]]:
    """Mechanically derive the minimum candidate-specific behavior vectors."""

    capability_id = capability.get("capabilityId")
    behavior_ids = {
        "valid-input-and-output-contract",
        "invalid-input-is-rejected",
        "structured-error-recovery",
    }
    runtime_ids: set[str] = set()
    implementation = capability.get("implementation", {})
    if isinstance(implementation, dict) and implementation.get("kind") == "http":
        behavior_ids.add("exact-request-binding-and-success-status")
    has_dynamic = any(
        isinstance(item, dict)
        and (
            item.get("informationClass") == "dynamic"
            or isinstance(item.get("valueDomain"), dict)
            and item["valueDomain"].get("kind") == "dynamic"
        )
        for item in [
            *capability.get("inputs", []),
            *capability.get("outputs", []),
        ]
    )
    if has_dynamic:
        behavior_ids.add("dynamic-values-are-not-frozen")
    if any(
        isinstance(item, dict)
        and (item.get("requiredWhen") or item.get("forbiddenWhen"))
        for item in capability.get("inputs", [])
    ):
        behavior_ids.add("conditional-rules-cover-active-and-inactive-branches")
    attachments = capability.get("attachments", {})
    if isinstance(attachments, dict) and attachments.get("mode") == "host-approved-reference":
        behavior_ids.add("attachment-resolution-failure-zero-dispatch")
        behavior_ids.add("attachment-request-field-and-metadata-contract")
        runtime_ids.add("attachment-resolution-runtime-vector")
    if capability.get("sideEffect") != "read":
        behavior_ids.add("unknown-write-outcome-is-non-retryable")
    protection = capability.get("runtimeProtection")
    if isinstance(protection, dict) and protection.get("mode") == "backend-authoritative":
        behavior_ids.add("backend-business-error-is-structured")
    for goal in contract.get("goals", []):
        if not isinstance(goal, dict) or not isinstance(goal.get("goalId"), str):
            continue
        goal_id = goal["goalId"]
        if capability_id in goal.get("requiredCapabilityIds", []):
            behavior_ids.update({
                f"goal-{goal_id}-different-information-orders-converge",
                f"goal-{goal_id}-all-known-skips-questions-and-tools",
                f"goal-{goal_id}-asks-only-currently-missing",
            })
        conditional_ids = {
            item if isinstance(item, str) else item.get("capabilityId")
            for item in goal.get("conditionalCapabilityIds", [])
            if isinstance(item, (str, dict))
        }
        if capability_id in conditional_ids:
            behavior_ids.add(f"goal-{goal_id}-conditional-branches")
    if any(
        isinstance(edge, dict)
        and edge.get("composition") == "derived"
        and capability_id in {edge.get("fromCapabilityId"), edge.get("toCapabilityId")}
        for edge in contract.get("capabilityGraph", {}).get("edges", [])
    ):
        behavior_ids.add("derived-composition-preserves-contract-and-write-guards")
    return [
        *(
            {"checkId": check_id, "phase": "behavior"}
            for check_id in sorted(behavior_ids)
        ),
        *(
            {"checkId": check_id, "phase": "runtime"}
            for check_id in sorted(runtime_ids)
        ),
    ]


def capability_verification_checks(
    capability: dict[str, Any],
    contract: dict[str, Any],
) -> list[Any]:
    required = required_capability_verification_checks(capability, contract)
    declared = deepcopy(capability.get("verificationChecks", []))
    seen = {
        (item["phase"], item["checkId"])
        for item in required
    }
    result: list[Any] = list(required)
    for item in declared if isinstance(declared, list) else []:
        phase = item.get("phase") if isinstance(item, dict) else "behavior"
        check_id = item.get("checkId") if isinstance(item, dict) else item
        identity = (phase, check_id)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def derive_verification_matrix(
    contract: dict[str, Any],
    compatibility: dict[str, Any],
) -> dict[str, Any]:
    compatibility_by_id = {
        item["capabilityId"]: item["status"]
        for item in compatibility.get("capabilityAssessments", [])
    }
    unresolved_conflicts: dict[str, list[str]] = {}
    for conflict in contract.get("conflicts", []):
        if not isinstance(conflict, dict) or conflict.get("status") != "unresolved":
            continue
        for capability_id in conflict.get("affectedCapabilityIds", []):
            unresolved_conflicts.setdefault(capability_id, []).append(str(conflict.get("conflictId")))
    capabilities = []
    for capability in contract["capabilities"]:
        capability_id = capability["capabilityId"]
        reasons: list[str] = []
        blocked = capability.get("readiness") == "blocked"
        if capability.get("missingEvidence"):
            reasons.append("missing-evidence")
        if capability.get("readiness") == "requires-review":
            reasons.append("canonical-readiness-requires-review")
        if not write_evidence_complete(capability, contract):
            reasons.append(
                "incomplete-side-effect-evidence"
                if capability.get("sideEffect") == "read"
                else "incomplete-write-evidence"
            )
        if compatibility_by_id.get(capability_id) != "enabled":
            reasons.append("host-not-fully-compatible")
        for conflict_id in unresolved_conflicts.get(capability_id, []):
            reasons.append(f"unresolved-conflict:{conflict_id}")
        reasons.append("behavior-verification-pending")
        reasons.append("runtime-verification-pending")
        capabilities.append({
            "capabilityId": capability_id,
            "status": {
                "generated": True,
                "behaviorVerified": False,
                "runtimeVerified": False,
                "hostVerified": False,
                "requiresReview": not blocked,
                "blocked": blocked,
            },
            "reasons": reasons,
            "checks": capability_verification_checks(capability, contract),
        })

    workflows = []
    for workflow in contract.get("workflows", []):
        workflows.append({
            "workflowId": workflow["workflowId"],
            "status": {
                "generated": True,
                "behaviorVerified": False,
                "runtimeVerified": False,
                "hostVerified": False,
                "bypassVerified": False,
                "requiresReview": True,
                "blocked": False,
            },
            "checks": deepcopy(workflow.get("verificationChecks", [])),
        })
    return {
        "schemaVersion": VNEXT_SCHEMA,
        "contractId": contract["contractId"],
        "canonicalContractRef": "canonical-contract.json",
        "delivery": {
            "functionCore": {"status": "pending"},
            "mcpServer": {"status": "pending"},
            "skill": {"status": "pending"},
            "runtime": {"status": "not-run"},
            "deployment": {"status": "not-deployed"},
        },
        "capabilities": capabilities,
        "workflows": workflows,
    }
