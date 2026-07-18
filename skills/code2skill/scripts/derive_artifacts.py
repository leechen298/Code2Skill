#!/usr/bin/env python3
"""Derive strict-export artifacts that must mechanically mirror a bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def derive_draft(bundle: dict[str, Any]) -> dict[str, Any]:
    capabilities = [item for item in bundle.get("capabilities", []) if isinstance(item, dict)]
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
        for item in capability.get("inputs", []):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            name = item["name"]
            qualified = f"tools.{tool}.input.{name}"
            refs = evidence(item.get("evidenceRefs"), capability_refs)
            inputs.append({
                "name": qualified,
                "valueType": item.get("type"),
                "required": item.get("required"),
                "evidenceRefs": refs,
            })

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
                if not isinstance(source_value, dict) or source_value.get("kind") != "input":
                    continue
                mappings.append({
                    "inputName": source_value.get("inputName"),
                    "target": binding.get("location"),
                    "targetPath": ".".join(str(segment) for segment in binding.get("path", [])),
                    "evidenceRefs": evidence(binding.get("evidenceRefs"), step_refs),
                })
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

    return {
        "schemaVersion": "v1",
        "recordingId": bundle.get("recordingId"),
        "status": "ready",
        "inputs": inputs,
        "provenance": provenance,
        "requestChain": request_chain,
        "missingEvidence": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    args = parser.parse_args()
    root = args.artifact_root.resolve()
    bundle = read_json(root / "capability-bundle.json")
    write_json(root / "function-core" / "capability-bundle.json", bundle)
    write_json(root / "capability-draft.json", derive_draft(bundle))
    print("Derived function-core/capability-bundle.json and capability-draft.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
