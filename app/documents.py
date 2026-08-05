from __future__ import annotations

import io
import re
from pathlib import Path


ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}


def extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix}. Use PDF, TXT, or Markdown.")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    raise ValueError("Text encoding is not UTF-8 or GB18030")


def split_posts(text: str, min_chars: int = 80) -> list[tuple[str, str]]:
    """Split on explicit dividers or Markdown headings; never keep title-only chunks."""
    normalized = text.replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*(?:---+|===+|\*\*\*+)\s*\n", normalized)
    if len(blocks) == 1:
        blocks = re.split(r"(?=^#{1,2}\s+.+$)", normalized, flags=re.MULTILINE)
    result: list[tuple[str, str]] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = [x.strip() for x in block.splitlines()]
        title = re.sub(r"^#{1,6}\s+", "", lines[0]) if lines else ""
        body = "\n".join(lines[1:]).strip() if (lines and (lines[0].startswith("#") or len(lines[0]) <= 80)) else block
        if len(body) >= min_chars:
            result.append((title, body))
    if not result and len(normalized) >= min_chars:
        result.append(("", normalized))
    return result

