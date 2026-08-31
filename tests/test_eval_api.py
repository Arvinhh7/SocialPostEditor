import tempfile
import unittest
from pathlib import Path

from app import main as api
from app.db import Database
from app.evals import DeterministicEvalRunner
from app.models import EvalCaseCreate, EvalGenerationRequest, EvalRunCompareRequest


class EvalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = api.db
        self.original_runner = api.eval_runner
        api.db = Database(Path(self.temp.name) / "test.db")
        api.db.init()
        api.eval_runner = DeterministicEvalRunner(api.db)

    def tearDown(self):
        api.db = self.original_db
        api.eval_runner = self.original_runner
        self.temp.cleanup()

    def _generation(self, text: str, post_id: int) -> int:
        return api.db.save_generation(
            {
                "role_id": 2,
                "request": {"platform": "LinkedIn", "proof_points": []},
                "retrieved": [{"post_id": post_id, "text": "reference"}],
                "draft": text,
                "final_text": text,
                "review": [{"verdict": "PASS", "issues": []}],
                "status": "PASS",
            }
        )

    def test_create_run_read_and_compare(self):
        post = api.db.add_post(
            {"role_id": 2, "title": "RAG", "text": "一篇用于评测检索结果的历史文章，内容足够长并且属于当前角色。"}
        )
        case = api.create_eval_case(
            EvalCaseCreate(
                role_id=2,
                name="API retrieval case",
                input_data={"topic": "RAG", "top_k": 1},
                expected_data={"relevant_post_ids": [post["id"]]},
            )
        )
        first_generation = self._generation("没有无依据数字。", post["id"])
        second_generation = self._generation("仍然没有无依据数字。", post["id"])

        first = api.run_evaluation(
            EvalGenerationRequest(eval_case_id=case["id"], generation_run_id=first_generation)
        )
        second = api.run_evaluation(
            EvalGenerationRequest(eval_case_id=case["id"], generation_run_id=second_generation)
        )
        stored = api.get_eval_run(first["id"])
        comparison = api.compare_evaluation_runs(EvalRunCompareRequest(run_ids=[first["id"], second["id"]]))

        self.assertEqual(api.list_eval_cases(2), [case])
        self.assertEqual(api.get_eval_case(case["id"]), case)
        self.assertEqual(stored["status"], "COMPLETED")
        self.assertEqual(comparison["baseline_run_id"], first["id"])
        self.assertEqual(len(comparison["metrics"]), 4)
        self.assertTrue(all(item["values"][1]["delta_from_baseline"] == 0 for item in comparison["metrics"]))

    def test_comparison_rejects_different_cases(self):
        post = api.db.add_post(
            {"role_id": 2, "title": "RAG", "text": "一篇用于评测检索结果的历史文章，内容足够长并且属于当前角色。"}
        )
        run_ids = []
        for index in range(2):
            case = api.create_eval_case(
                EvalCaseCreate(
                    role_id=2,
                    name=f"case {index}",
                    input_data={"topic": "RAG", "top_k": 1},
                    expected_data={"relevant_post_ids": [post["id"]]},
                )
            )
            generation_id = self._generation("没有数字。", post["id"])
            run_ids.append(
                api.run_evaluation(
                    EvalGenerationRequest(eval_case_id=case["id"], generation_run_id=generation_id)
                )["id"]
            )

        with self.assertRaises(Exception) as context:
            api.compare_evaluation_runs(EvalRunCompareRequest(run_ids=run_ids))
        self.assertEqual(context.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
