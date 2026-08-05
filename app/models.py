from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    verdict: Literal["PASS", "REVISE"]
    issues: list[str] = Field(default_factory=list)
    revision_instruction: str = ""

