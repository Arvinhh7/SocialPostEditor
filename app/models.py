from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=3000)
    identity_rules: str = Field(default="", max_length=5000)


class PostCreate(BaseModel):
    role_id: int
    title: str = Field(default="", max_length=300)
    text: str = Field(min_length=20)
    platform: str = Field(default="", max_length=80)
    language: str = Field(default="", max_length=40)
    content_type: str = Field(default="", max_length=80)
    topic: str = Field(default="", max_length=300)
    tone: str = Field(default="", max_length=200)
    authenticity: int = Field(default=3, ge=1, le=5)
    published_at: str | None = None
    source_name: str = Field(default="manual", max_length=300)


class RetrievalRequest(BaseModel):
    role_id: int
    topic: str = Field(min_length=1, max_length=1000)
    platform: str = Field(default="LinkedIn", max_length=80)
    language: str = Field(default="zh-CN", max_length=40)
    format: str = Field(default="post", max_length=80)
    tone: str = Field(default="", max_length=200)
    goal: str = Field(default="", max_length=1000)
    audience: str = Field(default="", max_length=500)
    top_k: int = Field(default=4, ge=1, le=10)


class GenerationRequest(BaseModel):
    role_id: int
    topic: str = Field(min_length=1, max_length=1000)
    platform: str = Field(default="LinkedIn", max_length=80)
    language: str = Field(default="zh-CN", max_length=40)
    format: str = Field(default="post", max_length=80)
    goal: str = Field(default="教育受众并建立可信度", max_length=1000)
    audience: str = Field(default="", max_length=500)
    tone: str = Field(default="克制、教育型、基于证据", max_length=200)
    length: str = Field(default="300-500字", max_length=80)
    banned_phrases: list[str] = Field(default_factory=list, max_length=30)
    proof_points: list[str] = Field(default_factory=list, max_length=30)
    cta: str = Field(default="", max_length=500)
    candidates: int = Field(default=1, ge=1, le=3)

    @field_validator("proof_points", "banned_phrases")
    @classmethod
    def clean_items(cls, items: list[str]) -> list[str]:
        return [item.strip() for item in items if item.strip()]


class FeedbackCreate(BaseModel):
    role_id: int
    task_summary: str = Field(default="", max_length=1000)
    draft: str = Field(min_length=1)
    final_text: str = Field(min_length=1)
    reason: str = Field(default="", max_length=3000)
    similarity_rating: int | None = Field(default=None, ge=1, le=5)


class ReviewResult(BaseModel):
    verdict: Literal["PASS", "REVISE", "BLOCKED"]
    issues: list[str] = Field(default_factory=list)
    revision_instruction: str = ""
    blocked_reason: str = ""


class EvidenceContract(BaseModel):
    """Deterministic claim and acceptance boundary for one generation run."""

    version: Literal["1.0"] = "1.0"
    required_points: list[str] = Field(default_factory=list)
    allowed_numeric_claims: list[str] = Field(default_factory=list)
    forbidden_phrases: list[str] = Field(default_factory=list)
    role_rules: str = ""
    reference_post_ids: list[int] = Field(default_factory=list)
    reference_usage: Literal["style_and_reasoning_only"] = "style_and_reasoning_only"
    platform: str = ""
    language: str = ""
    content_format: str = ""
    acceptance: dict[str, float | int] = Field(
        default_factory=lambda: {
            "unsupported_number_count_max": 0,
            "banned_phrase_count_max": 0,
            "copy_similarity_max": 0.72,
        }
    )


class EvalCaseCreate(BaseModel):
    """A versioned, reusable input and expected outcome for evaluation."""

    role_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    input_data: dict[str, Any]
    expected_data: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=30)
    version: str = Field(default="1.0.0", min_length=1, max_length=40)
    active: bool = True

    @field_validator("name", "version")
    @classmethod
    def clean_eval_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_eval_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class EvalRunCreate(BaseModel):
    """One evaluation execution against an existing case or generation."""

    eval_case_id: int = Field(gt=0)
    generation_run_id: int | None = Field(default=None, gt=0)
    config: dict[str, Any] = Field(default_factory=dict)
    status: Literal["RUNNING", "COMPLETED", "FAILED"] = "RUNNING"


class EvalScore(BaseModel):
    """A normalized metric result with a reproducible pass threshold."""

    metric_name: str = Field(min_length=1, max_length=120)
    value: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    passed: bool | None = None
    reason: str = Field(default="", max_length=3000)
    evaluator: str = Field(default="rule", min_length=1, max_length=120)
    version: str = Field(default="1.0.0", min_length=1, max_length=40)

    @field_validator("metric_name", "evaluator", "version")
    @classmethod
    def clean_score_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def derive_passed(self) -> "EvalScore":
        self.passed = self.value >= self.threshold
        return self


class EvalGenerationRequest(BaseModel):
    eval_case_id: int = Field(gt=0)
    generation_run_id: int = Field(gt=0)


class EvalRunCompareRequest(BaseModel):
    run_ids: list[int] = Field(min_length=2, max_length=20)

    @field_validator("run_ids")
    @classmethod
    def clean_run_ids(cls, run_ids: list[int]) -> list[int]:
        if any(run_id <= 0 for run_id in run_ids):
            raise ValueError("run_ids must contain positive integers")
        unique = list(dict.fromkeys(run_ids))
        if len(unique) < 2:
            raise ValueError("run_ids must contain at least two different runs")
        return unique


class ReviewActionCreate(BaseModel):
    action: Literal["EDIT", "APPROVE", "REJECT"]
    edited_text: str | None = None
    reason: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def validate_review_action(self) -> "ReviewActionCreate":
        self.reason = self.reason.strip()
        if self.edited_text is not None:
            self.edited_text = self.edited_text.strip()
        if self.action == "EDIT" and not self.edited_text:
            raise ValueError("edited_text is required for EDIT")
        if self.action == "REJECT" and not self.reason:
            raise ValueError("reason is required for REJECT")
        if self.action == "REJECT" and self.edited_text is not None:
            raise ValueError("edited_text is not allowed for REJECT")
        return self
