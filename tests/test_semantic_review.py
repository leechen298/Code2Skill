from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_SKILL = REPO_ROOT / "skills" / "code2skill-generate" / "SKILL.md"
MAIN_AGENT = (
    REPO_ROOT
    / "skills"
    / "code2skill-generate"
    / "agents"
    / "openai.yaml"
)
FLOW_SKILL = REPO_ROOT / "skills" / "code2skill-review-flow" / "SKILL.md"
FLOW_AGENT = (
    REPO_ROOT
    / "skills"
    / "code2skill-review-flow"
    / "agents"
    / "openai.yaml"
)
SOURCE_SKILL = REPO_ROOT / "skills" / "code2skill-review-source" / "SKILL.md"
SOURCE_AGENT = (
    REPO_ROOT
    / "skills"
    / "code2skill-review-source"
    / "agents"
    / "openai.yaml"
)
ANON_EVALUATION = REPO_ROOT / "docs" / "evaluation.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def frontmatter(text: str) -> str:
    match = re.match(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    if match is None:
        raise AssertionError("Skill must start with YAML frontmatter")
    return match.group("body")


def assert_concepts(
    case: unittest.TestCase,
    text: str,
    concepts: dict[str, tuple[str, ...]],
) -> None:
    for label, alternatives in concepts.items():
        with case.subTest(concept=label):
            case.assertTrue(
                any(value in text for value in alternatives),
                f"{label} must be documented using one of {alternatives!r}",
            )


class SplitReviewSkillsTest(unittest.TestCase):
    def test_three_skills_are_independently_installable(self) -> None:
        expected = (
            ("code2skill-generate", MAIN_SKILL, MAIN_AGENT),
            ("code2skill-review-flow", FLOW_SKILL, FLOW_AGENT),
            ("code2skill-review-source", SOURCE_SKILL, SOURCE_AGENT),
        )
        discovered: list[str] = []

        for name, skill_path, agent_path in expected:
            with self.subTest(skill=name):
                self.assertTrue(skill_path.is_file())
                self.assertTrue(agent_path.is_file())
                metadata = frontmatter(read(skill_path))
                self.assertRegex(metadata, rf"(?m)^name:\s*{re.escape(name)}\s*$")
                self.assertRegex(metadata, r"(?m)^description:\s*\S.+$")
                agent = read(agent_path)
                self.assertIn("display_name:", agent)
                self.assertIn("default_prompt:", agent)
                self.assertIn(f"${name}", agent)
                discovered.append(name)

        self.assertEqual(len(discovered), len(set(discovered)))
        self.assertFalse((REPO_ROOT / "skills" / "code2skill").exists())

    def test_generator_does_not_claim_review_conclusions(self) -> None:
        skill = read(MAIN_SKILL)
        agent = read(MAIN_AGENT)
        removed_reference = (
            REPO_ROOT
            / "skills"
            / "code2skill-generate"
            / "references"
            / "core-semantic-review.md"
        )

        self.assertFalse(removed_reference.exists())
        self.assertNotIn("core-semantic-review.md", skill)
        self.assertIn("不自行声明主流程完整或源码精确", skill)
        self.assertIn("code2skill-review-flow", skill)
        self.assertIn("code2skill-review-source", skill)
        self.assertIn("Do not claim main-flow completeness or source fidelity", agent)
        self.assertIn("$code2skill-review-flow", agent)
        self.assertIn("$code2skill-review-source", agent)

    def test_flow_review_discovers_goals_before_trusting_generated_skills(
        self,
    ) -> None:
        skill = read(FLOW_SKILL)

        assert_concepts(
            self,
            skill,
            {
                "source-first review": ("源码优先",),
                "source-backed goal discovery": (
                    "从源码独立识别主要目标",
                    "从授权源码独立识别主要用户目标",
                ),
                "generated Skills are not the inventory": (
                    "不要把已有 Skill 列表当成目标全集",
                    "不要把已有 Skill 列表当成目标全集",
                ),
                "representative standard path": ("代表性标准路径",),
                "required capabilities": ("必要 Function/MCP",),
                "cross-Tool handoff": ("上下游 Tool 交接",),
                "terminal request": ("终端请求",),
            },
        )
        self.assertLess(
            skill.index("先从源码入口独立识别主要用户目标"),
            skill.index("再读取生成包进行比较"),
        )

    def test_flow_review_uses_lightweight_completion_statuses(self) -> None:
        skill = read(FLOW_SKILL)

        for status in ("`完整`", "`基本可用`", "`阻塞`", "`未验证`"):
            with self.subTest(status=status):
                self.assertIn(status, skill)

        assert_concepts(
            self,
            skill,
            {
                "one path per goal": ("一项目标默认只核对一条代表性标准路径",),
                "missing goal blocker": ("缺少主要 Skill",),
                "missing capability blocker": ("必要 Tool/交接",),
                "wrong request blocker": ("必然形成错误请求",),
                "wrong global prerequisite blocker": ("错误设为全局前置",),
                "live API is a separate boundary": (
                    "未调用真实 API 是单独的验证边界",
                ),
                "complete is scoped": (
                    "不等于逐字段源码精确或真实 API 已验证",
                ),
            },
        )
        self.assertIn("只把 `阻塞` 当成交付前必须修复的问题", skill)

    def test_flow_review_does_not_expand_into_source_fidelity_audit(self) -> None:
        skill = read(FLOW_SKILL)

        self.assertIn("不负责逐字段证明生成结果与源码完全一致", skill)
        self.assertIn("推荐使用 `code2skill-review-source` 深入检查", skill)
        self.assertIn("不重建全部目标、字段和分支矩阵", skill)
        self.assertIn("不深入后端 Service", skill)
        self.assertIn("不生成 Contract、证据矩阵、审核报告", skill)

    def test_source_review_rederives_selected_request_semantics(self) -> None:
        skill = read(SOURCE_SKILL)

        assert_concepts(
            self,
            skill,
            {
                "selected scope": ("待审核的 Skill、主要目标、Tool 或能力范围",),
                "source-first": ("源码优先",),
                "generated claims are untrusted": (
                    "视为未验证假设",
                    "不能作为源码证据",
                ),
                "field provenance": ("字段来源与跨 Tool 交接",),
                "same-name fields": ("同名字段",),
                "deterministic transforms": ("确定性请求转换",),
                "goal-specific chain": ("每个目标自己的调用链",),
                "key imports": ("有限追踪关键 import",),
                "attachment binding": ("业务 URL", "后续请求字段"),
            },
        )
        self.assertLess(
            skill.index("先从源码重新推导目标能力"),
            skill.index("再与 Function、MCP 和 Skill 比较"),
        )

    def test_source_review_does_not_claim_all_goal_completion(self) -> None:
        skill = read(SOURCE_SKILL)

        self.assertIn("不负责重新盘点完整主要目标", skill)
        self.assertIn("不负责从源码重新枚举全部主要目标", skill)
        self.assertIn(
            "不输出 `完整`、`基本可用`、`阻塞`、`未验证` 的全目标状态",
            skill,
        )
        self.assertIn("转交 `code2skill-review-flow`", skill)
        self.assertIn("不要把本 Skill 的结果当成全目标主流程完成度结论", skill)

    def test_both_reviews_are_read_only_offline_and_lightweight(self) -> None:
        for name, path, agent_path in (
            ("flow", FLOW_SKILL, FLOW_AGENT),
            ("source", SOURCE_SKILL, SOURCE_AGENT),
        ):
            with self.subTest(review=name):
                skill = read(path)
                agent = read(agent_path)
                self.assertIn("默认只读、离线、源码优先", skill)
                self.assertIn("调用真实业务接口或写接口", skill)
                self.assertIn("不生成", skill)
                self.assertIn("Stay offline.", agent)
                self.assertIn(
                    "permission to fix does not authorize live API calls",
                    agent,
                )

    def test_readme_documents_short_review_names_and_independent_use(self) -> None:
        readme = read(REPO_ROOT / "README.md")

        self.assertIn(
            "--skill code2skill-generate code2skill-review-flow code2skill-review-source",
            readme,
        )
        self.assertIn("`code2skill-review-flow`：检查用户能否通过主要流程", readme)
        self.assertIn("`code2skill-review-source`：深入检查请求字段", readme)
        self.assertIn("两个 Review Skill 按需独立使用", readme)
        installation = read(REPO_ROOT / "docs" / "installation.md")
        self.assertIn("从 `code2skill` 更名为 `code2skill-generate`", installation)
        self.assertIn(
            'npx skills remove --global --agent "$AGENT_ID" code2skill',
            installation,
        )

    def test_evaluation_discloses_models_without_raw_business_evidence(
        self,
    ) -> None:
        self.assertTrue(ANON_EVALUATION.is_file())
        report = read(ANON_EVALUATION)
        readme = read(REPO_ROOT / "README.md")

        self.assertIn("# Code2Skill 生成结果评估", report)
        self.assertIn("不能用于还原原始业务", report)
        self.assertIn("Function/MCP 能力覆盖与请求正确性合计 **6 分**", report)
        self.assertIn("本次评估不使用三个生成结果各自生成的 Review 报告", report)
        self.assertIn(
            "最终产物无法可靠证明 Producer 实际读取了哪些源码文件",
            report,
        )
        self.assertIn("(docs/evaluation.md)", readme)
        for expected in (
            "| Codex（Ultra） | 2026-07-24 | 47 分 45 秒 | **9.6** | **9.0** | **9.4** |",
            "| Kimi Code（K3） | 2026-07-24 | 约 93 分钟 | **9.5** | **8.0** | **8.9** |",
            "| Codex（High） | 2026-07-24 | 20 分 29 秒 | **9.0** | **7.5** | **8.4** |",
        ):
            with self.subTest(score=expected):
                self.assertIn(expected, report)
        for expected in (
            "| Codex（Ultra） | 2026-07-24 | 47 分 45 秒 | **9.4** |",
            "| Kimi Code（K3） | 2026-07-24 | 约 93 分钟 | **8.9** |",
            "| Codex（High） | 2026-07-24 | 20 分 29 秒 | **8.4** |",
        ):
            with self.subTest(readme_summary=expected):
                self.assertIn(expected, readme)
        self.assertIn("## 生成耗时口径", report)
        self.assertIn("不用于推断模型的一般速度", report)
        for marker in (
            "http://",
            "https://",
            "/Users/",
            "/home/",
            "src/",
            "generated/",
            "localhost",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, report)
        self.assertIsNone(
            re.search(
                r"`[^`\n]*\.(?:vue|jsx?|tsx?|java|mjs)(?::\d+)?`",
                report,
            )
        )
        for concept in (
            "### 体系一：主流程完成度",
            "### 体系二：业务语义精确度",
            "`code2skill-review-flow`",
            "`code2skill-review-source`",
            "主流程完成度 × 60% + 业务语义精确度 × 40%",
        ):
            with self.subTest(evaluation_concept=concept):
                self.assertIn(concept, report)
        self.assertRegex(report, r"评估日期：\d{4}-\d{2}-\d{2}")

    def test_readme_is_a_short_entrypoint_and_links_detailed_docs(self) -> None:
        readme = read(REPO_ROOT / "README.md")
        expected_docs = {
            "installation": REPO_ROOT / "docs" / "installation.md",
            "generated results": REPO_ROOT / "docs" / "generated-results.md",
            "advanced validation": REPO_ROOT / "docs" / "advanced-validation.md",
            "evaluation": ANON_EVALUATION,
        }

        self.assertLessEqual(
            len(readme.splitlines()),
            130,
            "README should remain a concise project entrypoint",
        )
        for label, path in expected_docs.items():
            with self.subTest(document=label):
                self.assertTrue(path.is_file())
                self.assertIn(f"(docs/{path.name})", readme)

        installation = read(expected_docs["installation"])
        for concept in (
            "npx skills add",
            "只安装 Skill",
            "stdio",
            "Streamable HTTP",
            '"command"',
            '"args"',
            '"cwd"',
            '"env"',
            "mcpServers",
            "不是 MCP 协议",
        ):
            with self.subTest(concept=concept):
                self.assertIn(concept, installation)

    def test_review_instructions_are_generic_not_fixture_specific(self) -> None:
        combined = "\n".join((read(FLOW_SKILL), read(SOURCE_SKILL)))

        for forbidden in (
            "HomeKing",
            "homeking",
            "好慷",
            "/leave/options",
            "/leave/submit",
            "staff-apply",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
