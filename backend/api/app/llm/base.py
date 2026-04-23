from __future__ import annotations

from pydantic import BaseModel, Field


class RouterOutput(BaseModel):
    intent: str
    entities: dict[str, str] = Field(default_factory=dict)
    need_kb: bool = True
    need_tool: bool = False
    need_human: bool = False
    risk_level: str = "low"
    clarify_needed: bool = False


class CompletionResult(BaseModel):
    text: str
    raw: dict | None = None
