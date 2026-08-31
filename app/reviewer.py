from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .llm import LLMClient, LLMError, extract_json
from .models import ReviewResult


class IndependentReviewer:
    """Read-only semantic reviewer with no database or approval authority."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    @staticmethod
    def _blocked(reason: str) -> dict[str, Any]:
        return ReviewResult(
            verdict="BLOCKED",
            issues=[],
            revision_instruction="",
            blocked_reason=reason,
        ).model_dump()

    def evaluate(
        self,
        *,
        text: str,
        package: dict[str, Any],
        deterministic_issues: list[str],
    ) -> dict[str, Any]:
        instructions = (
            "你是只读的独立风格与事实评审器。你只能审查并给出结论，不能改写正文、批准发布或修改任何记录。"
            "检查角色一致性、任务完成度、AI模板感、照抄、虚构事实、宣传强度、CTA 和禁用表达。"
            "逐项对照 Evidence Contract；合同之外的数字、客户结果、案例一律视为问题。"
            "只返回 JSON：{\"verdict\":\"PASS|REVISE\",\"issues\":[...],\"revision_instruction\":\"...\"}。"
        )
        payload = json.dumps(
            {
                "package": package,
                "draft": text,
                "deterministic_issues": deterministic_issues,
            },
            ensure_ascii=False,
        )
        try:
            raw = self.llm.complete(instructions, payload, 1000)
        except LLMError as exc:
            return self._blocked(f"Reviewer backend failed: {exc}")
        if not raw.strip():
            return self._blocked("Reviewer backend returned empty output")
        try:
            review = ReviewResult.model_validate(extract_json(raw))
        except (LLMError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            return self._blocked(f"Reviewer returned an invalid verdict: {exc}")
        if review.verdict == "BLOCKED":
            return self._blocked("Reviewer returned BLOCKED instead of a PASS or REVISE judgment")

        issues = list(dict.fromkeys([*deterministic_issues, *review.issues]))
        if issues:
            review.verdict = "REVISE"
            review.issues = issues
            review.revision_instruction = (
                review.revision_instruction or "逐项修复 issues，不引入 Evidence Contract 之外的新事实。"
            )
        else:
            review.verdict = "PASS"
            review.issues = []
            review.revision_instruction = ""
        return review.model_dump()
