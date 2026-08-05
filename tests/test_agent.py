import tempfile
import unittest
from pathlib import Path

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
        self.assertTrue(self.db.get_generation(result["candidates"][0]["run_id"]))

    def test_unsupported_number_is_rejected(self):
        issues = self.agent._numeric_claim_issues("效果提升 42%", [])
        self.assertTrue(issues)
        self.assertFalse(self.agent._numeric_claim_issues("效果提升 42%", ["已验证提升 42%"] ))

    def test_role_data_does_not_leak(self):
        other = self.db.create_role({"name": "Other voice", "description": "", "identity_rules": ""})
        self.db.add_post({"role_id": other["id"], "title": "secret", "text": "This private role sample must never be retrieved by role two." * 2})
        hits = self.agent.retrieve(2, {"topic": "private role sample", "platform": "", "language": "", "format": "", "tone": ""}, 10)
        self.assertNotIn("secret", {hit["title"] for hit in hits})


if __name__ == "__main__":
    unittest.main()
