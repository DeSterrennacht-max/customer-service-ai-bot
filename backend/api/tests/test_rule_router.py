from types import SimpleNamespace

from backend.api.app.services.knowledge_service import chunk_markdown
from backend.api.app.services.rule_router import RuleRouter


def test_rule_router_routes_high_risk_keywords() -> None:
    result = RuleRouter().route("我要投诉并申请退款")
    assert result is not None
    assert result.action == "handoff"
    assert result.risk_level == "high"


def test_rule_router_routes_start_command_to_welcome() -> None:
    result = RuleRouter().route("/start")
    assert result is not None
    assert result.action == "welcome"
    assert result.intent == "welcome"


def test_chunk_markdown_splits_long_text() -> None:
    chunks = chunk_markdown("a" * 1200, chunk_size=400)
    assert len(chunks) == 3


def test_rule_router_uses_bot_specific_high_risk_keywords() -> None:
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["赔偿"],
        sensitive_keywords_json=["辱骂"],
    )

    result = RuleRouter().route("我要赔偿", bot_profile=bot_profile)

    assert result is not None
    assert result.action == "handoff"
    assert result.risk_level == "high"


def test_rule_router_returns_none_for_normal_question() -> None:
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["赔偿"],
        sensitive_keywords_json=["辱骂"],
    )

    result = RuleRouter().route("标准版多少钱", bot_profile=bot_profile)

    assert result is None
