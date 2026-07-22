from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.test_validate_artifacts import (
    create_base,
    install_document_contract_markers,
    write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FINALIZER_PATH = REPO_ROOT / "skills" / "code2skill" / "scripts" / "finalize_export.py"
DERIVER_PATH = REPO_ROOT / "skills" / "code2skill" / "scripts" / "derive_artifacts.py"
SCRIPTS_PATH = FINALIZER_PATH.parent
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))
import validate_artifacts as ARTIFACT_VALIDATOR  # noqa: E402
import validate_vnext as VNEXT_VALIDATOR  # noqa: E402
from contract_model import operation_summary_for_capability  # noqa: E402

SPEC = importlib.util.spec_from_file_location("code2skill_finalize_export", FINALIZER_PATH)
assert SPEC is not None and SPEC.loader is not None
FINALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FINALIZER)


def evidence_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def mcp_success(data: Any, status: Any = "success") -> dict[str, Any]:
    structured = {"status": status, "data": data}
    return {
        "isError": False,
        "structuredContent": structured,
        "content": [{
            "type": "text",
            "text": json.dumps(structured, ensure_ascii=False, separators=(",", ":")),
        }],
    }


def check(label: str, *, zero_external_writes: bool | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "name": label,
        "command": f"python3 verify_{label}.py",
        "exitCode": 0,
        "status": "passed",
        "evidenceHash": evidence_hash(label),
    }
    if zero_external_writes is not None:
        value["zeroExternalWrites"] = zero_external_writes
    return value


def runtime_check(
    capability_id: str,
    *,
    label: str | None = None,
    input_hash: str | None = None,
    result_hash: str | None = None,
) -> dict[str, Any]:
    value = check(label or f"{capability_id}-runtime")
    value.update({
        "toolName": capability_id.replace("-", "_"),
        "inputHash": input_hash or evidence_hash(f"{capability_id}-live-input"),
        "resultHash": result_hash or evidence_hash(f"{capability_id}-live-result"),
    })
    return value


