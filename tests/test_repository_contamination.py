from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "code2skill-generate"
TEXT_SUFFIXES = {".json", ".md", ".mjs", ".py", ".yaml", ".yml", ".txt"}
TRANSIENT_COMPONENTS = {".git", ".pytest_cache", "__pycache__"}


def repository_files() -> list[Path]:
    return sorted(
        path
        for path in REPO_ROOT.rglob("*")
        if path.is_file()
        and TRANSIENT_COMPONENTS.isdisjoint(path.relative_to(REPO_ROOT).parts)
    )


class RepositoryContaminationTest(unittest.TestCase):
    def test_vnext_assets_keep_only_authoring_inputs_not_stale_derived_views(self) -> None:
        derived_views = {
            "capability-bundle.json",
            "capability-draft.json",
            "consumer-requirements.json",
            "goal-contract.json",
            "host-compatibility-report.json",
            "verification-matrix.json",
        }
        present = {
            path.name
            for path in (SKILL_ROOT / "assets").iterdir()
            if path.is_file()
        }
        self.assertTrue(derived_views.isdisjoint(present))

    def test_repository_contains_only_product_source_and_tests(self) -> None:
        allowed_top_level = {
            ".gitignore",
            "LICENSE",
            "README.md",
            "README.zh-CN.md",
            "cordis.patch.yml",
            "docs",
            "package.json",
            "skills",
            "tests",
        }
        unexpected = sorted(
            path.name
            for path in REPO_ROOT.iterdir()
            if path.name not in TRANSIENT_COMPONENTS
            and path.name not in allowed_top_level
        )
        self.assertEqual(unexpected, [])

        allowed_skill_entries = {
            "SKILL.md",
            "agents",
            "assets",
            "references",
            "scripts",
        }
        unexpected_skill_entries = sorted(
            path.name
            for path in SKILL_ROOT.iterdir()
            if path.name not in allowed_skill_entries
        )
        self.assertEqual(unexpected_skill_entries, [])

    def test_no_external_snapshots_or_private_evaluation_artifact_directories(self) -> None:
        forbidden_components = {
            "customer-data",
            "external-sources",
            "fixtures",
            "generated",
            "golden",
            "private-evaluator",
            "recordings",
            "source-snapshots",
        }
        contaminated: list[str] = []
        for path in repository_files():
            relative = path.relative_to(REPO_ROOT)
            if forbidden_components & {part.lower() for part in relative.parts[:-1]}:
                contaminated.append(relative.as_posix())
        self.assertEqual(contaminated, [])

    def test_no_machine_specific_home_paths_or_secret_bearing_files(self) -> None:
        forbidden_file_names = {
            ".env",
            ".env.local",
            "credentials.json",
            "id_ed25519",
            "id_rsa",
        }
        forbidden_suffixes = {".jks", ".key", ".keystore", ".p12", ".pem"}
        unsafe_files = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in repository_files()
            if path.name.lower() in forbidden_file_names
            or path.suffix.lower() in forbidden_suffixes
        ]
        self.assertEqual(unsafe_files, [])

        home_patterns = (
            re.compile(re.escape("/" + "Users" + "/") + r"[^/\s]+/"),
            re.compile(re.escape("/" + "home" + "/") + r"[^/\s]+/"),
            re.compile(r"[A-Za-z]:\\(?:" + "Users" + r"|Documents and Settings)\\"),
        )
        leaked_paths: list[str] = []
        for path in repository_files():
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(text) for pattern in home_patterns):
                leaked_paths.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(leaked_paths, [])

    def test_portable_templates_use_relative_synthetic_evidence(self) -> None:
        contract = json.loads(
            (SKILL_ROOT / "assets" / "canonical-contract.json").read_text(
                encoding="utf-8"
            )
        )
        topology = json.loads(
            (SKILL_ROOT / "assets" / "source-topology.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(contract["contractId"].startswith("synthetic-"))
        self.assertTrue(topology["topologyId"].startswith("synthetic-"))

        source_ids = {source["sourceId"] for source in topology["sources"]}
        self.assertTrue(source_ids)
        self.assertTrue(all(source_id.startswith("sample-") for source_id in source_ids))
        for source in topology["sources"]:
            root = Path(source["root"])
            self.assertFalse(root.is_absolute())
            self.assertNotIn("..", root.parts)

        for evidence in contract["evidenceCatalog"]:
            self.assertIn(evidence["sourceId"], source_ids)
            locator = evidence["locator"].split("#", 1)[0].split(":", 1)[0]
            path = Path(locator)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertIsNone(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", locator))

    def test_vnext_document_assets_match_portable_contracts(self) -> None:
        profile = json.loads(
            (SKILL_ROOT / "assets" / "export-profile.json").read_text(
                encoding="utf-8"
            )
        )
        context = (SKILL_ROOT / "assets" / "feature-context.md").read_text(
            encoding="utf-8"
        )
        setup = (SKILL_ROOT / "assets" / "MCP-SETUP.md").read_text(
            encoding="utf-8"
        )
        report_schema = json.loads(
            (
                SKILL_ROOT
                / "assets"
                / "verification-report.schema.json"
            ).read_text(encoding="utf-8")
        )

        self.assertIn(profile["featureSurface"]["kind"], {
            "route",
            "backend-api",
            "rpc",
            "message",
            "worker",
            "other",
        })
        self.assertNotIn("pageRoute", profile)
        self.assertFalse((SKILL_ROOT / "assets" / "PAGE.md").exists())
        self.assertIn("references/feature-context.md", context)
        self.assertIn("证据 ID", context)
        self.assertIn("来源 ID", context)
        self.assertIn("可移植定位符", context)
        self.assertIn("npx skills add", setup)
        self.assertIn("只安装 Skill", setup)
        self.assertIn("stdio", setup)
        self.assertIn("Streamable HTTP", setup)
        self.assertIn("每个独立服务声明必需的基址环境变量", setup)
        self.assertIn("不默认指向测试、预发或生产环境", setup)
        self.assertIn("业务 API 基址不作为公共 Tool 参数", setup)
        for topic in ("MCP 启动", "MCP 注册", "认证", "环境变量"):
            self.assertIn(topic, setup)

        runtime_check = report_schema["$defs"]["passedRuntimeCheck"]
        runtime_requirement = runtime_check["allOf"][1]["required"]
        self.assertEqual(
            runtime_requirement,
            ["toolName", "inputHash", "resultHash"],
        )
        bypass_check = report_schema["$defs"]["passedBypassCheck"]
        self.assertIs(
            bypass_check["allOf"][1]["properties"]["zeroExternalWrites"]["const"],
            True,
        )


if __name__ == "__main__":
    unittest.main()
