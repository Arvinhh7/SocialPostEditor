import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.db import Database
from app.evals import (
    DeterministicEvalRunner,
    retrieval_scores,
    unsupported_number_score,
    xiaohongshu_structure_score,
)
from app.models import EvalCaseCreate, EvalRunCreate, EvalScore


class EvalModelTests(unittest.TestCase):
    def test_score_derives_passed_from_threshold(self):
        passed = EvalScore(metric_name="groundedness", value=0.91, threshold=0.9)
        failed = EvalScore(metric_name="groundedness", value=0.89, threshold=0.9, passed=True)

        self.assertTrue(passed.passed)
        self.assertFalse(failed.passed)

    def test_score_rejects_values_outside_normalized_range(self):
        with self.assertRaises(ValidationError):
            EvalScore(metric_name="groundedness", value=1.1, threshold=0.9)

    def test_case_cleans_duplicate_tags(self):
        case = EvalCaseCreate(
            role_id=2,
            name="  grounded post  ",
            input_data={"topic": "RAG"},
            tags=["rag", " rag ", ""],
        )

        self.assertEqual(case.name, "grounded post")
        self.assertEqual(case.tags, ["rag"])


class DeterministicMetricTests(unittest.TestCase):
    def test_retrieval_metrics(self):
        scores = retrieval_scores([9, 2, 7, 4], [2, 4], 4)
        by_name = {score.metric_name: score for score in scores}

        self.assertEqual(by_name["retrieval_precision_at_4"].value, 0.5)
        self.assertEqual(by_name["retrieval_recall_at_4"].value, 1.0)
        self.assertEqual(by_name["retrieval_mrr_at_4"].value, 0.5)

    def test_retrieval_metrics_require_a_relevant_post(self):
        with self.assertRaises(ValueError):
            retrieval_scores([1, 2], [], 2)

    def test_numeric_groundedness_counts_supported_tokens(self):
        score = unsupported_number_score("提升 42%，持续 3 天", ["实验持续 3 天"])

        self.assertEqual(score.value, 0.5)
        self.assertFalse(score.passed)
        self.assertIn("42%", score.reason)

    def test_xiaohongshu_structure_contract(self):
        body = (
            "第一次做 RAG 时，我以为只要把文章放进数据库就够了。后来才发现，真正困难的是判断检索结果是否有用。"
            "这也是为什么我们先做固定评测集。\n\n"
            "现在每次调整权重都会运行相同案例。分数没有提升，就不替换当前方案。这比凭感觉修改提示词可靠得多。"
        )
        score = xiaohongshu_structure_score("我给 RAG 加了一把尺子", body, ["RAG", "Agent开发"])

        self.assertEqual(score.value, 1.0)
        self.assertTrue(score.passed)


class EvalDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.db.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_eval_case_run_and_score_round_trip(self):
        case_model = EvalCaseCreate(
            role_id=2,
            name="xiaohongshu groundedness",
            input_data={"topic": "第一次做 RAG 的复盘", "top_k": 4},
            expected_data={"required_post_ids": [1, 2]},
            tags=["rag", "xiaohongshu"],
        )
        case = self.db.create_eval_case(case_model.model_dump())

        self.assertEqual(case["input_data"]["top_k"], 4)
        self.assertEqual(case["expected_data"]["required_post_ids"], [1, 2])
        self.assertEqual(self.db.get_eval_case(case["id"]), case)
        self.assertEqual(self.db.list_eval_cases(2), [case])

        run_model = EvalRunCreate(eval_case_id=case["id"], config={"retrieval_mode": "hybrid"})
        run = self.db.create_eval_run(run_model.model_dump())
        self.assertEqual(run["status"], "RUNNING")
        self.assertIsNone(run["completed_at"])

        score_model = EvalScore(
            metric_name="retrieval_precision_at_4",
            value=0.75,
            threshold=0.7,
            reason="3 of 4 retrieved posts are relevant",
            evaluator="deterministic",
        )
        score = self.db.add_eval_score(run["id"], score_model.model_dump())
        self.assertTrue(score["passed"])
        self.assertEqual(self.db.list_eval_scores(run["id"]), [score])
        stored_run = self.db.get_eval_run(run["id"])
        self.assertIsNotNone(stored_run)
        self.assertEqual(stored_run["scores"], [score])

        finished = self.db.finish_eval_run(run["id"], "COMPLETED")
        self.assertIsNotNone(finished)
        self.assertEqual(finished["status"], "COMPLETED")
        self.assertIsNotNone(finished["completed_at"])

    def test_finished_run_rejects_running_status(self):
        case = self.db.create_eval_case(
            EvalCaseCreate(role_id=2, name="case", input_data={"topic": "RAG"}).model_dump()
        )
        run = self.db.create_eval_run(EvalRunCreate(eval_case_id=case["id"]).model_dump())

        with self.assertRaises(ValueError):
            self.db.finish_eval_run(run["id"], "RUNNING")

    def test_runner_scores_a_stored_generation_without_regeneration(self):
        post = self.db.add_post(
            {
                "role_id": 2,
                "title": "RAG 复盘",
                "text": "这是一篇用于检索评测的真实历史文章，主要讨论如何验证 RAG 检索结果是否可靠。",
            }
        )
        generation_id = self.db.save_generation(
            {
                "role_id": 2,
                "request": {"platform": "LinkedIn", "proof_points": ["测试持续 3 天"]},
                "retrieved": [{"post_id": post["id"], "text": post["text"]}],
                "draft": "测试持续 3 天。",
                "final_text": "测试持续 3 天。",
                "review": [{"verdict": "PASS", "issues": []}],
                "status": "PASS",
            }
        )
        case = self.db.create_eval_case(
            EvalCaseCreate(
                role_id=2,
                name="stored generation",
                input_data={"topic": "RAG", "top_k": 1},
                expected_data={"relevant_post_ids": [post["id"]]},
            ).model_dump()
        )

        result = DeterministicEvalRunner(self.db).evaluate_generation(case["id"], generation_id)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(len(result["scores"]), 4)
        self.assertTrue(all(score["passed"] for score in result["scores"]))

    def test_runner_blocks_cross_role_evaluation(self):
        other = self.db.create_role({"name": "Other", "description": "", "identity_rules": ""})
        generation_id = self.db.save_generation(
            {
                "role_id": 2,
                "request": {"platform": "LinkedIn", "proof_points": []},
                "retrieved": [],
                "draft": "draft",
                "final_text": "final",
                "review": [],
                "status": "PASS",
            }
        )
        case = self.db.create_eval_case(
            EvalCaseCreate(role_id=other["id"], name="wrong role", input_data={"topic": "RAG"}).model_dump()
        )

        with self.assertRaises(ValueError):
            DeterministicEvalRunner(self.db).evaluate_generation(case["id"], generation_id)

    def test_runner_scores_xiaohongshu_generation_not_expected_example(self):
        generation_id = self.db.save_generation(
            {
                "role_id": 2,
                "request": {"platform": "xiaohongshu", "proof_points": []},
                "retrieved": [],
                "draft": "太短",
                "final_text": "太短",
                "review": [{"verdict": "PASS", "issues": []}],
                "status": "PASS",
            }
        )
        case = self.db.create_eval_case(
            EvalCaseCreate(
                role_id=2,
                name="score actual xiaohongshu output",
                input_data={"topic": "RAG", "platform": "xiaohongshu"},
                expected_data={
                    "content_package": {
                        "title": "这个期望示例结构完整但不能替代生成结果",
                        "body": "合格的期望示例正文。" * 30 + "\n\n第二段。",
                        "hashtags": ["RAG"],
                    }
                },
            ).model_dump()
        )

        result = DeterministicEvalRunner(self.db).evaluate_generation(case["id"], generation_id)
        score = next(item for item in result["scores"] if item["metric_name"] == "xiaohongshu_structure")
        self.assertEqual(score["value"], 0.25)
        self.assertFalse(score["passed"])

    def test_runner_rejects_blocked_generation(self):
        generation_id = self.db.save_generation(
            {
                "role_id": 2,
                "request": {"platform": "LinkedIn", "proof_points": []},
                "retrieved": [],
                "draft": "draft",
                "final_text": "draft",
                "review": [{"verdict": "BLOCKED", "blocked_reason": "review unavailable"}],
                "status": "BLOCKED",
            }
        )
        case = self.db.create_eval_case(
            EvalCaseCreate(role_id=2, name="blocked output", input_data={"topic": "RAG"}).model_dump()
        )

        with self.assertRaises(ValueError):
            DeterministicEvalRunner(self.db).evaluate_generation(case["id"], generation_id)


if __name__ == "__main__":
    unittest.main()
