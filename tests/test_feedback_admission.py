import sqlite3
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app import main as api
from app.agent import WritingAgent
from app.config import Settings
from app.db import Database
from app.models import FeedbackAdmissionDecision, FeedbackCreate


def feedback_payload(role_id: int = 2, task_summary: str = "AI 品牌内容复盘") -> dict:
    return {
        "role_id": role_id,
        "task_summary": task_summary,
        "draft": "这是需要修改的初稿。",
        "final_text": "这是人工确认后的完整表达，保留真实细节并删除没有依据的承诺。",
        "reason": "删除夸张结论",
        "similarity_rating": 5,
    }


class FeedbackAdmissionModelTests(unittest.TestCase):
    def test_reject_requires_reason(self):
        with self.assertRaises(ValidationError):
            FeedbackAdmissionDecision(action="REJECT")


class FeedbackAdmissionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.db"
        self.db = Database(self.path)
        self.db.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_candidate_is_not_retrieved_until_admitted(self):
        candidate = self.db.add_feedback(feedback_payload())
        settings = Settings(
            database_path=self.path,
            llm_mode="mock",
            llm_provider="openai",
            openai_api_key="",
            openai_base_url="https://api.openai.com/v1",
            openai_model="mock",
            deepseek_api_key="",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="mock",
            retrieval_mode="hybrid",
            retrieval_top_k=3,
            max_rewrite_rounds=2,
        )
        agent = WritingAgent(self.db, settings)

        self.assertEqual(candidate["admission_status"], "CANDIDATE")
        self.assertEqual(agent._feedback_examples(2, {"topic": "AI 品牌内容复盘"}), [])

        decision = self.db.decide_feedback_admission(
            candidate["id"], {"action": "ADMIT", "reason": "可作为稳定写作偏好"}
        )
        examples = agent._feedback_examples(2, {"topic": "AI 品牌内容复盘"})

        self.assertEqual(decision["feedback"]["admission_status"], "ADMITTED")
        self.assertEqual([item["feedback_id"] for item in examples], [candidate["id"]])
        self.assertEqual(len(self.db.list_feedback_admission_actions(candidate["id"])), 1)

    def test_rejected_feedback_stays_out_and_decision_is_terminal(self):
        candidate = self.db.add_feedback(feedback_payload())
        decision = self.db.decide_feedback_admission(
            candidate["id"], {"action": "REJECT", "reason": "这次修改只适用于临时活动"}
        )

        self.assertEqual(decision["feedback"]["admission_status"], "REJECTED")
        self.assertEqual(self.db.list_feedback(2, "ADMITTED"), [])
        with self.assertRaises(ValueError):
            self.db.decide_feedback_admission(candidate["id"], {"action": "ADMIT", "reason": "反复改判"})

    def test_legacy_feedback_is_admitted_to_preserve_existing_behavior(self):
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("DROP TABLE feedback_admission_actions")
            conn.execute("ALTER TABLE feedback RENAME TO feedback_current")
            conn.executescript(
                """
                CREATE TABLE feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL,
                    task_summary TEXT NOT NULL DEFAULT '',
                    draft TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    similarity_rating INTEGER,
                    created_at TEXT NOT NULL
                );
                INSERT INTO feedback
                (role_id,task_summary,draft,final_text,reason,similarity_rating,created_at)
                VALUES (2,'旧反馈','旧初稿','旧终稿','旧原因',5,'2026-01-01T00:00:00+00:00');
                DROP TABLE feedback_current;
                """
            )
            conn.commit()
        finally:
            conn.close()

        migrated = Database(self.path)
        migrated.init()
        row = migrated.list_feedback(2, "ADMITTED")[0]
        self.assertEqual(row["final_text"], "旧终稿")
        self.assertIsNotNone(row["decided_at"])


class FeedbackAdmissionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = api.db
        api.db = Database(Path(self.temp.name) / "test.db")
        api.db.init()

    def tearDown(self):
        api.db = self.original_db
        self.temp.cleanup()

    def test_create_list_and_admit_feedback(self):
        created = api.create_feedback(FeedbackCreate(**feedback_payload()))
        candidates = api.list_feedback(2, "CANDIDATE")
        admitted = api.decide_feedback_admission(
            created["id"], FeedbackAdmissionDecision(action="ADMIT", reason="确认可复用")
        )

        self.assertEqual(candidates[0]["id"], created["id"])
        self.assertEqual(admitted["feedback"]["admission_status"], "ADMITTED")
        self.assertEqual(api.list_feedback_admission_actions(created["id"])[0]["action"], "ADMIT")


if __name__ == "__main__":
    unittest.main()
