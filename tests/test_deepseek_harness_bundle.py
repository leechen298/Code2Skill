from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "package.json"
PATCH = REPO_ROOT / "cordis.patch.yml"
SKILLS = (
    "code2skill-generate",
    "code2skill-review-flow",
    "code2skill-review-source",
)


class DeepSeekHarnessBundleTest(unittest.TestCase):
    def test_package_declares_installable_dsh_bundle_without_install_scripts(self) -> None:
        package = json.loads(PACKAGE.read_text(encoding="utf-8"))

        self.assertEqual(package["name"], "@leechen298/code2skill")
        self.assertEqual(
            package["dsh"], {"bundle": {"patch": "./cordis.patch.yml"}}
        )
        self.assertIn("cordis.patch.yml", package["files"])
        self.assertIn("skills", package["files"])
        self.assertNotIn("scripts", package)
        self.assertNotIn("dependencies", package)

    def test_patch_mounts_only_the_packaged_skill_root(self) -> None:
        patch = PATCH.read_text(encoding="utf-8")

        self.assertIn("id: code2skill-bundled-skills", patch)
        self.assertIn("name: '@deepseek-ai/dsh-skill-filesystem'", patch)
        self.assertIn("providerName: code2skill-bundle", patch)
        self.assertIn("includeDefaultRoots: false", patch)
        self.assertIn("watch: false", patch)
        self.assertIn("@leechen298/code2skill/package.json", patch)
        self.assertIn("'skills'", patch)
        self.assertNotIn("prepare", patch)
        self.assertNotIn("postinstall", patch)

    def test_packaged_skills_have_harness_compatible_frontmatter(self) -> None:
        package = json.loads(PACKAGE.read_text(encoding="utf-8"))
        self.assertIn("skills", package["files"])

        for expected_name in SKILLS:
            skill_file = REPO_ROOT / "skills" / expected_name / "SKILL.md"
            raw = skill_file.read_text(encoding="utf-8")
            match = re.match(r"\A---\n(?P<header>.*?)\n---\n", raw, re.DOTALL)
            self.assertIsNotNone(match, skill_file)
            header = match.group("header")
            self.assertIn(f"name: {expected_name}", header)
            description = next(
                (
                    line.removeprefix("description:").strip()
                    for line in header.splitlines()
                    if line.startswith("description:")
                ),
                "",
            )
            self.assertTrue(description, skill_file)
            self.assertRegex(expected_name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


if __name__ == "__main__":
    unittest.main()
