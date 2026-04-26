from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.api.app.db.models.entities import BotProfile


DEFAULT_HIGH_RISK_KEYWORDS = {"人工", "投诉", "退款", "退费", "律师", "举报"}
DEFAULT_SENSITIVE_KEYWORDS = {"骂", "骗", "垃圾", "诈骗"}
START_COMMANDS = {"/start"}
EMAIL_PATTERN = re.compile(r"(?<![A-Z0-9._%+\-])([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})(?![A-Z0-9_%+\-])", re.IGNORECASE)


@dataclass(slots=True)
class RuleRouteResult:
    action: str
    intent: str
    risk_level: str = "low"
    entities: dict[str, str] = field(default_factory=dict)
    matched_keywords: list[str] = field(default_factory=list)


class RuleRouter:
    def route(self, message: str, bot_profile: BotProfile | None = None) -> RuleRouteResult | None:
        first_token = message.strip().split(maxsplit=1)[0].lower() if message.strip() else ""
        if any(first_token == command or first_token.startswith(f"{command}@") for command in START_COMMANDS):
            return RuleRouteResult(action="welcome", intent="welcome", risk_level="low")

        high_risk_keywords = self._normalize_keywords(
            bot_profile.high_risk_keywords_json if bot_profile else None,
            DEFAULT_HIGH_RISK_KEYWORDS,
        )
        sensitive_keywords = self._normalize_keywords(
            bot_profile.sensitive_keywords_json if bot_profile else None,
            DEFAULT_SENSITIVE_KEYWORDS,
        )
        matched_risk = [keyword for keyword in high_risk_keywords | sensitive_keywords if keyword in message]
        if matched_risk:
            return RuleRouteResult(action="handoff", intent="human_request", risk_level="high", matched_keywords=matched_risk)

        email_match = EMAIL_PATTERN.search(message)
        if self._email_auto_reply_enabled(bot_profile) and email_match:
            return RuleRouteResult(
                action="email_auto_reply",
                intent="email_capture",
                risk_level="low",
                entities={"email": email_match.group(1)},
            )

        return None

    @staticmethod
    def _normalize_keywords(values: list[str] | None, defaults: set[str]) -> set[str]:
        source = values if values else list(defaults)
        normalized = {item.strip() for item in source if item and item.strip()}
        return normalized or set(defaults)

    @staticmethod
    def _email_auto_reply_enabled(bot_profile: BotProfile | None) -> bool:
        if bot_profile is None:
            return False
        return bool(getattr(bot_profile, "email_auto_reply_enabled", False))
