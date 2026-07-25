from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill-generate"
ASSETS = SKILL_ROOT / "assets"
SCRIPTS = SKILL_ROOT / "scripts"
DERIVER = SCRIPTS / "derive_artifacts.py"

sys.path.insert(0, str(SCRIPTS))

from contract_model import (  # noqa: E402
    derive_bundle,
    derive_consumer_requirements,
    derive_documentation_contract,
    derive_goal_contract,
    derive_host_compatibility,
    derive_verification_matrix,
    evaluate_goal_state,
    json_schema_errors,
    validate_canonical_contract,
    validate_source_topology,
    write_evidence_complete,
)
from validate_vnext import validate_vnext_artifacts  # noqa: E402
import validate_artifacts as validate_artifacts_module  # noqa: E402
from validate_artifacts import Diagnostics, parse_source_maps  # noqa: E402


DERIVED_FILES = (
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
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_path(locator: str) -> Path:
    return Path(locator.split("#", 1)[0].split(":", 1)[0])


class SyntheticVNextFixture:
    """A portable candidate plus separate, explicitly mapped synthetic roots."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.candidate = root / "candidate"
        self.candidate.mkdir()
        self.topology = read_json(ASSETS / "source-topology.json")
        self.contract = read_json(ASSETS / "canonical-contract.json")
        self.host_profile = read_json(ASSETS / "host-profile.json")
        write_json(self.candidate / "source-topology.json", self.topology)
        write_json(self.candidate / "canonical-contract.json", self.contract)
        write_json(self.candidate / "host-profile.json", self.host_profile)

        self.source_roots: dict[str, Path] = {}
        for source in self.topology["sources"]:
            source_id = source["sourceId"]
            source_root = (root / "authorized-sources" / source_id).resolve()
            source_root.mkdir(parents=True)
            self.source_roots[source_id] = source_root

        for item in self.contract["evidenceCatalog"]:
            path = self.source_roots[item["sourceId"]] / evidence_path(item["locator"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"synthetic evidence for {item['semanticRole']}\n",
                encoding="utf-8",
            )

        (self.candidate / "portable-workflow-guard.mjs").write_bytes(
            (ASSETS / "portable-workflow-guard.mjs").read_bytes()
        )
        (self.candidate / "portable-error-normalizer.mjs").write_bytes(
            (ASSETS / "portable-error-normalizer.mjs").read_bytes()
        )
        write_exports: list[str] = []
        workflows_by_entry = {
            workflow["entryCapabilityId"]: workflow
            for workflow in self.contract["workflows"]
        }
        for capability in self.contract["capabilities"]:
            if capability["sideEffect"] == "read":
                continue
            workflow = workflows_by_entry.get(capability["capabilityId"])
            if workflow is None:
                write_exports.append(
                    "export async function "
                    f"{capability['functionExport']}(input, context) {{\n"
                    "  return context.dispatch(input);\n"
                    "}"
                )
                continue
            workflow_id = workflow["workflowId"]
            write_exports.append(
                "export async function "
                f"{capability['functionExport']}(input, context) {{\n"
                "  const workflowGuard = workflowGuardFor(context);\n"
                f"  const protectedWorkflowState = protectedWorkflowStateFor(context, {json.dumps(workflow_id)});\n"
                "  return workflowGuard.dispatchWithPolicy({\n"
                f"    workflowId: {json.dumps(workflow_id)},\n"
                "    input,\n"
                "    runtimeContext: context,\n"
                "    operationKey: protectedWorkflowState.operationKey,\n"
                "  }, context.dispatch);\n"
                "}"
            )
        runtime_source = (
            "import { PortableWorkflowGuard } "
            "from '../portable-workflow-guard.mjs';\n\n"
            "function workflowGuardFor(context) {\n"
            "  if (!(context.workflowGuard instanceof PortableWorkflowGuard)) {\n"
            "    throw new Error('synthetic workflow Guard context is required');\n"
            "  }\n"
            "  return context.workflowGuard;\n"
            "}\n\n"
            "function protectedWorkflowStateFor(context, workflowId) {\n"
            "  const state = context.protectedWorkflowState;\n"
            "  if (!state || state.workflowId !== workflowId) throw new Error('protected workflow state is required');\n"
            "  return state;\n"
            "}\n\n"
            + "\n\n".join(write_exports)
            + "\n"
        )
        (self.candidate / "function-core").mkdir()
        (self.candidate / "function-core" / "index.mjs").write_text(
            runtime_source,
            encoding="utf-8",
        )
        (self.candidate / "mcp-tool").mkdir()
        (self.candidate / "mcp-tool" / "index.mjs").write_text(
            "// Workflow enforcement is imported by the Function core.\n",
            encoding="utf-8",
        )

    def derive(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(DERIVER), str(self.candidate)],
            check=False,
            capture_output=True,
            text=True,
        )

    def save_contract_and_derive(self, contract: dict[str, Any]) -> None:
        self.contract = contract
        write_json(self.candidate / "canonical-contract.json", contract)
        result = self.derive()
        if result.returncode != 0:
            raise AssertionError(result.stderr)

    def validate(self, source_maps: dict[str, Path] | None = None) -> list[str]:
        diagnostics = TestDiagnostics()
        validate_vnext_artifacts(
            self.candidate,
            self.root / "unused-single-source-root",
            self.source_roots if source_maps is None else source_maps,
            True,
            diagnostics,
        )
        return diagnostics.errors


class TestDiagnostics:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")


class VNextContractTest(unittest.TestCase):
    def derive_or_validate(
        self,
        fixture: SyntheticVNextFixture,
        contract: dict[str, Any],
    ) -> list[str]:
        fixture.contract = contract
        write_json(fixture.candidate / "canonical-contract.json", contract)
        result = fixture.derive()
        if result.returncode != 0:
            return [result.stderr]
        return fixture.validate()

    def assert_diagnostic_contains(
        self,
        diagnostics: list[str],
        *term_groups: tuple[str, ...],
    ) -> None:
        combined = "\n".join(diagnostics).lower()
        for alternatives in term_groups:
            self.assertTrue(
                any(term.lower() in combined for term in alternatives),
                f"expected one of {alternatives!r} in diagnostics:\n{combined}",
            )

    def configure_string_attachment_result(
        self,
        contract: dict[str, Any],
        value_kind: str,
        schema_format: str | None,
    ) -> None:
        string_schema: dict[str, Any] = {"type": "string"}
        if schema_format is not None:
            string_schema["format"] = schema_format
        upload = next(
            item
            for item in contract["capabilities"]
            if item["attachments"]["mode"] == "host-approved-reference"
        )
        upload["outputs"][0]["type"] = "string"
        upload["outputs"][0]["schema"] = copy.deepcopy(string_schema)
        upload["attachments"]["resultBinding"] = {
            "kind": "source-defined",
            "valueKind": value_kind,
            "outputPath": ["uploadedAttachmentGrant"],
            "scoping": {"subject": False, "session": False},
            "reuse": "reusable",
            "evidenceRefs": ["ev-contract-attachment"],
        }
        for capability in contract["capabilities"]:
            if capability["attachments"]["mode"] != "business-upload-results":
                continue
            attachment_input = next(
                item for item in capability["inputs"]
                if item["name"] == "attachmentGrants"
            )
            attachment_input["schema"]["items"] = copy.deepcopy(string_schema)
        for goal in contract["goals"]:
            for information in goal["informationNeeds"]:
                if information["informationId"] == "approved-attachments":
                    information["type"] = "string"
                    information["schema"] = copy.deepcopy(string_schema)
        submit_workflow = next(
            item for item in contract["workflows"]
            if item["entryCapabilityId"] == "submit-sample-request"
        )
        attachment_binding = next(
            item for item in submit_workflow["bindings"]
            if item["name"] == "attachmentGrantIds"
        )
        attachment_binding["actualSource"]["path"] = ["*"]

    def contract_mutation_errors(self, mutate: Any) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            mutate(contract)
            return self.derive_or_validate(fixture, contract)

    def test_canonical_first_derivation_is_deterministic_and_restores_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            first = fixture.derive()
            self.assertEqual(first.returncode, 0, first.stderr)
            first_hashes = {
                relative: digest(fixture.candidate / relative)
                for relative in DERIVED_FILES
            }

            write_json(
                fixture.candidate / "capability-bundle.json",
                {"tampered": "derived views are not authoring sources"},
            )
            second = fixture.derive()
            self.assertEqual(second.returncode, 0, second.stderr)
            second_hashes = {
                relative: digest(fixture.candidate / relative)
                for relative in DERIVED_FILES
            }
            third = fixture.derive()
            self.assertEqual(third.returncode, 0, third.stderr)
            third_hashes = {
                relative: digest(fixture.candidate / relative)
                for relative in DERIVED_FILES
            }

            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(second_hashes, third_hashes)
            self.assertEqual(
                read_json(fixture.candidate / "capability-bundle.json"),
                derive_bundle(fixture.contract),
            )
            self.assertEqual(
                read_json(fixture.candidate / "goal-contract.json"),
                derive_goal_contract(fixture.contract),
            )

            bundle = read_json(fixture.candidate / "capability-bundle.json")
            self.assertEqual(bundle["featureBoundary"], fixture.contract["featureBoundary"])
            canonical_by_id = {
                item["capabilityId"]: item for item in fixture.contract["capabilities"]
            }
            projected_by_id = {
                item["capabilityId"]: item for item in bundle["capabilities"]
            }
            projected_facts = {
                "exposure",
                "inputs",
                "outputs",
                "constraints",
                "attachments",
                "errorContract",
                "operationPolicy",
                "runtimeProtection",
                "readiness",
            }
            for capability_id, projected in projected_by_id.items():
                canonical_capability = canonical_by_id[capability_id]
                for fact in projected_facts:
                    if fact in canonical_capability:
                        self.assertEqual(projected[fact], canonical_capability[fact])

            matrix = read_json(fixture.candidate / "verification-matrix.json")
            self.assertEqual(
                matrix["delivery"],
                {
                    "functionCore": {"status": "pending"},
                    "mcpServer": {"status": "pending"},
                    "skill": {"status": "pending"},
                    "runtime": {"status": "not-run"},
                    "deployment": {"status": "not-deployed"},
                },
            )

    def test_function_and_mcp_schema_contracts_are_canonical_projections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            mcp_schema_path = fixture.candidate / "mcp-tool" / "schema-contract.json"
            mcp_schema = read_json(mcp_schema_path)
            mcp_schema["capabilities"][0]["inputSchema"]["required"] = [
                "synthetic-drift"
            ]
            write_json(mcp_schema_path, mcp_schema)

            errors = fixture.validate()

        self.assertTrue(
            any(
                "mcp-tool/schema-contract.json" in item
                and "deterministically derived" in item
                for item in errors
            ),
            errors,
        )

    def test_documentation_contract_is_a_canonical_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            path = fixture.candidate / "references/capability-contracts.json"
            documentation_contract = read_json(path)
            for field in (
                "goals",
                "capabilityGraph",
                "handoffs",
                "consumerRequirements",
                "workflows",
                "conflicts",
            ):
                self.assertEqual(
                    documentation_contract[field],
                    fixture.contract[field],
                )
            documentation_contract["capabilities"][0]["sideEffect"] = "create"
            write_json(path, documentation_contract)
            errors = fixture.validate()

        self.assertTrue(
            any(
                "references/capability-contracts.json" in item
                and "deterministically derived" in item
                for item in errors
            ),
            errors,
        )

    def test_documentation_contract_digest_covers_goal_graph_handoff_and_host_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            baseline = derive_documentation_contract(fixture.contract)
            baseline_digest = hashlib.sha256(
                json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            mutations = (
                lambda contract: contract["goals"][0].update(
                    {"intent": "A changed but still valid user-visible outcome."}
                ),
                lambda contract: contract["capabilityGraph"]["nodes"][0].update(
                    {"independentValue": "A changed independently useful outcome."}
                ),
                lambda contract: contract["handoffs"][0]["mappings"][0].update(
                    {"evidenceRefs": ["ev-contract-catalog", "ev-service-selection"]}
                ),
                lambda contract: contract["consumerRequirements"]["requirements"][0].update(
                    {"description": "A changed generic Consumer Host requirement."}
                ),
            )
            for mutate in mutations:
                contract = copy.deepcopy(fixture.contract)
                mutate(contract)
                derived = derive_documentation_contract(contract)
                changed_digest = hashlib.sha256(
                    json.dumps(derived, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                self.assertNotEqual(baseline_digest, changed_digest)

    def test_portable_error_normalizer_preserves_recovery_and_unknown_outcome(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is required for the portable error normalizer vector")
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "probe.mjs"
            normalizer_url = (ASSETS / "portable-error-normalizer.mjs").resolve().as_uri()
            probe.write_text(
                f"""import {{ normalizeToolError }} from {json.dumps(normalizer_url)};
const ordinary = normalizeToolError({{
  code: 'MISSING_FIELD',
  message: 'A field is missing',
  details: {{ field: 'value', stack: 'secret' }},
  retryable: true,
}});
if (ordinary.code !== 'MISSING_FIELD' || ordinary.retryable !== true) throw new Error('ordinary recovery lost');
if (ordinary.details.field !== 'value' || 'stack' in ordinary.details) throw new Error('details not sanitized');
const unknown = normalizeToolError({{
  code: 'UNKNOWN_DISPATCH_OUTCOME',
  message: 'possibly dispatched',
  dispatchOccurred: true,
  automaticRetryAllowed: true,
}});
if (unknown.code !== 'UNKNOWN_DISPATCH_OUTCOME') throw new Error('unknown outcome code lost');
if (unknown.retryable !== false || unknown.details.dispatchOccurred !== true) throw new Error('unknown outcome became retryable');
for (const sideEffect of ['create', 'update']) {{
  const unstructuredWrite = normalizeToolError(
    new Error('connection ended without a structured result'),
    {{ sideEffect }},
  );
  if (unstructuredWrite.code !== 'UNKNOWN_DISPATCH_OUTCOME') throw new Error(`${{sideEffect}} write was treated as a known failure`);
  if (unstructuredWrite.details.dispatchOccurred !== true) throw new Error(`${{sideEffect}} write lost dispatch uncertainty`);
  if (unstructuredWrite.retryable !== false) throw new Error(`${{sideEffect}} write became retryable`);
}}
const timedOutWrite = normalizeToolError(
  {{ code: 'ETIMEDOUT', message: 'socket timed out', details: {{}}, retryable: true }},
  {{ sideEffect: 'create', automaticRetry: 'never' }},
);
if (timedOutWrite.code !== 'UNKNOWN_DISPATCH_OUTCOME') throw new Error('transport code was mistaken for known write outcome');
if (timedOutWrite.retryable !== false || timedOutWrite.details.outcomeKnown !== false) throw new Error('uncertain transport write became retryable');
const knownWriteRejection = normalizeToolError(
  {{
    code: 'BUSINESS_RULE_REJECTED',
    message: 'synthetic rule rejected the request',
    details: {{ field: 'value' }},
    dispatchOccurred: false,
    outcomeKnown: true,
    retryable: true,
  }},
  {{ sideEffect: 'update', automaticRetry: 'never' }},
);
if (knownWriteRejection.code !== 'BUSINESS_RULE_REJECTED') throw new Error('known business rejection was lost');
if (knownWriteRejection.retryable !== false || knownWriteRejection.details.outcomeKnown !== true) throw new Error('write policy allowed an automatic retry');
console.log('portable error normalizer vector passed');
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(probe)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("vector passed", result.stdout)

    def test_nested_output_paths_merge_without_overwriting_parent_array_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            schema_contract = read_json(
                fixture.candidate / "mcp-tool" / "schema-contract.json"
            )
            catalog = next(
                item for item in schema_contract["capabilities"]
                if item["capabilityId"] == "list-sample-request-kinds"
            )
            selection_schema = (
                catalog["outputSchema"]["properties"]["data"]["properties"]
                ["options"]["items"]["properties"]["selectionGrant"]
            )

        self.assertEqual(selection_schema["type"], "object")
        self.assertEqual(
            set(selection_schema["required"]),
            {"grantId", "requiresAttachment", "allowsAttachment"},
        )

    def test_nullable_output_schema_preserves_both_source_proven_value_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            catalog = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "list-sample-request-kinds"
            )
            options = next(
                item for item in catalog["outputs"]
                if item["path"] == ["options"]
            )
            options["schema"]["type"] = ["array", "null"]
            options["schema"]["items"]["properties"]["hint"] = {
                "type": ["string", "null"],
            }
            options["schema"]["items"]["required"].append("hint")

            fixture.save_contract_and_derive(contract)
            schema_contract = read_json(
                fixture.candidate / "mcp-tool" / "schema-contract.json"
            )
            catalog_schema = next(
                item for item in schema_contract["capabilities"]
                if item["capabilityId"] == "list-sample-request-kinds"
            )["outputSchema"]
            options_schema = (
                catalog_schema["properties"]["data"]["properties"]["options"]
            )
            hint_schema = options_schema["items"]["properties"]["hint"]

        self.assertEqual(options_schema["type"], ["array", "null"])
        self.assertEqual(hint_schema["type"], ["string", "null"])
        self.assertEqual(
            json_schema_errors(
                {"status": 200, "data": {"options": None}},
                catalog_schema,
            ),
            [],
        )
        self.assertEqual(
            json_schema_errors(
                {
                    "status": 200,
                    "data": {
                        "options": [{
                            "label": "synthetic",
                            "selectionGrant": {
                                "grantId": "grant",
                                "requiresAttachment": False,
                                "allowsAttachment": False,
                            },
                            "hint": None,
                        }],
                    },
                },
                catalog_schema,
            ),
            [],
        )
        self.assertEqual(
            json_schema_errors(
                {
                    "status": 200,
                    "data": {
                        "options": [{
                            "label": "synthetic",
                            "selectionGrant": {
                                "grantId": "grant",
                                "requiresAttachment": False,
                                "allowsAttachment": False,
                            },
                            "hint": "source-proven guidance",
                        }],
                    },
                },
                catalog_schema,
            ),
            [],
        )
        errors = json_schema_errors(
            {
                "status": 200,
                "data": {
                    "options": [{
                        "label": "synthetic",
                        "selectionGrant": {
                            "grantId": "grant",
                            "requiresAttachment": False,
                            "allowsAttachment": False,
                        },
                        "hint": 42,
                    }],
                },
            },
            catalog_schema,
        )
        self.assertTrue(any("expected one of string, null" in item for item in errors), errors)

    def test_output_schema_rejects_invalid_or_mismatched_type_unions(self) -> None:
        mutations = {
            "unknown type": ["string", "synthetic-unknown"],
            "duplicate type": ["string", "string"],
            "single type union": ["string"],
            "non-null union": ["string", "number"],
        }
        for label, schema_types in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                output = next(
                    item for item in contract["capabilities"][0]["outputs"]
                    if item["path"] == ["options"]
                )
                output["schema"]["type"] = schema_types

                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("nullable union", "nullable unions", "nullable two-type"),
            )

        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            output = next(
                item for item in contract["capabilities"][0]["outputs"]
                if item["path"] == ["options"]
            )
            output["schema"]["type"] = ["object", "null"]

            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(errors, ("include the declared output type",))

    def test_nested_output_declaration_must_agree_with_parent_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            catalog = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "list-sample-request-kinds"
            )
            nested = next(
                item for item in catalog["outputs"]
                if item["path"] == ["options", "*", "selectionGrant"]
            )
            nested["schema"]["properties"]["grantId"]["type"] = "number"

            errors = self.derive_or_validate(fixture, contract)

        self.assertIn("must agree with the same nested path", "\n".join(errors))

    def test_cross_capability_references_are_resolved_and_typed(self) -> None:
        def validate_mutation(mutator: Any) -> list[str]:
            with tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                mutator(contract)
                return self.derive_or_validate(fixture, contract)

        def validating_input(contract: dict[str, Any]) -> dict[str, Any]:
            capability = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "validate-sample-request"
            )
            return next(item for item in capability["inputs"] if item["name"] == "selectionGrant")

        cases = [
            (
                "upstream output",
                lambda contract: validating_input(contract)["sourceStrategies"][0].update(
                    {"outputPath": ["phantom-output"]}
                ),
                "exactly declared provider output",
            ),
            (
                "dynamic output",
                lambda contract: validating_input(contract)["valueDomain"].update(
                    {"sourcePath": ["phantom-output"]}
                ),
                "exactly declared provider output",
            ),
            (
                "goal output",
                lambda contract: contract["goals"][0]["informationNeeds"][0]["satisfiedBy"][0].update(
                    {"outputPath": ["phantom-output"]}
                ),
                "exactly declared provider output",
            ),
            (
                "handoff target",
                lambda contract: contract["handoffs"][0]["mappings"][0].update(
                    {"targetInput": "phantomInput"}
                ),
                "declared target input",
            ),
            (
                "unknown graph kind",
                lambda contract: contract["capabilityGraph"]["edges"][0].update(
                    {"kind": "invented-edge"}
                ),
                "declared handoff kind",
            ),
            (
                "goal membership",
                lambda contract: contract["goals"][0].update(
                    {"requiredCapabilityIds": ["list-sample-request-kinds"]}
                ),
                "must be derived exactly",
            ),
            (
                "host requirements",
                lambda contract: contract["capabilities"][-1].update(
                    {"hostRequirements": ["agent-skills-discovery"]}
                ),
                "must exactly equal",
            ),
            (
                "portable architecture",
                lambda contract: contract["portableCore"].update(
                    {"architectureBinding": "controller-dto"}
                ),
                "must not bind",
            ),
        ]
        for label, mutator, expected in cases:
            with self.subTest(label=label):
                errors = validate_mutation(mutator)
                self.assertIn(expected, "\n".join(errors), errors)

    def test_business_upload_results_are_not_user_attested_or_disconnected(self) -> None:
        def validate_mutation(kind: str) -> str:
            with tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                submit = next(
                    item for item in contract["capabilities"]
                    if item["capabilityId"] == "submit-sample-request"
                )
                attachment_input = next(
                    item for item in submit["inputs"] if item["name"] == "attachmentGrants"
                )
                if kind == "user-source":
                    attachment_input["sourceStrategies"] = ["user"]
                    attachment_input.pop("targetRequiredness")
                elif kind == "missing-consumer-binding":
                    submit["attachments"]["consumerBindings"] = []
                elif kind == "missing-runtime-binding":
                    submit["implementation"]["steps"][0]["bindings"] = [
                        binding
                        for binding in submit["implementation"]["steps"][0]["bindings"]
                        if binding["source"].get("inputName") != "attachmentGrants"
                    ]
                return "\n".join(self.derive_or_validate(fixture, contract))

        expectations = {
            "user-source": "may come only from declared upstream business-upload Tools",
            "missing-consumer-binding": "business upload results need at least one",
            "missing-runtime-binding": "must bind attachment input",
        }
        for kind, expected in expectations.items():
            with self.subTest(kind=kind):
                self.assertIn(expected, validate_mutation(kind))

    def test_attachment_result_kind_must_match_its_declared_output_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            upload["attachments"]["resultBinding"]["valueKind"] = "url"

            errors = self.derive_or_validate(fixture, contract)

        self.assertIn("requires a declared string output", "\n".join(errors))

    def test_backend_authoritative_write_does_not_require_a_local_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            backend_write = next(
                item
                for item in fixture.contract["capabilities"]
                if item.get("runtimeProtection", {}).get("mode")
                == "backend-authoritative"
            )
            self.assertEqual(backend_write["operationPolicy"]["confirmation"], "not-required")
            self.assertNotIn("workflowId", backend_write)
            self.assertNotIn(
                backend_write["capabilityId"],
                {item["entryCapabilityId"] for item in fixture.contract["workflows"]},
            )
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.validate(), [])

    def test_client_visible_read_side_effect_evidence_passes_the_full_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = next(
                item
                for item in contract["capabilities"]
                if item["sideEffect"] == "read"
            )
            client_invocation = capability["exposure"]["evidenceRefs"][0]
            capability["evidenceCoverage"]["sideEffect"] = {
                "declaredSideEffect": "read",
                "assertionLevel": "fact",
                "evidenceRefs": [client_invocation],
            }

            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertEqual(errors, [])

    def test_backend_internal_maintenance_does_not_reclassify_a_client_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = next(
                item
                for item in contract["capabilities"]
                if item["sideEffect"] == "read"
            )
            client_invocation = capability["exposure"]["evidenceRefs"][0]
            hidden_maintenance_ref = "ev-service-hidden-maintenance"
            contract["evidenceCatalog"].append({
                "evidenceId": hidden_maintenance_ref,
                "sourceId": "sample-service",
                "locator": "src/internal/catalog-maintenance.py#refresh",
                "semanticRole": "side-effect",
                "assertionLevel": "fact",
            })
            hidden_evidence_path = (
                fixture.source_roots["sample-service"]
                / "src/internal/catalog-maintenance.py"
            )
            hidden_evidence_path.parent.mkdir(parents=True, exist_ok=True)
            hidden_evidence_path.write_text(
                "synthetic hidden maintenance evidence\n",
                encoding="utf-8",
            )
            capability["exposure"]["supplementalEvidenceRefs"].append(
                hidden_maintenance_ref
            )
            capability["evidenceRefs"].append(hidden_maintenance_ref)
            capability["evidenceCoverage"]["sideEffect"] = {
                "declaredSideEffect": "read",
                "assertionLevel": "fact",
                "evidenceRefs": [client_invocation],
            }

            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertEqual(errors, [])

    def test_optional_observed_upstream_value_must_classify_target_requiredness(self) -> None:
        for information_class in ("optional", "derived"):
            with self.subTest(information_class=information_class), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                submit = next(
                    item for item in contract["capabilities"]
                    if item["capabilityId"] == "submit-sample-request"
                )
                optional_input = next(
                    item for item in submit["inputs"]
                    if item["name"] == "attachmentGrants"
                )
                optional_input["informationClass"] = information_class
                optional_input.pop("targetRequiredness")
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("targetrequiredness",),
                ("must be an object", "proven-optional", "unproven", "distinguish"),
            )

    def test_unproven_target_requiredness_binds_provider_and_surfaces_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            optional_input = next(
                item for item in submit["inputs"]
                if item["name"] == "attachmentGrants"
            )
            optional_input["targetRequiredness"] = {
                "status": "unproven",
                "normalProvider": {
                    "capabilityId": "upload-sample-attachment",
                    "outputPath": ["uploadedAttachmentGrant"],
                    "mappingKind": "append-to-array",
                },
                "evidenceRefs": [
                    "ev-client-upload-call",
                    "ev-client-submit-request",
                ],
            }
            optional_input["evidenceRefs"].extend([
                "ev-client-upload-call",
                "ev-client-submit-request",
            ])

            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()
            matrix = read_json(fixture.candidate / "verification-matrix.json")

        self.assertEqual(errors, [])
        submit_row = next(
            item for item in matrix["capabilities"]
            if item["capabilityId"] == "submit-sample-request"
        )
        self.assertTrue(
            any(
                item.get("kind") == "target-requiredness-unproven"
                and item.get("inputName") == "attachmentGrants"
                and item.get("providerCapabilityId") == "upload-sample-attachment"
                for item in submit_row["reviewItems"]
            ),
            submit_row,
        )
        self.assertIn(
            "optional-upstream-omission-preserves-target-api-decision",
            {
                item["checkId"] if isinstance(item, dict) else item
                for item in submit_row["checks"]
            },
        )

    def test_unproven_target_requiredness_provider_must_match_source_strategy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            optional_input = next(
                item for item in submit["inputs"]
                if item["name"] == "attachmentGrants"
            )
            optional_input["targetRequiredness"] = {
                "status": "unproven",
                "normalProvider": {
                    "capabilityId": "upload-sample-attachment",
                    "outputPath": ["wrongOutput"],
                    "mappingKind": "append-to-array",
                },
                "evidenceRefs": [
                    "ev-client-upload-call",
                    "ev-client-submit-request",
                ],
            }
            optional_input["evidenceRefs"].extend([
                "ev-client-upload-call",
                "ev-client-submit-request",
            ])
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("normalprovider",),
            ("exactly match", "upstream-tool"),
        )

    def test_target_requiredness_cannot_borrow_neighboring_contract_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            optional_input = next(
                item for item in submit["inputs"]
                if item["name"] == "attachmentGrants"
            )
            optional_input["targetRequiredness"] = {
                "status": "unproven",
                "normalProvider": {
                    "capabilityId": "upload-sample-attachment",
                    "outputPath": ["uploadedAttachmentGrant"],
                    "mappingKind": "append-to-array",
                },
                "evidenceRefs": ["ev-contract-catalog"],
            }
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("targetrequiredness",),
            ("retained on this exact input",),
        )

    def test_transport_contract_alone_cannot_prove_an_observed_normal_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            optional_input = next(
                item for item in submit["inputs"]
                if item["name"] == "attachmentGrants"
            )
            optional_input["targetRequiredness"] = {
                "status": "unproven",
                "normalProvider": {
                    "capabilityId": "upload-sample-attachment",
                    "outputPath": ["uploadedAttachmentGrant"],
                    "mappingKind": "append-to-array",
                },
                "evidenceRefs": ["ev-contract-attachment"],
            }
            optional_input["evidenceRefs"].append("ev-contract-attachment")
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("transport contract alone is insufficient", "observed normal provider"),
        )

    def test_supplementary_backend_request_evidence_cannot_prove_the_normal_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            backend_evidence = next(
                item for item in contract["evidenceCatalog"]
                if item["evidenceId"] == "ev-service-attachment"
            )
            backend_evidence["semanticRole"] = "request-construction"
            submit = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            optional_input = next(
                item for item in submit["inputs"]
                if item["name"] == "attachmentGrants"
            )
            optional_input["targetRequiredness"] = {
                "status": "unproven",
                "normalProvider": {
                    "capabilityId": "upload-sample-attachment",
                    "outputPath": ["uploadedAttachmentGrant"],
                    "mappingKind": "append-to-array",
                },
                "evidenceRefs": ["ev-service-attachment"],
            }
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("primary source", "supplementary backend evidence"),
            ("observed normal provider",),
        )

    def test_target_requiredness_cannot_conflict_with_a_hard_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            handoff = next(
                item for item in contract["handoffs"]
                if item["fromCapabilityId"] == "upload-sample-attachment"
                and item["toCapabilityId"] == "submit-sample-request"
            )
            handoff["required"] = True
            edge = next(
                item for item in contract["capabilityGraph"]["edges"]
                if item["fromCapabilityId"] == "upload-sample-attachment"
                and item["toCapabilityId"] == "submit-sample-request"
            )
            edge.update({"kind": "hard-precondition", "required": True})
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("targetrequiredness",),
            ("optional and non-hard",),
        )

    def test_ui_confirmation_and_post_evidence_cannot_justify_a_host_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item
                for item in contract["capabilities"]
                if item.get("runtimeProtection", {}).get("mode")
                == "deterministic-workflow"
                and item["capabilityId"] == "submit-sample-request"
            )
            client_post_ref = submit["exposure"]["evidenceRefs"][0]
            submit["runtimeProtection"]["evidenceRefs"].append(client_post_ref)
            submit["runtimeProtection"]["hardWorkflowEvidence"] = {
                "protectedValueIssuance": [client_post_ref],
                "protectedValueBinding": [client_post_ref],
                "preDispatchEnforcement": [client_post_ref],
            }

            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        for category in (
            "protectedValueIssuance",
            "protectedValueBinding",
            "preDispatchEnforcement",
        ):
            self.assertTrue(
                any(
                    f"hardWorkflowEvidence.{category}" in item
                    and "appropriate semanticRole" in item
                    for item in errors
                ),
                errors,
            )

    def test_neighboring_transport_contract_cannot_justify_a_host_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item
                for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            unrelated_contract_ref = "ev-contract-catalog"
            submit["runtimeProtection"]["evidenceRefs"].append(
                unrelated_contract_ref
            )
            submit["runtimeProtection"]["hardWorkflowEvidence"][
                "protectedValueIssuance"
            ] = [unrelated_contract_ref]
            submit["runtimeProtection"]["hardWorkflowEvidence"][
                "protectedValueBinding"
            ] = [unrelated_contract_ref]

            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        for category in ("protectedValueIssuance", "protectedValueBinding"):
            self.assertTrue(
                any(
                    f"hardWorkflowEvidence.{category}" in item
                    and "this capability's protected input producer" in item
                    for item in errors
                ),
                errors,
            )

    def test_canonical_derivation_rejects_missing_hard_workflow_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item
                for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            submit["runtimeProtection"].pop("hardWorkflowEvidence")
            write_json(fixture.candidate / "canonical-contract.json", contract)

            result = fixture.derive()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hardWorkflowEvidence", result.stderr)

    def test_frontend_observed_write_can_remain_unresolved_without_guessing_backend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = next(
                item
                for item in contract["capabilities"]
                if item.get("runtimeProtection", {}).get("mode")
                == "backend-authoritative"
            )
            client_ref = capability["exposure"]["evidenceRefs"][0]
            capability["readiness"] = "requires-review"
            capability["missingEvidence"] = [
                "backend-protection-owner",
                "backend-authorization",
                "backend-idempotency",
                "backend-unknown-outcome",
            ]
            capability["runtimeProtection"] = {
                "mode": "unresolved",
                "evidenceRefs": [client_ref],
            }
            capability["exposure"]["supplementalEvidenceRefs"] = []
            capability["evidenceRefs"] = [client_ref]
            for coverage in capability["evidenceCoverage"].values():
                coverage["assertionLevel"] = "unknown"
                coverage["evidenceRefs"] = [client_ref]
            # The client still proves the observed request shape.  Only the
            # backend safety claims are unresolved; weakening exact transport
            # evidence would turn this into a different (and less useful)
            # fixture.

            errors = self.derive_or_validate(fixture, contract)
            self.assertEqual(errors, [])

            invalid = copy.deepcopy(contract)
            unresolved = next(
                item
                for item in invalid["capabilities"]
                if item.get("runtimeProtection", {}).get("mode") == "unresolved"
            )
            unresolved["readiness"] = "ready"
            write_json(fixture.candidate / "canonical-contract.json", invalid)
            result = fixture.derive()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot be ready", result.stderr)

    def test_requires_review_must_name_the_exact_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = contract["capabilities"][0]
            capability["readiness"] = "requires-review"
            capability["missingEvidence"] = []
            write_json(fixture.candidate / "canonical-contract.json", contract)

            result = fixture.derive()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must name the missing evidence", result.stderr)

    def test_supplemental_backend_evidence_cannot_create_client_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = contract["capabilities"][0]
            capability["exposure"]["evidenceRefs"] = [
                capability["exposure"]["supplementalEvidenceRefs"][0]
            ]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("exposure",),
            ("supplementary backend evidence", "supplemental backend evidence"),
            ("cannot create",),
        )

    def test_client_request_exposure_requires_an_observed_api_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            write = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "save-sample-draft"
            )
            write["exposure"]["evidenceRefs"] = ["ev-client-goal"]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("semanticrole",),
            ("client api invocation",),
        )

    def test_explicitly_scoped_service_feature_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["featureBoundary"] = {
                "scopeKind": "business-feature",
                "primaryEvidenceRole": "explicitly-scoped-service-feature",
                "backendEvidenceRole": "supplement-and-verify",
                "inclusionRule": "explicitly-scoped-surface",
                "serviceSourceIds": ["sample-service"],
                "supplementarySourceIds": [
                    "sample-client",
                    "sample-contract",
                    "sample-tests",
                ],
            }
            evidence_by_id = {
                item["evidenceId"]: item for item in contract["evidenceCatalog"]
            }
            service_source = next(
                item
                for item in fixture.topology["sources"]
                if item["sourceId"] == "sample-service"
            )
            service_source["semanticRoles"].append("explicit-operation")
            write_json(fixture.candidate / "source-topology.json", fixture.topology)
            for capability in contract["capabilities"]:
                service_ref = next(
                    ref
                    for ref in capability["exposure"]["supplementalEvidenceRefs"]
                    if evidence_by_id[ref]["sourceId"] == "sample-service"
                )
                explicit_ref = f"ev-explicit-{capability['capabilityId']}"
                explicit_evidence = copy.deepcopy(evidence_by_id[service_ref])
                explicit_evidence.update({
                    "evidenceId": explicit_ref,
                    "semanticRole": "explicit-operation",
                })
                contract["evidenceCatalog"].append(explicit_evidence)
                capability["exposure"] = {
                    "kind": "explicitly-scoped-operation",
                    "evidenceRefs": [explicit_ref],
                    "supplementalEvidenceRefs": [
                        ref
                        for ref in capability["exposure"]["supplementalEvidenceRefs"]
                    ],
                }
            errors = self.derive_or_validate(fixture, contract)

        self.assertEqual(errors, [])

    def test_every_capability_needs_a_structured_actionable_error_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["capabilities"][0].pop("errorContract")
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("errorcontract",),
            ("must be an object", "structured actionable"),
        )

    def test_host_profile_identity_is_structural_not_vendor_token_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            fixture.host_profile["profileId"] = "synthetic-vendor-a-deployment"
            fixture.host_profile["description"] = (
                "Deployment evidence may identify its concrete Host; portable requirements remain structural."
            )
            write_json(fixture.candidate / "host-profile.json", fixture.host_profile)
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.validate(), [])

    def test_fixture_uses_distinct_explicit_source_ids_and_absolute_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            source_ids = validate_source_topology(fixture.topology)
            validate_canonical_contract(fixture.contract, source_ids)

            self.assertEqual(source_ids, set(fixture.source_roots))
            self.assertEqual(len(set(fixture.source_roots.values())), len(source_ids))
            self.assertTrue(all(path.is_absolute() for path in fixture.source_roots.values()))
            cli_diagnostics = Diagnostics()
            parsed_maps = parse_source_maps(
                [
                    f"{source_id}={fixture.source_roots[source_id]}"
                    for source_id in sorted(source_ids)
                ],
                cli_diagnostics,
            )
            self.assertEqual(cli_diagnostics.errors, [])
            self.assertEqual(parsed_maps, fixture.source_roots)
            for evidence in fixture.contract["evidenceCatalog"]:
                self.assertTrue(
                    (
                        fixture.source_roots[evidence["sourceId"]]
                        / evidence_path(evidence["locator"])
                    ).is_file()
                )
            self.assertEqual(fixture.validate(), [])

            incomplete_maps = dict(fixture.source_roots)
            incomplete_maps.pop(next(iter(incomplete_maps)))
            errors = fixture.validate(incomplete_maps)
            self.assertTrue(
                any("every available source needs an explicit --source-map" in item for item in errors),
                errors,
            )

    def test_missing_evidence_file_and_path_traversal_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = fixture.contract["evidenceCatalog"][0]
            evidence_file = (
                fixture.source_roots[evidence["sourceId"]]
                / evidence_path(evidence["locator"])
            )
            evidence_file.unlink()
            errors = fixture.validate()
            self.assertTrue(
                any("does not resolve to a file" in item for item in errors),
                errors,
            )

        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["evidenceCatalog"][0]["locator"] = "../outside-source#symbol"
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()
            self.assertTrue(
                any("must not traverse outside its declared source root" in item for item in errors),
                errors,
            )

    def test_dynamic_value_domains_cannot_freeze_one_observed_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            dynamic_input = next(
                input_value
                for capability in contract["capabilities"]
                for input_value in capability["inputs"]
                if input_value["valueDomain"]["kind"] == "dynamic"
            )
            dynamic_input["valueDomain"]["values"] = ["synthetic-observation"]
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()
            self.assertTrue(
                any("must not freeze one observed dynamic response" in item for item in errors),
                errors,
            )

    def test_conditionally_required_information_needs_an_activation_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            conditional_input = next(
                input_value
                for capability in contract["capabilities"]
                for input_value in capability["inputs"]
                if input_value.get("informationClass") == "requiredWhen"
            )
            conditional_input["requiredWhen"] = []
            conditional_input["targetRequiredness"] = {
                "status": "proven-optional",
                "evidenceRefs": ["ev-contract-attachment"],
            }
            conditional_input["evidenceRefs"].append("ev-contract-attachment")
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()
            self.assertTrue(
                any("requiredWhen information must declare" in item for item in errors),
                errors,
            )

    def test_attachment_contract_rejects_arbitrary_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item
                for item in contract["capabilities"]
                if item["attachments"]["mode"] == "host-approved-reference"
            )
            upload["inputs"][0]["name"] = "local_file_path"
            upload["attachments"]["forbiddenInputs"] = ["unverified-url"]
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()
            self.assertTrue(
                any("must not accept arbitrary local file paths" in item for item in errors),
                errors,
            )
            self.assertTrue(
                any("must forbid local paths and unverified URLs" in item for item in errors),
                errors,
            )

    def test_attachment_upload_result_preserves_source_defined_string_contracts(self) -> None:
        for value_kind in ("url", "file-id"):
            with self.subTest(value_kind=value_kind), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                self.configure_string_attachment_result(
                    contract,
                    value_kind,
                    "uri" if value_kind == "url" else None,
                )
                fixture.save_contract_and_derive(contract)
                errors = fixture.validate()

            self.assertEqual(errors, [])

    def test_attachment_result_url_schema_format_cannot_be_relabeled(self) -> None:
        cases = (
            ("url", "url", "must equal the standard JSON Schema format `uri`"),
            ("file-id", "uri", "non-URL upload results must not use a URL-formatted output Schema"),
        )
        for value_kind, schema_format, expected in cases:
            with self.subTest(value_kind=value_kind), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                self.configure_string_attachment_result(
                    contract,
                    value_kind,
                    schema_format,
                )
                errors = self.derive_or_validate(fixture, contract)

            self.assertIn(expected, "\n".join(errors))

    def test_composite_required_when_condition_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            conditional = next(
                item for item in goal["informationNeeds"]
                if item["classification"] == "requiredWhen"
            )
            conditional["condition"] = {
                "operator": "and",
                "conditions": [
                    {
                        "path": ["current-selection", "requiresAttachment"],
                        "operator": "equals",
                        "value": True,
                    },
                    {
                        "path": ["request-data"],
                        "operator": "present",
                    },
                ],
                "evidenceRefs": ["ev-service-selection"],
            }
            goal["conditionalCapabilityIds"] = [{
                "capabilityId": "upload-sample-attachment",
                "condition": copy.deepcopy(conditional["condition"]),
            }]
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertEqual(errors, [])

    def test_required_when_activation_dependency_cannot_be_optional(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            selection = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "current-selection"
            )
            selection["classification"] = "optional"
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertTrue(
            any("activation dependency cannot be optional" in item for item in errors),
            errors,
        )

    def test_host_degradation_is_capability_and_goal_specific(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            consumer = derive_consumer_requirements(fixture.contract)
            compatibility = derive_host_compatibility(
                fixture.contract,
                consumer,
                fixture.host_profile,
            )

        status_by_capability = {
            item["capabilityId"]: item["status"]
            for item in compatibility["capabilityAssessments"]
        }
        status_by_goal = {
            item["goalId"]: item["status"]
            for item in compatibility["goalAssessments"]
        }
        self.assertIn("enabled", set(status_by_capability.values()))
        self.assertIn("requires-host-integration", set(status_by_capability.values()))
        self.assertIn("enabled", set(status_by_goal.values()))
        self.assertIn("requires-host-integration", set(status_by_goal.values()))
        self.assertEqual(compatibility["overallStatus"], "compatible-with-restrictions")

    def test_canonical_review_is_not_misreported_as_a_host_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            reviewed = contract["capabilities"][0]
            reviewed["readiness"] = "requires-review"
            reviewed["missingEvidence"] = ["source-defined review question"]
            host_profile = copy.deepcopy(fixture.host_profile)
            for support in host_profile["capabilities"].values():
                support["status"] = "supported"

            consumer = derive_consumer_requirements(contract)
            compatibility = derive_host_compatibility(
                contract,
                consumer,
                host_profile,
            )
            assessment = next(
                item for item in compatibility["capabilityAssessments"]
                if item["capabilityId"] == reviewed["capabilityId"]
            )
            related_goal = next(
                goal for goal in contract["goals"]
                if reviewed["capabilityId"] in goal["requiredCapabilityIds"]
            )
            goal_assessment = next(
                item for item in compatibility["goalAssessments"]
                if item["goalId"] == related_goal["goalId"]
            )
            matrix = derive_verification_matrix(contract, compatibility)
            matrix_row = next(
                item for item in matrix["capabilities"]
                if item["capabilityId"] == reviewed["capabilityId"]
            )

        self.assertEqual(assessment["status"], "enabled")
        self.assertEqual(assessment["canonicalReadiness"], "requires-review")
        self.assertEqual(assessment["missingRequirementIds"], [])
        self.assertEqual(assessment["externalIntegrationRequirementIds"], [])
        self.assertEqual(goal_assessment["status"], "enabled")
        self.assertIn("canonical-readiness-requires-review", matrix_row["reasons"])
        self.assertNotIn("host-not-fully-compatible", matrix_row["reasons"])

    def test_incomplete_write_evidence_stays_under_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            write_capability = next(
                item for item in contract["capabilities"] if item["sideEffect"] != "read"
            )
            write_capability["evidenceCoverage"].pop("authorization")
            self.assertFalse(write_evidence_complete(write_capability))

            consumer = derive_consumer_requirements(contract)
            compatibility = derive_host_compatibility(
                contract,
                consumer,
                fixture.host_profile,
            )
            matrix = derive_verification_matrix(contract, compatibility)

        record = next(
            item
            for item in matrix["capabilities"]
            if item["capabilityId"] == write_capability["capabilityId"]
        )
        self.assertTrue(record["status"]["requiresReview"])
        self.assertFalse(record["status"]["runtimeVerified"])
        self.assertIn("incomplete-write-evidence", record["reasons"])

        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = next(
                item for item in contract["capabilities"] if item["sideEffect"] != "read"
            )
            capability["evidenceCoverage"].pop("authorization")
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()
            self.assertTrue(
                any(
                    "without complete operation-bound fact-level side-effect evidence cannot be ready"
                    in item
                    for item in errors
                ),
                errors,
            )

    def test_client_fact_cannot_impersonate_authoritative_write_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            write = next(
                item for item in contract["capabilities"] if item["sideEffect"] != "read"
            )
            client_fact = write["exposure"]["evidenceRefs"][0]
            for coverage in write["evidenceCoverage"].values():
                coverage["evidenceRefs"] = [client_fact]

            self.assertFalse(write_evidence_complete(write, contract))
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertTrue(
            any(
                "without complete operation-bound fact-level side-effect evidence cannot be ready"
                in item
                for item in errors
            ),
            errors,
        )

    def test_trusted_confirmation_cannot_be_self_attested_by_public_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item
                for item in contract["capabilities"]
                if item["operationPolicy"]["confirmation"] == "trusted-confirmation-required"
            )
            submit["inputs"].append({
                "name": "userConfirmed",
                "description": "Synthetic untrusted confirmation flag.",
                "type": "boolean",
                "required": True,
                "informationClass": "required",
                "sourceStrategies": ["user"],
                "valueDomain": {"kind": "unconstrained"},
                "requiredWhen": [],
                "forbiddenWhen": [],
                "freshness": {"refreshWhen": ["user-edited"]},
                "evidenceRefs": ["ev-client-submit-call"],
            })
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertTrue(
            any("cannot self-attest trusted user confirmation" in item for item in errors),
            errors,
        )

    def test_trusted_confirmation_declares_generic_host_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            submit = next(
                item
                for item in contract["capabilities"]
                if item["operationPolicy"]["confirmation"] == "trusted-confirmation-required"
            )
            submit["hostRequirements"] = [
                item for item in submit["hostRequirements"]
                if item != "trusted-confirmation"
            ]
            fixture.save_contract_and_derive(contract)
            errors = fixture.validate()

        self.assertTrue(
            any("trustedConfirmation Host requirement" in item for item in errors),
            errors,
        )

    def test_only_deterministic_writes_require_a_workflow_and_runtime_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["workflows"].pop()
            write_json(fixture.candidate / "canonical-contract.json", contract)
            result = fixture.derive()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "must map to exactly one workflow",
                result.stderr,
            )

        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            (fixture.candidate / "portable-workflow-guard.mjs").unlink()
            errors = fixture.validate()
            self.assertTrue(
                any("is required by deterministic-workflow capabilities" in item for item in errors),
                errors,
            )

    def test_source_evidence_symlink_cannot_escape_its_mapped_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = fixture.contract["evidenceCatalog"][0]
            evidence_file = (
                fixture.source_roots[evidence["sourceId"]]
                / evidence_path(evidence["locator"])
            )
            outside_file = fixture.root / "outside-authorized-source.txt"
            outside_file.write_text("synthetic outside evidence\n", encoding="utf-8")
            evidence_file.unlink()
            try:
                evidence_file.symlink_to(outside_file)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")

            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("symlink", "symbolic link"),
            ("outside", "escape"),
            ("source root", "mapped root", "authorized root"),
        )

    def test_duplicate_capability_graph_node_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["capabilityGraph"]["nodes"].append(
                copy.deepcopy(contract["capabilityGraph"]["nodes"][0])
            )
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("capabilitygraph.nodes", "capability graph node"),
            ("duplicate", "exactly once"),
        )

    def test_duplicate_workflow_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            duplicate = copy.deepcopy(contract["workflows"][0])
            duplicate["workflowId"] = "synthetic-duplicate-workflow"
            contract["workflows"].append(duplicate)
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("workflow",),
            ("duplicate", "exactly one"),
        )

    def test_workflow_membership_must_be_explicit_unique_and_closed(self) -> None:
        for case in ("missing", "entry-omitted", "duplicate", "unknown"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                workflow = contract["workflows"][0]
                entry_id = workflow["entryCapabilityId"]
                if case == "missing":
                    workflow.pop("capabilityIds")
                elif case == "entry-omitted":
                    workflow["capabilityIds"] = [
                        capability["capabilityId"]
                        for capability in contract["capabilities"]
                        if capability["capabilityId"] != entry_id
                    ][:1]
                elif case == "duplicate":
                    workflow["capabilityIds"].append(entry_id)
                else:
                    workflow["capabilityIds"].append("unknown-fictional-capability")
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("capabilityids",),
                ("must be an array", "include", "duplicate", "unknown"),
            )

    def test_duplicate_verification_matrix_row_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            matrix_path = fixture.candidate / "verification-matrix.json"
            matrix = read_json(matrix_path)
            matrix["capabilities"].append(copy.deepcopy(matrix["capabilities"][0]))
            write_json(matrix_path, matrix)
            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("verification-matrix",),
            ("duplicate", "exactly once"),
        )

    def test_workflow_host_verification_requires_every_declared_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            workflow = contract["workflows"][0]
            member_id = next(
                capability["capabilityId"]
                for capability in contract["capabilities"]
                if capability["capabilityId"] != workflow["entryCapabilityId"]
            )
            workflow["capabilityIds"].append(member_id)
            fixture.save_contract_and_derive(contract)

            compatibility_path = fixture.candidate / "host-compatibility-report.json"
            compatibility = read_json(compatibility_path)
            assessment = next(
                item for item in compatibility["capabilityAssessments"]
                if item["capabilityId"] == member_id
            )
            assessment["status"] = "disabled"
            write_json(compatibility_path, compatibility)

            matrix_path = fixture.candidate / "verification-matrix.json"
            matrix = read_json(matrix_path)
            workflow_row = next(
                item for item in matrix["workflows"]
                if item["workflowId"] == workflow["workflowId"]
            )
            workflow_row["status"].update({
                "generated": True,
                "behaviorVerified": True,
                "runtimeVerified": True,
                "hostVerified": True,
                "bypassVerified": True,
                "requiresReview": False,
                "blocked": False,
            })
            write_json(matrix_path, matrix)
            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("verification-matrix.workflows", "hostverified"),
            ("every covered capability",),
        )

    def test_unknown_goal_completion_operator_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["goals"][0]["completionPredicate"]["operator"] = (
                "synthetic-unknown-operator"
            )
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("completionpredicate.operator", "completion predicate"),
            ("not an allowed", "unknown", "unsupported", "invalid"),
        )

    def test_system_produced_goal_information_cannot_fall_back_to_user_input(self) -> None:
        mutations = (
            (
                "derived-user",
                lambda contract, need: need.update({"satisfiedBy": [{"kind": "user"}]}),
            ),
            (
                "unsupported-local-derived",
                lambda contract, need: need.update({"satisfiedBy": [{"kind": "derived"}]}),
            ),
            (
                "dynamic-user",
                lambda contract, need: (
                    need.update({"classification": "dynamic", "satisfiedBy": [{"kind": "user"}]})
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                goal = next(
                    item for item in contract["goals"]
                    if item["goalId"] == "save-sample-draft"
                )
                need = next(
                    item for item in goal["informationNeeds"]
                    if item["informationId"] == "saved-draft"
                )
                goal["requiredCapabilityIds"] = []
                mutate(contract, need)
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("satisfiedby", "acquisition"),
                ("system-produced", "invalid acquisition kind", "cannot be satisfied by user"),
            )

        defensive_goal = {
            "goalId": "defensive-derived-vector",
            "informationNeeds": [{
                "informationId": "server-result",
                "classification": "derived",
                "satisfiedBy": [{"kind": "user"}],
            }],
            "completionPredicate": {
                "operator": "all-satisfied",
                "informationIds": ["server-result"],
            },
            "agentPolicy": {"stopWhenPredicateSatisfied": True},
        }
        self.assertNotIn(
            "server-result",
            evaluate_goal_state(defensive_goal, {})["askInformationIds"],
        )

    def test_required_when_goal_condition_must_reference_known_information(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            conditional_need = next(
                need
                for goal in contract["goals"]
                for need in goal["informationNeeds"]
                if need["classification"] == "requiredWhen"
            )
            conditional_need["condition"]["path"][0] = (
                "synthetic-unknown-information"
            )
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("condition.path", "condition"),
            ("declared information", "unknown information", "unknown input"),
        )

    def test_conditional_capability_ids_must_be_declared_and_known(self) -> None:
        with self.subTest(case="missing-declaration"):
            with tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                contract["goals"][0].pop("conditionalCapabilityIds")
                errors = self.derive_or_validate(fixture, contract)
            self.assert_diagnostic_contains(
                errors,
                ("conditionalcapabilityids",),
                ("must be declared", "required field", "missing"),
            )

        with self.subTest(case="unknown-capability"):
            with tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                contract["goals"][0]["conditionalCapabilityIds"] = [
                    "synthetic-unknown-capability"
                ]
                errors = self.derive_or_validate(fixture, contract)
            self.assert_diagnostic_contains(
                errors,
                ("conditionalcapabilityids",),
                ("unknown capability",),
            )

    def test_cross_field_constraint_rejects_unknown_input_and_operator(self) -> None:
        for case in ("unknown-input", "unknown-operator"):
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = SyntheticVNextFixture(Path(directory))
                    contract = copy.deepcopy(fixture.contract)
                    constraint = next(
                        item
                        for capability in contract["capabilities"]
                        for item in capability["constraints"]
                        if item["kind"] == "cross-field" and "if" in item
                    )
                    if case == "unknown-input":
                        constraint["if"]["path"][0] = "syntheticMissingInput"
                    else:
                        constraint["then"]["operator"] = "synthetic-unknown-operator"
                    errors = self.derive_or_validate(fixture, contract)

                if case == "unknown-input":
                    self.assert_diagnostic_contains(
                        errors,
                        ("constraint",),
                        ("unknown input", "syntheticmissinginput"),
                    )
                else:
                    self.assert_diagnostic_contains(
                        errors,
                        ("constraint",),
                        ("operator",),
                        ("invalid", "unknown", "unsupported"),
                    )

    def test_vnext_does_not_require_legacy_workflow_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            for relative in validate_artifacts_module.BASE_FILES:
                path = fixture.candidate / relative
                if path.exists():
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.suffix == ".json":
                    write_json(path, {})
                else:
                    path.write_text("synthetic placeholder\n", encoding="utf-8")
            self.assertFalse((fixture.candidate / "workflow.json").exists())
            diagnostics = Diagnostics()
            writes = {"synthetic-write": {"sideEffect": "create"}}
            with (
                mock.patch.object(
                    validate_artifacts_module,
                    "validate_profile",
                    return_value=(set(), "SYNTHETIC_DRY_RUN", None),
                ),
                mock.patch.object(
                    validate_artifacts_module,
                    "validate_bundle",
                    return_value=writes,
                ),
                mock.patch.object(validate_artifacts_module, "validate_draft"),
                mock.patch.object(validate_artifacts_module, "validate_runtime"),
                mock.patch.object(validate_artifacts_module, "validate_documents"),
                mock.patch.object(
                    validate_artifacts_module,
                    "validate_vnext_artifacts",
                ),
            ):
                validate_artifacts_module.validate(
                    fixture.candidate,
                    fixture.root / "unused-source",
                    True,
                    diagnostics,
                    fixture.source_roots,
                )

        self.assertEqual(diagnostics.errors, [])

    def test_hard_workflow_bindings_are_source_defined_not_an_upload_formula(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            fixture.derive()
            errors = fixture.validate()

        self.assertEqual(errors, [])
        binding_sets = [
            {binding["name"] for binding in workflow["bindings"]}
            for workflow in fixture.contract["workflows"]
        ]
        self.assertNotEqual(binding_sets[0], binding_sets[1])
        for workflow in fixture.contract["workflows"]:
            self.assertEqual(
                workflow["guardAsset"],
                "portable-workflow-guard.mjs#dispatchWithPolicy",
            )
            self.assertTrue(all(
                binding["expectedSource"]["kind"] in {
                    "protected-runtime-state",
                    "constant",
                }
                for binding in workflow["bindings"]
            ))

    def test_write_function_cannot_call_fetch_before_guard_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            function_path = fixture.candidate / "function-core" / "index.mjs"
            source = function_path.read_text(encoding="utf-8")
            modified = source.replace(
                "  return workflowGuard.",
                "  await fetch('https://example.invalid/direct-write');\n"
                "  return workflowGuard.",
                1,
            )
            self.assertNotEqual(source, modified)
            function_path.write_text(modified, encoding="utf-8")
            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("external side effect", "fetch"),
            ("before its guard", "before guard", "before guarded dispatch"),
        )

    def test_write_function_cannot_hide_pre_guard_side_effect_behind_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            function_path = fixture.candidate / "function-core" / "index.mjs"
            source = function_path.read_text(encoding="utf-8")
            modified = source.replace(
                "  return workflowGuard.",
                "  const hiddenWrite = context.writeFileSync;\n"
                "  hiddenWrite('/synthetic/path', 'value');\n"
                "  return workflowGuard.",
                1,
            )
            self.assertNotEqual(source, modified)
            function_path.write_text(modified, encoding="utf-8")
            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("aliased external side effect",),
            ("before", "guard"),
        )

    def test_workflow_expected_values_cannot_come_from_public_tool_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["workflows"][0]["bindings"][0]["expectedSource"] = {
                "kind": "capability-input",
                "inputName": "hostAttachmentGrant",
            }

            errors = self.derive_or_validate(fixture, contract)

        self.assertIn("never a public Tool argument", "\n".join(errors))

    def test_write_function_cannot_receive_or_pass_expected_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            function_path = fixture.candidate / "function-core" / "index.mjs"
            source = function_path.read_text(encoding="utf-8")
            modified = source.replace(
                "operationKey: protectedWorkflowState.operationKey",
                "expectedBindings: bindings,\n    operationKey: protectedWorkflowState.operationKey",
                1,
            )
            self.assertNotEqual(source, modified)
            function_path.write_text(modified, encoding="utf-8")

            errors = fixture.validate()

        self.assertIn(
            "must not receive or pass caller-projected workflow bindings",
            "\n".join(errors),
        )

    def test_write_function_cannot_substitute_a_second_public_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            function_path = fixture.candidate / "function-core" / "index.mjs"
            source = function_path.read_text(encoding="utf-8")
            modified = source.replace(
                "    input,\n    runtimeContext: context,",
                "    input: context.publicArguments,\n    runtimeContext: context,",
                1,
            )
            self.assertNotEqual(source, modified)
            function_path.write_text(modified, encoding="utf-8")

            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("exact input", "substitute"),
            ("guard",),
        )

    def test_write_runtime_cannot_use_a_module_global_guard_singleton(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            function_path = fixture.candidate / "function-core" / "index.mjs"
            source = function_path.read_text(encoding="utf-8")
            modified = source.replace(
                "\n\nfunction workflowGuardFor",
                "\n\nconst sharedWorkflowGuard = new PortableWorkflowGuard();"
                "\n\nfunction workflowGuardFor",
                1,
            )
            self.assertNotEqual(source, modified)
            function_path.write_text(modified, encoding="utf-8")
            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("module-global guard", "module global guard", "global guard"),
            ("unrelated subjects", "unrelated sessions", "singleton"),
        )

    def test_portable_guard_executes_positive_and_bypass_matrix(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is required for the portable workflow guard probe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "guard-probe.mjs"
            guard_url = (ASSETS / "portable-workflow-guard.mjs").resolve().as_uri()
            probe.write_text(
                f"""import {{ PortableWorkflowGuard }} from {json.dumps(guard_url)};

const sha256 = "a".repeat(64);
const base = {{
  subjectId: "subject-a",
  sessionId: "session-a",
  target: "synthetic-target",
  payload: {{ title: "synthetic request", count: 2 }},
  expiresAt: 2_000,
}};
const results = {{}};

function newGuard(now = () => 1_000) {{
  return new PortableWorkflowGuard({{ now }});
}}

function issueAttachment(guard, overrides = {{}}) {{
  return guard.issueAttachmentGrant({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    attachmentRef: "opaque:synthetic-attachment",
    fileName: "synthetic-input.bin",
    mediaType: "application/octet-stream",
    sizeBytes: 4,
    sha256,
    expiresAt: base.expiresAt,
    ...overrides,
  }});
}}

async function expectRejected(name, action) {{
  let dispatchCount = 0;
  try {{
    await action(async () => {{
      dispatchCount += 1;
      return {{ ok: true }};
    }});
    results[name] = {{ code: null, dispatchCount }};
  }} catch (error) {{
    results[name] = {{ code: error.code, dispatchCount }};
  }}
}}

async function upload(guard, attachment, dispatch) {{
  const confirmation = guard.issueUploadConfirmationGrant({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    attachmentGrantId: attachment.grantId,
    confirmed: true,
    expiresAt: base.expiresAt,
  }});
  return guard.dispatchUploadOnce({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    attachmentGrantId: attachment.grantId,
    confirmationGrantId: confirmation.grantId,
  }}, dispatch);
}}

function issueSubmitGrants(guard, overrides = {{}}) {{
  const payload = overrides.payload ?? base.payload;
  const subjectId = overrides.subjectId ?? base.subjectId;
  const sessionId = overrides.sessionId ?? base.sessionId;
  const target = overrides.target ?? base.target;
  const expiresAt = overrides.expiresAt ?? base.expiresAt;
  const attachmentGrantIds = overrides.attachmentGrantIds ?? [];
  const validation = guard.issueValidationGrant({{
    subjectId,
    sessionId,
    target,
    payload,
    attachmentGrantIds,
    expiresAt,
  }});
  const confirmation = guard.issueConfirmationGrant({{
    subjectId,
    sessionId,
    target,
    payload,
    validationGrantId: validation.grantId,
    attachmentGrantIds,
    confirmed: true,
    expiresAt,
  }});
  return {{ validation, confirmation, payload, subjectId, sessionId, target, attachmentGrantIds }};
}}

function submitBindings(grants, overrides = {{}}) {{
  return {{
    subjectId: grants.subjectId,
    sessionId: grants.sessionId,
    target: grants.target,
    payload: grants.payload,
    validationGrantId: grants.validation.grantId,
    confirmationGrantId: grants.confirmation.grantId,
    attachmentGrantIds: grants.attachmentGrantIds,
    ...overrides,
  }};
}}

// Complete upload and submit path.
{{
  const guard = newGuard();
  const attachment = issueAttachment(guard);
  let uploadDispatches = 0;
  const uploaded = await upload(guard, attachment, async () => {{
    uploadDispatches += 1;
    return {{ attachmentToken: "opaque:synthetic-upload-result" }};
  }});
  const grants = issueSubmitGrants(guard, {{
    attachmentGrantIds: [uploaded.uploadedAttachmentGrant.grantId],
  }});
  let submitDispatches = 0;
  const submitResult = await guard.dispatchOnce(submitBindings(grants), async () => {{
    submitDispatches += 1;
    return {{ created: true }};
  }});
  results.normal = {{ uploadDispatches, submitDispatches, created: submitResult.created }};
}}

// Attachment input and integrity failures occur before any dispatch.
await expectRejected("localPath", async () => {{
  issueAttachment(newGuard(), {{ attachmentRef: "/tmp/synthetic-input.bin" }});
}});
await expectRejected("unverifiedUrl", async () => {{
  issueAttachment(newGuard(), {{ attachmentRef: "https://example.invalid/synthetic.bin" }});
}});
await expectRejected("hashMismatch", async () => {{
  issueAttachment(newGuard(), {{ sha256: "not-a-valid-sha256" }});
}});
await expectRejected("metadataMismatch", async () => {{
  issueAttachment(newGuard(), {{ sizeBytes: 1_048_577 }});
}});
await expectRejected("uploadMissingConfirmation", async (dispatch) => {{
  const guard = newGuard();
  const attachment = issueAttachment(guard);
  await guard.dispatchUploadOnce({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    attachmentGrantId: attachment.grantId,
    confirmationGrantId: "upload-confirmation:missing",
  }}, dispatch);
}});

// Grant stores are isolated between Guard instances.
await expectRejected("isolatedStore", async () => {{
  const first = newGuard();
  const second = newGuard();
  const attachment = issueAttachment(first);
  second.issueUploadConfirmationGrant({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    attachmentGrantId: attachment.grantId,
    confirmed: true,
    expiresAt: base.expiresAt,
  }});
}});

// Missing protected grants never reach the submit callback.
await expectRejected("missingValidation", async (dispatch) => {{
  const guard = newGuard();
  await guard.dispatchOnce({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    payload: base.payload,
    validationGrantId: "validation:missing",
    confirmationGrantId: "confirmation:missing",
    attachmentGrantIds: [],
  }}, dispatch);
}});
await expectRejected("missingConfirmation", async (dispatch) => {{
  const guard = newGuard();
  const validation = guard.issueValidationGrant({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    payload: base.payload,
    attachmentGrantIds: [],
    expiresAt: base.expiresAt,
  }});
  await guard.dispatchOnce({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    payload: base.payload,
    validationGrantId: validation.grantId,
    confirmationGrantId: "confirmation:missing",
    attachmentGrantIds: [],
  }}, dispatch);
}});
await expectRejected("unapprovedAttachment", async () => {{
  const guard = newGuard();
  const attachment = issueAttachment(guard);
  guard.issueValidationGrant({{
    subjectId: base.subjectId,
    sessionId: base.sessionId,
    target: base.target,
    payload: base.payload,
    attachmentGrantIds: [attachment.grantId],
    expiresAt: base.expiresAt,
  }});
}});

// Payload, identity, session, and expiry are bound before dispatch.
await expectRejected("payloadMismatch", async (dispatch) => {{
  const guard = newGuard();
  const grants = issueSubmitGrants(guard);
  await guard.dispatchOnce(
    submitBindings(grants, {{ payload: {{ ...base.payload, count: 3 }} }}),
    dispatch,
  );
}});
await expectRejected("wrongSubject", async (dispatch) => {{
  const guard = newGuard();
  const grants = issueSubmitGrants(guard);
  await guard.dispatchOnce(submitBindings(grants, {{ subjectId: "subject-b" }}), dispatch);
}});
await expectRejected("wrongSession", async (dispatch) => {{
  const guard = newGuard();
  const grants = issueSubmitGrants(guard);
  await guard.dispatchOnce(submitBindings(grants, {{ sessionId: "session-b" }}), dispatch);
}});
await expectRejected("expired", async (dispatch) => {{
  let clock = 1_000;
  const guard = newGuard(() => clock);
  const grants = issueSubmitGrants(guard);
  clock = 2_001;
  await guard.dispatchOnce(submitBindings(grants), dispatch);
}});

// Successful grants are single-use; the rejected second call dispatches zero times.
{{
  const guard = newGuard();
  const grants = issueSubmitGrants(guard);
  await guard.dispatchOnce(submitBindings(grants), async () => ({{ created: true }}));
  await expectRejected("reuse", async (dispatch) => {{
    await guard.dispatchOnce(submitBindings(grants), dispatch);
  }});
}}

// A thrown dispatch has unknown outcome and consumes the grants before dispatch.
{{
  const guard = newGuard();
  const grants = issueSubmitGrants(guard);
  let firstDispatches = 0;
  let unknownCode = null;
  let automaticRetryAllowed = null;
  try {{
    await guard.dispatchOnce(submitBindings(grants), async () => {{
      firstDispatches += 1;
      throw new Error("synthetic disconnect after dispatch");
    }});
  }} catch (error) {{
    unknownCode = error.code;
    automaticRetryAllowed = error.automaticRetryAllowed;
  }}
  await expectRejected("unknownOutcomeRetry", async (dispatch) => {{
    await guard.dispatchOnce(submitBindings(grants), dispatch);
  }});
  results.unknownOutcome = {{ firstDispatches, unknownCode, automaticRetryAllowed }};
}}

process.stdout.write(JSON.stringify(results));
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(probe)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(result.stdout)

        self.assertEqual(
            observed["normal"],
            {"uploadDispatches": 1, "submitDispatches": 1, "created": True},
        )
        expected_pre_dispatch_codes = {
            "localPath": "LOCAL_PATH_FORBIDDEN",
            "unverifiedUrl": "UNAPPROVED_ATTACHMENT_REFERENCE",
            "hashMismatch": "INVALID_ATTACHMENT",
            "metadataMismatch": "INVALID_ATTACHMENT",
            "uploadMissingConfirmation": "INVALID_GRANT",
            "isolatedStore": "INVALID_GRANT",
            "missingValidation": "INVALID_GRANT",
            "missingConfirmation": "INVALID_GRANT",
            "unapprovedAttachment": "INVALID_GRANT",
            "payloadMismatch": "GRANT_BINDING_MISMATCH",
            "wrongSubject": "GRANT_BINDING_MISMATCH",
            "wrongSession": "GRANT_BINDING_MISMATCH",
            "expired": "EXPIRED_GRANT",
            "reuse": "GRANT_ALREADY_USED",
            "unknownOutcomeRetry": "GRANT_ALREADY_USED",
        }
        for name, expected_code in expected_pre_dispatch_codes.items():
            with self.subTest(name=name):
                self.assertEqual(observed[name]["code"], expected_code)
                self.assertEqual(observed[name]["dispatchCount"], 0)
        self.assertEqual(observed["unknownOutcome"]["firstDispatches"], 1)
        self.assertEqual(
            observed["unknownOutcome"]["unknownCode"],
            "UNKNOWN_DISPATCH_OUTCOME",
        )
        self.assertIs(observed["unknownOutcome"]["automaticRetryAllowed"], False)

    def test_generic_guard_supports_a_simple_non_validation_write(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("Node.js is required for the portable workflow guard probe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe = root / "generic-guard-probe.mjs"
            guard_url = (ASSETS / "portable-workflow-guard.mjs").resolve().as_uri()
            probe.write_text(
                f"""import {{ PortableWorkflowGuard }} from {json.dumps(guard_url)};

const guard = new PortableWorkflowGuard({{
  now: () => 1000,
  protectedOperations: [
    {{
      workflowId: "synthetic-confirmed-delete",
      operationKey: "item-mismatch",
      bindingSources: {{
        itemId: {{ kind: "capability-input", inputName: "itemId", path: [] }},
        trustedDecision: {{ kind: "runtime-context", claim: "trusted-decision", requirementId: "trusted-confirmation", path: ["trustedDecision"] }},
      }},
      expectedBindings: {{ itemId: "item-mismatch", trustedDecision: {{ source: "runtime", approved: true }} }},
      singleUse: true,
      expiresAt: 2000,
    }},
    {{
      workflowId: "synthetic-confirmed-delete",
      operationKey: "item-1",
      bindingSources: {{
        itemId: {{ kind: "capability-input", inputName: "itemId", path: [] }},
        trustedDecision: {{ kind: "runtime-context", claim: "trusted-decision", requirementId: "trusted-confirmation", path: ["trustedDecision"] }},
      }},
      expectedBindings: {{ itemId: "item-1", trustedDecision: {{ source: "runtime", approved: true }} }},
      singleUse: true,
      expiresAt: 2000,
    }},
  ],
}});
const observed = {{ missingDispatches: 0, forgedDispatches: 0, mismatchDispatches: 0, unsupportedDispatches: 0, successfulDispatches: 0, replayDispatches: 0 }};
try {{
  new PortableWorkflowGuard({{
    now: () => 1000,
    protectedOperations: [{{
      workflowId: "synthetic-policy-mismatch",
      operationKey: "mismatch",
      bindingSources: {{ singleUse: {{ kind: "constant", value: true }}, expiresAt: {{ kind: "constant", value: 2000 }} }},
      expectedBindings: {{ singleUse: true, expiresAt: 2000 }},
      singleUse: false,
      expiresAt: 2000,
    }}],
  }});
}} catch (error) {{ observed.policyMismatchCode = error.code; }}
try {{
  await guard.dispatchWithPolicy({{
    workflowId: "synthetic-confirmed-delete",
    input: {{}},
    runtimeContext: {{ trustedDecision: {{ source: "runtime", approved: true }} }},
    operationKey: "item-1",
  }}, async () => {{ observed.missingDispatches += 1; }});
}} catch (error) {{ observed.missingCode = error.code; }}

try {{
  await guard.dispatchWithPolicy({{
    workflowId: "synthetic-confirmed-delete",
    input: {{ itemId: "caller-invented" }},
    runtimeContext: {{ trustedDecision: {{ source: "runtime", approved: true }} }},
    operationKey: "caller-invented",
  }}, async () => {{ observed.forgedDispatches += 1; }});
}} catch (error) {{ observed.forgedCode = error.code; }}

try {{
  await guard.dispatchWithPolicy({{
    workflowId: "synthetic-confirmed-delete",
    input: {{ itemId: "item-mismatch" }},
    runtimeContext: {{ trustedDecision: {{ source: "runtime", approved: false }} }},
    operationKey: "item-mismatch",
  }}, async () => {{ observed.mismatchDispatches += 1; }});
}} catch (error) {{ observed.mismatchCode = error.code; }}

try {{
  await guard.dispatchWithPolicy({{
    workflowId: "synthetic-confirmed-delete",
    input: {{ itemId: "item-1" }},
    runtimeContext: {{ trustedDecision: {{ source: "runtime", approved: true }} }},
    operationKey: "item-1",
    bindings: {{ callerSupplied: true }},
  }}, async () => {{ observed.unsupportedDispatches += 1; }});
}} catch (error) {{ observed.unsupportedCode = error.code; }}

const request = {{
  workflowId: "synthetic-confirmed-delete",
  input: {{ itemId: "item-1", meta: {{ preserved: true }} }},
  runtimeContext: {{ trustedDecision: {{ source: "runtime", approved: true }} }},
  operationKey: "item-1",
}};
await guard.dispatchWithPolicy(request, async (safeInput) => {{
  observed.successfulDispatches += 1;
  observed.safeInput = safeInput;
  observed.frozen = Object.isFrozen(safeInput) && Object.isFrozen(safeInput.meta);
  return {{ deleted: true }};
}});
try {{
  await guard.dispatchWithPolicy(request, async () => {{ observed.replayDispatches += 1; }});
}} catch (error) {{ observed.replayCode = error.code; }}
process.stdout.write(JSON.stringify(observed));
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(probe)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(result.stdout)

        self.assertEqual(observed["missingCode"], "MISSING_BINDING")
        self.assertEqual(observed["policyMismatchCode"], "INVALID_CONFIGURATION")
        self.assertEqual(observed["missingDispatches"], 0)
        self.assertEqual(observed["forgedCode"], "PROTECTED_OPERATION_NOT_FOUND")
        self.assertEqual(observed["forgedDispatches"], 0)
        self.assertEqual(observed["mismatchCode"], "BINDING_MISMATCH")
        self.assertEqual(observed["mismatchDispatches"], 0)
        self.assertEqual(observed["unsupportedCode"], "INVALID_POLICY")
        self.assertEqual(observed["unsupportedDispatches"], 0)
        self.assertEqual(observed["successfulDispatches"], 1)
        self.assertEqual(
            observed["safeInput"],
            {"itemId": "item-1", "meta": {"preserved": True}},
        )
        self.assertIs(observed["frozen"], True)
        self.assertEqual(observed["replayCode"], "OPERATION_ALREADY_USED")
        self.assertEqual(observed["replayDispatches"], 0)

    def test_nested_condition_path_must_resolve_inside_declared_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            validation = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "validate-sample-request"
            )
            attachments = next(
                item for item in validation["inputs"]
                if item["name"] == "attachmentGrants"
            )
            attachments["requiredWhen"][0]["path"] = [
                "selectionGrant",
                "phantomField",
            ]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("requiredwhen", "condition"),
            ("declared", "schema", "resolve"),
        )

    def test_business_upload_result_rejects_any_non_provider_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            validation = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "validate-sample-request"
            )
            attachments = next(
                item for item in validation["inputs"]
                if item["name"] == "attachmentGrants"
            )
            attachments["sourceStrategies"].append({
                "kind": "trusted-host-context",
                "requirementId": "attachment-resolution",
            })
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("business upload results",),
            ("upstream", "business-upload"),
        )

    def test_opaque_attachment_grant_must_be_resolved_not_uploaded_as_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            source = upload["implementation"]["steps"][0]["bindings"][0]["source"]
            source.clear()
            source.update({"kind": "input", "inputName": "hostAttachmentGrant"})
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("attachment-resolution", "metadata"),
            ("resolved", "must not be sent", "exactly once"),
        )

    def test_upload_authorization_without_content_transfer_is_not_a_complete_attachment_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            authorization_step = upload["implementation"]["steps"][0]
            authorization_step["stepId"] = "getUploadAuthorization"
            authorization_step["bindings"] = []
            upload["implementation"]["outputStepId"] = "getUploadAuthorization"
            upload["attachments"]["contentBindings"] = []
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("attachment-resolution", "contentbindings"),
            ("business upload request", "resolved exactly once"),
        )

    def test_attachment_content_binding_must_match_the_real_upload_field(self) -> None:
        mutations = (
            ("declared-path", lambda upload: upload["attachments"]["contentBindings"][0].update({"path": ["notFile"]})),
            ("implementation-path", lambda upload: upload["implementation"]["steps"][0]["bindings"][0].update({"path": ["notFile"]})),
            ("output-step", lambda upload: upload["attachments"]["contentBindings"][0].update({"stepId": "notTheOutputStep"})),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                upload = next(
                    item for item in contract["capabilities"]
                    if item["capabilityId"] == "upload-sample-attachment"
                )
                mutate(upload)
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("contentbinding", "outputstepid"),
                ("exactly cover", "actual business upload request"),
            )

    def test_attachment_content_binding_is_closed_and_evidence_backed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            upload["attachments"]["contentBindings"][0]["hostAdapter"] = "example"
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("contentbinding",),
            ("exclusively", "explicitly"),
        )

    def test_attachment_request_field_requires_fact_level_binding_evidence(self) -> None:
        cases = (
            ("fact-user-entry", "ev-client-goal", None, "request-construction"),
            ("unknown-request-construction", "ev-client-upload-request", "unknown", "fact-level"),
            ("fact-side-effect", "ev-service-attachment", None, "request-construction"),
        )
        for label, evidence_id, assertion_level, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                upload = next(
                    item for item in contract["capabilities"]
                    if item["capabilityId"] == "upload-sample-attachment"
                )
                content_binding = upload["attachments"]["contentBindings"][0]
                implementation_binding = upload["implementation"]["steps"][0]["bindings"][0]
                content_binding["path"] = ["notFile"]
                implementation_binding["path"] = ["notFile"]
                content_binding["evidenceRefs"] = [evidence_id]
                implementation_binding["evidenceRefs"] = [evidence_id]
                if assertion_level is not None:
                    evidence = next(
                        item for item in contract["evidenceCatalog"]
                        if item["evidenceId"] == evidence_id
                    )
                    evidence["assertionLevel"] = assertion_level
                errors = self.derive_or_validate(fixture, contract)

            self.assertIn(expected, "\n".join(errors), errors)

    def test_attachment_declaration_and_runtime_binding_share_request_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            upload["attachments"]["contentBindings"][0]["evidenceRefs"] = [
                "ev-client-upload-request"
            ]
            upload["implementation"]["steps"][0]["bindings"][0]["evidenceRefs"] = [
                "ev-contract-catalog"
            ]
            errors = self.derive_or_validate(fixture, contract)

        self.assertIn("must share its qualifying request-binding evidence", "\n".join(errors))

    def test_resolved_attachment_target_cannot_be_shadowed_by_another_binding(self) -> None:
        for shadow_path in (["file"], ["file", "content"]):
            with self.subTest(shadow_path=shadow_path), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                upload = next(
                    item for item in contract["capabilities"]
                    if item["capabilityId"] == "upload-sample-attachment"
                )
                alternate_input = copy.deepcopy(upload["inputs"][0])
                alternate_input.update({
                    "name": "alternateContent",
                    "description": "Synthetic ordinary input that must not shadow resolved attachment content.",
                    "type": "string",
                    "schema": {"type": "string"},
                    "required": False,
                    "informationClass": "optional",
                    "sourceStrategies": ["user"],
                })
                upload["inputs"].append(alternate_input)
                upload["implementation"]["steps"][0]["bindings"].append({
                    "source": {"kind": "input", "inputName": "alternateContent"},
                    "location": "multipart",
                    "path": shadow_path,
                    "evidenceRefs": ["ev-service-attachment"],
                })
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("request binding target",),
                ("equal", "contain"),
            )

    def test_opaque_upload_boundary_handles_one_host_grant_per_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            second_input = copy.deepcopy(upload["inputs"][0])
            second_input["name"] = "secondHostAttachmentGrant"
            upload["inputs"].append(second_input)
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("exactly one",),
            ("separate calls",),
        )

    def test_attachment_contract_cannot_hide_host_fields_or_skip_proven_guards(self) -> None:
        mutations = (
            (
                "host-extension",
                lambda upload: upload["attachments"].update({"hostPlugin": "platform-local-path"}),
                ("platform-specific", "portable fields"),
            ),
            (
                "wrong-workflow",
                lambda upload: upload["attachments"].update({"enforcedByWorkflow": "different-workflow"}),
                ("protects the business upload", "deterministic workflow"),
            ),
            (
                "missing-success-output",
                lambda upload: upload["successRule"].update({"requiredOutputPaths": []}),
                ("source-defined upload result", "requiredoutputpaths"),
            ),
        )
        for label, mutate, expected in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                upload = next(
                    item for item in contract["capabilities"]
                    if item["capabilityId"] == "upload-sample-attachment"
                )
                mutate(upload)
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(errors, expected)

    def test_host_attachment_resolution_cannot_consume_an_ordinary_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            draft = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "save-sample-draft"
            )
            source = draft["implementation"]["steps"][0]["bindings"][0]["source"]
            source["kind"] = "host_resolved_attachment"
            source["requirementId"] = "attachment-resolution"
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("host_resolved_attachment",),
            ("host-approved", "business upload"),
        )

    def test_attachment_binding_must_reach_the_actual_output_request_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            validation = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "validate-sample-request"
            )
            validation["implementation"]["steps"].append({
                "stepId": "noopOutput",
                "method": "POST",
                "authentication": "runtime_context",
                "url": "https://application.example/api/sample-request/noop",
                "headers": {"accept": "application/json"},
                "bindings": [],
                "successStatusCodes": [200],
                "evidenceRefs": ["ev-service-validation"],
            })
            validation["implementation"]["outputStepId"] = "noopOutput"
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("outputstepid", "final business request"),
            ("attachmentgrants",),
        )

    def test_generic_host_requirement_ids_cannot_swap_facility_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            requirements = {
                item["requirementId"]: item
                for item in contract["consumerRequirements"]["requirements"]
            }
            requirements["authentication-injection"]["hostCapability"], requirements["session-state"]["hostCapability"] = (
                requirements["session-state"]["hostCapability"],
                requirements["authentication-injection"]["hostCapability"],
            )
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("authentication-injection", "session-state"),
            ("must map", "hostcapability"),
        )

    def test_read_only_annotation_cannot_also_be_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            read_capability = next(
                item for item in contract["capabilities"]
                if item["sideEffect"] == "read"
            )
            read_capability["annotations"]["destructiveHint"] = True
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("read-only",),
            ("destructive",),
        )

    def test_portable_core_and_implementation_reject_vendor_runtime_assumptions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["portableCore"]["runtimeAssumption"] = "synthetic-vendor-plugin"
            contract["capabilities"][0]["implementation"]["kind"] = "vendor-plugin"
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("portablecore",),
            ("runtime", "producer", "unsupported"),
        )

    def test_optional_planning_edge_cannot_become_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            edge = next(
                item for item in contract["capabilityGraph"]["edges"]
                if item["kind"] == "optional-planning"
            )
            edge["required"] = True
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("optional planning", "optional-planning"),
            ("mandatory", "must not", "required"),
        )

    def test_workflow_source_paths_must_resolve_and_expected_paths_cannot_be_empty(self) -> None:
        for case in ("phantom-actual", "missing-expected"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                binding = next(
                    item for item in contract["workflows"][0]["bindings"]
                    if item["actualSource"]["kind"] == "capability-input"
                )
                if case == "phantom-actual":
                    binding["actualSource"]["path"] = ["phantomField"]
                else:
                    binding["expectedSource"]["path"] = []
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("workflow", "bindings"),
                ("path", "schema", "state"),
            )

    def test_workflow_subject_claim_cannot_be_relabelled_as_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            binding = next(
                item for item in contract["workflows"][0]["bindings"]
                if item["name"] == "subject"
            )
            binding["actualSource"] = {
                "kind": "runtime-context",
                "claim": "session",
                "requirementId": "session-state",
                "path": ["sessionId"],
            }
            binding["expectedSource"]["path"] = ["subject"]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("runtime claim",),
            ("subject", "session"),
        )

    def test_candidate_cannot_replace_the_reviewed_portable_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            guard = fixture.candidate / "portable-workflow-guard.mjs"
            guard.write_text(
                guard.read_text(encoding="utf-8").replace(
                    "return await dispatch(safeInput);",
                    "return await dispatch(input);",
                    1,
                ),
                encoding="utf-8",
            )
            errors = fixture.validate()

        self.assert_diagnostic_contains(
            errors,
            ("byte-exact", "reviewed"),
            ("guard",),
        )

    def test_canonical_schema_rejects_unenforced_conditional_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            request_data = next(
                item for item in contract["capabilities"][2]["inputs"]
                if item["name"] == "requestData"
            )
            request_data["schema"]["if"] = {
                "properties": {"subject": {"const": "synthetic"}}
            }
            request_data["schema"]["then"] = {"required": ["note"]}
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("unsupported", "unenforced"),
            ("if", "then"),
        )

    def test_security_critical_host_requirement_cannot_weaken_on_missing_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            authentication = next(
                item for item in contract["consumerRequirements"]["requirements"]
                if item["requirementId"] == "authentication-injection"
            )
            authentication["onMissing"] = "requires-host-integration"
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("authentication-injection",),
            ("onmissing", "disable"),
        )

    def test_implementation_rejects_host_or_vendor_extension_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            capability = contract["capabilities"][0]
            capability["implementation"]["hostAdapter"] = "synthetic-host"
            capability["implementation"]["steps"][0]["hostPlugin"] = "synthetic-plugin"
            fixture.save_contract_and_derive(contract)
            diagnostics = Diagnostics()
            bundle = read_json(fixture.candidate / "capability-bundle.json")
            validate_artifacts_module.validate_bundle(
                bundle,
                {"https://application.example"},
                diagnostics,
            )

        self.assert_diagnostic_contains(
            diagnostics.errors,
            ("runtime/host extension", "unsupported"),
            ("hostadapter", "hostplugin"),
        )

    def test_any_satisfied_provider_capabilities_are_alternatives_not_all_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "save-sample-draft"
            )
            goal["completionPredicate"] = {
                "operator": "any-satisfied",
                "informationIds": ["draft-request-data", "saved-draft"],
            }
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("requiredcapabilityids", "optionalcapabilityids"),
            ("derived exactly", "optional"),
        )

    def test_dynamic_consumer_must_inherit_provider_scope_and_freshness_exactly(self) -> None:
        for field, value in (
            ("tenantScoped", False),
            ("freshness", {"ttlSeconds": 600, "refreshWhen": ["expired"]}),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                dynamic_input = next(
                    input_value
                    for capability in contract["capabilities"]
                    for input_value in capability["inputs"]
                    if input_value.get("informationClass") == "dynamic"
                )
                dynamic_input["valueDomain"][field] = value
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("valuedomain", field.lower()),
                ("exactly match", "provider output dynamic domain"),
            )

    def test_dynamic_information_cannot_be_relabelled_as_a_static_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            dynamic_input = next(
                input_value
                for capability in contract["capabilities"]
                for input_value in capability["inputs"]
                if input_value.get("informationClass") == "dynamic"
            )
            dynamic_input["valueDomain"] = {
                "kind": "static",
                "values": ["one-observed-value"],
                "evidenceRefs": ["ev-client-goal"],
            }
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("valuedomain.kind",),
            ("dynamic provider domain", "cannot be frozen"),
        )

    def test_authorized_source_ids_cannot_alias_one_physical_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            aliased_maps = dict(fixture.source_roots)
            aliased_maps["sample-service"] = aliased_maps["sample-client"]
            errors = fixture.validate(aliased_maps)

        self.assert_diagnostic_contains(
            errors,
            ("distinct sourceid",),
            ("distinct authorized roots", "all resolve"),
        )

    def test_evidence_role_must_be_declared_by_its_source_topology_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            client_evidence = next(
                item
                for item in contract["evidenceCatalog"]
                if item["evidenceId"] == "ev-client-goal"
            )
            client_evidence["semanticRole"] = "transport-contract"
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("semanticrole",),
            ("source topology entry",),
        )

    def test_http_contract_facts_cannot_be_backed_only_by_user_entry_evidence(self) -> None:
        mutations = (
            (
                "step",
                lambda capability: capability["implementation"]["steps"][0].update(
                    {"evidenceRefs": ["ev-client-goal"]}
                ),
                ("http operation", "serialization"),
            ),
            (
                "binding",
                lambda capability: capability["implementation"]["steps"][0]["bindings"][0].update(
                    {"evidenceRefs": ["ev-client-goal"]}
                ),
                ("request binding",),
            ),
            (
                "output",
                lambda capability: capability["outputs"][0].update(
                    {"evidenceRefs": ["ev-client-goal"]}
                ),
                ("response field and output schema",),
            ),
            (
                "success-rule",
                lambda capability: capability["successRule"].update(
                    {"evidenceRefs": ["ev-client-goal"]}
                ),
                ("minimum successful response and required output",),
            ),
        )
        for label, mutate, purpose in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = SyntheticVNextFixture(Path(directory))
                contract = copy.deepcopy(fixture.contract)
                capability = next(
                    item
                    for item in contract["capabilities"]
                    if item["capabilityId"] == "list-sample-request-kinds"
                )
                mutate(capability)
                errors = self.derive_or_validate(fixture, contract)

            self.assert_diagnostic_contains(
                errors,
                ("fact-level",),
                purpose,
                ("semanticrole", "appropriate semanticrole"),
            )

    def test_write_cannot_be_downgraded_to_read_while_retaining_write_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            save = next(
                item
                for item in contract["capabilities"]
                if item["capabilityId"] == "save-sample-draft"
            )
            save["sideEffect"] = "read"
            save["operationPolicy"]["sideEffect"] = "read"
            save["annotations"].update({
                "readOnlyHint": True,
                "destructiveHint": False,
            })
            save.pop("runtimeProtection")
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("evidencecoverage",),
            ("declared side effect", "declaredsideeffect", "exactly the evidence categories"),
        )

    def test_write_evidence_cannot_be_borrowed_from_another_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            upload = next(
                item
                for item in contract["capabilities"]
                if item["capabilityId"] == "upload-sample-attachment"
            )
            upload["evidenceCoverage"]["sideEffect"]["evidenceRefs"] = [
                "ev-service-submit"
            ]
            self.assertFalse(write_evidence_complete(upload, contract))
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("operation-bound",),
            ("side-effect evidence",),
        )

    def test_conditional_rule_requires_fact_level_business_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            conditional_input = next(
                input_value
                for capability in contract["capabilities"]
                for input_value in capability["inputs"]
                if input_value.get("requiredWhen")
            )
            conditional_input["requiredWhen"][0]["evidenceRefs"] = ["ev-client-goal"]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("requiredwhen", "evidencerefs"),
            ("fact-level conditional business rule",),
            ("semanticrole", "appropriate semanticrole"),
        )

    def test_goal_must_supply_every_required_capability_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            goal = next(
                item
                for item in contract["goals"]
                if item["goalId"] == "submit-sample-request"
            )
            request_data = next(
                item
                for item in goal["informationNeeds"]
                if item["informationId"] == "request-data"
            )
            request_data["supplies"] = [
                supply
                for supply in request_data["supplies"]
                if supply["capabilityId"] != "submit-sample-request"
            ]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("submit-sample-request.requestdata",),
            ("required capability input", "one exact supplies mapping"),
        )

    def test_required_when_information_dependencies_must_be_acyclic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            goal = next(
                item
                for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            attachment_source = next(
                item
                for item in goal["informationNeeds"]
                if item["informationId"] == "attachment-source"
            )
            approved_attachments = next(
                item
                for item in goal["informationNeeds"]
                if item["informationId"] == "approved-attachments"
            )
            attachment_source["condition"] = {
                "path": ["approved-attachments"],
                "operator": "present",
                "evidenceRefs": ["ev-service-selection"],
            }
            approved_attachments["condition"] = {
                "path": ["attachment-source"],
                "operator": "present",
                "evidenceRefs": ["ev-service-selection"],
            }
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("requiredwhen information dependencies",),
            ("acyclic",),
        )

    def test_every_capability_graph_node_must_belong_to_a_goal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["goals"] = [
                goal
                for goal in contract["goals"]
                if goal["goalId"] != "save-sample-draft"
            ]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("capabilitygraph node",),
            ("partial or complete goal",),
            ("save-sample-draft",),
        )

    def test_dynamic_capability_input_cannot_accept_user_constructed_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            dynamic_input = next(
                input_value
                for capability in contract["capabilities"]
                for input_value in capability["inputs"]
                if input_value.get("informationClass") == "dynamic"
            )
            dynamic_input["sourceStrategies"] = ["user"]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("dynamic information",),
            ("arbitrary user input", "cannot construct"),
        )

    def test_undeclared_derived_calculation_is_not_an_input_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            input_value = contract["capabilities"][0]["inputs"][0]
            input_value["sourceStrategies"] = ["derived-calculation"]
            errors = self.derive_or_validate(fixture, contract)

        self.assert_diagnostic_contains(
            errors,
            ("sourcestrategies",),
            ("derived-calculation", "must be one of"),
        )

    def test_goal_cannot_offer_user_input_for_an_upstream_only_opaque_value(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            approved = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "approved-attachments"
            )
            approved["satisfiedBy"].append({"kind": "user"})

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("every advertised goal acquisition source",),
            ("supplied capability input source strategy",),
        )

    def test_goal_trusted_host_source_must_match_target_requirement(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "submit-sample-request"
            )
            confirmation = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "trusted-confirmation"
            )
            confirmation["satisfiedBy"][0]["requirementId"] = "session-state"

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("every advertised goal acquisition source",),
            ("host requirement", "source strategy"),
        )

    def test_one_goal_value_needs_a_source_compatible_with_every_supplied_input(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            validate = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "validate-sample-request"
            )
            submit = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "submit-sample-request"
            )
            next(
                item for item in validate["inputs"]
                if item["name"] == "requestData"
            )["sourceStrategies"] = ["user"]
            next(
                item for item in submit["inputs"]
                if item["name"] == "requestData"
            )["sourceStrategies"] = [{
                "kind": "trusted-host-context",
                "requirementId": "session-state",
            }]
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "submit-sample-request"
            )
            request_data = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "request-data"
            )
            request_data["satisfiedBy"] = [
                {"kind": "user"},
                {
                    "kind": "trusted-host-context",
                    "requirementId": "session-state",
                },
            ]

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("every advertised goal acquisition source",),
            ("supplied capability input source strategy",),
        )

    def test_optional_goal_information_cannot_supply_a_required_tool_input(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            request_data = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "request-data"
            )
            request_data["classification"] = "optional"

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("optional goal information",),
            ("unconditionally required capability input",),
        )

    def test_goal_required_when_must_match_the_supplied_capability_condition(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            approved = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "approved-attachments"
            )
            approved["condition"]["value"] = False

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("goal condition supplying",),
            ("must match the capability requiredwhen rule",),
        )

    def test_capability_input_cannot_be_required_and_forbidden_by_the_same_condition(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            capability = next(
                item for item in contract["capabilities"]
                if item["capabilityId"] == "validate-sample-request"
            )
            attachment_input = next(
                item for item in capability["inputs"]
                if item["name"] == "attachmentGrants"
            )
            attachment_input["forbiddenWhen"] = copy.deepcopy(
                attachment_input["requiredWhen"]
            )

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("same condition",),
            ("require and forbid",),
        )

    def test_goal_dependency_cycle_including_supplies_and_providers_is_rejected(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            attachment_source = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "attachment-source"
            )
            attachment_source["condition"] = {
                "path": ["approved-attachments"],
                "operator": "present",
                "evidenceRefs": ["ev-service-selection"],
            }

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("goal acquisition, supplies, and activation dependencies",),
            ("acyclic",),
        )

    def test_goal_need_cannot_add_a_fake_output_path_to_change_cardinality(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "save-sample-draft"
            )
            draft = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "draft-request-data"
            )
            draft["path"] = ["*"]
            draft["supplies"][0]["mappingKind"] = "select-one"

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("unsupported information-need fields",),
            ("path",),
        )

    def test_goal_supplies_mapping_must_be_unique_per_capability_input(self) -> None:
        for case in ("same-need", "separate-need"):
            with self.subTest(case=case):
                def mutate(contract: dict[str, Any], case: str = case) -> None:
                    goal = next(
                        item for item in contract["goals"]
                        if item["goalId"] == "save-sample-draft"
                    )
                    draft = next(
                        item for item in goal["informationNeeds"]
                        if item["informationId"] == "draft-request-data"
                    )
                    if case == "same-need":
                        draft["supplies"].append(copy.deepcopy(draft["supplies"][0]))
                        return
                    duplicate = copy.deepcopy(draft)
                    duplicate["informationId"] = "second-draft-request-data"
                    goal["informationNeeds"].append(duplicate)
                    goal["completionPredicate"]["informationIds"].append(
                        duplicate["informationId"]
                    )

                errors = self.contract_mutation_errors(mutate)

                self.assert_diagnostic_contains(
                    errors,
                    ("duplicates a capability input",),
                    ("already supplied", "information mapping"),
                )

    def test_conditional_capability_condition_must_match_its_linked_need(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            goal["conditionalCapabilityIds"] = [{
                "capabilityId": "upload-sample-attachment",
                "condition": {
                    "path": ["request-data", "subject"],
                    "operator": "present",
                    "evidenceRefs": ["ev-service-selection"],
                },
            }]

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("object-form conditional capability",),
            ("same condition", "linked requiredwhen"),
        )

    def test_primitive_goal_need_rejects_a_non_object_schema(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "save-sample-draft"
            )
            saved = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "saved-draft"
            )
            saved["schema"] = "not-a-schema"

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("schema",),
            ("portable json schema object",),
        )

    def test_goal_completion_predicate_rejects_duplicate_information_ids(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "save-sample-draft"
            )
            goal["completionPredicate"]["informationIds"].append("saved-draft")

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("completionpredicate.informationids",),
            ("cover the goal", "duplicate"),
        )

    def test_goal_cannot_override_inactive_conditional_completion_semantics(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "prepare-sample-request"
            )
            goal["completionPredicate"]["conditionalNeedsOnlyWhenActive"] = False

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("conditionalneedsonlywhenactive",),
            ("must be true", "inactive conditional needs"),
        )

    def test_goal_rejects_duplicate_acquisition_sources(self) -> None:
        def mutate(contract: dict[str, Any]) -> None:
            goal = next(
                item for item in contract["goals"]
                if item["goalId"] == "save-sample-draft"
            )
            saved = next(
                item for item in goal["informationNeeds"]
                if item["informationId"] == "saved-draft"
            )
            saved["satisfiedBy"].append(copy.deepcopy(saved["satisfiedBy"][0]))

        errors = self.contract_mutation_errors(mutate)

        self.assert_diagnostic_contains(
            errors,
            ("satisfiedby",),
            ("duplicates an acquisition source",),
        )


if __name__ == "__main__":
    unittest.main()
