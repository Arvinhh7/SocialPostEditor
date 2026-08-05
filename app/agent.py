from __future__ import annotations

import json
import re
from dataclasses import asdict
from difflib import SequenceMatcher
from typing import Any

from .config import Settings
from .db import Database
from .llm import LLMClient, LLMError, extract_json
from .retrieval import Retriever


DEFAULT_PROFILE = {
    "zh": {"values": [], "voice": "", "openings": "", "rhythm": "", "cta": "", "avoid": []},
    "en": {"values": [], "voice": "", "openings": "", "rhythm": "", "cta": "", "avoid": []},
}


def _clip(text: str, limit: int = 2200) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class WritingAgent:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.llm = LLMClient(settings)
        self.retriever = Retriever(settings.retrieval_mode)

    def rebuild_profile(self, role_id: int) -> dict[str, Any]:
        role = self.db.get_role(role_id)
        if not role:
            raise ValueError("Role not found")
        posts = [p for p in self.db.list_posts(role_id) if int(p.get("authenticity", 3)) >= 4]
        if not posts:
            raise ValueError("At least one post with authenticity >= 4 is required")
        samples = [{"id": p["id"], "language": p["language"], "topic": p["topic"], "text": _clip(p["text"])} for p in posts[:30]]
        instructions = (
            "你是作者画像分析器。根据真实样本总结稳定特征，不推测身份或经历。"
            "只返回 JSON 对象，顶层必须是 zh 和 en；两者各含 values(array), voice, openings, rhythm, cta, avoid(array)。"
        )
        raw = self.llm.complete(instructions, json.dumps({"role": role, "samples": samples}, ensure_ascii=False), 1800)
        profile = extract_json(raw)
        for language in ("zh", "en"):
            profile.setdefault(language, DEFAULT_PROFILE[language])
        return self.db.save_profile(role_id, profile, [int(p["id"]) for p in posts[:30]])

    def retrieve(self, role_id: int, query: dict[str, Any], top_k: int | None = None) -> list[dict[str, Any]]:
        if not self.db.get_role(role_id):
            raise ValueError("Role not found")
        hits = self.retriever.search(self.db.list_posts(role_id), query, top_k or self.settings.retrieval_top_k)
        return [hit.to_dict() for hit in hits]

    def _feedback_examples(self, role_id: int, query: dict[str, Any], top_k: int = 2) -> list[dict[str, str]]:
        rows = self.db.list_feedback(role_id)
        if not rows:
            return []
        pseudo_posts = [
            {
                "id": row["id"], "title": row["task_summary"], "text": row["final_text"],
                "topic": row["task_summary"], "tone": "", "platform": "", "language": "",
                "content_type": "feedback", "authenticity": 5, "published_at": row["created_at"],
            }
            for row in rows
        ]
        ids = {hit.post_id for hit in self.retriever.search(pseudo_posts, query, top_k)}
        return [
            {"draft": _clip(row["draft"], 900), "final_text": _clip(row["final_text"], 900), "reason": row["reason"]}
            for row in rows if row["id"] in ids
        ]

    @staticmethod
    def _numeric_claim_issues(text: str, proof_points: list[str]) -> list[str]:
        allowed = " ".join(proof_points)
        issues = []
        for token in set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?", text)):
            if token not in allowed:
                issues.append(f"出现 proof_points 未支持的数字：{token}")
        return issues

    @staticmethod
    def _copy_issues(text: str, references: list[dict[str, Any]]) -> list[str]:
        issues = []
        for reference in references:
            ratio = SequenceMatcher(None, re.sub(r"\s+", "", text), re.sub(r"\s+", "", reference["text"])).ratio()
            if ratio > 0.72:
                issues.append(f"与历史样本 {reference['post_id']} 过度相似（{ratio:.0%}）")
        return issues

    def _local_review(self, text: str, task: dict[str, Any], references: list[dict[str, Any]]) -> list[str]:
        issues = self._numeric_claim_issues(text, task.get("proof_points", []))
        for phrase in task.get("banned_phrases", []):
            if phrase.lower() in text.lower():
                issues.append(f"包含禁用表达：{phrase}")
        issues.extend(self._copy_issues(text, references))
        if len(text.strip()) < 40:
            issues.append("内容过短，未形成完整表达")
        return issues

    def _draft(self, package: dict[str, Any], candidate_index: int) -> str:
        instructions = (
            "你是个性化社交媒体写作 Agent。严格按资料包写作。角色规则和 proof_points 是硬边界；"
            "历史文章只用于学习判断方式、节奏和语气，不得逐句仿写；反馈案例用于避免重复错误。"
            "不要补充资料包之外的数字、客户、案例、结果或亲历。直接输出可发布正文，不解释过程。"
        )
        payload = dict(package)
        payload["candidate_index"] = candidate_index
        return self.llm.complete(instructions, "任务资料(JSON)：" + json.dumps(payload, ensure_ascii=False), 2200).strip()

    def _review(self, text: str, package: dict[str, Any]) -> dict[str, Any]:
        local_issues = self._local_review(text, package["task"], package["references"])
        instructions = (
            "你是独立风格与事实评审器。检查角色一致性、任务完成度、AI模板感、照抄、虚构事实、"
            "宣传强度、CTA 和禁用表达。proof_points 之外的数字、客户结果、案例一律视为问题。"
            "只返回 JSON：{\"verdict\":\"PASS|REVISE\",\"issues\":[...],\"revision_instruction\":\"...\"}。"
        )
        raw = self.llm.complete(instructions, json.dumps({"package": package, "draft": text, "local_issues": local_issues}, ensure_ascii=False), 1000)
        try:
            review = extract_json(raw)
        except (LLMError, json.JSONDecodeError):
            review = {"verdict": "REVISE" if local_issues else "PASS", "issues": [], "revision_instruction": ""}
        review["issues"] = list(dict.fromkeys([*local_issues, *review.get("issues", [])]))
        if review["issues"]:
            review["verdict"] = "REVISE"
            review["revision_instruction"] = review.get("revision_instruction") or "逐项修复 issues，不引入新事实。"
        else:
            review["verdict"] = "PASS"
        return review

    def _revise(self, text: str, package: dict[str, Any], review: dict[str, Any]) -> str:
        instructions = (
            "你是定向改稿编辑。只修复评审指出的问题，保留原稿中合格的观点与语气。"
            "不得引入 proof_points 之外的新数字、案例、客户结果或经历。直接输出完整修订正文。"
        )
        return self.llm.complete(instructions, "任务资料(JSON)：" + json.dumps({"task": package["task"], "profile": package["profile"], "draft": text, "review": review}, ensure_ascii=False), 2200).strip()

    def generate(self, task: dict[str, Any]) -> dict[str, Any]:
        role_id = int(task["role_id"])
        role = self.db.get_role(role_id)
        if not role:
            raise ValueError("Role not found")
        profile_record = self.db.latest_profile(role_id)
        profile = profile_record["profile"] if profile_record else DEFAULT_PROFILE
        references = self.retrieve(role_id, task, self.settings.retrieval_top_k)
        package = {
            "role": role,
            "profile": profile,
            "references": [{**hit, "text": _clip(hit["text"])} for hit in references],
            "feedback": self._feedback_examples(role_id, task),
            "task": task,
        }
        candidates = []
        for index in range(1, int(task.get("candidates", 1)) + 1):
            draft = self._draft(package, index)
            text, reviews = draft, []
            for _ in range(self.settings.max_rewrite_rounds + 1):
                review = self._review(text, package)
                reviews.append(review)
                if review["verdict"] == "PASS" or len(reviews) > self.settings.max_rewrite_rounds:
                    break
                text = self._revise(text, package, review)
            final_review = reviews[-1]
            run_id = self.db.save_generation(
                {"role_id": role_id, "request": task, "retrieved": references, "draft": draft, "final_text": text, "review": reviews, "status": final_review["verdict"]}
            )
            candidates.append({"run_id": run_id, "draft": draft, "final_text": text, "status": final_review["verdict"], "reviews": reviews})
        return {"mode": self.settings.llm_mode, "provider": self.llm.provider, "model": self.llm.model, "profile_version": profile_record["version"] if profile_record else None, "retrieved": references, "candidates": candidates}
