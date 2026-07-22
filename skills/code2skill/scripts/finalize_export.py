#!/usr/bin/env python3
"""Finalize a candidate with capability-scoped and workflow-scoped evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from contract_model import (
    capability_verification_checks,
    derive_schema_contract,
    json_schema_errors,
    workflow_capability_ids,
)


HEX64 = re.compile(r"^[a-f0-9]{64}$")
FINALIZATION_FILES = {
    "preflight-report.json",
    "approval-audit.json",
    "live-verification.json",
    "verification-matrix.json",
    "export-manifest.json",
}
FINALIZATION_MUTATIONS = FINALIZATION_FILES | {
    "function-core/validation-receipt.json",
}
PHASE_STATUSES = {"passed", "failed", "not-run", "requires-review", "blocked"}
CAPABILITY_PHASES = ("behavior", "runtime", "host")
WORKFLOW_PHASES = ("bypass", "runtime", "host")
TRANSIENT_REASONS = {
    "behavior-verification-pending",
    "runtime-verification-pending",
    "host-verification-pending",
    "canonical-verification-checks-pending",
    "workflow-bypass-verification-pending",
}
ATTACHMENT_RUNTIME_ASSERTIONS = {
    "resolverCalls": 1,
    "businessDispatches": 1,
    "resolutionFailureDispatches": 0,
    "rawGrantForwarded": False,
    "resolvedContentBound": True,
    "sizeVerified": True,
    "digestVerified": True,
}


class FinalizationError(ValueError):
    """Raised when supplied verification evidence is incomplete or inconsistent."""


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _snapshot_finalization_files(root: Path) -> dict[str, bytes | None]:
    return {
        relative: (root / relative).read_bytes() if (root / relative).is_file() else None
        for relative in FINALIZATION_MUTATIONS
    }


def _restore_finalization_files(root: Path, snapshot: dict[str, bytes | None]) -> None:
    for relative, content in snapshot.items():
        path = root / relative
        if content is None:
            if path.is_file():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument(
        "--verification-report",
        type=Path,
        required=True,
        help="JSON report with executed global checks and per-capability behavior evidence",
    )
    parser.add_argument(
        "--live-input",
        type=Path,
        action="append",
        required=True,
        help="sanitized live MCP input; repeat for capability-scoped evidence",
    )
    parser.add_argument(
        "--live-result",
        type=Path,
        action="append",
        required=True,
        help="sanitized live MCP result; repeat for capability-scoped evidence",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path.cwd(),
        help="legacy/base source root used when explicit vNext source mappings are omitted",
    )
    parser.add_argument(
        "--source-map",
        action="append",
        default=[],
        metavar="SOURCE_ID=PATH",
        help="repeat for every explicitly authorized vNext source root",
    )
    return parser.parse_args()


def _nonempty(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinalizationError(f"{location} must be a non-empty string")
    return value


def _require_exact_fields(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    location: str,
) -> None:
    missing = required - set(value)
    unexpected = set(value) - required - optional
    if missing:
        raise FinalizationError(
            f"{location} is missing required fields: {', '.join(sorted(missing))}"
        )
    if unexpected:
        raise FinalizationError(
            f"{location} contains unsupported fields: {', '.join(sorted(unexpected))}"
        )


def _phase_status(value: Any, location: str) -> str:
    if not isinstance(value, str) or value not in PHASE_STATUSES:
        raise FinalizationError(f"{location} must be one of {sorted(PHASE_STATUSES)}")
    return value


def _strict_attachment_proof(
    value: Any,
    evidence_hash: str,
    location: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalizationError(f"{location} must be an object")
    expected_keys = {
        *ATTACHMENT_RUNTIME_ASSERTIONS,
        "stepId",
        "location",
        "path",
        "traceEvidenceHash",
    }
    if set(value) != expected_keys:
        raise FinalizationError(
            f"{location} must contain exactly the reviewed attachment trace fields"
        )
    if any(
        (
            type(value.get(key)) is not type(expected)
            or value.get(key) != expected
        )
        for key, expected in ATTACHMENT_RUNTIME_ASSERTIONS.items()
    ):
        raise FinalizationError(
            f"{location} contains an invalid attachment resolver/dispatch assertion"
        )
    _nonempty(value.get("stepId"), f"{location}.stepId")
    _nonempty(value.get("location"), f"{location}.location")
    path = value.get("path")
    if (
        not isinstance(path, list)
        or not path
        or any(not isinstance(item, str) or not item for item in path)
    ):
        raise FinalizationError(
            f"{location}.path must be a non-empty array of request field names"
        )
    trace_hash = value.get("traceEvidenceHash")
    if not isinstance(trace_hash, str) or not HEX64.fullmatch(trace_hash):
        raise FinalizationError(f"{location}.traceEvidenceHash must be a SHA-256 digest")
    try:
        computed_hash = digest_json({
            key: child
            for key, child in value.items()
            if key != "traceEvidenceHash"
        })
    except (TypeError, ValueError) as error:
        raise FinalizationError(f"{location} must contain only JSON trace values") from error
    if trace_hash != computed_hash or evidence_hash != computed_hash:
        raise FinalizationError(
            f"{location}.traceEvidenceHash and the check evidenceHash must equal the canonical trace digest"
        )
    return dict(value)


def _strict_check(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalizationError(f"{location} must be an object")
    _require_exact_fields(
        value,
        {"name", "command", "exitCode", "status", "evidenceHash"},
        {
            "checkId",
            "phase",
            "layer",
            "toolName",
            "inputHash",
            "resultHash",
            "zeroExternalWrites",
            "attachmentProof",
        },
        location,
    )
    command = _nonempty(value.get("command"), f"{location}.command")
    status = value.get("status")
    if status not in {"passed", "failed"}:
        raise FinalizationError(f"{location}.status must be passed or failed")
    exit_code = value.get("exitCode")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code < 0:
        raise FinalizationError(f"{location}.exitCode must be a non-negative integer")
    if status == "passed" and exit_code != 0:
        raise FinalizationError(f"{location} cannot pass with a non-zero exitCode")
    evidence_hash = value.get("evidenceHash")
    if not isinstance(evidence_hash, str) or not HEX64.fullmatch(evidence_hash):
        raise FinalizationError(f"{location}.evidenceHash must be a SHA-256 digest")
    result = {
        "name": _nonempty(value.get("name"), f"{location}.name"),
        "command": command,
        "exitCode": exit_code,
        "status": status,
        "evidenceHash": evidence_hash,
    }
    for key in ("checkId", "phase", "layer", "zeroExternalWrites"):
        if key in value:
            result[key] = value[key]
    if "zeroExternalWrites" in value and not isinstance(
        value.get("zeroExternalWrites"), bool
    ):
        raise FinalizationError(f"{location}.zeroExternalWrites must be boolean")
    if "phase" in value and value.get("phase") not in {
        "behavior",
        "runtime",
        "host",
        "bypass",
    }:
        raise FinalizationError(f"{location}.phase is invalid")
    if "layer" in value:
        _nonempty(value.get("layer"), f"{location}.layer")
    if "checkId" in value:
        _nonempty(value.get("checkId"), f"{location}.checkId")
    if "toolName" in value:
        result["toolName"] = _nonempty(value.get("toolName"), f"{location}.toolName")
    for key in ("inputHash", "resultHash"):
        if key in value:
            digest = value.get(key)
            if not isinstance(digest, str) or not HEX64.fullmatch(digest):
                raise FinalizationError(f"{location}.{key} must be a SHA-256 digest")
            result[key] = digest
    if "attachmentProof" in value:
        result["attachmentProof"] = _strict_attachment_proof(
            value.get("attachmentProof"),
            evidence_hash,
            f"{location}.attachmentProof",
        )
    return result


def _legacy_checks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise FinalizationError("verification report must contain at least one executed check")
    checks = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, dict)
            or item.get("status") != "passed"
            or not isinstance(item.get("command"), str)
            or not item["command"].strip()
        ):
            raise FinalizationError(
                f"verification report legacy checks[{index}] must record a passed executed command"
            )
        checks.append(dict(item))
    return checks


def _strict_checks(value: Any, location: str, *, passed: bool | None = None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise FinalizationError(f"{location} must be an array")
    checks = [_strict_check(item, f"{location}[{index}]") for index, item in enumerate(value)]
    if passed is True and (not checks or any(item["status"] != "passed" for item in checks)):
        raise FinalizationError(f"{location} must contain only passed executed checks")
    return checks


def _phase(record: dict[str, Any], name: str, location: str) -> tuple[str, list[dict[str, Any]]]:
    value = record.get(name)
    if isinstance(value, dict):
        _require_exact_fields(
            value,
            {"status", "checks"},
            set(),
            f"{location}.{name}",
        )
        status = _phase_status(value.get("status"), f"{location}.{name}.status")
        checks = _strict_checks(
            value.get("checks", []),
            f"{location}.{name}.checks",
            passed=True if status == "passed" else None,
        )
        return status, _checks_for_phase(checks, name, f"{location}.{name}.checks")

    return "not-run", []


def _checks_for_phase(
    checks: list[dict[str, Any]],
    phase: str,
    location: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        declared_phase = check.get("phase")
        if declared_phase is not None and declared_phase != phase:
            raise FinalizationError(
                f"{location}[{index}].phase declares {declared_phase!r}, expected {phase!r}"
            )
        normalized = dict(check)
        normalized["phase"] = phase
        result.append(normalized)
    return result


def _required_phase(
    record: dict[str, Any],
    phase: str,
    location: str,
) -> tuple[str, list[dict[str, Any]]]:
    if phase not in record:
        raise FinalizationError(
            f"{location} must explicitly record phase-specific {phase} status/checks"
        )
    return _phase(record, phase, location)


def _check_identity(check: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(check.get("checkId", check.get("name", ""))),
        str(check.get("command", "")),
        str(check.get("evidenceHash", "")),
    )


def _reject_cross_phase_check_reuse(
    phases: dict[str, tuple[str, list[dict[str, Any]]]],
    location: str,
) -> None:
    owner_by_check: dict[tuple[str, str, str], str] = {}
    for phase, (_, checks) in phases.items():
        for check in checks:
            identity = _check_identity(check)
            previous = owner_by_check.get(identity)
            if previous is not None and previous != phase:
                raise FinalizationError(
                    f"{location} reuses the same executed check across {previous} and {phase}; "
                    "each verification phase needs phase-specific evidence"
                )
            owner_by_check[identity] = phase


def _canonical_workflow_ids(contract: dict[str, Any]) -> list[str]:
    workflows = contract.get("workflows", [])
    if not isinstance(workflows, list):
        raise FinalizationError("canonical-contract.workflows must be an array")
    result = []
    for index, workflow in enumerate(workflows):
        if not isinstance(workflow, dict):
            raise FinalizationError(f"canonical-contract.workflows[{index}] must be an object")
        workflow_id = _nonempty(
            workflow.get("workflowId"), f"canonical-contract.workflows[{index}].workflowId"
        )
        if workflow_id in result:
            raise FinalizationError(f"duplicate canonical workflowId: {workflow_id}")
        result.append(workflow_id)
    return result


def _canonical_capabilities(contract: dict[str, Any]) -> list[dict[str, Any]]:
    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise FinalizationError("canonical-contract.capabilities must be a non-empty array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            raise FinalizationError(f"canonical-contract.capabilities[{index}] must be an object")
        capability_id = _nonempty(
            capability.get("capabilityId"), f"canonical-contract.capabilities[{index}].capabilityId"
        )
        if capability_id in seen:
            raise FinalizationError(f"duplicate canonical capabilityId: {capability_id}")
        seen.add(capability_id)
        result.append(capability)
    return result


def _expected_checks_by_phase(
    value: dict[str, Any],
    location: str,
    allowed_phases: tuple[str, ...],
    default_phase: str,
) -> dict[str, set[str]]:
    checks = value.get("verificationChecks", [])
    if not isinstance(checks, list):
        raise FinalizationError(f"{location}.verificationChecks must be an array")
    result = {phase: set() for phase in allowed_phases}
    for index, item in enumerate(checks):
        item_location = f"{location}.verificationChecks[{index}]"
        if isinstance(item, str):
            check_id = _nonempty(item, item_location)
            phase = default_phase
        elif isinstance(item, dict):
            check_id = _nonempty(item.get("checkId"), f"{item_location}.checkId")
            phase = _nonempty(item.get("phase"), f"{item_location}.phase")
            if phase not in allowed_phases:
                raise FinalizationError(
                    f"{item_location}.phase must be one of {list(allowed_phases)}"
                )
        else:
            raise FinalizationError(f"{item_location} must be a check ID or phased check object")
        if check_id in result[phase]:
            raise FinalizationError(f"{item_location} duplicates {phase} check {check_id}")
        result[phase].add(check_id)
    return result


def _actual_check_ids(checks: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("checkId", item.get("name")))
        for item in checks
        if item.get("checkId") or item.get("name")
    }


def _require_runtime_check_bindings(
    phase: tuple[str, list[dict[str, Any]]],
    tool_name: str,
    location: str,
) -> None:
    status, checks = phase
    if status != "passed":
        return
    for index, check in enumerate(checks):
        check_location = f"{location}[{index}]"
        if check.get("toolName") != tool_name:
            raise FinalizationError(
                f"{check_location}.toolName must equal canonical Tool {tool_name}"
            )
        for key in ("inputHash", "resultHash"):
            value = check.get(key)
            if not isinstance(value, str) or not HEX64.fullmatch(value):
                raise FinalizationError(
                    f"{check_location}.{key} must bind the live pair with a SHA-256 digest"
                )


def _require_attachment_runtime_proof(
    phase: tuple[str, list[dict[str, Any]]],
    capability: dict[str, Any],
    location: str,
) -> None:
    status, checks = phase
    if status != "passed":
        return
    attachments = capability.get("attachments")
    content_bindings = (
        attachments.get("contentBindings", [])
        if isinstance(attachments, dict)
        else []
    )
    if not isinstance(content_bindings, list) or not content_bindings:
        raise FinalizationError(
            f"{location} cannot prove attachment dispatch without Canonical contentBindings"
        )

    expected_keys = {
        *ATTACHMENT_RUNTIME_ASSERTIONS,
        "stepId",
        "location",
        "path",
        "traceEvidenceHash",
    }
    valid_proofs: list[dict[str, Any]] = []
    for check in checks:
        check_id = check.get("checkId", check.get("name"))
        proof = check.get("attachmentProof")
        if check_id != "attachment-resolution-runtime-vector" or not isinstance(proof, dict):
            continue
        evidence_hash = check.get("evidenceHash")
        trace_payload = {
            key: value
            for key, value in proof.items()
            if key != "traceEvidenceHash"
        }
        computed_trace_hash = digest_json(trace_payload)
        if (
            set(proof) != expected_keys
            or any(proof.get(key) != value for key, value in ATTACHMENT_RUNTIME_ASSERTIONS.items())
            or proof.get("traceEvidenceHash") != computed_trace_hash
            or evidence_hash != computed_trace_hash
        ):
            continue
        valid_proofs.append(proof)

    for index, binding in enumerate(content_bindings):
        binding_location = f"canonical capability attachment contentBindings[{index}]"
        if not isinstance(binding, dict):
            raise FinalizationError(f"{binding_location} must be an object")
        step_id = _nonempty(binding.get("stepId"), f"{binding_location}.stepId")
        request_location = _nonempty(
            binding.get("location"), f"{binding_location}.location"
        )
        path = binding.get("path")
        if (
            not isinstance(path, list)
            or not path
            or any(not isinstance(item, str) or not item for item in path)
        ):
            raise FinalizationError(
                f"{binding_location}.path must be a non-empty portable request path"
            )
        if not any(
            proof.get("stepId") == step_id
            and proof.get("location") == request_location
            and proof.get("path") == path
            for proof in valid_proofs
        ):
            raise FinalizationError(
                f"{location} must include an executed attachmentProof bound to Canonical "
                f"stepId={step_id!r}, location={request_location!r}, path={path!r}, and "
                "the check evidenceHash; it must show one resolver call, one business "
                "dispatch, zero dispatch on resolution failure, no raw-grant forwarding, "
                "resolved-content binding, and size/digest verification"
            )


def _runtime_check_matches_live(
    checks: list[dict[str, Any]],
    tool_name: str,
    live_record: dict[str, Any],
) -> bool:
    return any(
        check.get("status") == "passed"
        and check.get("toolName") == tool_name
        and check.get("inputHash") == live_record.get("inputHash")
        and check.get("resultHash") == live_record.get("resultHash")
        for check in checks
    )


def _read_report(
    report: Any,
    canonical: dict[str, Any] | None,
    bundle_capabilities: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(report, dict):
        raise FinalizationError("verification report must be an object")

    # Compatibility is intentionally narrow: the old aggregate report can only
    # prove one read-only capability, never a multi-Tool or write package.
    if canonical is None and "capabilities" not in report:
        if (
            len(bundle_capabilities) != 1
            or bundle_capabilities[0].get("sideEffect") != "read"
            or report.get("status") != "passed"
        ):
            raise FinalizationError(
                "aggregate verification reports are supported only for one legacy read-only capability"
            )
        checks = _legacy_checks(report.get("checks"))
        capability_id = _nonempty(
            bundle_capabilities[0].get("capabilityId"), "bundle.capabilities[0].capabilityId"
        )
        return True, checks, {
            capability_id: {
                "behavior": ("passed", checks),
                "runtime": ("not-run", []),
                "host": ("not-run", []),
            }
        }, {}

    if canonical is None:
        raise FinalizationError("capability-scoped vNext verification requires canonical-contract.json")
    if report.get("schemaVersion") != "vNext":
        raise FinalizationError("vNext verification report schemaVersion must equal vNext")
    _require_exact_fields(
        report,
        {
            "schemaVersion",
            "contractId",
            "status",
            "checks",
            "capabilities",
            "workflows",
        },
        set(),
        "verification-report",
    )
    if report.get("contractId") != canonical.get("contractId"):
        raise FinalizationError("verification report contractId must match canonical-contract.json")
    if report.get("status") not in {"passed", "partial"}:
        raise FinalizationError("vNext verification report status must be passed or partial")
    global_checks = _strict_checks(report.get("checks", []), "verification-report.checks", passed=True)

    canonical_capabilities = _canonical_capabilities(canonical)
    canonical_capability_by_id = {item["capabilityId"]: item for item in canonical_capabilities}
    expected_capability_ids = [item["capabilityId"] for item in canonical_capabilities]
    records = report.get("capabilities")
    if not isinstance(records, list):
        raise FinalizationError("verification-report.capabilities must be an array")
    capability_records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        location = f"verification-report.capabilities[{index}]"
        if not isinstance(record, dict):
            raise FinalizationError(f"{location} must be an object")
        _require_exact_fields(
            record,
            {"capabilityId", *CAPABILITY_PHASES},
            set(),
            location,
        )
        capability_id = _nonempty(record.get("capabilityId"), f"{location}.capabilityId")
        if capability_id in capability_records:
            raise FinalizationError(f"duplicate capability verification: {capability_id}")
        normalized = {
            phase: _required_phase(record, phase, location)
            for phase in CAPABILITY_PHASES
        }
        _reject_cross_phase_check_reuse(normalized, location)
        if capability_id in canonical_capability_by_id:
            canonical_tool_name = _nonempty(
                canonical_capability_by_id[capability_id].get("toolName"),
                f"canonical capability {capability_id}.toolName",
            )
            _require_runtime_check_bindings(
                normalized["runtime"],
                canonical_tool_name,
                f"{location}.runtime.checks",
            )
            attachments = canonical_capability_by_id[capability_id].get("attachments", {})
            attachment_proof_checks = [
                (phase, check)
                for phase in CAPABILITY_PHASES
                for check in normalized[phase][1]
                if "attachmentProof" in check
            ]
            if (
                isinstance(attachments, dict)
                and attachments.get("mode") == "host-approved-reference"
            ):
                if any(
                    phase != "runtime"
                    or check.get("checkId", check.get("name"))
                    != "attachment-resolution-runtime-vector"
                    for phase, check in attachment_proof_checks
                ):
                    raise FinalizationError(
                        f"{location} may attach attachmentProof only to the runtime attachment-resolution-runtime-vector check"
                    )
                _require_attachment_runtime_proof(
                    normalized["runtime"],
                    canonical_capability_by_id[capability_id],
                    f"{location}.runtime.checks",
                )
            elif attachment_proof_checks:
                raise FinalizationError(
                    f"{location} must not include attachmentProof for a capability without a Canonical Host-approved attachment boundary"
                )
            capability_with_required_checks = dict(
                canonical_capability_by_id[capability_id]
            )
            capability_with_required_checks["verificationChecks"] = (
                capability_verification_checks(
                    canonical_capability_by_id[capability_id],
                    canonical,
                )
            )
            expected_checks = _expected_checks_by_phase(
                capability_with_required_checks,
                f"canonical capability {capability_id}",
                CAPABILITY_PHASES,
                "behavior",
            )
            missing_checks: list[str] = []
            for phase in CAPABILITY_PHASES:
                missing = expected_checks[phase] - _actual_check_ids(normalized[phase][1])
                if normalized[phase][0] == "passed" and missing:
                    raise FinalizationError(
                        f"{location}.{phase} is missing canonical {phase} checks: {sorted(missing)}"
                    )
                missing_checks.extend(f"{phase}:{check_id}" for check_id in sorted(missing))
            normalized["missingChecks"] = missing_checks
        capability_records[capability_id] = normalized
    if set(capability_records) != set(expected_capability_ids):
        raise FinalizationError(
            "verification report must cover every canonical capability exactly once"
        )

    expected_workflow_ids = _canonical_workflow_ids(canonical)
    workflow_values = report.get("workflows", [])
    if not isinstance(workflow_values, list):
        raise FinalizationError("verification-report.workflows must be an array")
    workflow_records: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(workflow_values):
        location = f"verification-report.workflows[{index}]"
        if not isinstance(record, dict):
            raise FinalizationError(f"{location} must be an object")
        _require_exact_fields(
            record,
            {"workflowId", *WORKFLOW_PHASES},
            set(),
            location,
        )
        workflow_id = _nonempty(record.get("workflowId"), f"{location}.workflowId")
        if workflow_id in workflow_records:
            raise FinalizationError(f"duplicate workflow verification: {workflow_id}")
        normalized = {
            phase: _required_phase(record, phase, location)
            for phase in WORKFLOW_PHASES
        }
        _reject_cross_phase_check_reuse(normalized, location)
        bypass_status, bypass_checks = normalized["bypass"]
        if bypass_status == "passed" and any(
            check.get("zeroExternalWrites") is not True for check in bypass_checks
        ):
            raise FinalizationError(
                f"{location}.bypass checks must prove zeroExternalWrites=true"
            )
        canonical_workflow = next(
            (
                item
                for item in canonical.get("workflows", [])
                if isinstance(item, dict) and item.get("workflowId") == workflow_id
            ),
            None,
        )
        if canonical_workflow is not None:
            entry_capability_id = _nonempty(
                canonical_workflow.get("entryCapabilityId"),
                f"canonical workflow {workflow_id}.entryCapabilityId",
            )
            entry_capability = canonical_capability_by_id.get(entry_capability_id)
            if entry_capability is None:
                raise FinalizationError(
                    f"canonical workflow {workflow_id} references unknown entry capability {entry_capability_id}"
                )
            entry_tool_name = _nonempty(
                entry_capability.get("toolName"),
                f"canonical capability {entry_capability_id}.toolName",
            )
            _require_runtime_check_bindings(
                normalized["runtime"],
                entry_tool_name,
                f"{location}.runtime.checks",
            )
            expected_checks = _expected_checks_by_phase(
                canonical_workflow,
                f"canonical workflow {workflow_id}",
                WORKFLOW_PHASES,
                "bypass",
            )
            for phase in WORKFLOW_PHASES:
                missing_checks = expected_checks[phase] - _actual_check_ids(normalized[phase][1])
                if normalized[phase][0] == "passed" and missing_checks:
                    raise FinalizationError(
                        f"{location}.{phase} is missing canonical {phase} checks: "
                        f"{sorted(missing_checks)}"
                    )
        workflow_records[workflow_id] = normalized
    if set(workflow_records) != set(expected_workflow_ids):
        raise FinalizationError(
            "verification report must cover every canonical workflow exactly once"
        )
    return False, global_checks, capability_records, workflow_records


def _unwrap_live_entries(value: Any, kind: str) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("capabilities"), list):
        values = value["capabilities"]
    elif isinstance(value, list):
        values = value
    else:
        values = [value]
    result = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise FinalizationError(f"live {kind}[{index}] must be an object")
        result.append(item)
    return result


def _live_payload(item: dict[str, Any], kind: str) -> Any:
    preferred = "input" if kind == "input" else "result"
    if preferred in item:
        return item[preferred]
    return {key: value for key, value in item.items() if key != "capabilityId"}


def _live_tool_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("name"), str):
        return value["name"]
    params = value.get("params")
    if isinstance(params, dict) and isinstance(params.get("name"), str):
        if value.get("method") != "tools/call":
            raise FinalizationError(
                "JSON-RPC live input evidence must use method=tools/call"
            )
        return params["name"]
    return None


def _live_tool_arguments(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("name"), str):
        arguments = value.get("arguments")
    else:
        params = value.get("params")
        if isinstance(params, dict) and value.get("method") != "tools/call":
            raise FinalizationError(
                "JSON-RPC live input evidence must use method=tools/call"
            )
        arguments = params.get("arguments") if isinstance(params, dict) else None
    return arguments if isinstance(arguments, dict) else None


def _path_exists(value: Any, path: list[Any]) -> bool:
    if not path:
        return value is not None
    segment, *remaining = path
    if segment == "*":
        children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
        return any(_path_exists(child, remaining) for child in children)
    if isinstance(value, dict) and segment in value:
        return _path_exists(value[segment], remaining)
    if isinstance(value, list) and isinstance(segment, int) and 0 <= segment < len(value):
        return _path_exists(value[segment], remaining)
    return False


def _contains_forbidden_key(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key in forbidden or _contains_forbidden_key(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item, forbidden) for item in value)
    return False


def _has_matching_text_projection(result: dict[str, Any], structured: dict[str, Any]) -> bool:
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return False
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
            continue
        try:
            projected = json.loads(block["text"])
        except json.JSONDecodeError:
            continue
        if projected == structured:
            return True
    return False


def _validate_live_result(
    capability_id: str,
    capability: dict[str, Any],
    result: Any,
) -> None:
    if not isinstance(result, dict) or result.get("isError") is not False:
        raise FinalizationError(
            f"live result for {capability_id} must have isError=false"
        )
    structured = result.get("structuredContent")
    if not isinstance(structured, dict) or not isinstance(structured.get("data"), (dict, list)):
        raise FinalizationError(
            f"live result for {capability_id} must contain structuredContent.data"
        )
    if not _has_matching_text_projection(result, structured):
        raise FinalizationError(
            f"live result for {capability_id} must contain a text content JSON projection matching structuredContent"
        )
    data = structured["data"]
    success_rule = capability.get("successRule")
    if not isinstance(success_rule, dict):
        raise FinalizationError(f"canonical capability {capability_id} needs a successRule")
    required_paths = success_rule.get("requiredOutputPaths", [])
    if not isinstance(required_paths, list):
        raise FinalizationError(
            f"canonical capability {capability_id} requiredOutputPaths must be an array"
        )
    for index, path in enumerate(required_paths):
        if not isinstance(path, list) or not path or not _path_exists(data, path):
            raise FinalizationError(
                f"live result for {capability_id} is missing required output path {index}: {path}"
            )
    forbidden = success_rule.get("forbiddenOutputKeys", [])
    if not isinstance(forbidden, list) or any(not isinstance(item, str) for item in forbidden):
        raise FinalizationError(
            f"canonical capability {capability_id} forbiddenOutputKeys must be strings"
        )
    if _contains_forbidden_key(data, set(forbidden)):
        raise FinalizationError(
            f"live result for {capability_id} contains a forbidden output key"
        )
    schema_projection = derive_schema_contract({
        "contractId": "live-result-validation",
        "capabilities": [capability],
        "workflows": [],
    })
    output_schema = schema_projection["capabilities"][0]["outputSchema"]
    schema_errors = json_schema_errors(structured, output_schema)
    if schema_errors:
        raise FinalizationError(
            f"live result for {capability_id} violates the Canonical outputSchema: "
            + "; ".join(schema_errors)
        )


def _read_live_evidence(
    input_paths: list[Path],
    result_paths: list[Path],
    capabilities: list[dict[str, Any]],
    *,
    legacy: bool,
) -> dict[str, dict[str, Any]]:
    capability_by_id = {
        item.get("capabilityId"): item
        for item in capabilities
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    capability_ids = list(capability_by_id)
    if len(input_paths) != len(result_paths):
        raise FinalizationError("--live-input and --live-result must be supplied in matching pairs")
    inputs: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for input_path, result_path in zip(input_paths, result_paths):
        inputs.extend(_unwrap_live_entries(read_json(input_path), "input"))
        results.extend(_unwrap_live_entries(read_json(result_path), "result"))

    if legacy:
        if len(inputs) != 1 or len(results) != 1:
            raise FinalizationError("legacy read-only finalization accepts one live input/result pair")
        result_payload = _live_payload(results[0], "result")
        if not isinstance(result_payload, dict) or result_payload.get("isError") is not False:
            raise FinalizationError(
                "live result must be a real successful MCP result with isError=false"
            )
        capability_id = capability_ids[0]
        return {
            capability_id: {
                "status": "passed",
                "isError": False,
                "inputHash": digest_json(_live_payload(inputs[0], "input")),
                "resultHash": digest_json(result_payload),
            }
        }

    input_by_id: dict[str, Any] = {}
    result_by_id: dict[str, Any] = {}
    for kind, values, target in (
        ("input", inputs, input_by_id),
        ("result", results, result_by_id),
    ):
        for index, item in enumerate(values):
            capability_id = _nonempty(item.get("capabilityId"), f"live {kind}[{index}].capabilityId")
            if capability_id not in capability_ids:
                raise FinalizationError(f"live {kind} names unknown capability: {capability_id}")
            if capability_id in target:
                raise FinalizationError(f"duplicate live {kind} evidence for capability: {capability_id}")
            target[capability_id] = _live_payload(item, kind)
    if set(input_by_id) != set(result_by_id):
        raise FinalizationError("live input/result evidence must map the same capabilityIds")

    input_schema_projection = derive_schema_contract({
        "contractId": "live-input-validation",
        "capabilities": capabilities,
        "workflows": [],
    })
    input_schema_by_capability_id = {
        item.get("capabilityId"): item.get("inputSchema")
        for item in input_schema_projection.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }

    evidence: dict[str, dict[str, Any]] = {}
    for capability_id in sorted(input_by_id):
        capability = capability_by_id[capability_id]
        expected_tool_name = _nonempty(
            capability.get("toolName"), f"canonical capability {capability_id}.toolName"
        )
        actual_tool_name = _live_tool_name(input_by_id[capability_id])
        if actual_tool_name != expected_tool_name:
            raise FinalizationError(
                f"live input for {capability_id} must call canonical Tool {expected_tool_name}"
            )
        live_arguments = _live_tool_arguments(input_by_id[capability_id])
        if live_arguments is None:
            raise FinalizationError(
                f"live input for {capability_id} must contain object arguments"
            )
        input_schema = input_schema_by_capability_id.get(capability_id)
        schema_errors = json_schema_errors(live_arguments, input_schema)
        if schema_errors:
            raise FinalizationError(
                f"live input for {capability_id} violates the Canonical inputSchema: "
                + "; ".join(schema_errors)
            )
        result = result_by_id[capability_id]
        _validate_live_result(capability_id, capability, result)
        evidence[capability_id] = {
            "status": "passed",
            "isError": False,
            "inputHash": digest_json(input_by_id[capability_id]),
            "resultHash": digest_json(result),
        }
    return evidence


def _initial_matrix_by_id(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    path = root / "verification-matrix.json"
    if not path.is_file():
        return {}, {}
    value = read_json(path)
    if not isinstance(value, dict):
        return {}, {}
    capabilities = {
        item.get("capabilityId"): item
        for item in value.get("capabilities", [])
        if isinstance(item, dict) and isinstance(item.get("capabilityId"), str)
    }
    workflows = {
        item.get("workflowId"): item
        for item in value.get("workflows", [])
        if isinstance(item, dict) and isinstance(item.get("workflowId"), str)
    }
    return capabilities, workflows


def _host_compatibility_by_id(
    root: Path,
    canonical: dict[str, Any] | None,
) -> dict[str, str]:
    if canonical is None:
        return {}
    path = root / "host-compatibility-report.json"
    if not path.is_file():
        return {}
    value = read_json(path)
    if not isinstance(value, dict) or value.get("contractId") != canonical.get("contractId"):
        raise FinalizationError(
            "host-compatibility-report.json must identify the current canonical contract"
        )
    assessments = value.get("capabilityAssessments")
    if not isinstance(assessments, list):
        raise FinalizationError(
            "host-compatibility-report.capabilityAssessments must be an array"
        )
    result: dict[str, str] = {}
    for index, assessment in enumerate(assessments):
        location = f"host-compatibility-report.capabilityAssessments[{index}]"
        if not isinstance(assessment, dict):
            raise FinalizationError(f"{location} must be an object")
        capability_id = _nonempty(assessment.get("capabilityId"), f"{location}.capabilityId")
        status = assessment.get("status")
        if status not in {"enabled", "requires-host-integration", "disabled", "blocked"}:
            raise FinalizationError(f"{location}.status is invalid")
        if capability_id in result:
            raise FinalizationError(f"duplicate Host compatibility assessment: {capability_id}")
        result[capability_id] = status
    return result


def _reason(reasons: list[str], value: str) -> None:
    if value not in reasons:
        reasons.append(value)


def _declared_blocking_reasons(value: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key in ("blockingReasons", "reasons"):
        reasons = value.get(key, [])
        if isinstance(reasons, list):
            for reason in reasons:
                if isinstance(reason, str) and reason and reason not in TRANSIENT_REASONS:
                    _reason(result, reason)
    return result


def _canonical_capability_blocking_reasons(
    canonical: dict[str, Any] | None,
    capability: dict[str, Any],
) -> list[str]:
    reasons = _declared_blocking_reasons(capability)
    if canonical is None:
        return reasons
    capability_id = capability.get("capabilityId")
    for conflict in canonical.get("conflicts", []):
        if (
            isinstance(conflict, dict)
            and conflict.get("status") == "unresolved"
            and capability_id in conflict.get("affectedCapabilityIds", [])
        ):
            conflict_id = conflict.get("conflictId")
            _reason(reasons, f"unresolved-conflict:{conflict_id}")
    return reasons


def _build_matrix(
    root: Path,
    canonical: dict[str, Any] | None,
    bundle_capabilities: list[dict[str, Any]],
    capability_records: dict[str, dict[str, Any]],
    workflow_records: dict[str, dict[str, Any]],
    live: dict[str, dict[str, Any]],
    *,
    legacy: bool,
) -> dict[str, Any]:
    initial_capabilities, initial_workflows = _initial_matrix_by_id(root)
    compatibility_by_id = _host_compatibility_by_id(root, canonical)
    if canonical is None:
        contract_id = str(read_json(root / "capability-bundle.json").get("recordingId"))
        canonical_capabilities = bundle_capabilities
        canonical_workflows: list[dict[str, Any]] = []
        canonical_ref = None
    else:
        contract_id = _nonempty(canonical.get("contractId"), "canonical-contract.contractId")
        canonical_capabilities = _canonical_capabilities(canonical)
        canonical_workflows = canonical.get("workflows", [])
        canonical_ref = "canonical-contract.json"
    canonical_capability_by_id = {
        item["capabilityId"]: item for item in canonical_capabilities
    }

    workflow_matrix = []
    workflow_approved: dict[str, bool] = {}
    workflow_runtime_ready: dict[str, bool] = {}
    workflow_caps: dict[str, set[str]] = {}
    for workflow in canonical_workflows:
        workflow_id = workflow["workflowId"]
        record = workflow_records[workflow_id]
        bypass_status, bypass_checks = record["bypass"]
        runtime_status, runtime_checks = record["runtime"]
        host_status, host_checks = record["host"]
        initial = initial_workflows.get(workflow_id, {})
        initial_status = initial.get("status", {}) if isinstance(initial.get("status"), dict) else {}
        reasons = _declared_blocking_reasons(initial)
        for reason in _declared_blocking_reasons(workflow):
            _reason(reasons, reason)
        phase_failed = any(
            status in {"failed", "blocked"}
            for status in (bypass_status, runtime_status, host_status)
        )
        blocked = bool(initial_status.get("blocked")) or phase_failed
        bypass_verified = bypass_status == "passed" and not blocked
        entry_capability_id = workflow.get("entryCapabilityId")
        entry_capability = canonical_capability_by_id.get(entry_capability_id, {})
        entry_tool_name = entry_capability.get("toolName")
        live_record = live.get(entry_capability_id, {})
        live_verified = (
            live_record.get("status") == "passed"
            and live_record.get("isError") is False
        )
        runtime_check_bound = (
            isinstance(entry_tool_name, str)
            and _runtime_check_matches_live(
                runtime_checks,
                entry_tool_name,
                live_record,
            )
        )
        if runtime_status == "passed" and live_verified and not runtime_check_bound:
            raise FinalizationError(
                f"workflow {workflow_id} runtime evidence hashes do not match the live entry Tool call"
            )
        runtime_verified = (
            runtime_status == "passed"
            and live_verified
            and runtime_check_bound
            and not blocked
        )
        workflow_member_ids = set(workflow_capability_ids(workflow))
        workflow_host_compatible = bool(workflow_member_ids) and all(
            compatibility_by_id.get(capability_id) == "enabled"
            for capability_id in workflow_member_ids
        )
        host_verified = (
            host_status == "passed"
            and workflow_host_compatible
            and not blocked
        )
        if not bypass_verified:
            _reason(reasons, "workflow-bypass-verification-pending")
        else:
            reasons = [
                item for item in reasons
                if item != "workflow-bypass-verification-pending"
            ]
        if not runtime_verified:
            _reason(reasons, "runtime-verification-pending")
        else:
            reasons = [
                item for item in reasons
                if item != "runtime-verification-pending"
            ]
        if host_status != "passed":
            _reason(reasons, "host-verification-pending")
        else:
            reasons = [
                item for item in reasons
                if item != "host-verification-pending"
            ]
        if not workflow_host_compatible:
            _reason(reasons, "host-not-fully-compatible")
        else:
            reasons = [
                item for item in reasons
                if item != "host-not-fully-compatible"
            ]
        workflow_ready = (
            bypass_verified
            and runtime_verified
            and host_verified
            and not reasons
        )
        requires_review = not blocked and not workflow_ready
        status = {
            "generated": True,
            "behaviorVerified": bypass_verified,
            "runtimeVerified": runtime_verified,
            "hostVerified": host_verified,
            "requiresReview": requires_review,
            "blocked": blocked,
            "bypassVerified": bypass_verified,
        }
        checks = bypass_checks + runtime_checks + host_checks
        workflow_row = {"workflowId": workflow_id, "status": status, "checks": checks}
        if reasons:
            workflow_row["reasons"] = reasons
        workflow_matrix.append(workflow_row)
        workflow_runtime_ready[workflow_id] = (
            not blocked and bypass_verified and runtime_verified
        )
        workflow_approved[workflow_id] = workflow_ready
        workflow_caps[workflow_id] = workflow_member_ids

    bundle_by_id = {
        item.get("capabilityId"): item
        for item in bundle_capabilities
        if isinstance(item.get("capabilityId"), str)
    }
    canonical_ids = {item.get("capabilityId") for item in canonical_capabilities}
    if set(bundle_by_id) != canonical_ids:
        raise FinalizationError(
            "capability-bundle.json must cover every canonical capability exactly once"
        )

    capability_matrix = []
    for capability in canonical_capabilities:
        capability_id = capability["capabilityId"]
        record = capability_records[capability_id]
        behavior_status, behavior_checks = record["behavior"]
        runtime_status, runtime_checks = record["runtime"]
        host_status, host_checks = record["host"]
        initial = initial_capabilities.get(capability_id, {})
        initial_status = initial.get("status", {}) if isinstance(initial.get("status"), dict) else {}
        reasons = list(initial.get("reasons", [])) if isinstance(initial.get("reasons"), list) else []
        behavior_verified = behavior_status == "passed"
        live_record = live.get(capability_id, {})
        live_verified = (
            live_record.get("status") == "passed"
            and live_record.get("isError") is False
        )
        tool_name = _nonempty(
            capability.get("toolName"),
            f"canonical capability {capability_id}.toolName",
        )
        runtime_check_bound = legacy or _runtime_check_matches_live(
            runtime_checks,
            tool_name,
            live_record,
        )
        if (
            not legacy
            and runtime_status == "passed"
            and live_verified
            and not runtime_check_bound
        ):
            raise FinalizationError(
                f"capability {capability_id} runtime evidence hashes do not match its live Tool call"
            )
        runtime_verified = (
            runtime_status == "passed"
            and live_verified
            and runtime_check_bound
        )
        side_effect = capability.get("sideEffect", bundle_by_id[capability_id].get("sideEffect"))
        if side_effect != bundle_by_id[capability_id].get("sideEffect"):
            raise FinalizationError(
                f"canonical and bundle sideEffect differ for capability {capability_id}"
            )
        host_requirements = capability.get("hostRequirements", [])
        if not isinstance(host_requirements, list):
            raise FinalizationError(
                f"canonical capability {capability_id}.hostRequirements must be an array"
            )
        host_verification_required = side_effect != "read" or bool(host_requirements)
        compatibility_status = compatibility_by_id.get(capability_id)
        if side_effect == "read":
            host_compatible = (
                compatibility_status == "enabled"
                if host_verification_required or compatibility_status is not None
                else True
            )
        else:
            # Older direct unit/API callers did not supply a compatibility view;
            # keep that narrow compatibility while still honoring an explicit
            # non-enabled assessment in real vNext candidates.
            host_compatible = compatibility_status in {None, "enabled"}
        host_verified = host_status == "passed" and host_compatible
        host_gate = host_compatible and (
            host_verified or not host_verification_required
        )
        associated = [
            workflow_id for workflow_id, ids in workflow_caps.items() if capability_id in ids
        ]
        protection = capability.get("runtimeProtection")
        protection_mode = (
            protection.get("mode") if isinstance(protection, dict) else None
        )
        if legacy:
            workflow_required = side_effect != "read"
        elif side_effect == "read":
            workflow_required = False
        elif protection_mode == "deterministic-workflow":
            workflow_required = True
            expected_workflow_id = protection.get("workflowId")
            if associated and associated != [expected_workflow_id]:
                raise FinalizationError(
                    f"capability {capability_id} is associated with workflows {associated}, "
                    f"but runtimeProtection names {expected_workflow_id}"
                )
        elif protection_mode in {"backend-authoritative", "unresolved"}:
            workflow_required = False
            if associated:
                raise FinalizationError(
                    f"capability {capability_id} may be associated with a workflow only when "
                    "runtimeProtection.mode is deterministic-workflow"
                )
        else:
            raise FinalizationError(
                f"write capability {capability_id} must declare a valid runtimeProtection.mode"
            )
        workflow_runtime_gate = bool(associated) and all(
            workflow_runtime_ready[item] for item in associated
        )
        workflow_gate = bool(associated) and all(
            workflow_approved[item] for item in associated
        )
        if workflow_required and not workflow_runtime_gate:
            runtime_verified = False
        phase_failed = any(
            status in {"failed", "blocked"}
            for status in (behavior_status, runtime_status, host_status)
        )
        blocked = (
            bool(initial_status.get("blocked"))
            or capability.get("readiness") == "blocked"
            or phase_failed
        )
        if blocked:
            behavior_verified = False
            runtime_verified = False
            host_verified = False
        if not behavior_verified:
            _reason(reasons, "behavior-verification-pending")
        else:
            reasons = [item for item in reasons if item != "behavior-verification-pending"]
        if not runtime_verified:
            _reason(reasons, "runtime-verification-pending")
        else:
            reasons = [item for item in reasons if item != "runtime-verification-pending"]
        if host_verification_required and not host_verified:
            _reason(reasons, "host-verification-pending")
        else:
            reasons = [item for item in reasons if item != "host-verification-pending"]
        if not host_compatible:
            _reason(reasons, "host-not-fully-compatible")
        else:
            reasons = [item for item in reasons if item != "host-not-fully-compatible"]
        missing_checks = record.get("missingChecks", [])
        if missing_checks:
            _reason(reasons, "canonical-verification-checks-pending")
        else:
            reasons = [
                item for item in reasons if item != "canonical-verification-checks-pending"
            ]
        blocking_reasons = [
            reason for reason in reasons if reason not in TRANSIENT_REASONS
        ]
        for reason in _canonical_capability_blocking_reasons(canonical, capability):
            _reason(reasons, reason)
            _reason(blocking_reasons, reason)

        canonical_review = (
            capability.get("readiness") == "requires-review"
            or bool(capability.get("missingEvidence"))
            or bool(missing_checks)
            or bool(blocking_reasons)
        )
        if side_effect == "read" or not workflow_required:
            approved = (
                behavior_verified
                and runtime_verified
                and host_gate
                and not blocked
                and not canonical_review
                and protection_mode != "unresolved"
            )
        else:
            if not associated:
                _reason(reasons, "constrained-workflow-missing")
            elif not workflow_gate:
                _reason(reasons, "workflow-bypass-verification-pending")
            approved = (
                behavior_verified
                and runtime_verified
                and host_gate
                and workflow_gate
                and not blocked
                and not canonical_review
            )
        requires_review = not blocked and not approved
        status = {
            "generated": True,
            "behaviorVerified": behavior_verified,
            "runtimeVerified": runtime_verified,
            "hostVerified": host_verified,
            "requiresReview": requires_review,
            "blocked": blocked,
        }
        checks = behavior_checks + runtime_checks + host_checks
        capability_matrix.append({
            "capabilityId": capability_id,
            "status": status,
            "reasons": reasons,
            "checks": checks,
        })

    runtime_verified_count = sum(
        1
        for row in capability_matrix
        if row.get("status", {}).get("runtimeVerified") is True
    )
    if capability_matrix and runtime_verified_count == len(capability_matrix):
        runtime_delivery_status = "verified"
    elif runtime_verified_count:
        runtime_delivery_status = "partially-verified"
    else:
        runtime_delivery_status = "not-run"
    matrix = {
        "schemaVersion": "vNext",
        "contractId": contract_id,
        "canonicalContractRef": canonical_ref,
        "delivery": {
            "functionCore": {"status": "generated"},
            "mcpServer": {"status": "generated"},
            "skill": {"status": "generated"},
            "runtime": {"status": runtime_delivery_status},
            "deployment": {"status": "not-deployed"},
        },
        "capabilities": capability_matrix,
        "workflows": workflow_matrix,
    }
    if legacy:
        matrix["compatibilityMode"] = "legacy-single-read-only"
    return matrix


def _item_decision(status: dict[str, Any]) -> str:
    if status.get("blocked") is True:
        return "blocked"
    if status.get("requiresReview") is True:
        return "requires-review"
    return "approved"


def _overall_decision(matrix: dict[str, Any]) -> str:
    decisions = [
        _item_decision(item["status"])
        for group in (matrix["capabilities"], matrix["workflows"])
        for item in group
    ]
    if decisions and all(item == "approved" for item in decisions):
        return "approved"
    if "approved" in decisions:
        return "partially-approved"
    if "requires-review" in decisions:
        return "requires-review"
    return "blocked"


def main() -> int:
    args = parse_args()
    root = args.artifact_root.resolve()
    validator = Path(__file__).with_name("validate_artifacts.py")
    validator_base = [
        sys.executable,
        str(validator),
        str(root),
        "--source-root",
        str(args.source_root.resolve()),
    ]
    for source_map in args.source_map:
        validator_base.extend(["--source-map", source_map])
    before = subprocess.run(validator_base + ["--pre-finalize"], check=False)
    if before.returncode != 0:
        return before.returncode

    try:
        report = read_json(args.verification_report)
        bundle = read_json(root / "capability-bundle.json")
        if not isinstance(bundle, dict) or not isinstance(bundle.get("capabilities"), list):
            raise FinalizationError("capability-bundle.json must contain capabilities")
        bundle_capabilities = [item for item in bundle["capabilities"] if isinstance(item, dict)]
        canonical_path = root / "canonical-contract.json"
        canonical = read_json(canonical_path) if canonical_path.is_file() else None
        if canonical is not None and not isinstance(canonical, dict):
            raise FinalizationError("canonical-contract.json must be an object")
        legacy, checks, capability_records, workflow_records = _read_report(
            report, canonical, bundle_capabilities
        )
        finalization_capabilities = (
            _canonical_capabilities(canonical) if canonical else bundle_capabilities
        )
        capability_ids = [item["capabilityId"] for item in finalization_capabilities]
        live = _read_live_evidence(
            args.live_input,
            args.live_result,
            finalization_capabilities,
            legacy=legacy,
        )
        if legacy:
            capability_records[capability_ids[0]]["runtime"] = ("passed", checks)
        matrix = _build_matrix(
            root,
            canonical,
            bundle_capabilities,
            capability_records,
            workflow_records,
            live,
            legacy=legacy,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, FinalizationError) as error:
        print(f"ERROR finalization evidence: {error}", file=sys.stderr)
        return 1

    snapshot = _snapshot_finalization_files(root)
    bundle_hash = digest_file(root / "capability-bundle.json")
    draft_hash = digest_file(root / "capability-draft.json")
    receipt = {
        "schemaVersion": "v1",
        "capabilityDraftHash": draft_hash,
        "bundleHash": bundle_hash,
        "validationStatus": "passed",
    }
    if canonical is not None:
        receipt["contractId"] = canonical["contractId"]
        receipt["canonicalContractHash"] = digest_file(root / "canonical-contract.json")
    write_json(root / "function-core/validation-receipt.json", receipt)

    base_hashes = {
        path.relative_to(root).as_posix(): digest_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in FINALIZATION_FILES
    }
    write_json(root / "preflight-report.json", {
        "schemaVersion": "v1",
        "status": "passed",
        "capabilityDraftHash": draft_hash,
        "bundleHash": bundle_hash,
        "generatedArtifactHashes": base_hashes,
        "checks": checks,
    })

    live_values = [dict({"capabilityId": capability_id}, **value) for capability_id, value in sorted(live.items())]
    all_live_passed = set(live) == set(capability_ids) and all(
        item["status"] == "passed" for item in live.values()
    )
    live_document = {
        "schemaVersion": "vNext" if not legacy else "v1",
        "status": "passed" if all_live_passed else "partial",
        "isError": False if all_live_passed else any(item.get("isError") is not False for item in live.values()),
        "inputHash": digest_json([{"capabilityId": item["capabilityId"], "inputHash": item["inputHash"]} for item in live_values]),
        "resultHash": digest_json([{"capabilityId": item["capabilityId"], "resultHash": item["resultHash"]} for item in live_values]),
        "capabilities": live_values,
    }
    if legacy:
        only = live_values[0]
        live_document["inputHash"] = only["inputHash"]
        live_document["resultHash"] = only["resultHash"]
    write_json(root / "live-verification.json", live_document)
    write_json(root / "verification-matrix.json", matrix)

    decision = _overall_decision(matrix)
    approved = {
        path.relative_to(root).as_posix(): digest_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"approval-audit.json", "export-manifest.json"}
    }
    approval = {
        "schemaVersion": "vNext" if not legacy else "v1",
        "decision": decision,
        "preflightStatus": "passed",
        "verificationMatrixRef": "verification-matrix.json",
        "capabilities": [
            {"capabilityId": item["capabilityId"], "decision": _item_decision(item["status"])}
            for item in matrix["capabilities"]
        ],
        "workflows": [
            {"workflowId": item["workflowId"], "decision": _item_decision(item["status"])}
            for item in matrix["workflows"]
        ],
        "artifacts": [
            {"relativePath": path, "sha256": value} for path, value in approved.items()
        ],
    }
    write_json(root / "approval-audit.json", approval)
    manifest_files = [
        {
            "relativePath": path.relative_to(root).as_posix(),
            "sha256": digest_file(path),
            "sanitized": True,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "export-manifest.json"
    ]
    write_json(
        root / "export-manifest.json",
        {"schemaVersion": "v0", "files": manifest_files},
    )

    if decision != "approved":
        print(
            f"Finalization recorded `{decision}`; unverified capabilities remain explicitly unapproved."
        )
    final_validation = subprocess.run(validator_base, check=False)
    if final_validation.returncode != 0:
        _restore_finalization_files(root, snapshot)
        print(
            "ERROR final validation failed; restored the candidate's pre-finalization audit state.",
            file=sys.stderr,
        )
    return final_validation.returncode


if __name__ == "__main__":
    raise SystemExit(main())
