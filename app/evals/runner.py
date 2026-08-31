from __future__ import annotations

import re
from typing import Any

from ..db import Database
from ..models import EvalRunCreate, EvalScore
from .metrics import retrieval_scores, unsupported_number_score, xiaohongshu_structure_score


class DeterministicEvalRunner:
    """Score a stored generation without calling an LLM or regenerating content."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _retrieved_ids(retrieved: list[dict[str, Any]]) -> list[int]:
        ids = []
        for item in retrieved:
            post_id = item.get("post_id", item.get("id"))
            if post_id is not None:
                ids.append(int(post_id))
        return ids

    @staticmethod
    def _is_xiaohongshu(platform: str) -> bool:
        return platform.strip().lower() in {"xiaohongshu", "小红书", "red"}

    @staticmethod
    def _content_package(text: str) -> dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0] if lines and len(lines[0]) <= 40 else ""
        hashtags = re.findall(r"(?<!\w)#([\w\u4e00-\u9fff-]+)", text)
        return {"title": title, "body": text, "hashtags": hashtags}

    def evaluate_generation(self, eval_case_id: int, generation_run_id: int) -> dict[str, Any]:
        case = self.db.get_eval_case(eval_case_id)
        if not case:
            raise ValueError("Evaluation case not found")
        generation = self.db.get_generation(generation_run_id)
        if not generation:
            raise ValueError("Generation run not found")
        if int(case["role_id"]) != int(generation["role_id"]):
            raise ValueError("Evaluation case and generation must belong to the same role")
        if generation["status"] not in {"PASS", "REVISE"}:
            raise ValueError("Only completed generation outputs can be evaluated")

        run = self.db.create_eval_run(
            EvalRunCreate(
                eval_case_id=eval_case_id,
                generation_run_id=generation_run_id,
                config={"metric_set": "deterministic_v1"},
            ).model_dump()
        )
        try:
            scores = self._score(case, generation)
            for score in scores:
                self.db.add_eval_score(run["id"], score.model_dump())
            self.db.finish_eval_run(run["id"], "COMPLETED")
        except Exception:
            self.db.finish_eval_run(run["id"], "FAILED")
            raise
        return self.db.get_eval_run(run["id"]) or {}

    def _score(self, case: dict[str, Any], generation: dict[str, Any]) -> list[EvalScore]:
        expected = case["expected_data"]
        request = generation["request"]
        scores: list[EvalScore] = []

        relevant_ids = expected.get("relevant_post_ids", [])
        if relevant_ids:
            top_k = int(case["input_data"].get("top_k", len(generation["retrieved"]) or 1))
            scores.extend(
                retrieval_scores(
                    self._retrieved_ids(generation["retrieved"]),
                    relevant_ids,
                    top_k,
                    expected.get("retrieval_thresholds"),
                )
            )

        proof_points = expected.get("proof_points", request.get("proof_points", []))
        scores.append(unsupported_number_score(generation["final_text"], proof_points))

        platform = str(case["input_data"].get("platform", request.get("platform", "")))
        if self._is_xiaohongshu(platform):
            content = self._content_package(generation["final_text"])
            scores.append(
                xiaohongshu_structure_score(
                    content["title"],
                    content["body"],
                    content["hashtags"],
                )
            )
        return scores