def capability(
    capability_id: str,
    side_effect: str = "read",
    *,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    value = {
        "capabilityId": capability_id,
        "toolName": capability_id.replace("-", "_"),
        "sideEffect": side_effect,
        "readiness": "ready",
        "missingEvidence": [],
        "implementation": {"kind": "local"},
        "outputs": [{
            "path": ["items"],
            "type": "array",
            "schema": {"type": "array", "items": {"type": "string"}},
        }],
        "successRule": {
            "requiredOutputPaths": [["items"]],
            "forbiddenOutputKeys": ["error", "errors"],
        },
    }
    if side_effect != "read":
        value["runtimeProtection"] = (
            {
                "mode": "deterministic-workflow",
                "workflowId": workflow_id,
            }
            if workflow_id is not None
            else {
                "mode": "backend-authoritative",
                "owner": "target-api",
            }
        )
    return value


def canonical(
    capabilities: list[dict[str, Any]], workflows: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    normalized_workflows = copy.deepcopy(workflows or [])
    for workflow in normalized_workflows:
        workflow.setdefault("capabilityIds", [workflow.get("entryCapabilityId")])
    return {
        "schemaVersion": "vNext",
        "contractId": "fictional-catalog-contract",
        "capabilities": capabilities,
        "workflows": normalized_workflows,
    }


def capability_report(
    capability_id: str,
    *,
    input_hash: str | None = None,
    result_hash: str | None = None,
) -> dict[str, Any]:
    # The finalizer derives a non-optional verification floor even when a
    # Canonical author omits verificationChecks.  Supplying a harmless
    # superset here keeps these synthetic report fixtures focused on the gate
    # under test while still representing executed behavior evidence.
    behavior_check_ids = [
        "valid-input-and-output-contract",
        "invalid-input-is-rejected",
        "structured-error-recovery",
        "exact-request-binding-and-success-status",
        "dynamic-values-are-not-frozen",
        "conditional-rules-cover-active-and-inactive-branches",
        "attachment-resolution-failure-zero-dispatch",
        "attachment-request-field-and-metadata-contract",
        "unknown-write-outcome-is-non-retryable",
        "backend-business-error-is-structured",
        f"{capability_id}-behavior",
    ]
    if capability_id == "list-knowledge-topics":
        behavior_check_ids.extend([
            "goal-inspect-fictional-topics-different-information-orders-converge",
            "goal-inspect-fictional-topics-all-known-skips-questions-and-tools",
            "goal-inspect-fictional-topics-asks-only-currently-missing",
        ])
    return {
        "capabilityId": capability_id,
        "behavior": {
            "status": "passed",
            "checks": [check(check_id) for check_id in behavior_check_ids],
        },
        "runtime": {
            "status": "passed",
            "checks": [runtime_check(
                capability_id,
                input_hash=input_hash,
                result_hash=result_hash,
            )],
        },
        "host": {"status": "passed", "checks": [check(f"{capability_id}-host")]},
    }


def attachment_runtime_proof(
    *,
    step_id: str = "uploadAttachment",
    location: str = "multipart",
    path: list[str | int] | None = None,
) -> dict[str, Any]:
    trace = {
        "resolverCalls": 1,
        "businessDispatches": 1,
        "resolutionFailureDispatches": 0,
        "rawGrantForwarded": False,
        "resolvedContentBound": True,
        "sizeVerified": True,
        "digestVerified": True,
        "stepId": step_id,
        "location": location,
        "path": path or ["file"],
    }
    return {
        **trace,
        "traceEvidenceHash": FINALIZER.digest_json(trace),
    }


def install_complete_readonly_vnext(candidate: Path) -> dict[str, Any]:
    """Turn the legacy one-Tool fixture into a complete synthetic vNext candidate."""

    bundle = json.loads((candidate / "capability-bundle.json").read_text())
    export_profile = json.loads((candidate / "export-profile.json").read_text())
    export_profile["allowedRuntimeOrigins"] = []
    export_profile.pop("pageRoute", None)
    write_json(candidate / "export-profile.json", export_profile)
    (candidate / "PAGE.md").unlink(missing_ok=True)
    legacy = bundle["capabilities"][0]
    capability_id = legacy["capabilityId"]
    request_evidence_id = "ev-fictional-topic-request"
    response_evidence_id = "ev-fictional-topic-response"
    side_effect_evidence_id = "ev-fictional-topic-side-effect"
    topology = {
        "schemaVersion": "vNext",
        "topologyId": "fictional-topic-sources",
        "authorizationBoundary": {
            "discoveryPolicy": "explicit-roots-only",
            "machineWideDiscovery": False,
            "portableLocatorsOnly": True,
        },
        "sources": [{
            "sourceId": "fictional-topic-contract",
            "semanticRoles": ["client-api-call"],
            "root": ".",
            "availability": "available",
            "searched": True,
            "searchSummary": "A repository-owned synthetic client contract was inspected.",
        }, {
            "sourceId": "fictional-topic-service",
            "semanticRoles": ["transport-contract"],
            "root": "skills",
            "availability": "available",
            "searched": True,
            "searchSummary": "A distinct repository-owned synthetic service contract was inspected.",
        }],
        "missingSources": [],
    }
    canonical_capability = {
        "capabilityId": capability_id,
        "toolName": legacy["toolName"],
        "functionExport": legacy["functionExport"],
        "description": legacy["description"],
        "authentication": legacy["authentication"],
        "readiness": "ready",
        "missingEvidence": [],
        "exposure": {
            "kind": "client-request",
            "evidenceRefs": [request_evidence_id],
            "supplementalEvidenceRefs": [
                response_evidence_id,
                side_effect_evidence_id,
            ],
        },
        "inputs": [],
        "outputs": [{
            "path": ["topics"],
            "type": "array",
            "schema": {"type": "array", "items": {"type": "string"}},
            "valueDomain": {"kind": "unconstrained"},
            "description": "A fictional topic catalog used only by the finalization fixture.",
            "evidenceRefs": [response_evidence_id],
        }],
        "constraints": [],
        "attachments": {"mode": "none"},
        "implementation": legacy["implementation"],
        "successRule": {
            **legacy["successRule"],
            "evidenceRefs": [response_evidence_id],
        },
        "errorContract": {
            "format": "structured",
            "preservesRecoveryContext": True,
            "codePath": ["code"],
            "messagePath": ["message"],
            "detailsPath": ["details"],
            "retryabilityPath": ["retryable"],
            "defaultRetryable": False,
            "evidenceRefs": [response_evidence_id],
        },
        "operationPolicy": {
            "sideEffect": "read",
            "idempotency": "safe",
            "automaticRetry": "read-only-bounded",
            "confirmation": "not-required",
            "unknownOutcome": "not-applicable",
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "sideEffect": "read",
        "hostRequirements": ["agent-skills-discovery", "mcp-tool-invocation"],
        "evidenceCoverage": {
            "sideEffect": {
                "assertionLevel": "fact",
                "declaredSideEffect": "read",
                "evidenceRefs": [side_effect_evidence_id],
            },
        },
        "verificationChecks": [f"{capability_id}-behavior"],
        "evidenceRefs": [
            request_evidence_id,
            response_evidence_id,
            side_effect_evidence_id,
        ],
    }
    contract = {
        "schemaVersion": "vNext",
        "contractId": "fictional-topic-contract",
        "recordingId": bundle["recordingId"],
        "sourceTopologyRef": "source-topology.json",
        "portableCore": {
            "languageBinding": "none",
            "frameworkBinding": "none",
            "architectureBinding": "none",
            "hostBinding": "none",
            "discoveryBasis": "observable-semantic-evidence",
        },
        "featureBoundary": {
            "scopeKind": "business-feature",
            "primaryEvidenceRole": "client-feature",
            "backendEvidenceRole": "supplement-and-verify",
            "inclusionRule": "client-observed-only",
            "clientSourceIds": ["fictional-topic-contract"],
            "supplementarySourceIds": ["fictional-topic-service"],
        },
        "conflicts": [],
        "evidenceCatalog": [
            {
                "evidenceId": request_evidence_id,
                "sourceId": "fictional-topic-contract",
                "locator": "README.md#synthetic-finalization-source",
                "semanticRole": "client-api-call",
                "assertionLevel": "fact",
            },
            {
                "evidenceId": response_evidence_id,
                "sourceId": "fictional-topic-service",
                "locator": "code2skill/SKILL.md#core-contract",
                "semanticRole": "transport-contract",
                "assertionLevel": "fact",
            },
            {
                "evidenceId": side_effect_evidence_id,
                "sourceId": "fictional-topic-service",
                "locator": "code2skill/SKILL.md#non-negotiable-checks",
                "semanticRole": "transport-contract",
                "assertionLevel": "fact",
            },
        ],
        "server": {
            **bundle["server"],
            "evidenceRefs": [request_evidence_id],
        },
        "capabilities": [canonical_capability],
        "handoffs": [],
        "capabilityGraph": {
            "nodes": [{
                "capabilityId": capability_id,
                "independentValue": "Return the current fictional topic catalog.",
            }],
            "edges": [],
        },
        "goals": [{
            "goalId": "inspect-fictional-topics",
            "intent": "Inspect the current fictional topic catalog.",
            "informationNeeds": [{
                "informationId": "current-topics",
                "classification": "required",
                "type": "array",
                "schema": {"type": "array", "items": {"type": "string"}},
                "satisfiedBy": [{
                    "kind": "capability",
                    "capabilityId": capability_id,
                    "outputPath": ["topics"],
                }],
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["current-topics"],
            },
            "agentPolicy": {
                "acceptInformationInAnyOrder": True,
                "reuseFreshInformation": True,
                "askOnlyCurrentlyMissing": True,
                "skipUnnecessaryCapabilities": True,
                "stopWhenPredicateSatisfied": True,
            },
            "requiredCapabilityIds": [capability_id],
            "conditionalCapabilityIds": [],
            "optionalCapabilityIds": [],
            "supplies": [],
        }],
        "consumerRequirements": {"requirements": [
            {
                "requirementId": "agent-skills-discovery",
                "hostCapability": "agentSkillsDiscovery",
                "description": "Discover the portable synthetic Skill guidance.",
                "onMissing": "requires-host-integration",
            },
            {
                "requirementId": "mcp-tool-invocation",
                "hostCapability": "mcpToolInvocation",
                "description": "Invoke the declared synthetic Tool transport.",
                "onMissing": "disable",
            },
        ]},
        "workflows": [],
    }
    host_profile = {
        "schemaVersion": "vNext",
        "profileId": "fictional-generic-host",
        "description": "A generic synthetic Host with portable Skill discovery and MCP invocation.",
        "capabilities": {
            "agentSkillsDiscovery": {"status": "supported"},
            "mcpToolInvocation": {"status": "supported"},
        },
    }
    write_json(candidate / "source-topology.json", topology)
    write_json(candidate / "canonical-contract.json", contract)
    write_json(candidate / "host-profile.json", host_profile)
    operation_policy = json.dumps(
        canonical_capability["operationPolicy"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    operation_summary = json.dumps(
        operation_summary_for_capability(canonical_capability),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    mcp_path = candidate / "mcp-tool/index.mjs"
    mcp_source = mcp_path.read_text(encoding="utf-8")
    mcp_source = mcp_source.replace(
        "operationPolicy: {}, operationSummary: {}",
        f"operationPolicy: {operation_policy}, operationSummary: {operation_summary}",
    ).replace(
        "normalizeToolError(error, {})",
        f"normalizeToolError(error, {operation_policy})",
    )
    mcp_path.write_text(mcp_source, encoding="utf-8")
    derived = subprocess.run(
        [sys.executable, str(DERIVER_PATH), str(candidate)],
        check=False,
        capture_output=True,
        text=True,
    )
    if derived.returncode != 0:
        raise AssertionError(derived.stderr)
    install_document_contract_markers(
        candidate,
        json.loads(
            (candidate / "references/capability-contracts.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    return contract


class VNextFinalizationTest(unittest.TestCase):
    def test_final_matrix_derives_review_and_blocked_from_canonical_gates(self) -> None:
        base_status = {
            "generated": True,
            "behaviorVerified": True,
            "runtimeVerified": True,
            "hostVerified": False,
            "requiresReview": False,
            "blocked": False,
        }
        cases: list[tuple[str, dict[str, Any], list[dict[str, Any]], str]] = []

        missing_gate = capability("missing-gate")
        cases.append((
            "missing gate",
            canonical([missing_gate]),
            [{
                "capabilityId": "missing-gate",
                "status": {**base_status, "behaviorVerified": False, "runtimeVerified": False},
                "checks": [],
            }],
            "requiresReview",
        ))

        blocked = capability("blocked-read")
        blocked["readiness"] = "blocked"
        cases.append((
            "canonical blocked",
            canonical([blocked]),
            [{"capabilityId": "blocked-read", "status": dict(base_status), "checks": [check("blocked-read")]}],
            "canonically blocked",
        ))

        missing_evidence = capability("missing-evidence")
        missing_evidence["missingEvidence"] = ["authoritative response contract"]
        cases.append((
            "missing evidence",
            canonical([missing_evidence]),
            [{"capabilityId": "missing-evidence", "status": dict(base_status), "checks": [check("missing-evidence")]}],
            "requiresReview",
        ))

        conflicted = capability("conflicted-read")
        conflicted_contract = canonical([conflicted])
        conflicted_contract["conflicts"] = [{
            "conflictId": "conflict-one",
            "status": "unresolved",
            "affectedCapabilityIds": ["conflicted-read"],
        }]
        cases.append((
            "unresolved conflict",
            conflicted_contract,
            [{"capabilityId": "conflicted-read", "status": dict(base_status), "checks": [check("conflicted-read")]}],
            "requiresReview",
        ))

        for label, contract, rows, expected in cases:
            with self.subTest(label=label):
                diagnostics = ARTIFACT_VALIDATOR.Diagnostics()
                VNEXT_VALIDATOR._validate_verification_matrix(
                    contract,
                    {
                        "capabilityAssessments": [
                            {"capabilityId": rows[0]["capabilityId"], "status": "enabled"}
                        ]
                    },
                    {
                        "schemaVersion": "vNext",
                        "contractId": contract["contractId"],
                        "capabilities": rows,
                        "workflows": [],
                    },
                    False,
                    diagnostics,
                )
                self.assertTrue(any(expected in item for item in diagnostics.errors), diagnostics.errors)

    def test_runtime_verified_requires_live_evidence_for_same_capability(self) -> None:
        contract = canonical([capability("called-read"), capability("uncalled-read")])
        matrix = {
            "capabilities": [
                {
                    "capabilityId": "called-read",
                    "status": {"runtimeVerified": True},
                    "checks": [{
                        "phase": "runtime",
                        "status": "passed",
                        "toolName": "called_read",
                        "inputHash": "c" * 64,
                        "resultHash": "d" * 64,
                    }],
                },
                {"capabilityId": "uncalled-read", "status": {"runtimeVerified": True}},
            ],
            "workflows": [],
        }
        live = {
            "schemaVersion": "vNext",
            "status": "partial",
            "inputHash": "a" * 64,
            "resultHash": "b" * 64,
            "capabilities": [{
                "capabilityId": "called-read",
                "status": "passed",
                "isError": False,
                "inputHash": "c" * 64,
                "resultHash": "d" * 64,
            }],
        }
        diagnostics = ARTIFACT_VALIDATOR.Diagnostics()
        ARTIFACT_VALIDATOR._validate_vnext_live_matrix(contract, matrix, live, diagnostics)
        self.assertFalse(any("capabilities[0].status.runtimeVerified" in item for item in diagnostics.errors))
        self.assertFalse(any("capabilities[0].checks" in item for item in diagnostics.errors))
        self.assertTrue(
            any("capabilities[1].status.runtimeVerified" in item and "same capabilityId" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

        mismatched = copy.deepcopy(matrix)
        mismatched["capabilities"][0]["checks"][0]["resultHash"] = "e" * 64
        mismatch_diagnostics = ARTIFACT_VALIDATOR.Diagnostics()
        ARTIFACT_VALIDATOR._validate_vnext_live_matrix(
            contract,
            mismatched,
            live,
            mismatch_diagnostics,
        )
        self.assertTrue(
            any("capabilities[0].checks" in item and "live input/result hashes" in item for item in mismatch_diagnostics.errors),
            mismatch_diagnostics.errors,
        )

    def test_final_checks_and_preflight_reject_non_executed_evidence(self) -> None:
        contract = canonical([capability("list-items")])
        diagnostics = ARTIFACT_VALIDATOR.Diagnostics()
        VNEXT_VALIDATOR._validate_verification_matrix(
            contract,
            {"capabilityAssessments": [{"capabilityId": "list-items", "status": "enabled"}]},
            {
                "schemaVersion": "vNext",
                "contractId": contract["contractId"],
                "capabilities": [{
                    "capabilityId": "list-items",
                    "status": {
                        "generated": True,
                        "behaviorVerified": True,
                        "runtimeVerified": True,
                        "hostVerified": False,
                        "requiresReview": False,
                        "blocked": False,
                    },
                    "checks": [{"status": "passed"}],
                }],
                "workflows": [],
            },
            False,
            diagnostics,
        )
        self.assertTrue(any(".command" in item for item in diagnostics.errors), diagnostics.errors)
        self.assertTrue(any(".exitCode" in item for item in diagnostics.errors), diagnostics.errors)
        self.assertTrue(any(".evidenceHash" in item for item in diagnostics.errors), diagnostics.errors)

        preflight_diagnostics = ARTIFACT_VALIDATOR.Diagnostics()
        self.assertFalse(
            ARTIFACT_VALIDATOR._validate_preflight_checks(
                ["not-an-executed-check"],
                vnext=True,
                diagnostics=preflight_diagnostics,
            )
        )
        self.assertTrue(any("executed check object" in item for item in preflight_diagnostics.errors))

    def test_final_delivery_cannot_claim_unverified_runtime_or_deployment(self) -> None:
        contract = canonical([capability("list-items")])
        compatibility = {
            "capabilityAssessments": [
                {"capabilityId": "list-items", "status": "enabled"}
            ]
        }
        matrix = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "delivery": {
                "functionCore": {"status": "generated"},
                "mcpServer": {"status": "generated"},
                "skill": {"status": "generated"},
                "runtime": {"status": "verified"},
                "deployment": {"status": "deployed"},
            },
            "capabilities": [{
                "capabilityId": "list-items",
                "status": {
                    "generated": True,
                    "behaviorVerified": False,
                    "runtimeVerified": False,
                    "hostVerified": False,
                    "requiresReview": True,
                    "blocked": False,
                },
                "reasons": [
                    "behavior-verification-pending",
                    "runtime-verification-pending",
                ],
                "checks": [],
            }],
            "workflows": [],
        }
        diagnostics = ARTIFACT_VALIDATOR.Diagnostics()
        VNEXT_VALIDATOR._validate_verification_matrix(
            contract,
            compatibility,
            matrix,
            False,
            diagnostics,
        )
        self.assertTrue(
            any("final delivery states must be derived" in item for item in diagnostics.errors),
            diagnostics.errors,
        )

    def test_report_must_cover_every_capability_with_explicit_behavior(self) -> None:
        contract = canonical([capability("list-items"), capability("read-item")])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [{
                "capabilityId": "list-items",
                "runtime": {"status": "not-run", "checks": []},
            }],
            "workflows": [],
        }
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError, "missing required fields"
        ):
            FINALIZER._read_report(report, contract, contract["capabilities"])

        report["capabilities"] = [capability_report("list-items")]
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError, "cover every canonical capability exactly once"
        ):
            FINALIZER._read_report(report, contract, contract["capabilities"])

    def test_vnext_report_requires_distinct_phase_specific_checks(self) -> None:
        canonical_capability = capability("list-items")
        canonical_capability["verificationChecks"] = [{
            "checkId": "list-items-runtime-contract",
            "phase": "runtime",
        }]
        contract = canonical([canonical_capability])
        matrix_compatibility_report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [{
                "capabilityId": "list-items",
                "status": {
                    "behaviorVerified": True,
                    "runtimeVerified": True,
                    "hostVerified": True,
                },
                "checks": [check("shared-matrix-check")],
            }],
            "workflows": [],
        }
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError,
            "missing required fields",
        ):
            FINALIZER._read_report(
                matrix_compatibility_report,
                contract,
                contract["capabilities"],
            )

        shared_check = check("shared-phase-check")
        reused_report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [{
                "capabilityId": "list-items",
                "behavior": {"status": "passed", "checks": [copy.deepcopy(shared_check)]},
                "runtime": {"status": "passed", "checks": [copy.deepcopy(shared_check)]},
                "host": {"status": "passed", "checks": [copy.deepcopy(shared_check)]},
            }],
            "workflows": [],
        }
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError,
            "reuses the same executed check",
        ):
            FINALIZER._read_report(reused_report, contract, contract["capabilities"])

        wrong_phase_report = copy.deepcopy(reused_report)
        wrong_phase_report["capabilities"][0] = capability_report("list-items")
        wrong_phase_report["capabilities"][0]["behavior"]["checks"].append(
            check("list-items-runtime-contract")
        )
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError,
            "runtime is missing canonical runtime checks",
        ):
            FINALIZER._read_report(wrong_phase_report, contract, contract["capabilities"])

        workflow = {
            "workflowId": "publish-item-safely",
            "entryCapabilityId": "publish-item",
        }
        write_contract = canonical([
            capability(
                "publish-item",
                "create",
                workflow_id="publish-item-safely",
            )
        ], [workflow])
        shared_workflow_check = check(
            "shared-workflow-check",
            zero_external_writes=True,
        )
        workflow_reuse_report = {
            "schemaVersion": "vNext",
            "contractId": write_contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [capability_report("publish-item")],
            "workflows": [{
                "workflowId": "publish-item-safely",
                "bypass": {
                    "status": "passed",
                    "checks": [copy.deepcopy(shared_workflow_check)],
                },
                "runtime": {
                    "status": "passed",
                    "checks": [copy.deepcopy(shared_workflow_check)],
                },
                "host": {
                    "status": "passed",
                    "checks": [copy.deepcopy(shared_workflow_check)],
                },
            }],
        }
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError,
            "reuses the same executed check",
        ):
            FINALIZER._read_report(
                workflow_reuse_report,
                write_contract,
                write_contract["capabilities"],
            )

    def test_vnext_report_runtime_parser_enforces_the_closed_json_contract(self) -> None:
        contract = canonical([capability("list-items")])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [capability_report("list-items")],
            "workflows": [],
        }
        FINALIZER._read_report(report, contract, contract["capabilities"])

        mutations = []
        top_level = copy.deepcopy(report)
        top_level["unreviewed"] = True
        mutations.append(top_level)
        check_level = copy.deepcopy(report)
        check_level["checks"][0]["unreviewed"] = True
        mutations.append(check_level)
        phase_level = copy.deepcopy(report)
        phase_level["capabilities"][0]["behavior"]["unreviewed"] = True
        mutations.append(phase_level)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                FINALIZER.FinalizationError,
                "unsupported fields",
            ):
                FINALIZER._read_report(
                    mutation,
                    contract,
                    contract["capabilities"],
                )

        malformed_proof = copy.deepcopy(report)
        malformed_proof["capabilities"][0]["runtime"]["checks"][0][
            "attachmentProof"
        ] = {}
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError,
            "reviewed attachment trace fields",
        ):
            FINALIZER._read_report(
                malformed_proof,
                contract,
                contract["capabilities"],
            )

        unrelated_proof = copy.deepcopy(report)
        proof = attachment_runtime_proof()
        unrelated_check = unrelated_proof["capabilities"][0]["runtime"]["checks"][0]
        unrelated_check["attachmentProof"] = proof
        unrelated_check["evidenceHash"] = proof["traceEvidenceHash"]
        with self.assertRaisesRegex(
            FINALIZER.FinalizationError,
            "without a Canonical Host-approved attachment boundary",
        ):
            FINALIZER._read_report(
                unrelated_proof,
                contract,
                contract["capabilities"],
            )

    def test_attachment_runtime_pass_requires_resolver_and_dispatch_spy_proof(self) -> None:
        upload = capability("upload-fictional-attachment", "create")
        upload["attachments"] = {
            "mode": "host-approved-reference",
            "contentBindings": [{
                "inputName": "hostAttachmentGrant",
                "stepId": "uploadAttachment",
                "location": "multipart",
                "path": ["file"],
                "requirementId": "attachment-resolution",
            }],
        }
        upload["verificationChecks"] = [{
            "checkId": "attachment-resolution-runtime-vector",
            "phase": "runtime",
        }]
        contract = canonical([upload])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [capability_report(upload["capabilityId"])],
            "workflows": [],
        }
        runtime = report["capabilities"][0]["runtime"]["checks"][0]
        runtime["checkId"] = "attachment-resolution-runtime-vector"

        with self.assertRaisesRegex(FINALIZER.FinalizationError, "attachmentProof"):
            FINALIZER._read_report(report, contract, contract["capabilities"])

        runtime["attachmentProof"] = attachment_runtime_proof()
        runtime["evidenceHash"] = runtime["attachmentProof"]["traceEvidenceHash"]
        FINALIZER._read_report(report, contract, contract["capabilities"])

        for field, invalid in (
            ("resolverCalls", 2),
            ("businessDispatches", 0),
            ("resolutionFailureDispatches", 1),
            ("rawGrantForwarded", True),
            ("resolvedContentBound", False),
            ("sizeVerified", False),
            ("digestVerified", False),
            ("stepId", "differentStep"),
            ("location", "body"),
            ("path", ["differentField"]),
            ("traceEvidenceHash", evidence_hash("unrelated-trace")),
        ):
            with self.subTest(field=field):
                mutated = copy.deepcopy(report)
                mutated["capabilities"][0]["runtime"]["checks"][0]["attachmentProof"][field] = invalid
                with self.assertRaisesRegex(FINALIZER.FinalizationError, "attachmentProof"):
                    FINALIZER._read_report(mutated, contract, contract["capabilities"])

        missing_field = copy.deepcopy(report)
        del missing_field["capabilities"][0]["runtime"]["checks"][0]["attachmentProof"][
            "traceEvidenceHash"
        ]
        with self.assertRaisesRegex(FINALIZER.FinalizationError, "attachmentProof"):
            FINALIZER._read_report(missing_field, contract, contract["capabilities"])

        extra_field = copy.deepcopy(report)
        extra_field["capabilities"][0]["runtime"]["checks"][0]["attachmentProof"][
            "unboundClaim"
        ] = True
        with self.assertRaisesRegex(FINALIZER.FinalizationError, "attachmentProof"):
            FINALIZER._read_report(extra_field, contract, contract["capabilities"])

    def test_read_host_requirements_need_verified_compatible_host(self) -> None:
        read_capability = capability("list-items")
        read_capability["hostRequirements"] = ["session-state"]
        contract = canonical([read_capability])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [{
                **capability_report("list-items"),
                "host": {"status": "not-run", "checks": []},
            }],
            "workflows": [],
        }
        _, _, unverified_records, workflow_records = FINALIZER._read_report(
            report,
            contract,
            contract["capabilities"],
        )
        live = {
            "list-items": {
                "status": "passed",
                "isError": False,
                "inputHash": evidence_hash("list-items-live-input"),
                "resultHash": evidence_hash("list-items-live-result"),
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "capability-bundle.json", {
                "recordingId": "fictional-catalog",
                "capabilities": contract["capabilities"],
            })
            write_json(root / "host-compatibility-report.json", {
                "contractId": contract["contractId"],
                "capabilityAssessments": [{
                    "capabilityId": "list-items",
                    "status": "enabled",
                }],
            })
            unverified_matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                unverified_records,
                workflow_records,
                live,
                legacy=False,
            )

            verified_report = copy.deepcopy(report)
            verified_report["capabilities"][0]["host"] = {
                "status": "passed",
                "checks": [check("list-items-host")],
            }
            _, _, verified_records, _ = FINALIZER._read_report(
                verified_report,
                contract,
                contract["capabilities"],
            )
            write_json(root / "host-compatibility-report.json", {
                "contractId": contract["contractId"],
                "capabilityAssessments": [{
                    "capabilityId": "list-items",
                    "status": "requires-host-integration",
                }],
            })
            incompatible_matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                verified_records,
                workflow_records,
                live,
                legacy=False,
            )

        unverified_row = unverified_matrix["capabilities"][0]
        self.assertFalse(unverified_row["status"]["hostVerified"])
        self.assertTrue(unverified_row["status"]["requiresReview"])
        self.assertIn("host-verification-pending", unverified_row["reasons"])
        incompatible_row = incompatible_matrix["capabilities"][0]
        self.assertFalse(incompatible_row["status"]["hostVerified"])
        self.assertTrue(incompatible_row["status"]["requiresReview"])
        self.assertIn("host-not-fully-compatible", incompatible_row["reasons"])

    def test_live_evidence_only_promotes_the_matching_capability(self) -> None:
        contract = canonical([capability("list-items"), capability("read-item")])
        input_payload = {"name": "list_items", "arguments": {}}
        result_payload = mcp_success({"items": []})
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [
                capability_report(
                    "list-items",
                    input_hash=FINALIZER.digest_json(input_payload),
                    result_hash=FINALIZER.digest_json(result_payload),
                ),
                capability_report("read-item"),
            ],
            "workflows": [],
        }
        _, _, capability_records, workflow_records = FINALIZER._read_report(
            report, contract, contract["capabilities"]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "capability-bundle.json", {
                "recordingId": "fictional-catalog",
                "capabilities": contract["capabilities"],
            })
            write_json(root / "input.json", {
                "capabilityId": "list-items",
                "input": input_payload,
            })
            write_json(root / "result.json", {
                "capabilityId": "list-items",
                "result": result_payload,
            })
            live = FINALIZER._read_live_evidence(
                [root / "input.json"],
                [root / "result.json"],
                contract["capabilities"],
                legacy=False,
            )
            mismatched_records = copy.deepcopy(capability_records)
            mismatched_records["list-items"]["runtime"][1][0]["resultHash"] = (
                evidence_hash("different-live-result")
            )
            with self.assertRaisesRegex(
                FINALIZER.FinalizationError,
                "runtime evidence hashes do not match",
            ):
                FINALIZER._build_matrix(
                    root,
                    contract,
                    contract["capabilities"],
                    mismatched_records,
                    workflow_records,
                    live,
                    legacy=False,
                )
            matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                workflow_records,
                live,
                legacy=False,
            )
        status_by_id = {
            item["capabilityId"]: item["status"] for item in matrix["capabilities"]
        }
        self.assertTrue(status_by_id["list-items"]["runtimeVerified"])
        self.assertFalse(status_by_id["list-items"]["requiresReview"])
        self.assertFalse(status_by_id["read-item"]["runtimeVerified"])
        self.assertTrue(status_by_id["read-item"]["requiresReview"])
        self.assertEqual(
            matrix["delivery"]["runtime"]["status"],
            "partially-verified",
        )
        self.assertEqual(FINALIZER._overall_decision(matrix), "partially-approved")

    def test_live_evidence_binds_tool_name_and_success_output_contract(self) -> None:
        contract = canonical([capability("list-items")])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            result_path = root / "result.json"

            def verify(tool_name: str, result_value: dict[str, Any]) -> dict[str, dict[str, Any]]:
                write_json(input_path, {
                    "capabilityId": "list-items",
                    "input": {"name": tool_name, "arguments": {}},
                })
                write_json(result_path, {
                    "capabilityId": "list-items",
                    "result": result_value,
                })
                return FINALIZER._read_live_evidence(
                    [input_path],
                    [result_path],
                    contract["capabilities"],
                    legacy=False,
                )

            valid_result = mcp_success({"items": []})
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "canonical Tool list_items"):
                verify("read_item", valid_result)
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "isError=false"):
                verify("list_items", {**valid_result, "isError": True})
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "missing required output path"):
                verify("list_items", mcp_success({}))
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "forbidden output key"):
                verify(
                    "list_items",
                    mcp_success({"items": [], "nested": {"error": "fictional failure"}}),
                )
            with self.assertRaisesRegex(FINALIZER.FinalizationError, "violates the Canonical outputSchema"):
                verify("list_items", mcp_success({"items": "not-an-array"}))

            evidence = verify("list_items", valid_result)
            self.assertEqual(evidence["list-items"]["status"], "passed")

    def test_live_evidence_validates_direct_and_jsonrpc_arguments(self) -> None:
        read_item = capability("read-item")
        read_item["inputs"] = [{
            "name": "itemId",
            "description": "A fictional item identifier.",
            "type": "string",
            "schema": {"type": "string", "pattern": r"^item-[0-9]+$"},
            "required": True,
            "evidenceRefs": ["fictional-input-contract"],
        }]
        contract = canonical([read_item])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            result_path = root / "result.json"
            write_json(result_path, {
                "capabilityId": "read-item",
                "result": mcp_success({"items": []}),
            })

            def verify(live_call: dict[str, Any]) -> dict[str, dict[str, Any]]:
                write_json(input_path, {
                    "capabilityId": "read-item",
                    "input": live_call,
                })
                return FINALIZER._read_live_evidence(
                    [input_path],
                    [result_path],
                    contract["capabilities"],
                    legacy=False,
                )

            direct = verify({
                "name": "read_item",
                "arguments": {"itemId": "item-42"},
            })
            self.assertEqual(direct["read-item"]["status"], "passed")
            jsonrpc = verify({
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "read_item",
                    "arguments": {"itemId": "item-73"},
                },
            })
            self.assertEqual(jsonrpc["read-item"]["status"], "passed")

            invalid_calls = [
                {"name": "read_item", "arguments": {}},
                {"name": "read_item", "arguments": {"itemId": 42}},
                {"name": "read_item", "arguments": {"itemId": "wrong"}},
                {
                    "name": "read_item",
                    "arguments": {"itemId": "item-42", "unexpected": True},
                },
                {
                    "method": "tools/call",
                    "params": {
                        "name": "read_item",
                        "arguments": {"itemId": "item-42", "unexpected": True},
                    },
                },
            ]
            for live_call in invalid_calls:
                with self.subTest(live_call=live_call), self.assertRaisesRegex(
                    FINALIZER.FinalizationError,
                    "violates the Canonical inputSchema",
                ):
                    verify(live_call)
            with self.assertRaisesRegex(
                FINALIZER.FinalizationError,
                "must contain object arguments",
            ):
                verify({"name": "read_item"})
            with self.assertRaisesRegex(
                FINALIZER.FinalizationError,
                "method=tools/call",
            ):
                verify({
                    "jsonrpc": "2.0",
                    "id": 8,
                    "method": "resources/read",
                    "params": {
                        "name": "read_item",
                        "arguments": {"itemId": "item-42"},
                    },
                })

    def test_write_requires_live_host_and_zero_dispatch_bypass_evidence(self) -> None:
        workflow = {
            "workflowId": "publish-item-safely",
            "entryCapabilityId": "publish-item",
        }
        contract = canonical([
            capability(
                "publish-item",
                "create",
                workflow_id="publish-item-safely",
            )
        ], [workflow])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [capability_report("publish-item")],
            "workflows": [{
                "workflowId": "publish-item-safely",
                "bypass": {
                    "status": "passed",
                    "checks": [check("publish-bypass", zero_external_writes=True)],
                },
                "runtime": {
                    "status": "passed",
                    "checks": [runtime_check("publish-item", label="workflow-runtime")],
                },
                "host": {"status": "passed", "checks": [check("workflow-host")]},
            }],
        }
        _, _, capability_records, workflow_records = FINALIZER._read_report(
            report, contract, contract["capabilities"]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "capability-bundle.json", {
                "recordingId": "fictional-publishing",
                "capabilities": contract["capabilities"],
            })
            write_json(root / "host-compatibility-report.json", {
                "contractId": contract["contractId"],
                "capabilityAssessments": [{
                    "capabilityId": "publish-item",
                    "status": "enabled",
                }],
            })
            failed_live = {
                "publish-item": {
                    "status": "failed",
                    "isError": True,
                    "inputHash": evidence_hash("input"),
                    "resultHash": evidence_hash("result"),
                }
            }
            matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                workflow_records,
                failed_live,
                legacy=False,
            )
            successful_live = {
                "publish-item": {
                    "status": "passed",
                    "isError": False,
                    "inputHash": evidence_hash("publish-item-live-input"),
                    "resultHash": evidence_hash("publish-item-live-result"),
                }
            }
            approved_matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                workflow_records,
                successful_live,
                legacy=False,
            )
            runtime_pending_report = copy.deepcopy(report)
            runtime_pending_report["workflows"][0]["runtime"] = {
                "status": "not-run",
                "checks": [],
            }
            _, _, _, runtime_pending_workflows = FINALIZER._read_report(
                runtime_pending_report, contract, contract["capabilities"]
            )
            runtime_pending_matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                runtime_pending_workflows,
                successful_live,
                legacy=False,
            )
            host_pending_report = copy.deepcopy(report)
            host_pending_report["workflows"][0]["host"] = {
                "status": "not-run",
                "checks": [],
            }
            _, _, _, host_pending_workflows = FINALIZER._read_report(
                host_pending_report, contract, contract["capabilities"]
            )
            host_pending_matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                host_pending_workflows,
                successful_live,
                legacy=False,
            )
            failed_runtime_report = copy.deepcopy(report)
            failed_runtime_report["workflows"][0]["runtime"] = {
                "status": "failed",
                "checks": [check("workflow-runtime-failed")],
            }
            _, _, _, failed_runtime_workflows = FINALIZER._read_report(
                failed_runtime_report, contract, contract["capabilities"]
            )
            failed_runtime_matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                failed_runtime_workflows,
                successful_live,
                legacy=False,
            )
        capability_status = matrix["capabilities"][0]["status"]
        workflow_status = matrix["workflows"][0]["status"]
        self.assertTrue(workflow_status["bypassVerified"])
        self.assertFalse(capability_status["runtimeVerified"])
        self.assertTrue(capability_status["requiresReview"])
        self.assertEqual(FINALIZER._overall_decision(matrix), "requires-review")
        self.assertFalse(approved_matrix["capabilities"][0]["status"]["requiresReview"])
        self.assertEqual(FINALIZER._overall_decision(approved_matrix), "approved")
        pending_workflow_status = runtime_pending_matrix["workflows"][0]["status"]
        self.assertTrue(pending_workflow_status["bypassVerified"])
        self.assertFalse(pending_workflow_status["runtimeVerified"])
        self.assertTrue(pending_workflow_status["requiresReview"])
        self.assertFalse(runtime_pending_matrix["capabilities"][0]["status"]["runtimeVerified"])
        self.assertTrue(runtime_pending_matrix["capabilities"][0]["status"]["requiresReview"])
        host_pending_status = host_pending_matrix["workflows"][0]["status"]
        self.assertTrue(host_pending_status["bypassVerified"])
        self.assertTrue(host_pending_status["runtimeVerified"])
        self.assertFalse(host_pending_status["hostVerified"])
        self.assertTrue(host_pending_status["requiresReview"])
        self.assertTrue(host_pending_matrix["capabilities"][0]["status"]["requiresReview"])
        failed_workflow_status = failed_runtime_matrix["workflows"][0]["status"]
        self.assertTrue(failed_workflow_status["blocked"])
        self.assertFalse(failed_workflow_status["bypassVerified"])
        self.assertFalse(failed_workflow_status["runtimeVerified"])
        self.assertFalse(failed_workflow_status["hostVerified"])
        self.assertFalse(failed_runtime_matrix["capabilities"][0]["status"]["runtimeVerified"])

        report["workflows"][0]["bypass"]["checks"][0]["zeroExternalWrites"] = False
        with self.assertRaisesRegex(FINALIZER.FinalizationError, "zeroExternalWrites=true"):
            FINALIZER._read_report(report, contract, contract["capabilities"])

    def test_backend_authoritative_write_can_be_approved_without_workflow(self) -> None:
        write = capability("save-item-draft", "update")
        contract = canonical([write])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [capability_report("save-item-draft")],
            "workflows": [],
        }
        _, _, capability_records, workflow_records = FINALIZER._read_report(
            report,
            contract,
            contract["capabilities"],
        )
        live = {
            "save-item-draft": {
                "status": "passed",
                "isError": False,
                "inputHash": evidence_hash("save-item-draft-live-input"),
                "resultHash": evidence_hash("save-item-draft-live-result"),
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "capability-bundle.json", {
                "recordingId": "fictional-draft-save",
                "capabilities": contract["capabilities"],
            })
            matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                workflow_records,
                live,
                legacy=False,
            )

        status = matrix["capabilities"][0]["status"]
        self.assertTrue(status["behaviorVerified"])
        self.assertTrue(status["runtimeVerified"])
        self.assertTrue(status["hostVerified"])
        self.assertFalse(status["requiresReview"])
        self.assertNotIn(
            "constrained-workflow-missing",
            matrix["capabilities"][0]["reasons"],
        )
        self.assertEqual(matrix["workflows"], [])
        self.assertEqual(FINALIZER._overall_decision(matrix), "approved")

    def test_workflow_host_verification_requires_every_member_capability(self) -> None:
        workflow_id = "publish-fictional-item-safely"
        prepare = capability("prepare-fictional-item")
        publish = capability(
            "publish-fictional-item",
            "create",
            workflow_id=workflow_id,
        )
        workflow = {
            "workflowId": workflow_id,
            "entryCapabilityId": publish["capabilityId"],
            "capabilityIds": [prepare["capabilityId"], publish["capabilityId"]],
        }
        contract = canonical([prepare, publish], [workflow])
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "partial",
            "checks": [check("global")],
            "capabilities": [
                capability_report(prepare["capabilityId"]),
                capability_report(publish["capabilityId"]),
            ],
            "workflows": [{
                "workflowId": workflow_id,
                "bypass": {
                    "status": "passed",
                    "checks": [check("workflow-bypass", zero_external_writes=True)],
                },
                "runtime": {
                    "status": "passed",
                    "checks": [runtime_check(
                        publish["capabilityId"],
                        label="workflow-runtime",
                    )],
                },
                "host": {
                    "status": "passed",
                    "checks": [check("workflow-host")],
                },
            }],
        }
        _, _, capability_records, workflow_records = FINALIZER._read_report(
            report,
            contract,
            contract["capabilities"],
        )
        live = {
            capability_id: {
                "status": "passed",
                "isError": False,
                "inputHash": evidence_hash(f"{capability_id}-live-input"),
                "resultHash": evidence_hash(f"{capability_id}-live-result"),
            }
            for capability_id in (prepare["capabilityId"], publish["capabilityId"])
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "capability-bundle.json", {
                "recordingId": "fictional-multi-capability-workflow",
                "capabilities": contract["capabilities"],
            })
            write_json(root / "host-compatibility-report.json", {
                "contractId": contract["contractId"],
                "capabilityAssessments": [
                    {
                        "capabilityId": prepare["capabilityId"],
                        "status": "disabled",
                    },
                    {
                        "capabilityId": publish["capabilityId"],
                        "status": "enabled",
                    },
                ],
            })
            matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                workflow_records,
                live,
                legacy=False,
            )

        workflow_status = matrix["workflows"][0]["status"]
        self.assertFalse(workflow_status["hostVerified"])
        self.assertTrue(workflow_status["requiresReview"])
        self.assertIn(
            "host-not-fully-compatible",
            matrix["workflows"][0]["reasons"],
        )

    def test_initial_and_canonical_blocking_reasons_cannot_be_upgraded(self) -> None:
        contract = canonical([capability("list-items")])
        contract["conflicts"] = [{
            "conflictId": "canonical-disagreement",
            "status": "unresolved",
            "affectedCapabilityIds": ["list-items"],
        }]
        report = {
            "schemaVersion": "vNext",
            "contractId": contract["contractId"],
            "status": "passed",
            "checks": [check("global")],
            "capabilities": [capability_report("list-items")],
            "workflows": [],
        }
        _, _, capability_records, workflow_records = FINALIZER._read_report(
            report, contract, contract["capabilities"]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "capability-bundle.json", {
                "recordingId": "fictional-catalog",
                "capabilities": contract["capabilities"],
            })
            write_json(root / "verification-matrix.json", {
                "schemaVersion": "vNext",
                "contractId": contract["contractId"],
                "capabilities": [{
                    "capabilityId": "list-items",
                    "status": {
                        "generated": True,
                        "behaviorVerified": False,
                        "runtimeVerified": False,
                        "hostVerified": False,
                        "requiresReview": True,
                        "blocked": False,
                    },
                    "reasons": [
                        "policy-blocked-by-fictional-source",
                        "unresolved-conflict:initial-disagreement",
                        "behavior-verification-pending",
                        "runtime-verification-pending",
                    ],
                    "checks": [],
                }],
                "workflows": [],
            })
            matrix = FINALIZER._build_matrix(
                root,
                contract,
                contract["capabilities"],
                capability_records,
                workflow_records,
                {
                    "list-items": {
                        "status": "passed",
                        "isError": False,
                        "inputHash": evidence_hash("list-items-live-input"),
                        "resultHash": evidence_hash("list-items-live-result"),
                    }
                },
                legacy=False,
            )
        row = matrix["capabilities"][0]
        self.assertTrue(row["status"]["behaviorVerified"])
        self.assertTrue(row["status"]["runtimeVerified"])
        self.assertTrue(row["status"]["requiresReview"])
        self.assertIn("policy-blocked-by-fictional-source", row["reasons"])
        self.assertIn("unresolved-conflict:initial-disagreement", row["reasons"])
        self.assertIn("unresolved-conflict:canonical-disagreement", row["reasons"])

    def test_partial_finalization_still_returns_final_validator_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_base(root)
            contract = install_complete_readonly_vnext(candidate)
            report = {
                "schemaVersion": "vNext",
                "contractId": contract["contractId"],
                "status": "partial",
                "checks": [check("global")],
                "capabilities": [{
                    **capability_report("list-knowledge-topics"),
                    "runtime": {"status": "not-run", "checks": []},
                }],
                "workflows": [],
            }
            write_json(root / "report.json", report)
            write_json(root / "input.json", {
                "capabilityId": "list-knowledge-topics",
                "input": {"name": "list_knowledge_topics", "arguments": {}},
            })
            write_json(root / "result.json", {
                "capabilityId": "list-knowledge-topics",
                "result": mcp_success({"topics": []}),
            })
            arguments = Namespace(
                artifact_root=candidate,
                verification_report=root / "report.json",
                live_input=[root / "input.json"],
                live_result=[root / "result.json"],
                source_root=REPO_ROOT,
                source_map=[],
            )
            initial_matrix = (candidate / "verification-matrix.json").read_bytes()
            validator_runs = [
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 9),
            ]
            with patch.object(FINALIZER, "parse_args", return_value=arguments), patch.object(
                FINALIZER.subprocess, "run", side_effect=validator_runs
            ) as run_validator:
                return_code = FINALIZER.main()
            self.assertFalse((candidate / "approval-audit.json").exists())
            self.assertFalse((candidate / "live-verification.json").exists())
            self.assertEqual(
                (candidate / "verification-matrix.json").read_bytes(),
                initial_matrix,
            )
        self.assertEqual(return_code, 9)
        self.assertEqual(run_validator.call_count, 2)
        self.assertIn("--pre-finalize", run_validator.call_args_list[0].args[0])
        self.assertNotIn("--pre-finalize", run_validator.call_args_list[1].args[0])

    def test_vnext_cli_writes_exact_approved_matrix_for_one_read_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = create_base(root)
            contract = install_complete_readonly_vnext(candidate)
            input_payload = {"name": "list_knowledge_topics", "arguments": {}}
            result_payload = mcp_success({"topics": []})
            report = {
                "schemaVersion": "vNext",
                "contractId": contract["contractId"],
                "status": "passed",
                "checks": [check("global")],
                "capabilities": [capability_report(
                    "list-knowledge-topics",
                    input_hash=FINALIZER.digest_json(input_payload),
                    result_hash=FINALIZER.digest_json(result_payload),
                )],
                "workflows": [],
            }
            write_json(root / "report.json", report)
            write_json(root / "input.json", {
                "capabilityId": "list-knowledge-topics",
                "input": input_payload,
            })
            write_json(root / "result.json", {
                "capabilityId": "list-knowledge-topics",
                "result": result_payload,
            })
            result = subprocess.run([
                sys.executable,
                str(FINALIZER_PATH),
                str(candidate),
                "--verification-report",
                str(root / "report.json"),
                "--live-input",
                str(root / "input.json"),
                "--live-result",
                str(root / "result.json"),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            matrix = json.loads((candidate / "verification-matrix.json").read_text())
            approval = json.loads((candidate / "approval-audit.json").read_text())
        self.assertEqual(matrix["schemaVersion"], "vNext")
        self.assertEqual(matrix["contractId"], contract["contractId"])
        self.assertEqual(
            [item["capabilityId"] for item in matrix["capabilities"]],
            ["list-knowledge-topics"],
        )
        self.assertEqual(matrix["workflows"], [])
        self.assertTrue(matrix["capabilities"][0]["status"]["behaviorVerified"])
        self.assertTrue(matrix["capabilities"][0]["status"]["runtimeVerified"])
        self.assertEqual(matrix["delivery"], {
            "functionCore": {"status": "generated"},
            "mcpServer": {"status": "generated"},
            "skill": {"status": "generated"},
            "runtime": {"status": "verified"},
            "deployment": {"status": "not-deployed"},
        })
        self.assertEqual(approval["decision"], "approved")


if __name__ == "__main__":
    unittest.main()
