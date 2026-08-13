import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_FLOW_SKILL = (
    REPO_ROOT / "skills" / "code2skill-review-flow" / "SKILL.md"
)


class ReviewFlowSkillTest(unittest.TestCase):
    def test_repository_review_flow_records_lightweight_decision_rules(self) -> None:
        skill = REVIEW_FLOW_SKILL.read_text(encoding="utf-8")
        self.assertIn("过度拆分", skill)
        self.assertIn("补问", skill)
        self.assertIn("用户确认", skill)
        self.assertIn("误生成为 Tool", skill)
        self.assertIn("异步状态查询", skill)
        self.assertIn("源码依据", skill)
        self.assertIn("普通业务校验", skill)
        self.assertIn("确定性 Guard", skill)
        self.assertIn("必然提前写入", skill)
        self.assertIn("必然走错分支", skill)
        self.assertIn("P2", skill)
        self.assertIn("代表性主流程", skill)


if __name__ == "__main__":
    unittest.main()
