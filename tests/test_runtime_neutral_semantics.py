from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neutral_fixture_factory import (
    REPO_ROOT,
    build_async_candidate,
    build_host_integration_candidate,
    build_http_candidate,
    build_rpc_candidate,
    build_wayb_candidate,
    run_validator,
)


MAIN_SKILL = REPO_ROOT / "skills" / "code2skill-generate" / "SKILL.md"


class RuntimeNeutralRuleTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = MAIN_SKILL.read_text(encoding="utf-8")

    def test_http_scene_rules_remain_documented(self) -> None:
        self.assertIn("HTTP 场景具体规则", self.skill)
        self.assertIn("基于 `fetch`", self.skill)
        self.assertIn("httpStatus", self.skill)
        self.assertIn("bodyText", self.skill)

    def test_non_http_call_semantics_are_documented(self) -> None:
        self.assertIn("RPC：service/method/arguments", self.skill)
        self.assertIn("消息/任务：destination/key/payload", self.skill)
        self.assertIn("应用内 Service", self.skill)

    def test_three_delivery_modes_are_documented(self) -> None:
        self.assertIn("方式 A：可直接运行的薄包装", self.skill)
        self.assertIn("方式 B：原运行时内包装", self.skill)
        self.assertIn("方式 C：需要宿主接入", self.skill)
        self.assertIn("requires-host-integration", self.skill)

    def test_async_submission_does_not_claim_completion(self) -> None:
        self.assertIn("已接收/已入队", self.skill)
        self.assertIn("不得把回执/任务 ID 写成业务完成", self.skill)

    def test_wrapper_does_not_copy_business_implementation(self) -> None:
        self.assertIn("不得把业务方法搬进新 Node 包假装语义等价", self.skill)

    def test_deterministic_transformations_belong_to_function(self) -> None:
        self.assertIn("确定性转换必须由 Function 承担", self.skill)
        self.assertIn("或借开放 Schema/后端权威推卸", self.skill)


class RuntimeNeutralValidatorTest(unittest.TestCase):
    def test_http_candidate_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_http_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MCP discovery, and package tests passed", result.stdout)

    def test_http_candidate_missing_portable_result_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_http_candidate(Path(directory))
            (candidate / "portable-agent-result.mjs").unlink()
            result = run_validator(candidate)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("portable-agent-result.mjs", result.stderr)

    def test_rpc_candidate_passes_without_http_adapter(self) -> None:
        """Validator must accept a non-HTTP core package with fixed operation identity."""
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_rpc_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MCP discovery, and package tests passed", result.stdout)

    def test_rpc_tool_preserves_operation_identity_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_rpc_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_async_candidate_returns_receipt_not_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_async_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MCP discovery, and package tests passed", result.stdout)

    def test_wayb_candidate_wraps_original_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_wayb_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((candidate / "function-core" / "original-runtime.mjs").exists())

    def test_host_integration_candidate_reports_incomplete_runtime_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            candidate = build_host_integration_candidate(Path(directory))
            result = run_validator(candidate)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("runtime verification is incomplete", result.stdout)
            self.assertNotIn("MCP discovery, and package tests passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
