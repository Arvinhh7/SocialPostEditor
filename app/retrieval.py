from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def char_ngrams(text: str, sizes: tuple[int, ...] = (2, 3, 4)) -> list[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    return [normalized[i : i + n] for n in sizes for i in range(max(0, len(normalized) - n + 1))]


def keywords(text: str) -> set[str]:
    tokens = WORD_RE.findall(text.lower())
    latin = {x for x in tokens if len(x) > 1}
    chinese = {"".join(tokens[i : i + 2]) for i in range(len(tokens) - 1) if all("\u4e00" <= c <= "\u9fff" for c in tokens[i : i + 2])}
    return latin | chinese


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(term, 0.0) for term, value in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def tfidf_vectors(texts: list[str]) -> list[dict[str, float]]:
    docs = [Counter(char_ngrams(t)) for t in texts]
    document_frequency = Counter(term for doc in docs for term in doc)
    total = len(docs)
    vectors: list[dict[str, float]] = []
    for doc in docs:
        count = sum(doc.values()) or 1
        vectors.append({term: (freq / count) * (math.log((1 + total) / (1 + document_frequency[term])) + 1) for term, freq in doc.items()})
    return vectors


def _match(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    aa = {x.strip().lower() for x in re.split(r"[,，/|;；]", a) if x.strip()}
    bb = {x.strip().lower() for x in re.split(r"[,，/|;；]", b) if x.strip()}
    return len(aa & bb) / max(1, len(aa | bb))


def _recency(published_at: str | None) -> float:
    if not published_at:
        return 0.5
    try:
        moment = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        years = max(0.0, (datetime.now(timezone.utc) - moment).days / 365.25)
        return math.exp(-years / 2.0)
    except ValueError:
        return 0.5


@dataclass
class RetrievalHit:
    post_id: int
    title: str
    text: str
    final_score: float
    semantic_score: float
    keyword_score: float
    metadata_score: float
    authenticity_score: float
    recency_score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Retriever:
    """Small-corpus retriever with explainable scoring and MMR diversity."""

    def __init__(self, mode: str = "hybrid"):
        self.mode = mode

    @staticmethod
    def post_document(post: dict[str, Any]) -> str:
        return " ".join(str(post.get(k, "")) for k in ("content_type", "topic", "tone", "platform", "language", "title", "text"))

    @staticmethod
    def query_document(query: dict[str, Any]) -> str:
        return " ".join(str(query.get(k, "")) for k in ("topic", "format", "tone", "goal", "audience", "platform", "language"))

    def search(self, posts: list[dict[str, Any]], query: dict[str, Any], top_k: int = 4) -> list[RetrievalHit]:
        if not posts:
            return []
        qtext = self.query_document(query)
        documents = [self.post_document(p) for p in posts]
        vectors = tfidf_vectors([qtext, *documents])
        qvec, dvecs = vectors[0], vectors[1:]
        qkeywords = keywords(qtext)
        candidates: list[tuple[RetrievalHit, dict[str, float]]] = []
        for post, text, vec in zip(posts, documents, dvecs):
            semantic = cosine(qvec, vec)
            pkeywords = keywords(text)
            keyword = len(qkeywords & pkeywords) / max(1, len(qkeywords))
            metadata = (
                _match(str(query.get("platform", "")), str(post.get("platform", ""))) * 0.30
                + _match(str(query.get("language", "")), str(post.get("language", ""))) * 0.25
                + _match(str(query.get("format", "")), str(post.get("content_type", ""))) * 0.20
                + _match(str(query.get("tone", "")), str(post.get("tone", ""))) * 0.25
            )
            authenticity = max(1, min(5, int(post.get("authenticity", 3)))) / 5
            recency = _recency(post.get("published_at"))
            if self.mode == "tfidf":
                final = semantic + authenticity * 0.02
            else:
                final = semantic * 0.60 + keyword * 0.18 + metadata * 0.14 + authenticity * 0.06 + recency * 0.02
            reasons = []
            if semantic > 0.15: reasons.append("内容语义相关")
            if keyword > 0.10: reasons.append("关键词重合")
            if metadata > 0.20: reasons.append("平台/语言/语气匹配")
            if authenticity >= 0.8: reasons.append("高真实性样本")
            hit = RetrievalHit(int(post["id"]), str(post.get("title", "")), str(post["text"]), round(final, 6), round(semantic, 6), round(keyword, 6), round(metadata, 6), round(authenticity, 6), round(recency, 6), "、".join(reasons) or "弱相关候选")
            candidates.append((hit, vec))
        candidates.sort(key=lambda x: x[0].final_score, reverse=True)

        # Maximal Marginal Relevance prevents near-duplicate references from occupying all slots.
        selected: list[tuple[RetrievalHit, dict[str, float]]] = []
        remaining = candidates[: max(top_k * 4, top_k)]
        while remaining and len(selected) < top_k:
            if not selected:
                selected.append(remaining.pop(0))
                continue
            best_i, best_mmr = 0, -999.0
            for i, (hit, vec) in enumerate(remaining):
                redundancy = max(cosine(vec, chosen_vec) for _, chosen_vec in selected)
                mmr = 0.82 * hit.final_score - 0.18 * redundancy
                if mmr > best_mmr:
                    best_i, best_mmr = i, mmr
            selected.append(remaining.pop(best_i))
        return [item[0] for item in selected]

