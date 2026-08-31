from __future__ import annotations

import json
import re
from dataclasses import asdict
from difflib import SequenceMatcher
from time import perf_counter
from typing import Any, Callable

from .config import Settings
from .db import Database
from .evals.metrics import unsupported_number_issues
from .llm import LLMClient, extract_json
from .models import EvidenceContract
from .retrieval import Retriever
from .reviewer import IndependentReviewer


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
        self.reviewer = IndependentReviewer(self.llm)
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
        return unsupported_number_issues(text, proof_points)

    @staticmethod
    def _copy_issues(text: str, references: list[dict[str, Any]]) -> list[str]:
        issues = []
        for reference in references:
            ratio = SequenceMatcher(None, re.sub(r"\s+", "", text), re.sub(r"\s+", "", reference["text"])).ratio()
            if ratio > 0.72:
                issues.append(f"与历史样本 {reference['post_id']} 过度相似（{ratio:.0%}）")
        return issues

    @staticmethod
    def _build_evidence_contract(
        task: dict[str, Any],
        role: dict[str, Any],
        references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        proof_points = list(dict.fromkeys(str(item).strip() for item in task.get("proof_points", []) if str(item).strip()))
        forbidden = list(dict.fromkeys(str(item).strip() for item in task.get("banned_phrases", []) if str(item).strip()))
        contract = EvidenceContract(
            required_points=proof_points,
            allowed_numeric_claims=[point for point in proof_points if re.search(r"\d", point)],
            forbidden_phrases=forbidden,
            role_rules=str(role.get("identity_rules", "")),
            reference_post_ids=[int(item["post_id"]) for item in references],
            platform=str(task.get("platform", "")),
            language=str(task.get("language", "")),
            content_format=str(task.get("format", "")),
        )
        return contract.model_dump()

    def _local_review(
        self,
        text: str,
        evidence_contract: dict[str, Any],
        references: list[dict[str, Any]],
    ) -> list[str]:
        issues = self._numeric_claim_issues(text, evidence_contract.get("required_points", []))
        for phrase in evidence_contract.get("forbidden_phrases", []):
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
            "Evidence Contract 是本次内容的事实与验收合同，必须满足 required_points 和 forbidden_phrases；"
            "不要补充合同之外的数字、客户、案例、结果或亲历。直接输出可发布正文，不解释过程。"
        )
        payload = dict(package)
        payload["candidate_index"] = candidate_index
        return self.llm.complete(instructions, "任务资料(JSON)：" + json.dumps(payload, ensure_ascii=False), 2200).strip()

    def _review(self, text: str, package: dict[str, Any]) -> dict[str, Any]:
        local_issues = self._local_review(text, package["evidence_contract"], package["references"])
        return self.reviewer.evaluate(
            text=text,
            package=package,
            deterministic_issues=local_issues,
        )

    def _revise(self, text: str, package: dict[str, Any], review: dict[str, Any]) -> str:
        instructions = (
            "你是定向改稿编辑。只修复评审指出的问题，保留原稿中合格的观点与语气。"
            "必须继续遵守 Evidence Contract，不得引入合同之外的新数字、案例、客户结果或经历。直接输出完整修订正文。"
        )
        return self.llm.complete(
            instructions,
            "任务资料(JSON)：" + json.dumps(
                {
                    "task": package["task"],
                    "profile": package["profile"],
                    "evidence_contract": package["evidence_contract"],
                    "draft": text,
                    "review": review,
                },
                ensure_ascii=False,
            ),
            2200,
        ).strip()

    def _traced_step(
        self,
        run_id: int,
        step_index: int,
        step_name: str,
        step_input: dict[str, Any],
        operation: Callable[[], Any],
        prompt_version: str,
    ) -> Any:
        started = perf_counter()
        try:
            output = operation()
        except Exception as exc:
            self.db.add_generation_step(
                run_id,
                {
                    "step_index": step_index,
                    "step_name": step_name,
                    "input": step_input,
                    "output": {},
                    "provider": self.llm.provider,
                    "model": self.llm.model,
                    "prompt_version": prompt_version,
                    "duration_ms": round((perf_counter() - started) * 1000),
                    "status": "FAILED",
                    "error_message": str(exc)[:1000],
                },
            )
            raise
        self.db.add_generation_step(
            run_id,
            {
                "step_index": step_index,
                "step_name": step_name,
                "input": step_input,
                "output": output if isinstance(output, dict) else {"text": str(output)},
                "provider": self.llm.provider,
                "model": self.llm.model,
                "prompt_version": prompt_version,
                "duration_ms": round((perf_counter() - started) * 1000),
                "status": "COMPLETED",
            },
        )
        return output

    def generate(self, task: dict[str, Any]) -> dict[str, Any]:
        role_id = int(task["role_id"])
        role = self.db.get_role(role_id)
        if not role:
            raise ValueError("Role not found")
        profile_record = self.db.latest_profile(role_id)
        profile = profile_record["profile"] if profile_record else DEFAULT_PROFILE
        retrieval_started = perf_counter()
        references = self.retrieve(role_id, task, self.settings.retrieval_top_k)
        retrieval_duration_ms = round((perf_counter() - retrieval_started) * 1000)
        evidence_contract = self._build_evidence_contract(task, role, references)
        package = {
            "role": role,
            "profile": profile,
            "references": [{**hit, "text": _clip(hit["text"])} for hit in references],
            "feedback": self._feedback_examples(role_id, task),
            "task": task,
            "evidence_contract": evidence_contract,
        }
        candidates = []
        for index in range(1, int(task.get("candidates", 1)) + 1):
            run_id = self.db.start_generation(
                {"role_id": role_id, "request": task, "retrieved": references, "status": "RUNNING"}
            )
            step_index = 1
            self.db.add_generation_step(
                run_id,
                {
                    "step_index": step_index,
                    "step_name": "retrieve",
                    "input": {"query": task, "top_k": self.settings.retrieval_top_k},
                    "output": {
                        "hits": [
                            {"post_id": item["post_id"], "final_score": item["final_score"], "reason": item["reason"]}
                            for item in references
                        ]
                    },
                    "provider": "local",
                    "model": self.settings.retrieval_mode,
                    "prompt_version": "retrieval-v1",
                    "duration_ms": retrieval_duration_ms,
                    "status": "COMPLETED",
                },
            )
            step_index += 1
            self.db.add_generation_step(
                run_id,
                {
                    "step_index": step_index,
                    "step_name": "contract",
                    "input": {
                        "proof_point_count": len(task.get("proof_points", [])),
                        "reference_post_ids": [item["post_id"] for item in references],
                    },
                    "output": evidence_contract,
                    "provider": "local",
                    "model": "rules",
                    "prompt_version": "evidence-contract-v1",
                    "duration_ms": 0,
                    "status": "COMPLETED",
                },
            )
            step_index += 1
            draft, text, reviews = "", "", []
            try:
                draft = self._traced_step(
                    run_id,
                    step_index,
                    "draft",
                    {
                        "candidate_index": index,
                        "profile_version": profile_record["version"] if profile_record else None,
                        "reference_post_ids": [item["post_id"] for item in references],
                    },
                    lambda: self._draft(package, index),
                    "draft-v2",
                )
                text = draft
                step_index += 1
                for round_index in range(1, self.settings.max_rewrite_rounds + 2):
                    review = self._traced_step(
                        run_id,
                        step_index,
                        f"review_{round_index}",
                        {"round": round_index, "text": _clip(text)},
                        lambda current=text: self._review(current, package),
                        "review-v2",
                    )
                    reviews.append(review)
                    step_index += 1
                    if review["verdict"] in {"PASS", "BLOCKED"} or len(reviews) > self.settings.max_rewrite_rounds:
                        break
                    text = self._traced_step(
                        run_id,
                        step_index,
                        f"revise_{round_index}",
                        {"round": round_index, "text": _clip(text), "review": review},
                        lambda current=text, current_review=review: self._revise(current, package, current_review),
                        "revise-v2",
                    )
                    step_index += 1
                final_review = reviews[-1]
                self.db.add_generation_step(
                    run_id,
                    {
                        "step_index": step_index,
                        "step_name": "final",
                        "input": {"review_count": len(reviews)},
                        "output": {"text": text, "status": final_review["verdict"]},
                        "provider": "local",
                        "model": "workflow",
                        "prompt_version": "final-v1",
                        "duration_ms": 0,
                        "status": "COMPLETED",
                    },
                )
                self.db.finish_generation(
                    run_id,
                    {
                        "retrieved": references,
                        "draft": draft,
                        "final_text": text,
                        "review": reviews,
                        "status": final_review["verdict"],
                    },
                )
            except Exception:
                self.db.finish_generation(
                    run_id,
                    {
                        "retrieved": references,
                        "draft": draft,
                        "final_text": text,
                        "review": reviews,
                        "status": "FAILED",
                    },
                )
                raise
            candidates.append(
                {
                    "run_id": run_id,
                    "draft": draft,
                    "final_text": text,
                    "status": final_review["verdict"],
                    "approval_status": "NOT_APPLICABLE" if final_review["verdict"] == "BLOCKED" else "PENDING_REVIEW",
                    "reviews": reviews,
                }
            )
        return {"mode": self.settings.llm_mode, "provider": self.llm.provider, "model": self.llm.model, "profile_version": profile_record["version"] if profile_record else None, "retrieved": references, "candidates": candidates}
