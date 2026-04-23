from __future__ import annotations

import httpx

from backend.api.app.core.config import get_settings
from backend.api.app.llm.base import CompletionResult


class GeneratorLLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def preserve_structure(self, text: str, banned_phrases: list[str] | None = None) -> CompletionResult:
        banned_phrases = banned_phrases or []
        return CompletionResult(text=self._fallback(text, banned_phrases))

    def humanize(self, fact_answer: str, tone: str, banned_phrases: list[str] | None = None) -> CompletionResult:
        banned_phrases = banned_phrases or []
        if not self.settings.openai_api_key:
            return CompletionResult(text=self._fallback(fact_answer, banned_phrases))

        system_prompt = (
            "Rewrite the answer to sound like a human support agent. "
            "Keep facts unchanged. Avoid revealing AI/system identity. "
            f"Desired tone: {tone}. Banned phrases: {', '.join(banned_phrases) if banned_phrases else 'none'}."
        )
        payload = {
            "model": self.settings.generator_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": fact_answer},
            ],
            "temperature": 0.4,
        }
        response = httpx.post(
            f"{self.settings.openai_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]
        return CompletionResult(text=text, raw=data)

    @staticmethod
    def _fallback(answer: str, banned_phrases: list[str]) -> str:
        text = answer.strip()
        for phrase in banned_phrases:
            text = text.replace(phrase, "")
        return text
