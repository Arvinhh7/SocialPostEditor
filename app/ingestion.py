from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any

from .db import Database
from .documents import extract_text, split_posts


DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})[-_.年](?P<month>1[0-2]|0?[1-9])[-_.月](?P<day>3[01]|[12]\d|0?[1-9])日?(?!\d)"),
    re.compile(r"(?<!\d)(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?!\d)"),
)


def text_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", "", text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def infer_language(text: str) -> str:
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    if chinese_count == 0 and latin_count == 0:
        return ""
    return "zh-CN" if chinese_count >= max(1, latin_count * 0.2) else "en"


def infer_platform(filename: str, text: str) -> str:
    sample = f"{filename} {text[:500]}".lower()
    if any(marker in sample for marker in ("小红书", "xiaohongshu", "rednote", "_xhs", "-xhs")):
        return "小红书"
    if "linkedin" in sample or "领英" in sample:
        return "LinkedIn"
    if any(marker in sample for marker in ("微信公众号", "微信公众", "wechat", "_wx", "-wx")):
        return "微信公众号"
    if any(marker in sample for marker in ("微博", "weibo")):
        return "微博"
    return ""


def infer_content_type(title: str, text: str) -> str:
    sample = f"{title} {text[:800]}".lower()
    rules = (
        (("复盘", "总结", "踩坑", "retrospective", "lessons learned"), "项目复盘"),
        (("教程", "指南", "步骤", "怎么做", "how to", "tutorial"), "教程"),
        (("案例", "case study"), "案例分析"),
        (("清单", " checklist", "list of"), "清单"),
        (("为什么", "观点", "看法", "思考", "opinion"), "观点"),
    )
    for markers, label in rules:
        if any(marker in sample for marker in markers):
            return label
    return "文章"


def infer_tone(text: str) -> str:
    tones: list[str] = []
    if re.search(r"(^|[。！？\n])\s*(我|我们)", text):
        tones.append("第一人称")
    if any(marker in text.lower() for marker in ("证据", "数据", "验证", "测试", "evidence", "data")):
        tones.append("基于证据")
    if any(marker in text for marker in ("复盘", "反思", "踩坑", "教训")):
        tones.append("真实克制")
    if "?" in text or "？" in text:
        tones.append("启发式")
    if not tones:
        tones.append("自然")
    return ",".join(dict.fromkeys(tones))


def infer_published_at(filename: str) -> str | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(Path(filename).stem)
        if match:
            values = {key: int(value) for key, value in match.groupdict().items()}
            try:
                return date(values["year"], values["month"], values["day"]).isoformat()
            except ValueError:
                continue
    return None


def infer_post_metadata(
    *,
    filename: str,
    title: str,
    text: str,
    defaults: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    defaults = defaults or {}
    fallback_title = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    resolved_title = title.strip() or fallback_title or "未命名文章"
    inferred = {
        "title": resolved_title[:300],
        "platform": str(defaults.get("platform") or infer_platform(filename, text))[:80],
        "language": str(defaults.get("language") or infer_language(text))[:40],
        "content_type": str(defaults.get("content_type") or infer_content_type(resolved_title, text))[:80],
        "topic": str(defaults.get("topic") or resolved_title)[:300],
        "tone": str(defaults.get("tone") or infer_tone(text))[:200],
        "published_at": defaults.get("published_at") or infer_published_at(filename),
    }
    warnings: list[str] = []
    if not inferred["platform"]:
        warnings.append("未识别发布平台，可在导入后补充")
    if not inferred["language"]:
        warnings.append("未识别文章语言，可在导入后补充")
    if not title.strip():
        warnings.append("正文没有明确标题，已使用文件名")
    return inferred, warnings


def ingest_uploaded_posts(
    db: Database,
    uploaded: list[tuple[str, bytes]],
    role_id: int,
    defaults: dict[str, str],
    authenticity: int,
) -> dict[str, Any]:
    """Extract, infer, deduplicate, then atomically persist all valid posts."""
    existing_fingerprints = {text_fingerprint(post["text"]) for post in db.list_posts(role_id)}
    pending: list[tuple[dict[str, Any], list[str]]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for filename, content in uploaded:
        if len(content) > 10 * 1024 * 1024:
            failed.append({"source_name": filename, "reason": "文件超过 10 MB"})
            continue
        try:
            chunks = split_posts(extract_text(filename, content))
        except ValueError as exc:
            failed.append({"source_name": filename, "reason": str(exc)})
            continue
        if not chunks:
            failed.append({"source_name": filename, "reason": "没有找到至少 80 字的完整文章"})
            continue

        for title, text in chunks:
            fingerprint = text_fingerprint(text)
            if fingerprint in existing_fingerprints:
                skipped.append({"source_name": filename, "title": title, "reason": "内容重复"})
                continue
            metadata, warnings = infer_post_metadata(
                filename=filename,
                title=title,
                text=text,
                defaults=defaults,
            )
            pending.append(
                (
                    {
                        "role_id": role_id,
                        "text": text,
                        "authenticity": authenticity,
                        "source_name": filename,
                        **metadata,
                    },
                    warnings,
                )
            )
            existing_fingerprints.add(fingerprint)

    posts = db.add_posts([item for item, _warnings in pending])
    created = [
        {"post": post, "warnings": warnings}
        for post, (_item, warnings) in zip(posts, pending, strict=True)
    ]
    return {
        "summary": {
            "files_received": len(uploaded),
            "posts_created": len(created),
            "duplicates_skipped": len(skipped),
            "files_failed": len(failed),
        },
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }
