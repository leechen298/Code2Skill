#!/usr/bin/env python3
"""Language- and host-neutral helpers for Code2Skill vNext contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


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
WRITE_EVIDENCE = {
    "backendContract",
    "authorization",
    "validation",
    "idempotency",
    "unknownOutcome",
}


class ContractError(ValueError):
    """Raised when a vNext portable contract is internally inconsistent."""


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


def _conditional_capability_id(value: Any, location: str) -> str:
    if isinstance(value, str):
        return _string(value, location)
    item = _object(value, location)
    capability_id = _string(item.get("capabilityId"), f"{location}.capabilityId")
    condition = _object(item.get("condition"), f"{location}.condition")
    path = _list(condition.get("path"), f"{location}.condition.path")
    if not path:
        raise ContractError(f"{location}.condition.path must not be empty")
    for index, segment in enumerate(path):
        _string(segment, f"{location}.condition.path[{index}]")
    _string(condition.get("operator"), f"{location}.condition.operator")
    return capability_id


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
            and isinstance(condition.get("path"), list)
            and condition.get("path")
            and isinstance(condition.get("operator"), str)
            and condition.get("operator")
        ):
            conditional_ids.add(capability_id)
    for need in goal.get("informationNeeds", []):
        if not isinstance(need, dict) or need.get("classification") != "requiredWhen":
            continue
        condition = need.get("condition")
        if (
            not isinstance(condition, dict)
            or not isinstance(condition.get("path"), list)
            or not condition.get("path")
            or not isinstance(condition.get("operator"), str)
            or not condition.get("operator")
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
    if portable.get("languageBinding") != "none" or portable.get("hostBinding") != "none":
        raise ContractError("canonical-contract.portableCore must not bind a source language or consumer host")

    evidence_ids: set[str] = set()
    for index, evidence in enumerate(_list(contract.get("evidenceCatalog"), "canonical-contract.evidenceCatalog")):
        item = _object(evidence, f"canonical-contract.evidenceCatalog[{index}]")
        evidence_id = _string(item.get("evidenceId"), f"canonical-contract.evidenceCatalog[{index}].evidenceId")
        if evidence_id in evidence_ids:
            raise ContractError(f"duplicate evidenceId: {evidence_id}")
        evidence_ids.add(evidence_id)
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
        for ref in _string_list(item.get("evidenceRefs"), f"capability {capability_id}.evidenceRefs"):
            if ref not in evidence_ids:
                raise ContractError(f"capability {capability_id} references unknown evidence {ref}")
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
                condition_path = conditional_value["condition"]["path"]
                information_ids = {
                    need.get("informationId")
                    for need in item.get("informationNeeds", [])
                    if isinstance(need, dict) and isinstance(need.get("informationId"), str)
                }
                if condition_path[0] not in information_ids:
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
        _string(item.get("guardAsset"), f"canonical-contract.workflows[{index}].guardAsset")
        enforcement = _object(item.get("enforcement"), f"canonical-contract.workflows[{index}].enforcement")
        if enforcement.get("mustCompleteBeforeDispatch") is not True or enforcement.get("rejectWithoutDispatch") is not True:
            raise ContractError(f"workflow {workflow_id} must reject every bypass before dispatch")
        workflows_by_entry.setdefault(entry, []).append(item)

    for capability in contract["capabilities"]:
        if capability.get("sideEffect") == "read" or capability.get("readiness") != "ready":
            continue
        capability_id = capability["capabilityId"]
        workflows = workflows_by_entry.get(capability_id, [])
        if len(workflows) != 1:
            raise ContractError(f"ready write capability {capability_id} must map to exactly one deterministic workflow")
        if capability.get("workflowId") != workflows[0].get("workflowId"):
            raise ContractError(f"ready write capability {capability_id} must name its deterministic workflow")


def derive_bundle(contract: dict[str, Any]) -> dict[str, Any]:
    """Project the vNext canonical contract into the strict-export-v1 view."""

    capability_keys = (
        "capabilityId",
        "toolName",
        "functionExport",
        "description",
        "authentication",
        "inputs",
        "implementation",
        "successRule",
        "sideEffect",
        "evidenceRefs",
    )
    input_keys = ("name", "description", "type", "required", "evidenceRefs")
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
        projection["inputs"] = [
            {key: deepcopy(item[key]) for key in input_keys if key in item}
            for item in capability.get("inputs", [])
        ]
        capabilities.append(projection)
    handoffs = [
        {key: deepcopy(item[key]) for key in handoff_keys if key in item}
        for item in contract.get("handoffs", [])
    ]
    return {
        "schemaVersion": "v1",
        "recordingId": contract["recordingId"],
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
        elif missing or external or capability.get("readiness") == "requires-review":
            status = "requires-host-integration"
        else:
            status = "enabled"
        status_by_id[capability_id] = status
        assessments.append({
            "capabilityId": capability_id,
            "status": status,
            "missingRequirementIds": missing,
            "externalIntegrationRequirementIds": external,
        })

    goal_assessments = []
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
        if "blocked" in statuses:
            status = "blocked"
        elif "disabled" in statuses:
            status = "disabled"
        elif "requires-host-integration" in statuses:
            status = "requires-host-integration"
        else:
            status = "enabled"
        conditional_restrictions = [
            {"capabilityId": item, "status": status_by_id[item]}
            for item in conditional_ids
            if status_by_id.get(item) != "enabled"
        ]
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


def write_evidence_complete(capability: dict[str, Any]) -> bool:
    if capability.get("sideEffect") == "read":
        return True
    coverage = capability.get("evidenceCoverage")
    if not isinstance(coverage, dict):
        return False
    for category in WRITE_EVIDENCE:
        item = coverage.get(category)
        if not isinstance(item, dict) or item.get("assertionLevel") != "fact" or not item.get("evidenceRefs"):
            return False
    return True


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
        if not write_evidence_complete(capability):
            reasons.append("incomplete-write-evidence")
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
            "checks": deepcopy(capability.get("verificationChecks", [])),
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
        "capabilities": capabilities,
        "workflows": workflows,
    }
