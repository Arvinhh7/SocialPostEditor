from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import EvalScore


METRIC_VERSION = "1.0.0"
NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?%?")


def _unique_ids(values: Iterable[int], limit: int | None = None) -> list[int]:
    unique = list(dict.fromkeys(int(value) for value in values))
    return unique if limit is None else unique[:limit]


def retrieval_scores(
    retrieved_ids: Iterable[int],
    relevant_ids: Iterable[int],
    k: int,
    thresholds: dict[str, float] | None = None,
) -> list[EvalScore]:
    """Calculate Precision@K, Recall@K and reciprocal rank for one query."""
    if k < 1:
        raise ValueError("k must be at least 1")
    relevant = set(_unique_ids(relevant_ids))
    if not relevant:
        raise ValueError("relevant_ids must contain at least one post id")
    ranked = _unique_ids(retrieved_ids, k)
    matched = [post_id for post_id in ranked if post_id in relevant]
    precision = len(matched) / k
    recall = len(matched) / len(relevant)
    first_rank = next((rank for rank, post_id in enumerate(ranked, start=1) if post_id in relevant), None)
    reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
    limits = {"precision": 0.5, "recall": 0.5, "mrr": 0.5, **(thresholds or {})}
    common = {"evaluator": "deterministic", "version": METRIC_VERSION}
    return [
        EvalScore(
            metric_name=f"retrieval_precision_at_{k}",
            value=precision,
            threshold=limits["precision"],
            reason=f"{len(matched)} of {k} ranked slots contain a relevant post",
            **common,
        ),
        EvalScore(
            metric_name=f"retrieval_recall_at_{k}",
            value=recall,
            threshold=limits["recall"],
            reason=f"retrieved {len(matched)} of {len(relevant)} relevant posts",
            **common,
        ),
        EvalScore(
            metric_name=f"retrieval_mrr_at_{k}",
            value=reciprocal_rank,
            threshold=limits["mrr"],
            reason="no relevant post retrieved" if first_rank is None else f"first relevant post is at rank {first_rank}",
            **common,
        ),
    ]


def numeric_tokens(text: str) -> set[str]:
    return set(NUMBER_PATTERN.findall(text))


def unsupported_number_issues(text: str, proof_points: Iterable[str]) -> list[str]:
    allowed = numeric_tokens(" ".join(proof_points))
    unsupported = sorted(numeric_tokens(text) - allowed)
    return [f"出现 proof_points 未支持的数字：{token}" for token in unsupported]


def unsupported_number_score(
    text: str,
    proof_points: Iterable[str],
    threshold: float = 1.0,
) -> EvalScore:
    used = numeric_tokens(text)
    unsupported = numeric_tokens(text) - numeric_tokens(" ".join(proof_points))
    value = 1.0 if not used else (len(used) - len(unsupported)) / len(used)
    reason = "no unsupported numeric claims"
    if unsupported:
        reason = "unsupported numeric tokens: " + ", ".join(sorted(unsupported))
    return EvalScore(
        metric_name="numeric_claim_groundedness",
        value=value,
        threshold=threshold,
        reason=reason,
        evaluator="deterministic",
        version=METRIC_VERSION,
    )


def xiaohongshu_structure_score(
    title: str,
    body: str,
    hashtags: Iterable[str],
    threshold: float = 0.75,
) -> EvalScore:
    """Check a small, explicit delivery contract rather than subjective writing quality."""
    clean_title = title.strip()
    clean_body = body.strip()
    clean_tags = [tag.strip().lstrip("#") for tag in hashtags if tag.strip().lstrip("#")]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", clean_body) if part.strip()]
    checks = {
        "title_present": 1 <= len(clean_title) <= 40,
        "body_substantial": 80 <= len(clean_body) <= 2000,
        "multiple_paragraphs": len(paragraphs) >= 2,
        "hashtags_present": 1 <= len(clean_tags) <= 10,
    }
    value = sum(checks.values()) / len(checks)
    failed = [name for name, passed in checks.items() if not passed]
    reason = "all required delivery fields pass"
    if failed:
        reason = "failed checks: " + ", ".join(failed)
    return EvalScore(
        metric_name="xiaohongshu_structure",
        value=value,
        threshold=threshold,
        reason=reason,
        evaluator="deterministic",
        version=METRIC_VERSION,
    )
