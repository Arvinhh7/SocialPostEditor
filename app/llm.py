from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from .config import Settings


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise LLMError("Model did not return a JSON object")
        return json.loads(match.group(0))


class LLMClient:
    """Minimal Responses API client; keeps the project runnable without an SDK."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_mock(self) -> bool:
        return self.settings.llm_mode == "mock"

    @property
    def provider(self) -> str:
        return "mock" if self.is_mock else self.settings.llm_provider

    @property
    def model(self) -> str:
        if self.is_mock:
            return "mock"
        return self.settings.deepseek_model if self.settings.llm_provider == "deepseek" else self.settings.openai_model

    def complete(self, instructions: str, user_input: str, max_output_tokens: int = 1800) -> str:
        if self.is_mock:
            return self._mock(instructions, user_input)
        if self.settings.llm_provider == "deepseek":
            return self._deepseek_complete(instructions, user_input, max_output_tokens)
        return self._openai_complete(instructions, user_input, max_output_tokens)

    def _openai_complete(self, instructions: str, user_input: str, max_output_tokens: int) -> str:
        if not self.settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is required for the OpenAI provider")
        body = json.dumps(
            {
                "model": self.settings.openai_model,
                "instructions": instructions,
                "input": user_input,
                "max_output_tokens": max_output_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.openai_base_url}/responses",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"OpenAI API returned HTTP {exc.code}: {detail[:800]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"OpenAI API request failed: {exc}") from exc
        if payload.get("output_text"):
            return str(payload["output_text"])
        texts: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(content.get("text", ""))
        if not texts:
            raise LLMError("Responses API returned no output_text")
        return "\n".join(texts)

    def _deepseek_complete(self, instructions: str, user_input: str, max_output_tokens: int) -> str:
        if not self.settings.deepseek_api_key:
            raise LLMError("DEEPSEEK_API_KEY is required for the DeepSeek provider")
        body = json.dumps(
            {
                "model": self.settings.deepseek_model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_input},
                ],
                "thinking": {"type": "disabled"},
                "max_tokens": max_output_tokens,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.settings.deepseek_base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"DeepSeek API returned HTTP {exc.code}: {detail[:800]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMError(f"DeepSeek API request failed: {exc}") from exc
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("DeepSeek API returned no assistant content") from exc

    @staticmethod
    def _mock(instructions: str, user_input: str) -> str:
        """Deterministic local substitute for development and API tests."""
        lower = instructions.lower()
        if "verdict" in lower and "revision_instruction" in lower:
            return json.dumps({"verdict": "PASS", "issues": [], "revision_instruction": ""}, ensure_ascii=False)
        if "profile" in lower or "作者画像" in instructions:
            return json.dumps(
                {
                    "zh": {
                        "values": ["基于证据", "不做过度承诺", "帮助受众理解风险"],
                        "voice": "克制、清晰、教育型，先提出判断再解释原因",
                        "openings": "从常见误区、现实问题或可验证现象切入",
                        "rhythm": "短段落与长短句交替",
                        "cta": "低压力地邀请讨论或进一步了解",
                        "avoid": ["宏大口号", "绝对化判断", "无依据数字"],
                    },
                    "en": {
                        "values": ["evidence", "restraint", "practical education"],
                        "voice": "measured, clear, and explanatory",
                        "openings": "start from a concrete misconception or observed risk",
                        "rhythm": "short paragraphs with varied sentence length",
                        "cta": "invite a low-pressure conversation",
                        "avoid": ["hype", "absolute claims", "unsupported metrics"],
                    },
                },
                ensure_ascii=False,
            )
        marker = "任务资料(JSON)："
        try:
            payload = json.loads(user_input.split(marker, 1)[1]) if marker in user_input else {}
        except json.JSONDecodeError:
            payload = {}
        task = payload.get("task", {})
        topic = task.get("topic", "本次主题")
        goal = task.get("goal", "帮助读者形成更准确的判断")
        points = task.get("proof_points", [])
        cta = task.get("cta", "如果你也在研究这个问题，欢迎交流你的观察。")
        evidence = "\n".join(f"- {p}" for p in points) if points else "- 当前没有可公开的量化证据，因此这里只讨论方法和判断边界。"
        return f"{topic}\n\n很多讨论会直接跳到结论，但更值得先确认的是：我们依据什么做这个判断。\n\n{goal}。可以先从三件事入手：明确问题边界、核对可公开事实、把推测与已知信息分开。\n\n目前可以确认的依据包括：\n{evidence}\n\n这并不意味着结果一定会怎样。更稳妥的做法，是持续观察、记录并用真实反馈校正判断。\n\n{cta}".strip()
