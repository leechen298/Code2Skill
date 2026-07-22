from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill"
SCRIPTS = SKILL_ROOT / "scripts"
ASSETS = SKILL_ROOT / "assets"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from contract_model import (  # noqa: E402
    derive_bundle,
    derive_consumer_requirements,
    derive_host_compatibility,
    evaluate_goal_state,
    json_schema_errors,
    validate_canonical_contract,
    validate_source_topology,
    write_evidence_complete,
)
from validate_vnext import validate_vnext_artifacts  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain an object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Diagnostics:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")


def agent_policy() -> dict[str, bool]:
    return {
        "acceptInformationInAnyOrder": True,
        "reuseFreshInformation": True,
        "askOnlyCurrentlyMissing": True,
        "skipUnnecessaryCapabilities": True,
        "stopWhenPredicateSatisfied": True,
    }


def goal_state(value: Any, *, fresh: bool = True, present: bool | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {"__goalState": True, "value": value, "fresh": fresh}
    if fresh:
        state["acquiredNow"] = True
    if present is not None:
        state["present"] = present
    return state


def selection_state(requires_attachment: bool, *, fresh: bool = True) -> dict[str, Any]:
    return goal_state({
        "grantId": "synthetic-selection-grant",
        "requiresAttachment": requires_attachment,
        "allowsAttachment": True,
    }, fresh=fresh)


def validation_state() -> dict[str, Any]:
    return goal_state({
        "grantId": "synthetic-validation-grant",
        "payloadDigest": "synthetic-payload-digest",
    })


def one_capability_model(capability_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    topology = read_json(ASSETS / "source-topology.json")
    contract = read_json(ASSETS / "canonical-contract.json")
    capability = next(
        copy.deepcopy(item)
        for item in contract["capabilities"]
        if item["capabilityId"] == capability_id
    )
    output_path = copy.deepcopy(capability["outputs"][0]["path"])
    output_type = capability["outputs"][0]["type"]
    output_schema = copy.deepcopy(capability["outputs"][0].get("schema"))
    contract["conflicts"] = []
    contract["capabilities"] = [capability]
    contract["handoffs"] = []
    contract["capabilityGraph"] = {
        "nodes": [{"capabilityId": capability_id, "independentValue": "Complete one synthetic partial goal."}],
        "edges": [],
    }
    contract["goals"] = [{
        "goalId": f"use-{capability_id}",
        "intent": "Complete one synthetic goal without inheriting an unrelated page transcript.",
        "informationNeeds": [{
            "informationId": "result",
            "classification": "required",
            "type": output_type,
            **({"schema": output_schema} if isinstance(output_schema, dict) else {}),
            "satisfiedBy": [{
                "kind": "capability",
                "capabilityId": capability_id,
                "outputPath": output_path,
            }],
        }],
        "completionPredicate": {
            "operator": "all-satisfied",
            "informationIds": ["result"],
        },
        "requiredCapabilityIds": [capability_id],
        "conditionalCapabilityIds": [],
        "optionalCapabilityIds": [],
        "agentPolicy": agent_policy(),
    }]
    contract["workflows"] = [
        workflow
        for workflow in contract["workflows"]
        if workflow["entryCapabilityId"] == capability_id
    ]
    return topology, contract


def rewrite_locator_suffixes(contract: dict[str, Any], suffixes: dict[str, str]) -> None:
    counters: dict[str, int] = {}
    for evidence in contract["evidenceCatalog"]:
        source_id = evidence["sourceId"]
        suffix = suffixes[source_id]
        counters[source_id] = counters.get(source_id, 0) + 1
        symbol = evidence["locator"].split("#", 1)[-1]
        evidence["locator"] = f"synthetic/{counters[source_id]}/contract{suffix}#{symbol}"


def independent_service_worker_model() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a service-scoped model without copying the sample request fixture."""

    source_id = "fictional-worker-source"
    evidence_ids = {
        "backendContract": "ev-fictional-worker-contract",
        "authorization": "ev-fictional-worker-authorization",
        "validation": "ev-fictional-worker-validation",
        "idempotency": "ev-fictional-worker-idempotency",
        "unknownOutcome": "ev-fictional-worker-outcome",
        "response": "ev-fictional-worker-response",
    }
    capability_id = "enqueue-fictional-job"
    topology = {
        "schemaVersion": "vNext",
        "topologyId": "fictional-worker-topology",
        "authorizationBoundary": {
            "discoveryPolicy": "explicit-roots-only",
            "machineWideDiscovery": False,
            "portableLocatorsOnly": True,
        },
        "sources": [{
            "sourceId": source_id,
            "semanticRoles": [
                "explicit-operation",
                "authorization",
                "business-rule",
                "idempotency",
                "unknown-outcome",
                "transport-contract",
            ],
            "root": ".",
            "availability": "available",
            "searched": True,
        }],
        "missingSources": [],
    }
    contract = {
        "schemaVersion": "vNext",
        "contractId": "fictional-worker-contract",
        "recordingId": "fictional-worker-analysis",
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
            "primaryEvidenceRole": "explicitly-scoped-service-feature",
            "backendEvidenceRole": "supplement-and-verify",
            "inclusionRule": "explicitly-scoped-surface",
            "serviceSourceIds": [source_id],
            "supplementarySourceIds": [],
        },
        "conflicts": [],
        "evidenceCatalog": [
            {
                "evidenceId": evidence_ids[category],
                "sourceId": source_id,
                "locator": f"workers/enqueue_job.ex#{category}",
                "semanticRole": role,
                "assertionLevel": "fact",
            }
            for category, role in {
                "backendContract": "explicit-operation",
                "authorization": "authorization",
                "validation": "business-rule",
                "idempotency": "idempotency",
                "unknownOutcome": "unknown-outcome",
                "response": "transport-contract",
            }.items()
        ],
        "server": {
            "name": "fictional-worker-capabilities",
            "description": "A synthetic explicitly scoped worker operation.",
            "evidenceRefs": [evidence_ids["backendContract"]],
        },
        "capabilities": [{
            "capabilityId": capability_id,
            "toolName": "enqueue_fictional_job",
            "functionExport": "enqueueFictionalJob",
            "description": "Enqueue one fictional background job.",
            "authentication": "runtime_context",
            "readiness": "ready",
            "missingEvidence": [],
            "exposure": {
                "kind": "explicitly-scoped-operation",
                "evidenceRefs": [evidence_ids["backendContract"]],
                "supplementalEvidenceRefs": [],
            },
            "inputs": [{
                "name": "jobPayload",
                "description": "Synthetic JSON job payload.",
                "type": "object",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "jobKind": {"type": "string"},
                        "priority": {"type": "integer"},
                    },
                    "required": ["jobKind"],
                },
                "required": True,
                "informationClass": "required",
                "sourceStrategies": ["user", "trusted-host-context"],
                "valueDomain": {"kind": "unconstrained"},
                "requiredWhen": [],
                "forbiddenWhen": [],
                "evidenceRefs": [evidence_ids["backendContract"]],
            }],
            "outputs": [{
                "path": ["jobId"],
                "type": "string",
                "description": "Source-issued job identifier.",
                "valueDomain": {"kind": "unconstrained"},
                "evidenceRefs": [evidence_ids["response"]],
            }],
            "constraints": [],
            "attachments": {"mode": "none"},
            "implementation": {"kind": "local"},
            "successRule": {
                "kind": "output",
                "outputRequired": True,
                "forbiddenOutputKeys": ["error"],
                "requiredOutputPaths": [["jobId"]],
                "evidenceRefs": [evidence_ids["response"]],
            },
            "errorContract": {
                "format": "structured",
                "preservesRecoveryContext": True,
                "codePath": ["code"],
                "messagePath": ["message"],
                "detailsPath": ["details"],
                "retryabilityPath": ["retryable"],
                "defaultRetryable": False,
                "evidenceRefs": [evidence_ids["unknownOutcome"]],
            },
            "operationPolicy": {
                "sideEffect": "create",
                "idempotency": "idempotent",
                "automaticRetry": "never",
                "confirmation": "not-required",
                "unknownOutcome": "stop-and-reconcile",
            },
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "runtimeProtection": {
                "mode": "backend-authoritative",
                "owner": "target-api",
                "evidenceRefs": list(evidence_ids.values()),
            },
            "sideEffect": "create",
            "hostRequirements": [
                "agent-skills-discovery",
                "mcp-tool-invocation",
                "authentication-injection",
                "unknown-outcome-reconciliation",
            ],
            "evidenceCoverage": {
                "sideEffect": {
                    "declaredSideEffect": "create",
                    "assertionLevel": "fact",
                    "evidenceRefs": [evidence_ids["backendContract"]],
                },
                **{
                    category: {
                        "assertionLevel": "fact",
                        "evidenceRefs": [evidence_ids[category]],
                    }
                    for category in (
                        "backendContract",
                        "authorization",
                        "validation",
                        "idempotency",
                        "unknownOutcome",
                    )
                },
            },
            "verificationChecks": ["worker-contract-vector"],
            "evidenceRefs": list(evidence_ids.values()),
        }],
        "handoffs": [],
        "capabilityGraph": {
            "nodes": [{
                "capabilityId": capability_id,
                "independentValue": "Enqueue one explicitly scoped fictional job.",
            }],
            "edges": [],
        },
        "goals": [{
            "goalId": "enqueue-fictional-job",
            "intent": "Enqueue one job when its payload is known.",
            "informationNeeds": [{
                "informationId": "job-payload",
                "classification": "required",
                "type": "object",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "jobKind": {"type": "string"},
                        "priority": {"type": "integer"},
                    },
                    "required": ["jobKind"],
                },
                "satisfiedBy": [{"kind": "user"}],
                "supplies": [{
                    "capabilityId": capability_id,
                    "inputName": "jobPayload",
                    "mappingKind": "direct",
                }],
            }, {
                "informationId": "queued-job",
                "classification": "derived",
                "type": "string",
                "satisfiedBy": [{
                    "kind": "capability",
                    "capabilityId": capability_id,
                    "outputPath": ["jobId"],
                }],
                "reuseWhile": {
                    "sameSubject": True,
                    "evidenceRefs": [evidence_ids["idempotency"]],
                },
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["job-payload", "queued-job"],
            },
            "requiredCapabilityIds": [capability_id],
            "conditionalCapabilityIds": [],
            "optionalCapabilityIds": [],
            "agentPolicy": agent_policy(),
        }],
        "consumerRequirements": {"requirements": [
            {
                "requirementId": "agent-skills-discovery",
                "hostCapability": "agentSkillsDiscovery",
                "description": "Discover portable goal and recovery guidance.",
                "onMissing": "requires-host-integration",
            },
            {
                "requirementId": "mcp-tool-invocation",
                "hostCapability": "mcpToolInvocation",
                "description": "Invoke the declared Tool and preserve structured results.",
                "onMissing": "disable",
            },
            {
                "requirementId": "authentication-injection",
                "hostCapability": "authenticationInjection",
                "description": "Inject current identity outside public Tool arguments.",
                "onMissing": "disable",
            },
            {
                "requirementId": "unknown-outcome-reconciliation",
                "hostCapability": "unknownOutcomeReconciliation",
                "description": "Reconcile uncertain job enqueue outcomes before a later attempt.",
                "onMissing": "disable",
            },
        ]},
        "workflows": [],
    }
    return topology, contract


class CrossArchitectureProductScenarioTest(unittest.TestCase):
    def test_portable_schema_runtime_enforces_common_bounds(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "label": {"type": "string", "minLength": 2, "maxLength": 5},
                "score": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 2,
                    "uniqueItems": True,
                },
                "kind": {"type": "string", "const": "synthetic"},
                "resource": {"type": "string", "format": "uri"},
            },
            "required": ["label", "score", "tags", "kind", "resource"],
        }
        valid = {
            "label": "okay",
            "score": 1,
            "tags": ["a", "b"],
            "kind": "synthetic",
            "resource": "https://synthetic.example/resource/1",
        }
        invalid = {
            "label": "x",
            "score": 0,
            "tags": ["a", "a", "b"],
            "kind": "wrong",
            "resource": "not an absolute uri",
        }

        self.assertEqual(json_schema_errors(valid, schema), [])
        errors = json_schema_errors(invalid, schema)
        self.assertTrue(any("minLength" in item for item in errors), errors)
        self.assertTrue(any("exclusiveMinimum" in item for item in errors), errors)
        self.assertTrue(any("maxItems" in item for item in errors), errors)
        self.assertTrue(any("unique" in item for item in errors), errors)
        self.assertTrue(any("const" in item for item in errors), errors)
        self.assertTrue(any("absolute URI" in item for item in errors), errors)

    def assert_model_valid(self, topology: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
        source_ids = validate_source_topology(topology)
        validate_canonical_contract(contract, source_ids)
        bundle = derive_bundle(contract)
        self.assertEqual(bundle["featureBoundary"], contract["featureBoundary"])
        self.assertEqual(
            [item["capabilityId"] for item in bundle["capabilities"]],
            [item["capabilityId"] for item in contract["capabilities"]],
        )
        return bundle

    def test_three_structurally_different_synthetic_features_share_one_contract_model(self) -> None:
        # Case A: a client-local, read-only catalog with no HTTP operation.
        local_topology, local_contract = one_capability_model("list-sample-request-kinds")
        local = local_contract["capabilities"][0]
        local["exposure"]["kind"] = "client-local-behavior"
        local["implementation"] = {"kind": "local"}
        local["successRule"]["kind"] = "output"
        local["outputs"][0]["valueDomain"] = {
            "kind": "static",
            "values": ["synthetic-a", "synthetic-b"],
        }
        local_evidence = next(
            item
            for item in local_contract["evidenceCatalog"]
            if item["evidenceId"] == local["exposure"]["evidenceRefs"][0]
        )
        local_evidence["semanticRole"] = "client-local-behavior"
        rewrite_locator_suffixes(local_contract, {
            "sample-client": ".svelte",
            "sample-service": ".ex",
            "sample-contract": ".json",
            "sample-tests": ".feature",
        })
        local_bundle = self.assert_model_valid(local_topology, local_contract)
        self.assertEqual(local_bundle["capabilities"][0]["implementation"]["kind"], "local")

        # Case B: an ordinary client-observed write whose business validation
        # remains authoritative in a separately implemented target API.
        write_topology, write_contract = one_capability_model("save-sample-draft")
        rewrite_locator_suffixes(write_contract, {
            "sample-client": ".tsx",
            "sample-service": ".py",
            "sample-contract": ".graphql",
            "sample-tests": ".spec.rb",
        })
        write_bundle = self.assert_model_valid(write_topology, write_contract)
        write = write_bundle["capabilities"][0]
        self.assertEqual(write["runtimeProtection"]["mode"], "backend-authoritative")
        self.assertEqual(write["operationPolicy"]["confirmation"], "not-required")
        self.assertEqual(write_contract["workflows"], [])
        self.assertEqual(write["errorContract"]["format"], "structured")

        # Case C: a multi-capability feature with dynamic values, approved
        # attachments, an ordinary save, and a truly non-bypassable final write.
        complex_topology = read_json(ASSETS / "source-topology.json")
        complex_contract = read_json(ASSETS / "canonical-contract.json")
        rewrite_locator_suffixes(complex_contract, {
            "sample-client": ".vue",
            "sample-service": ".java",
            "sample-contract": ".proto",
            "sample-tests": ".test.go",
        })
        complex_bundle = self.assert_model_valid(complex_topology, complex_contract)
        self.assertGreaterEqual(len(complex_bundle["capabilities"]), 5)
        self.assertTrue(any(
            item.get("attachments", {}).get("uploadOwner") == "business-tool"
            for item in complex_bundle["capabilities"]
        ))
        self.assertEqual(
            {
                item["runtimeProtection"]["mode"]
                for item in complex_bundle["capabilities"]
                if item["sideEffect"] != "read"
            },
            {"backend-authoritative", "deterministic-workflow"},
        )

    def test_client_visible_read_semantics_do_not_require_backend_internal_side_effect_proof(self) -> None:
        _, contract = one_capability_model("list-sample-request-kinds")
        capability = contract["capabilities"][0]
        client_invocation = capability["exposure"]["evidenceRefs"][0]
        capability["evidenceCoverage"]["sideEffect"] = {
            "declaredSideEffect": "read",
            "assertionLevel": "fact",
            "evidenceRefs": [client_invocation],
        }

        self.assertTrue(write_evidence_complete(capability, contract))

        neighboring_write_ref = "ev-client-submit-call"
        capability["evidenceCoverage"]["sideEffect"]["evidenceRefs"] = [
            neighboring_write_ref
        ]
        capability["evidenceRefs"].append(neighboring_write_ref)
        self.assertFalse(write_evidence_complete(capability, contract))

    def test_contract_discovery_does_not_require_dto_controller_or_service_names(self) -> None:
        topology, contract = one_capability_model("save-sample-draft")
        for source in topology["sources"]:
            source["semanticRoles"] = [
                role.replace("business-rule", "operation-policy")
                for role in source["semanticRoles"]
            ]
        declared_roles = {
            role.lower()
            for source in topology["sources"]
            for role in source["semanticRoles"]
        }
        for architecture_name in ("dto", "controller", "viewmodel", "repository-pattern"):
            self.assertNotIn(architecture_name, declared_roles)
        self.assert_model_valid(topology, contract)

    def test_explicit_service_worker_uses_an_independent_business_model(self) -> None:
        topology, contract = independent_service_worker_model()
        bundle = self.assert_model_valid(topology, contract)
        capability = bundle["capabilities"][0]

        self.assertEqual(contract["featureBoundary"]["primaryEvidenceRole"], "explicitly-scoped-service-feature")
        self.assertEqual(capability["implementation"]["kind"], "local")
        self.assertEqual(capability["runtimeProtection"]["mode"], "backend-authoritative")
        self.assertTrue(write_evidence_complete(contract["capabilities"][0], contract))
        self.assertEqual(capability["inputs"][0]["name"], "jobPayload")
        self.assertNotIn("sample", json.dumps(contract).lower())

    def test_independent_service_worker_passes_the_full_vnext_contract_validator(self) -> None:
        topology, contract = independent_service_worker_model()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            source_root = root / "authorized-worker-source"
            candidate.mkdir()
            source_root.mkdir()
            write_json(candidate / "source-topology.json", topology)
            write_json(candidate / "canonical-contract.json", contract)
            host_capabilities = {
                requirement["hostCapability"]: {"status": "supported"}
                for requirement in contract["consumerRequirements"]["requirements"]
            }
            write_json(candidate / "host-profile.json", {
                "schemaVersion": "vNext",
                "profileId": "fictional-worker-host",
                "description": "A generic synthetic Host for an explicitly scoped worker operation.",
                "capabilities": host_capabilities,
            })
            for evidence in contract["evidenceCatalog"]:
                relative = Path(evidence["locator"].split("#", 1)[0])
                evidence_file = source_root / relative
                evidence_file.parent.mkdir(parents=True, exist_ok=True)
                evidence_file.write_text("synthetic independent worker evidence\n", encoding="utf-8")
            derived = subprocess.run(
                [sys.executable, str(SCRIPTS / "derive_artifacts.py"), str(candidate)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(derived.returncode, 0, derived.stderr)
            diagnostics = Diagnostics()
            validate_vnext_artifacts(
                candidate,
                root / "unused-source-root",
                {"fictional-worker-source": source_root},
                True,
                diagnostics,
            )

        self.assertEqual(diagnostics.errors, [])

    def test_progressive_goal_completion_converges_for_different_information_orders(self) -> None:
        contract = read_json(ASSETS / "canonical-contract.json")
        goal = next(item for item in contract["goals"] if item["goalId"] == "prepare-sample-request")

        user_first = evaluate_goal_state(goal, {
            "request-data": goal_state({"subject": "synthetic"}),
        })
        self.assertEqual(user_first["askInformationIds"], [])
        self.assertIn("current-selection", user_first["missingInformationIds"])

        user_then_selection = evaluate_goal_state(goal, {
            "request-data": goal_state({"subject": "synthetic"}),
            "current-selection": selection_state(False),
        })
        self.assertEqual(user_then_selection["missingInformationIds"], ["validation-result"])
        self.assertEqual(user_then_selection["acquisitionCapabilityIds"], ["validate-sample-request"])

        selection_first = evaluate_goal_state(goal, {
            "current-selection": selection_state(False),
        })
        self.assertIn("request-data", selection_first["askInformationIds"])

        completed_a = evaluate_goal_state(goal, {
            "request-data": goal_state({"subject": "synthetic"}),
            "current-selection": selection_state(False),
            "validation-result": validation_state(),
        })
        completed_b = evaluate_goal_state(goal, {
            "validation-result": validation_state(),
            "current-selection": selection_state(False),
            "request-data": goal_state({"subject": "synthetic"}),
        })
        self.assertTrue(completed_a["complete"])
        self.assertEqual(completed_a, completed_b)
        self.assertEqual(completed_a["missingInformationIds"], [])
        self.assertEqual(completed_a["acquisitionCapabilityIds"], [])
        self.assertEqual(completed_a["askInformationIds"], [])

    def test_conditions_and_freshness_recompute_only_currently_missing_information(self) -> None:
        contract = read_json(ASSETS / "canonical-contract.json")
        goal = next(item for item in contract["goals"] if item["goalId"] == "prepare-sample-request")
        attachment_required = evaluate_goal_state(goal, {
            "request-data": goal_state({"subject": "synthetic"}),
            "current-selection": selection_state(True),
        })
        self.assertIn("approved-attachments", attachment_required["missingInformationIds"])
        self.assertIn("upload-sample-attachment", attachment_required["acquisitionCapabilityIds"])

        stale_selection = evaluate_goal_state(goal, {
            "request-data": goal_state({"subject": "synthetic"}),
            "current-selection": selection_state(True, fresh=False),
        })
        self.assertIn("current-selection", stale_selection["missingInformationIds"])
        self.assertIn("approved-attachments", stale_selection["pendingConditionalInformationIds"])
        self.assertNotIn("approved-attachments", stale_selection["missingInformationIds"])

    def test_unknown_optional_activation_dependency_cannot_false_complete(self) -> None:
        contract = read_json(ASSETS / "canonical-contract.json")
        goal = copy.deepcopy(next(
            item for item in contract["goals"] if item["goalId"] == "prepare-sample-request"
        ))
        selection = next(
            item for item in goal["informationNeeds"]
            if item["informationId"] == "current-selection"
        )
        selection["classification"] = "optional"
        state = evaluate_goal_state(goal, {
            "request-data": goal_state({"subject": "synthetic"}),
            "validation-result": validation_state(),
        })

        self.assertFalse(state["complete"])
        self.assertIn("current-selection", state["missingInformationIds"])
        self.assertIn("list-sample-request-kinds", state["acquisitionCapabilityIds"])
        self.assertIn("approved-attachments", state["pendingConditionalInformationIds"])

    def test_business_object_with_value_field_is_not_mistaken_for_state_wrapper(self) -> None:
        goal = {
            "goalId": "choose-synthetic-option",
            "informationNeeds": [{
                "informationId": "current-selection",
                "classification": "required",
                "type": "object",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {"type": "string"},
                        "value": {"type": "string"},
                        "present": {"type": "boolean"},
                        "fresh": {"type": "boolean"},
                        "requiresAttachment": {"type": "boolean"},
                    },
                    "required": [
                        "label",
                        "value",
                        "present",
                        "fresh",
                        "requiresAttachment",
                    ],
                },
                "satisfiedBy": [{"kind": "user"}],
            }, {
                "informationId": "approved-attachments",
                "classification": "requiredWhen",
                "type": "string",
                "condition": {
                    "path": ["current-selection", "requiresAttachment"],
                    "operator": "equals",
                    "value": True,
                },
                "satisfiedBy": [{
                    "kind": "capability",
                    "capabilityId": "upload-synthetic-attachment",
                }],
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["current-selection", "approved-attachments"],
            },
        }
        state = evaluate_goal_state(goal, {
            "current-selection": {
                "label": "Synthetic option",
                "value": "synthetic-option",
                "present": True,
                "fresh": False,
                "requiresAttachment": True,
            },
            "request-data": {"subject": "synthetic"},
        })

        self.assertNotIn("current-selection", state["missingInformationIds"])
        self.assertIn("approved-attachments", state["missingInformationIds"])
        self.assertIn("upload-synthetic-attachment", state["acquisitionCapabilityIds"])

    def test_schema_invalid_known_information_remains_missing(self) -> None:
        goal = {
            "goalId": "collect-schema-valid-payload",
            "informationNeeds": [{
                "informationId": "payload",
                "classification": "required",
                "type": "object",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"count": {"type": "integer", "minimum": 1}},
                    "required": ["count"],
                },
                "satisfiedBy": [{"kind": "user"}],
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["payload"],
            },
        }

        state = evaluate_goal_state(goal, {
            "payload": goal_state({"count": "not-an-integer"}),
        })

        self.assertFalse(state["complete"])
        self.assertEqual(state["invalidInformationIds"], ["payload"])
        self.assertEqual(state["missingInformationIds"], ["payload"])
        self.assertEqual(state["askInformationIds"], ["payload"])

    def test_cached_information_needs_reuse_proof_but_new_information_does_not(self) -> None:
        goal = {
            "goalId": "reuse-source-scoped-token",
            "informationNeeds": [{
                "informationId": "source-token",
                "classification": "required",
                "type": "string",
                "satisfiedBy": [{"kind": "user"}],
                "reuseWhile": {"sameSubject": True, "notExpired": True},
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["source-token"],
            },
        }
        cached_without_proof = {
            "__goalState": True,
            "value": "cached-token",
            "fresh": True,
        }
        cached_with_partial_proof = {
            **cached_without_proof,
            "reuseProof": {"sameSubject": True},
        }
        cached_with_full_proof = {
            **cached_without_proof,
            "reuseProof": {"sameSubject": True, "notExpired": True},
        }
        acquired_now = {
            **cached_without_proof,
            "acquiredNow": True,
        }

        for value in (cached_without_proof, cached_with_partial_proof):
            with self.subTest(value=value):
                state = evaluate_goal_state(goal, {"source-token": value})
                self.assertFalse(state["complete"])
                self.assertEqual(state["missingInformationIds"], ["source-token"])

        self.assertTrue(evaluate_goal_state(
            goal,
            {"source-token": cached_with_full_proof},
        )["complete"])
        self.assertTrue(evaluate_goal_state(
            goal,
            {"source-token": acquired_now},
        )["complete"])

    def test_missing_values_and_failed_workflow_markers_do_not_complete_a_goal(self) -> None:
        contract = read_json(ASSETS / "canonical-contract.json")
        prepare = next(item for item in contract["goals"] if item["goalId"] == "prepare-sample-request")
        missing_values = evaluate_goal_state(prepare, {
            "request-data": goal_state(None, present=True),
            "current-selection": selection_state(False),
            "validation-result": validation_state(),
        })
        self.assertFalse(missing_values["complete"])
        self.assertEqual(missing_values["askInformationIds"], ["request-data"])

        submit = next(item for item in contract["goals"] if item["goalId"] == "submit-sample-request")
        for marker in (False, "failed", {"status": "failed"}):
            state = evaluate_goal_state(submit, {
                "workflow:submit-sample-request": goal_state(marker),
            })
            self.assertFalse(state["complete"], marker)
        completed = evaluate_goal_state(submit, {
            "workflow:submit-sample-request": goal_state({"status": "completed"}),
        })
        self.assertTrue(completed["complete"])

    def test_any_satisfied_uses_only_the_predicate_information_ids(self) -> None:
        goal = {
            "goalId": "choose-one-result",
            "informationNeeds": [
                {
                    "informationId": "requested-result-a",
                    "classification": "required",
                    "satisfiedBy": [{"kind": "user"}],
                },
                {
                    "informationId": "unrelated-context",
                    "classification": "required",
                    "satisfiedBy": [{"kind": "trusted-host-context"}],
                },
            ],
            "completionPredicate": {
                "operator": "any-satisfied",
                "informationIds": ["requested-result-a"],
            },
        }
        unrelated_only = evaluate_goal_state(goal, {
            "unrelated-context": goal_state("known"),
        })
        self.assertFalse(unrelated_only["complete"])
        requested = evaluate_goal_state(goal, {
            "requested-result-a": goal_state("done"),
        })
        self.assertTrue(requested["complete"])

    def test_goal_state_separates_trusted_context_from_user_questions(self) -> None:
        contract = read_json(ASSETS / "canonical-contract.json")
        submit = next(
            item for item in contract["goals"]
            if item["goalId"] == "submit-sample-request"
        )

        state = evaluate_goal_state(submit, {})

        self.assertIn("trusted-confirmation", state["trustedContextInformationIds"])
        self.assertNotIn("trusted-confirmation", state["askInformationIds"])
        self.assertIn("request-data", state["askInformationIds"])

    def test_goal_state_exposes_capability_alternatives_without_fixing_a_transcript(self) -> None:
        goal = {
            "goalId": "lookup-through-one-provider",
            "informationNeeds": [{
                "informationId": "lookup-result",
                "classification": "required",
                "satisfiedBy": [
                    {"kind": "capability", "capabilityId": "lookup-primary"},
                    {"kind": "capability", "capabilityId": "lookup-fallback"},
                ],
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["lookup-result"],
            },
        }

        state = evaluate_goal_state(goal, {})

        self.assertEqual(state["acquisitionOptions"], [{
            "informationId": "lookup-result",
            "capabilityIds": ["lookup-primary", "lookup-fallback"],
            "selection": "one-compatible-provider",
        }])

    def test_goal_state_keeps_user_fallback_when_a_tool_is_also_available(self) -> None:
        goal = {
            "goalId": "lookup-or-explain",
            "informationNeeds": [{
                "informationId": "lookup-result",
                "classification": "required",
                "satisfiedBy": [
                    {"kind": "user"},
                    {"kind": "capability", "capabilityId": "lookup-service"},
                ],
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["lookup-result"],
            },
        }

        state = evaluate_goal_state(goal, {})

        self.assertEqual(state["askInformationIds"], ["lookup-result"])
        self.assertEqual(state["acquisitionCapabilityIds"], ["lookup-service"])

    def test_any_satisfied_stops_without_requesting_the_other_branch(self) -> None:
        goal = {
            "goalId": "one-of-two-results",
            "agentPolicy": {"stopWhenPredicateSatisfied": True},
            "informationNeeds": [
                {
                    "informationId": "result-a",
                    "classification": "required",
                    "satisfiedBy": [{"kind": "user"}],
                },
                {
                    "informationId": "result-b",
                    "classification": "required",
                    "satisfiedBy": [{"kind": "capability", "capabilityId": "lookup-b"}],
                },
            ],
            "completionPredicate": {
                "operator": "any-satisfied",
                "informationIds": ["result-a", "result-b"],
            },
        }

        state = evaluate_goal_state(goal, {"result-a": goal_state("done")})

        self.assertTrue(state["complete"])
        self.assertEqual(state["missingInformationIds"], [])
        self.assertEqual(state["acquisitionCapabilityIds"], [])
        self.assertEqual(state["askInformationIds"], [])

    def test_goal_host_compatibility_requires_one_usable_acquisition_alternative(self) -> None:
        contract = read_json(ASSETS / "canonical-contract.json")
        contract["goals"].append({
            "goalId": "provider-only-alternative",
            "intent": "Resolve one synthetic provider result.",
            "informationNeeds": [{
                "informationId": "provider-result",
                "classification": "required",
                "type": "string",
                "satisfiedBy": [
                    {"kind": "capability", "capabilityId": "list-sample-request-kinds"},
                    {"kind": "capability", "capabilityId": "save-sample-draft"},
                ],
                "reuseWhile": {"fresh": True},
            }],
            "completionPredicate": {
                "operator": "any-satisfied",
                "informationIds": ["provider-result"],
            },
            "requiredCapabilityIds": [],
            "optionalCapabilityIds": [
                "list-sample-request-kinds",
                "save-sample-draft",
            ],
            "conditionalCapabilityIds": [],
            "agentPolicy": {
                "acceptInformationInAnyOrder": True,
                "reuseFreshInformation": True,
                "askOnlyCurrentlyMissing": True,
                "skipUnnecessaryCapabilities": True,
                "stopWhenPredicateSatisfied": True,
            },
        })
        host = read_json(ASSETS / "host-profile.json")
        host["capabilities"]["mcpToolInvocation"]["status"] = "unsupported"
        consumer = derive_consumer_requirements(contract)

        compatibility = derive_host_compatibility(contract, consumer, host)
        goal = next(
            item for item in compatibility["goalAssessments"]
            if item["goalId"] == "provider-only-alternative"
        )

        self.assertEqual(goal["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
