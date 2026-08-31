import sqlite3
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app import main as api
from app.db import Database
from app.models import ReviewActionCreate


class ReviewActionModelTests(unittest.TestCase):
    def test_edit_requires_text_and_reject_requires_reason(self):
        with self.assertRaises(ValidationError):
            ReviewActionCreate(action="EDIT")
        with self.assertRaises(ValidationError):
            ReviewActionCreate(action="REJECT")


class ApprovalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.init()

    def tearDown(self):
        self.temp.cleanup()

    def _generation(self, status: str = "PASS") -> int:
        return self.db.save_generation(
            {
                "role_id": 2,
                "request": {"topic": "审批测试", "platform": "xiaohongshu"},
                "retrieved": [],
                "draft": "自动初稿",
                "final_text": "自动审稿后的正文",
                "review": [{"verdict": status, "issues": []}],
                "status": status,
            }
        )

    def test_edit_approve_and_reopen_preserve_audit_history(self):
        run_id = self._generation()
        initial = self.db.get_generation(run_id)
        self.assertEqual(initial["status"], "PASS")
        self.assertEqual(initial["approval_status"], "PENDING_REVIEW")

        edited = self.db.add_review_action(
            run_id,
            ReviewActionCreate(action="EDIT", edited_text="人工修改后的正文", reason="语气更自然").model_dump(),
        )
        self.assertEqual(edited["previous_status"], "PENDING_REVIEW")
        self.assertEqual(edited["resulting_status"], "PENDING_REVIEW")
        self.assertTrue(edited["diff_text"])

        approved = self.db.add_review_action(
            run_id,
            ReviewActionCreate(action="APPROVE", reason="可以使用").model_dump(),
        )
        self.assertEqual(approved["resulting_status"], "APPROVED")
        generation = self.db.get_generation(run_id)
        self.assertEqual(generation["approval_status"], "APPROVED")
        self.assertEqual(generation["current_text"], "人工修改后的正文")

        reopened = self.db.add_review_action(
            run_id,
            ReviewActionCreate(action="EDIT", edited_text="批准后再次修改").model_dump(),
        )
        self.assertEqual(reopened["previous_status"], "APPROVED")
        self.assertEqual(reopened["resulting_status"], "PENDING_REVIEW")
        self.assertEqual(len(self.db.list_review_actions(run_id)), 3)

    def test_reject_and_invalid_transition(self):
        run_id = self._generation()
        rejected = self.db.add_review_action(
            run_id,
            ReviewActionCreate(action="REJECT", reason="事实依据不足").model_dump(),
        )
        self.assertEqual(rejected["resulting_status"], "REJECTED")
        self.assertEqual(self.db.list_review_inbox(2, "REJECTED")[0]["id"], run_id)

        with self.assertRaises(ValueError):
            self.db.add_review_action(run_id, ReviewActionCreate(action="APPROVE").model_dump())
        with self.assertRaises(ValueError):
            self.db.add_review_action(
                run_id,
                ReviewActionCreate(action="EDIT", edited_text="不允许直接重开被拒绝内容").model_dump(),
            )

    def test_failed_generation_cannot_enter_review(self):
        run_id = self.db.start_generation(
            {"role_id": 2, "request": {"topic": "失败"}, "retrieved": [], "status": "RUNNING"}
        )
        self.db.finish_generation(
            run_id,
            {"retrieved": [], "draft": "", "final_text": "", "review": [], "status": "FAILED"},
        )
        self.assertEqual(self.db.get_generation(run_id)["approval_status"], "NOT_APPLICABLE")

        with self.assertRaises(ValueError):
            self.db.add_review_action(run_id, ReviewActionCreate(action="APPROVE").model_dump())

    def test_legacy_generation_schema_is_migrated_without_losing_content(self):
        legacy_path = Path(self.temp.name) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        try:
            conn.executescript(
                """
                CREATE TABLE roles (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    identity_rules TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE generation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    request_json TEXT NOT NULL,
                    retrieved_json TEXT NOT NULL,
                    draft TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO roles VALUES (2, 'legacy', '', '', '2026-01-01T00:00:00+00:00');
                INSERT INTO generation_runs
                (role_id,request_json,retrieved_json,draft,final_text,review_json,status,created_at)
                VALUES (2, '{}', '[]', '旧初稿', '旧终稿', '[]', 'PASS', '2026-01-01T00:00:00+00:00');
                """
            )
            conn.commit()
        finally:
            conn.close()

        migrated = Database(legacy_path)
        migrated.init()
        generation = migrated.get_generation(1)
        self.assertEqual(generation["final_text"], "旧终稿")
        self.assertEqual(generation["human_final_text"], "旧终稿")
        self.assertEqual(generation["approval_status"], "PENDING_REVIEW")


class ApprovalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = api.db
        api.db = Database(Path(self.temp.name) / "test.db")
        api.db.init()

    def tearDown(self):
        api.db = self.original_db
        self.temp.cleanup()

    def test_review_inbox_and_action_api(self):
        run_id = api.db.save_generation(
            {
                "role_id": 2,
                "request": {"topic": "API 审批"},
                "retrieved": [],
                "draft": "初稿",
                "final_text": "自动终稿",
                "review": [{"verdict": "PASS", "issues": []}],
                "status": "PASS",
            }
        )
        inbox = api.review_inbox(2)
        response = api.create_review_action(
            run_id,
            ReviewActionCreate(action="APPROVE", edited_text="批准时直接修改的终稿", reason="人工确认"),
        )

        self.assertEqual(inbox[0]["id"], run_id)
        self.assertEqual(response["approval_status"], "APPROVED")
        self.assertEqual(response["current_text"], "批准时直接修改的终稿")
        self.assertEqual(len(api.list_review_actions(run_id)), 1)


if __name__ == "__main__":
    unittest.main()
