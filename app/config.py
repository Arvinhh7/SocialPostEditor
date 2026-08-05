from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load a small, dependency-free subset of dotenv syntax without overriding the shell."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_path: Path
    llm_mode: str
    llm_provider: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    retrieval_mode: str
    retrieval_top_k: int
    max_rewrite_rounds: int

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
        if provider not in {"openai", "deepseek"}:
            raise ValueError("LLM_PROVIDER must be openai or deepseek")
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        active_key = deepseek_key if provider == "deepseek" else openai_key
        requested_mode = os.getenv("LLM_MODE", "auto").strip().lower()
        if requested_mode in {"openai", "deepseek"}:
            provider, mode = requested_mode, "live"
        else:
            mode = ("live" if active_key else "mock") if requested_mode == "auto" else requested_mode
        if mode not in {"mock", "live"}:
            raise ValueError("LLM_MODE must be mock, live, auto, openai, or deepseek")
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH", "data/voice.db")),
            llm_mode=mode,
            llm_provider=provider,
            openai_api_key=openai_key,
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            deepseek_api_key=deepseek_key,
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            retrieval_mode=os.getenv("RETRIEVAL_MODE", "hybrid").lower(),
            retrieval_top_k=max(1, _int("RETRIEVAL_TOP_K", 4)),
            max_rewrite_rounds=max(0, min(4, _int("MAX_REWRITE_ROUNDS", 2))),
        )


settings = Settings.from_env()
