from __future__ import annotations

from backend.api.app.llm.base import RouterOutput
from backend.api.app.llm.router_client import RouterLLMClient


class SemanticRouterService:
    def __init__(self) -> None:
        self.client = RouterLLMClient()

    def route(self, message: str) -> RouterOutput:
        return self.client.classify(message)
