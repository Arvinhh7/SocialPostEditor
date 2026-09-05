import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main as api
from app.db import Database
from app.models import (
    GenerationRequest,
    PostBulkMetadataUpdate,
    PostMetadataUpdate,
    RoleCreate,
    RoleGenerateDefaults,
    RoleUpdate,
)


class ExperienceImprovementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = api.db
        self.original_agent_db = api.agent.db
        api.db = Database(Path(self.temp.name) / "test.db")
        api.db.init()
        api.agent.db = api.db

    def tearDown(self):
        api.db = self.original_db
        api.agent.db = self.original_agent_db
        self.temp.cleanup()

    def test_role_defaults_apply_only_to_omitted_request_fields(self):
        role = api.create_role(
            RoleCreate(
                name="默认参数角色",
                identity_rules="不能虚构数据",
                default_generate_params=RoleGenerateDefaults(
                    platform="小红书",
                    audience="AI 产品经理",
                    tone="真实、克制",
                    banned_phrases=["绝对领先"],
                ),
            )
        )
        payload = GenerationRequest(
            role_id=role["id"],
            topic="角色默认值测试",
            proof_points=["已经完成本地测试"],
            tone="本次使用更直接的语气",
            banned_phrases=[],
        )

        with patch.object(api.agent, "_generate_effective", return_value={"candidates": []}) as generate:
            response = api.generate(payload)

        effective = generate.call_args.args[0]
        self.assertEqual(effective["platform"], "小红书")
        self.assertEqual(effective["audience"], "AI 产品经理")
        self.assertEqual(effective["tone"], "本次使用更直接的语气")
        self.assertEqual(effective["banned_phrases"], [])
        self.assertEqual(response["effective_request"], effective)

        direct = api.agent.resolve_generation_task(
            {"role_id": role["id"], "topic": "直接调用", "proof_points": []}
        )
        self.assertEqual(direct["platform"], "小红书")
        self.assertEqual(direct["tone"], "真实、克制")

    def test_existing_role_can_add_or_clear_generate_defaults(self):
        updated = api.update_role(
            2,
            RoleUpdate(
                default_generate_params=RoleGenerateDefaults(
                    platform="LinkedIn",
                    tone="基于证据",
                )
            ),
        )
        self.assertEqual(updated["default_generate_params"]["platform"], "LinkedIn")

        cleared = api.update_role(2, RoleUpdate(default_generate_params=None))
        self.assertEqual(cleared["default_generate_params"], {})

    def test_review_inbox_contains_actionable_summary(self):
        run_id = api.db.save_generation(
            {
                "role_id": 2,
                "request": {"topic": "审核摘要"},
                "retrieved": [],
                "draft": "初稿",
                "final_text": "改写后的终稿",
                "review": [
                    {"verdict": "REVISE", "issues": ["包含禁用表达：绝对领先"]},
                    {"verdict": "PASS", "issues": []},
                ],
                "status": "PASS",
            }
        )
        api.db.add_generation_step(
            run_id,
            {
                "step_index": 1,
                "step_name": "revise_1",
                "input": {},
                "output": {"text": "改写后的终稿"},
                "provider": "mock",
                "model": "mock",
                "prompt_version": "revise-v2",
                "duration_ms": 1,
                "status": "COMPLETED",
            },
        )

        summary = api.review_inbox(2)[0]["review_summary"]
        self.assertEqual(summary["auto_status"], "PASS")
        self.assertEqual(summary["review_count"], 2)
        self.assertEqual(summary["rewrite_count"], 1)
        self.assertEqual(summary["issues"], ["包含禁用表达：绝对领先"])
        self.assertIn("经过 1 轮改写", summary["summary_text"])

    def test_bulk_metadata_update_is_role_scoped_and_atomic(self):
        first = api.db.add_post({"role_id": 2, "title": "一", "text": "第一篇正文" * 10})
        second = api.db.add_post({"role_id": 2, "title": "二", "text": "第二篇正文" * 10})
        other_role = api.db.create_role({"name": "其他角色"})
        other = api.db.add_post({"role_id": other_role["id"], "title": "三", "text": "第三篇正文" * 10})

        with self.assertRaises(ValueError):
            api.db.bulk_update_post_metadata(
                2, [first["id"], other["id"]], {"platform": "小红书"}
            )
        self.assertEqual(api.db.get_post(first["id"])["platform"], "")

        response = api.bulk_update_post_metadata(
            PostBulkMetadataUpdate(
                role_id=2,
                post_ids=[first["id"], second["id"], first["id"]],
                changes=PostMetadataUpdate(platform="小红书", authenticity=5),
            )
        )
        self.assertEqual(response["updated_count"], 2)
        self.assertTrue(all(post["platform"] == "小红书" for post in response["posts"]))
        self.assertTrue(all(post["authenticity"] == 5 for post in response["posts"]))

    def test_metadata_title_rejects_whitespace_only(self):
        with self.assertRaises(ValueError):
            PostMetadataUpdate(title="   ")

    def test_review_inbox_is_paginated(self):
        for index in range(3):
            api.db.save_generation(
                {
                    "role_id": 2,
                    "request": {"topic": f"分页 {index}"},
                    "retrieved": [],
                    "draft": "初稿",
                    "final_text": "终稿",
                    "review": [{"verdict": "PASS", "issues": []}],
                    "status": "PASS",
                }
            )
        first_page = api.review_inbox(2, limit=2)
        second_page = api.review_inbox(2, limit=2, offset=2)
        self.assertEqual(len(first_page), 2)
        self.assertEqual(len(second_page), 1)
        self.assertGreater(first_page[0]["id"], first_page[1]["id"])


if __name__ == "__main__":
    unittest.main()
