import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent import WritingAgent
from app.cli import seed
from app.config import Settings
from app.db import Database


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            database_path=Path(self.temp.name) / "test.db", llm_mode="mock", llm_provider="openai", openai_api_key="",
            openai_base_url="https://api.openai.com/v1", openai_model="mock", deepseek_api_key="",
            deepseek_base_url="https://api.deepseek.com", deepseek_model="deepseek-v4-flash", retrieval_mode="hybrid",
            retrieval_top_k=3, max_rewrite_rounds=2,
        )
        self.db = Database(self.settings.database_path)
        self.db.init()
        seed(self.db)
        self.agent = WritingAgent(self.db, self.settings)

    def tearDown(self):
        self.temp.cleanup()

    def test_end_to_end_mock(self):
        profile = self.agent.rebuild_profile(2)
        self.assertEqual(profile["version"], 1)
        result = self.agent.generate({
            "role_id": 2, "topic": "AI 第一推荐是否可信", "platform": "LinkedIn", "language": "zh-CN",
            "format": "教育", "goal": "澄清误区", "audience": "品牌负责人", "tone": "克制",
            "length": "300字", "banned_phrases": ["颠覆行业"], "proof_points": [], "cta": "欢迎交流。", "candidates": 1,
        })
        self.assertTrue(result["retrieved"])
        self.assertEqual(result["candidates"][0]["status"], "PASS")
        self.assertEqual(result["candidates"][0]["approval_status"], "PENDING_REVIEW")
        generation = self.db.get_generation(result["candidates"][0]["run_id"])
        self.assertTrue(generation)
        self.assertEqual(generation["approval_status"], "PENDING_REVIEW")
        self.assertEqual([step["step_name"] for step in generation["steps"]], ["retrieve", "contract", "draft", "review_1", "final"])
        self.assertTrue(all(step["status"] == "COMPLETED" for step in generation["steps"]))
        self.assertTrue(all(step["duration_ms"] >= 0 for step in generation["steps"]))
        contract = generation["steps"][1]["output"]
        self.assertEqual(contract["version"], "1.0")
        self.assertEqual(contract["reference_usage"], "style_and_reasoning_only")
        self.assertEqual(contract["acceptance"]["unsupported_number_count_max"], 0)

    def test_unsupported_number_is_rejected(self):
        issues = self.agent._numeric_claim_issues("效果提升 42%", [])
        self.assertTrue(issues)
        self.assertFalse(self.agent._numeric_claim_issues("效果提升 42%", ["已验证提升 42%"] ))

    def test_evidence_contract_is_deterministic_and_scoped(self):
        references = self.agent.retrieve(2, {"topic": "AI 品牌可见性", "platform": "LinkedIn"}, 2)
        role = self.db.get_role(2)
        contract = self.agent._build_evidence_contract(
            {
                "proof_points": ["测试提升 42%", "测试提升 42%", "不含数字的必要观点"],
                "banned_phrases": ["绝对保证", "绝对保证"],
                "platform": "LinkedIn",
                "language": "zh-CN",
                "format": "教育型短文",
            },
            role,
            references,
        )
        self.assertEqual(contract["required_points"], ["测试提升 42%", "不含数字的必要观点"])
        self.assertEqual(contract["allowed_numeric_claims"], ["测试提升 42%"])
        self.assertEqual(contract["forbidden_phrases"], ["绝对保证"])
        self.assertEqual(contract["reference_post_ids"], [item["post_id"] for item in references])
        self.assertIn("不得虚构", contract["role_rules"])

    def test_role_data_does_not_leak(self):
        other = self.db.create_role({"name": "Other voice", "description": "", "identity_rules": ""})
        self.db.add_post({"role_id": other["id"], "title": "secret", "text": "This private role sample must never be retrieved by role two." * 2})
        hits = self.agent.retrieve(2, {"topic": "private role sample", "platform": "", "language": "", "format": "", "tone": ""}, 10)
        self.assertNotIn("secret", {hit["title"] for hit in hits})

    def test_failed_draft_is_recorded_at_the_exact_step(self):
        with patch.object(self.agent, "_draft", side_effect=RuntimeError("draft provider failed")):
            with self.assertRaises(RuntimeError):
                self.agent.generate(
                    {
                        "role_id": 2,
                        "topic": "失败轨迹测试",
                        "platform": "LinkedIn",
                        "proof_points": [],
                        "candidates": 1,
                    }
                )

        failed_run = self.db.list_generation_runs(2)[0]
        steps = self.db.list_generation_steps(failed_run["id"])
        self.assertEqual(failed_run["status"], "FAILED")
        self.assertEqual([step["step_name"] for step in steps], ["retrieve", "contract", "draft"])
        self.assertEqual(steps[-1]["status"], "FAILED")
        self.assertIn("draft provider failed", steps[-1]["error_message"])

    def test_revision_rounds_have_ordered_steps(self):
        reviews = [
            {"verdict": "REVISE", "issues": ["需要修改"], "revision_instruction": "修改一次"},
            {"verdict": "PASS", "issues": [], "revision_instruction": ""},
        ]
        with patch.object(self.agent, "_review", side_effect=reviews):
            with patch.object(self.agent, "_revise", return_value="修改后的完整正文，保留事实边界并修复评审问题。" * 2):
                result = self.agent.generate(
                    {
                        "role_id": 2,
                        "topic": "重写轨迹测试",
                        "platform": "LinkedIn",
                        "proof_points": [],
                        "candidates": 1,
                    }
                )

        generation = self.db.get_generation(result["candidates"][0]["run_id"])
        self.assertEqual(
            [step["step_name"] for step in generation["steps"]],
            ["retrieve", "contract", "draft", "review_1", "revise_1", "review_2", "final"],
        )

    def test_blocked_reviewer_stops_without_revision_or_human_approval(self):
        blocked = {
            "verdict": "BLOCKED",
            "issues": [],
            "revision_instruction": "",
            "blocked_reason": "Reviewer backend failed",
        }
        with patch.object(self.agent, "_review", return_value=blocked):
            with patch.object(self.agent, "_revise") as revise:
                result = self.agent.generate(
                    {
                        "role_id": 2,
                        "topic": "审核阻塞测试",
                        "platform": "LinkedIn",
                        "proof_points": [],
                        "candidates": 1,
                    }
                )

        candidate = result["candidates"][0]
        generation = self.db.get_generation(candidate["run_id"])
        revise.assert_not_called()
        self.assertEqual(candidate["status"], "BLOCKED")
        self.assertEqual(candidate["approval_status"], "NOT_APPLICABLE")
        self.assertEqual(generation["status"], "BLOCKED")
        self.assertEqual(generation["approval_status"], "NOT_APPLICABLE")
        self.assertEqual(
            [step["step_name"] for step in generation["steps"]],
            ["retrieve", "contract", "draft", "review_1", "final"],
        )


if __name__ == "__main__":
    unittest.main()
