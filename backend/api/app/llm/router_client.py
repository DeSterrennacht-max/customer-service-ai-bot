from __future__ import annotations

import json
import re

import httpx

from backend.api.app.core.config import get_settings
from backend.api.app.llm.base import RouterOutput


class RouterLLMClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def classify(self, message: str) -> RouterOutput:
        if not self.settings.openai_api_key:
            return self._fallback(message)

        prompt = (
            "You are a customer service semantic router. Return compact JSON only with keys "
            "intent, entities, need_kb, need_tool, need_human, risk_level, clarify_needed."
        )
        payload = {
            "model": self.settings.router_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        response = httpx.post(
            f"{self.settings.openai_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return RouterOutput.model_validate(json.loads(content))

    def _fallback(self, message: str) -> RouterOutput:
        lower = message.lower()
        if any(word in lower for word in ["refund", "退款", "投诉", "人工", "agent"]):
            return RouterOutput(intent="human_request", need_kb=False, need_human=True, risk_level="high")
        if re.search(r"[A-Z]{2,5}-\d{4,8}", message):
            return RouterOutput(intent="other", entities={"ticket_id": re.search(r"[A-Z]{2,5}-\d{4,8}", message).group(0)}, need_kb=False)
        if "怎么" in message or "如何" in message or "?" in message or "？" in message:
            return RouterOutput(intent="knowledge", need_kb=True)
        return RouterOutput(intent="unclear", clarify_needed=True, risk_level="medium")
