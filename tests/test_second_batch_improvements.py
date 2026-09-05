import tempfile
import unittest
from pathlib import Path

from app import main as api
from app.db import Database
from app.models import (
    FeedbackBulkAdmissionDecision,
    PostRetrievalStatusUpdate,
    RetrievalFeedbackCreate,
    RoleCloneRequest,
)


class SecondBatchImprovementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = api.db
        api.db = Database(Path(self.temp.name) / "test.db")
        api.db.init()

    def tearDown(self):
        api.db = self.original_db
        self.temp.cleanup()

    @staticmethod
    def feedback_payload(role_id: int, suffix: str) -> dict:
        return {
            "role_id": role_id,
            "task_summary": f"候选反馈 {suffix}",
            "draft": f"初稿 {suffix}",
            "final_text": f"人工终稿 {suffix}",
            "reason": "稳定偏好",
            "similarity_rating": 5,
        }

    def test_role_clone_copies_configuration_but_not_memory(self):
        source = api.db.create_role(
            {
                "name": "源角色",
                "description": "同一作者",
                "identity_rules": "不得虚构数据",
                "default_generate_params": {
                    "platform": "小红书",
                    "tone": "真实克制",
                    "audience": "产品经理",
                },
            }
        )
        api.db.add_post({"role_id": source["id"], "title": "私有文章", "text": "源角色历史文章" * 10})

        cloned = api.clone_role(
            source["id"],
            RoleCloneRequest(
                name="公众号角色",
                default_generate_params_overrides={"platform": "微信公众号", "tone": None},
            ),
        )

        self.assertEqual(cloned["identity_rules"], "不得虚构数据")
        self.assertEqual(cloned["default_generate_params"]["platform"], "微信公众号")
        self.assertEqual(cloned["default_generate_params"]["audience"], "产品经理")
        self.assertNotIn("tone", cloned["default_generate_params"])
        self.assertEqual(api.db.list_posts(cloned["id"]), [])
        self.assertIsNone(api.db.latest_profile(cloned["id"]))

    def test_bulk_feedback_admission_is_role_scoped_and_atomic(self):
        first = api.db.add_feedback(self.feedback_payload(2, "A"))
        second = api.db.add_feedback(self.feedback_payload(2, "B"))
        response = api.decide_feedback_admission_bulk(
            FeedbackBulkAdmissionDecision(
                role_id=2,
                feedback_ids=[first["id"], second["id"], first["id"]],
                action="ADMIT",
                reason="均为稳定偏好",
            )
        )
        self.assertEqual(response["decided_count"], 2)
        self.assertTrue(
            all(item["feedback"]["admission_status"] == "ADMITTED" for item in response["decisions"])
        )

        third = api.db.add_feedback(self.feedback_payload(2, "C"))
        with self.assertRaises(ValueError):
            api.db.decide_feedback_admission_bulk(
                2,
                [first["id"], third["id"]],
                {"action": "REJECT", "reason": "整批应回滚"},
            )
        self.assertEqual(api.db.get_feedback(third["id"])["admission_status"], "CANDIDATE")

    def test_retrieval_feedback_only_accepts_posts_from_the_run(self):
        included = api.db.add_post(
            {"role_id": 2, "title": "被召回文章", "text": "这是一篇被当前任务召回的历史文章。" * 10}
        )
        unrelated = api.db.add_post(
            {"role_id": 2, "title": "未召回文章", "text": "这是一篇没有被当前任务召回的历史文章。" * 10}
        )
        run_id = api.db.save_generation(
            {
                "role_id": 2,
                "request": {"topic": "检索反馈测试"},
                "retrieved": [{"post_id": included["id"], "reason": "测试命中"}],
                "draft": "初稿",
                "final_text": "最终稿",
                "review": [{"verdict": "PASS", "issues": []}],
                "status": "PASS",
            }
        )

        recorded = api.create_generation_retrieval_feedback(
            run_id,
            RetrievalFeedbackCreate(
                post_id=included["id"],
                action="NOT_RELEVANT",
                reason="主题相似但观点不适合本次任务",
            ),
        )
        self.assertEqual(recorded["post_retrieval_status"], "ACTIVE")
        self.assertEqual(recorded["effect"], "RECORDED_ONLY")
        self.assertEqual(len(api.list_generation_retrieval_feedback(run_id)), 1)
        self.assertEqual(api.db.get_generation(run_id)["retrieval_feedback"][0]["post_id"], included["id"])

        with self.assertRaises(ValueError):
            api.db.add_retrieval_feedback(
                run_id,
                {"post_id": unrelated["id"], "action": "NOT_RELEVANT", "reason": "不应接受"},
            )

    def test_retire_and_restore_control_future_rag_candidates(self):
        post = api.db.add_post(
            {
                "role_id": 2,
                "title": "旧风格文章",
                "text": "这篇文章已经过时，不再代表当前表达方式。" * 10,
                "authenticity": 5,
            }
        )
        run_id = api.db.save_generation(
            {
                "role_id": 2,
                "request": {"topic": "旧风格"},
                "retrieved": [{"post_id": post["id"]}],
                "draft": "初稿",
                "final_text": "终稿",
                "review": [{"verdict": "PASS", "issues": []}],
                "status": "PASS",
            }
        )

        retired = api.update_post_retrieval_status(
            post["id"],
            PostRetrievalStatusUpdate(action="RETIRE", reason="风格已经过时"),
        )
        self.assertEqual(retired["post"]["retrieval_status"], "RETIRED")
        self.assertEqual(api.db.list_posts(2, "ACTIVE"), [])
        self.assertEqual(api.db.list_posts(2, "RETIRED")[0]["id"], post["id"])

        restored = api.update_post_retrieval_status(
            post["id"],
            PostRetrievalStatusUpdate(action="RESTORE", reason="人工重新确认"),
        )
        self.assertEqual(restored["post"]["retrieval_status"], "ACTIVE")
        self.assertEqual(api.db.list_posts(2, "ACTIVE")[0]["id"], post["id"])
        actions = api.list_post_retrieval_actions(post["id"])
        self.assertEqual([item["action"] for item in actions], ["RETIRE", "RESTORE"])


if __name__ == "__main__":
    unittest.main()
