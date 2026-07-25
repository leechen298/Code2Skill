#!/usr/bin/env python3
"""Deterministically derive legacy and vNext Code2Skill artifact views."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from contract_model import (
    ContractError,
    derive_bundle,
    derive_consumer_requirements,
    derive_documentation_contract,
    derive_goal_contract,
    derive_host_compatibility,
    derive_schema_contract,
    derive_verification_matrix,
    validate_canonical_contract,
    validate_source_topology,
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evidence(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return value
    return fallback


def derive_draft(
    bundle: dict[str, Any],
    canonical_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capabilities = [item for item in bundle.get("capabilities", []) if isinstance(item, dict)]
    canonical_by_id = {
        item.get("capabilityId"): item
        for item in (canonical_contract or {}).get("capabilities", [])
        if isinstance(item, dict)
    }
    by_id = {item.get("capabilityId"): item for item in capabilities}
    handoffs = [item for item in bundle.get("handoffs", []) if isinstance(item, dict)]
    inputs: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    request_chain: list[dict[str, Any]] = []
    order = 0

    for capability in capabilities:
        tool = capability.get("toolName")
        if not isinstance(tool, str) or not tool:
            continue
        capability_refs = evidence(capability.get("evidenceRefs"), ["source-contract-ledger"])
        capability_id = capability.get("capabilityId")
        canonical_capability = canonical_by_id.get(capability_id, {})
        canonical_inputs = {
            item.get("name"): item
            for item in canonical_capability.get("inputs", [])
            if isinstance(item, dict)
        }
        for item in capability.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            name = item["name"]
            qualified = f"tools.{tool}.input.{name}"
            refs = evidence(item.get("evidenceRefs"), capability_refs)
            derived_input = {
                "name": qualified,
                "valueType": item.get("type"),
                "required": item.get("required"),
                "evidenceRefs": refs,
            }
            canonical_input = canonical_inputs.get(name, {})
            for field in (
                "informationClass",
                "sourceStrategies",
                "valueDomain",
                "requiredWhen",
                "forbiddenWhen",
                "freshness",
            ):
                if field in canonical_input:
                    derived_input[field] = canonical_input[field]
            inputs.append(derived_input)

            matched_handoff = None
            matched_mapping = None
            for handoff in handoffs:
                if handoff.get("toCapabilityId") != capability_id:
                    continue
                for mapping in handoff.get("mappings", []):
                    if isinstance(mapping, dict) and mapping.get("targetInput") == name:
                        matched_handoff = handoff
                        matched_mapping = mapping
                        break
                if matched_handoff is not None:
                    break

            if matched_handoff is not None and matched_mapping is not None:
                source_capability = by_id.get(matched_handoff.get("fromCapabilityId"), {})
                source_tool = source_capability.get("toolName")
                source_path = matched_mapping.get("sourcePath", [])
                pointer = "/" + "/".join(str(segment) for segment in source_path)
                source = "prior_response"
                detail = f"prior_response:{source_tool}:{pointer}"
                refs = evidence(matched_handoff.get("evidenceRefs"), refs)
            elif canonical_contract is not None:
                strategies = canonical_input.get("sourceStrategies", [])
                strategy_kinds = [
                    value if isinstance(value, str) else value.get("kind")
                    for value in strategies
                    if isinstance(value, (str, dict))
                ]
                if "user" in strategy_kinds:
                    source = "provided"
                    detail = "direct Tool argument supplied by the user or trusted caller"
                elif any(value in {"trusted-host-context", "host-approved-attachment", "bounded-content"} for value in strategy_kinds):
                    source = "context"
                    detail = "trusted Consumer Host context"
                elif "derived-calculation" in strategy_kinds:
                    source = "context"
                    detail = "protected runtime derivation"
                else:
                    source = "provided"
                    detail = "direct Tool argument"
            elif "runtime_context" in str(capability.get("authentication", "")):
                source = "context"
                detail = "trusted MCP runtime context"
            else:
                source = "provided"
                detail = "direct Tool argument"
            provenance.append({
                "field": qualified,
                "source": source,
                "sourceDetail": detail,
                "evidenceRefs": refs,
            })

        implementation = capability.get("implementation", {})
        if not isinstance(implementation, dict) or implementation.get("kind") != "http":
            continue
        for step in implementation.get("steps", []):
            if not isinstance(step, dict):
                continue
            step_refs = evidence(step.get("evidenceRefs"), capability_refs)
            mappings = []
            for binding in step.get("bindings", []):
                if not isinstance(binding, dict):
                    continue
                source_value = binding.get("source")
                if not isinstance(source_value, dict) or source_value.get("kind") not in {
                    "input",
                    "host_resolved_attachment",
                }:
                    continue
                mapping = {
                    "inputName": source_value.get("inputName"),
                    "target": binding.get("location"),
                    "targetPath": ".".join(str(segment) for segment in binding.get("path", [])),
                    "evidenceRefs": evidence(binding.get("evidenceRefs"), step_refs),
                }
                if source_value.get("kind") == "host_resolved_attachment":
                    mapping["sourceKind"] = "host-resolved-attachment"
                    mapping["requirementId"] = source_value.get("requirementId")
                mappings.append(mapping)
            request_chain.append({
                "stepId": f"{tool}.{step.get('stepId')}",
                "order": order,
                "method": step.get("method"),
                "urlTemplate": step.get("url"),
                "authentication": step.get("authentication"),
                "inputMappings": mappings,
                "evidenceRefs": step_refs,
            })
            order += 1

    missing_evidence: list[str] = []
    readiness = "ready"
    if canonical_contract is not None:
        for capability in canonical_contract.get("capabilities", []):
            if not isinstance(capability, dict):
                continue
            missing_evidence.extend(
                item for item in capability.get("missingEvidence", [])
                if isinstance(item, str) and item not in missing_evidence
            )
            if capability.get("readiness") == "blocked":
                readiness = "blocked"
            elif capability.get("readiness") == "requires-review" and readiness != "blocked":
                readiness = "requires-review"
        if missing_evidence and readiness == "ready":
            readiness = "requires-review"

    return {
        "schemaVersion": "v1",
        "recordingId": bundle.get("recordingId"),
        "status": readiness,
        "inputs": inputs,
        "provenance": provenance,
        "requestChain": request_chain,
        "missingEvidence": missing_evidence,
    }


def derive_vnext(root: Path) -> list[str]:
    topology = read_json(root / "source-topology.json")
    contract = read_json(root / "canonical-contract.json")
    host_profile = read_json(root / "host-profile.json")
    source_ids = validate_source_topology(topology)
    validate_canonical_contract(contract, source_ids)

    bundle = derive_bundle(contract)
    goal_contract = derive_goal_contract(contract)
    consumer_requirements = derive_consumer_requirements(contract)
    compatibility = derive_host_compatibility(contract, consumer_requirements, host_profile)
    verification_matrix = derive_verification_matrix(contract, compatibility)
    schema_contract = derive_schema_contract(contract)
    documentation_contract = derive_documentation_contract(contract)

    write_json(root / "capability-bundle.json", bundle)
    write_json(root / "function-core" / "capability-bundle.json", bundle)
    write_json(root / "capability-draft.json", derive_draft(bundle, contract))
    write_json(root / "goal-contract.json", goal_contract)
    write_json(root / "consumer-requirements.json", consumer_requirements)
    write_json(root / "host-compatibility-report.json", compatibility)
    write_json(root / "verification-matrix.json", verification_matrix)
    write_json(root / "function-core" / "schema-contract.json", schema_contract)
    write_json(root / "mcp-tool" / "schema-contract.json", schema_contract)
    write_json(root / "references" / "capability-contracts.json", documentation_contract)
    return [
        "capability-bundle.json",
        "function-core/capability-bundle.json",
        "capability-draft.json",
        "goal-contract.json",
        "consumer-requirements.json",
        "host-compatibility-report.json",
        "verification-matrix.json",
        "function-core/schema-contract.json",
        "mcp-tool/schema-contract.json",
        "references/capability-contracts.json",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args()
    root = args.artifact_root.resolve()
    if (root / "canonical-contract.json").is_file():
        try:
            generated = derive_vnext(root)
        except ContractError as error:
            parser.error(str(error))
        print("Derived vNext artifacts: " + ", ".join(generated) + ".")
        documentation_contract = root / "references" / "capability-contracts.json"
        documentation_digest = hashlib.sha256(documentation_contract.read_bytes()).hexdigest()
        print(
            "Documentation review marker: "
            f"<!-- code2skill-capability-contract-sha256:{documentation_digest} -->"
        )
        return 0

    bundle = read_json(root / "capability-bundle.json")
    write_json(root / "function-core" / "capability-bundle.json", bundle)
    write_json(root / "capability-draft.json", derive_draft(bundle))
    print("Derived function-core/capability-bundle.json and capability-draft.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
