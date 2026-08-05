"""Run an end-to-end smoke test without touching the production database."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.agent import WritingAgent
from app.cli import seed
from app.config import settings
from app.db import Database


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="social-agent-smoke-") as directory:
        db = Database(Path(directory) / "smoke.db")
        db.init()
        seed(db)
        agent = WritingAgent(db, settings)
        profile = agent.rebuild_profile(2)
        query = {
            "role_id": 2,
            "topic": "品牌是否能保证成为 ChatGPT 第一推荐",
            "platform": "LinkedIn",
            "language": "zh-CN",
            "format": "风险教育",
            "goal": "澄清误区",
            "audience": "品牌市场负责人",
            "tone": "克制、基于证据",
        }
        hits = agent.retrieve(2, query, 3)
        result = agent.generate(
            {
                **query,
                "length": "200-350字",
                "banned_phrases": ["绝对保证", "颠覆行业"],
                "proof_points": ["模型回答会受到问题表达、上下文和可用信息影响"],
                "cta": "邀请读者分享自己的观察。",
                "candidates": 1,
            }
        )
        candidate = result["candidates"][0]
        stored = db.get_generation(candidate["run_id"])
        print(
            json.dumps(
                {
                    "provider": result["provider"],
                    "model": result["model"],
                    "profile_version": profile["version"],
                    "profile_languages": sorted(profile["profile"].keys()),
                    "rag_hit_count": len(hits),
                    "rag_top_hit": hits[0]["title"] if hits else None,
                    "rag_top_score": hits[0]["final_score"] if hits else None,
                    "agent_status": candidate["status"],
                    "review_rounds": len(candidate["reviews"]),
                    "generated_chars": len(candidate["final_text"]),
                    "run_saved": stored is not None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
