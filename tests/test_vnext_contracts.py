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
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill"
ASSETS = SKILL_ROOT / "assets"
SCRIPTS = SKILL_ROOT / "scripts"
DERIVER = SCRIPTS / "derive_artifacts.py"

sys.path.insert(0, str(SCRIPTS))

from contract_model import (  # noqa: E402
    derive_bundle,
    derive_consumer_requirements,
    derive_goal_contract,
    derive_host_compatibility,
    derive_verification_matrix,
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
        write_exports: list[str] = []
        for capability in self.contract["capabilities"]:
            if capability["sideEffect"] == "read":
                continue
            dispatch = (
                "dispatchUploadOnce"
                if capability["operationPolicy"]["confirmation"]
                == "upload-confirmation-required"
                else "dispatchOnce"
            )
            write_exports.append(
                "export async function "
                f"{capability['functionExport']}(input, context) {{\n"
                "  const workflowGuard = workflowGuardFor(context);\n"
                f"  return workflowGuard.{dispatch}(input, context);\n"
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
                any("without complete fact-level evidence cannot be ready" in item for item in errors),
                errors,
            )

    def test_every_write_requires_one_workflow_and_the_runtime_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            contract = copy.deepcopy(fixture.contract)
            contract["workflows"].pop()
            write_json(fixture.candidate / "canonical-contract.json", contract)
            result = fixture.derive()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "must map to exactly one deterministic workflow",
                result.stderr,
            )

        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticVNextFixture(Path(directory))
            result = fixture.derive()
            self.assertEqual(result.returncode, 0, result.stderr)
            (fixture.candidate / "portable-workflow-guard.mjs").unlink()
            errors = fixture.validate()
            self.assertTrue(
                any("is required by every vNext write workflow" in item for item in errors),
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
            ("declared information", "unknown information"),
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

    def test_attachment_workflows_require_metadata_hash_and_result_grants(self) -> None:
        cases = {
            "fileName": "upload",
            "mediaType": "upload",
            "sizeBytes": "upload",
            "sha256": "upload",
            "attachmentGrantIds": "submit",
        }
        for missing_binding, workflow_kind in cases.items():
            with self.subTest(missing_binding=missing_binding):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = SyntheticVNextFixture(Path(directory))
                    contract = copy.deepcopy(fixture.contract)
                    if workflow_kind == "upload":
                        capability = next(
                            item
                            for item in contract["capabilities"]
                            if item["operationPolicy"]["confirmation"]
                            == "upload-confirmation-required"
                        )
                    else:
                        capability = next(
                            item
                            for item in contract["capabilities"]
                            if item.get("attachments", {}).get("mode")
                            == "opaque-upload-results"
                            and item["sideEffect"] != "read"
                        )
                    workflow = next(
                        item
                        for item in contract["workflows"]
                        if item["entryCapabilityId"] == capability["capabilityId"]
                    )
                    workflow["bindings"].remove(missing_binding)
                    errors = self.derive_or_validate(fixture, contract)

                self.assert_diagnostic_contains(
                    errors,
                    ("bindings",),
                    (
                        "uploads must bind"
                        if workflow_kind == "upload"
                        else "attachment-consuming writes must bind",
                    ),
                )

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


if __name__ == "__main__":
    unittest.main()
