from __future__ import annotations

import argparse
import json

from .agent import WritingAgent
from .config import settings
from .db import Database


SEED_POSTS = [
    {
        "title": "第一推荐不是一个可以购买的承诺",
        "text": "当品牌问怎样保证成为 AI 的第一推荐时，问题本身就需要先拆开。模型回答会受到问题表达、上下文和可用信息影响。与其承诺一个固定位置，更实际的是持续检查品牌信息是否准确、可理解、可验证。GEO 的价值不在于制造确定性，而在于减少信息缺口并观察变化。",
        "platform": "LinkedIn", "language": "zh-CN", "content_type": "风险教育", "topic": "GEO,AI Visibility", "tone": "克制,教育型", "authenticity": 5,
    },
    {
        "title": "隐藏文字为什么可能带来风险",
        "text": "把人看不见、机器能读取的指令塞进页面，看起来像一条捷径。但它同时会制造新的治理问题：谁批准了这些内容，什么时候更新，出现错误后如何追溯？品牌传播不应该把可见性建立在不可解释的做法上。先保证公开信息清楚、一致、可核验，通常是更稳妥的起点。",
        "platform": "LinkedIn", "language": "zh-CN", "content_type": "打假", "topic": "AI投毒,品牌风险", "tone": "基于证据,克制", "authenticity": 5,
    },
    {
        "title": "Visibility needs evidence",
        "text": "AI visibility is not a fixed ranking you can purchase. Answers change with the question, context, and available evidence. A more useful program starts by making brand information consistent, understandable, and verifiable, then measuring how outputs change over time. The goal is not certainty. It is a better evidence trail and fewer information gaps.",
        "platform": "LinkedIn", "language": "en", "content_type": "education", "topic": "GEO,AI Visibility", "tone": "measured,evidence-led", "authenticity": 5,
    },
]


def seed(db: Database) -> int:
    existing_titles = {p["title"] for p in db.list_posts(2)}
    created = 0
    for post in SEED_POSTS:
        if post["title"] not in existing_titles:
            db.add_post({"role_id": 2, "source_name": "built-in demo", **post})
            created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Personalized social writing agent CLI")
    parser.add_argument("command", choices=("init", "seed", "demo"))
    args = parser.parse_args()
    db = Database(settings.database_path)
    db.init()
    if args.command == "init":
        print(json.dumps({"database": str(db.path), "roles": db.list_roles()}, ensure_ascii=False, indent=2))
        return
    created = seed(db)
    if args.command == "seed":
        print(json.dumps({"created": created, "total": len(db.list_posts(2))}, ensure_ascii=False, indent=2))
        return
    agent = WritingAgent(db, settings)
    if not db.latest_profile(2):
        agent.rebuild_profile(2)
    result = agent.generate(
        {
            "role_id": 2,
            "topic": "品牌能否保证在 ChatGPT 中成为第一推荐？",
            "platform": "LinkedIn",
            "language": "zh-CN",
            "format": "教育型短文",
            "goal": "澄清常见误区并建立可信度",
            "audience": "品牌市场负责人",
            "tone": "克制、教育型、基于证据",
            "length": "300-500字",
            "banned_phrases": ["绝对保证", "颠覆行业"],
            "proof_points": ["模型回答会受到问题表达、上下文和可用信息影响"],
            "cta": "邀请读者分享他们观察 AI 品牌可见性的方式。",
            "candidates": 1,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

