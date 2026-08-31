import unittest

from app.llm import LLMError
from app.reviewer import IndependentReviewer


class StubLLM:
    def __init__(self, response: str = "", error: Exception | None = None):
        self.response = response
        self.error = error

    def complete(self, instructions: str, user_input: str, max_output_tokens: int = 1000) -> str:
        if self.error:
            raise self.error
        return self.response


class IndependentReviewerTests(unittest.TestCase):
    def test_reviewer_has_no_database_authority(self):
        reviewer = IndependentReviewer(StubLLM('{"verdict":"PASS","issues":[],"revision_instruction":""}'))
        self.assertFalse(hasattr(reviewer, "db"))

    def test_backend_failure_is_blocked_and_never_passes(self):
        reviewer = IndependentReviewer(StubLLM(error=LLMError("provider unavailable")))
        result = reviewer.evaluate(text="draft", package={}, deterministic_issues=[])
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("provider unavailable", result["blocked_reason"])

    def test_empty_or_invalid_output_is_blocked(self):
        for response in ("", "not json", '{"verdict":"MAYBE"}', '{"verdict":"BLOCKED"}'):
            with self.subTest(response=response):
                reviewer = IndependentReviewer(StubLLM(response))
                result = reviewer.evaluate(text="draft", package={}, deterministic_issues=[])
                self.assertEqual(result["verdict"], "BLOCKED")

    def test_deterministic_issue_overrides_model_pass(self):
        reviewer = IndependentReviewer(StubLLM('{"verdict":"PASS","issues":[],"revision_instruction":""}'))
        result = reviewer.evaluate(
            text="draft",
            package={},
            deterministic_issues=["出现 Evidence Contract 未支持的数字：42%"],
        )
        self.assertEqual(result["verdict"], "REVISE")
        self.assertEqual(len(result["issues"]), 1)


if __name__ == "__main__":
    unittest.main()
