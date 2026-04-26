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
        email_auto_reply_enabled=True,
    )

    result = RuleRouter().route("标准版多少钱", bot_profile=bot_profile)

    assert result is None


def test_rule_router_routes_whole_email_message() -> None:
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["赔偿"],
        sensitive_keywords_json=["辱骂"],
        email_auto_reply_enabled=True,
    )

    result = RuleRouter().route(" customer@example.com ", bot_profile=bot_profile)

    assert result is not None
    assert result.action == "email_auto_reply"
    assert result.intent == "email_capture"
    assert result.entities == {"email": "customer@example.com"}


def test_rule_router_routes_email_inside_sentence() -> None:
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["赔偿"],
        sensitive_keywords_json=["辱骂"],
        email_auto_reply_enabled=True,
    )

    result = RuleRouter().route("我的邮箱是 customer@example.com，请帮我开户。", bot_profile=bot_profile)

    assert result is not None
    assert result.action == "email_auto_reply"
    assert result.intent == "email_capture"
    assert result.entities == {"email": "customer@example.com"}


def test_rule_router_does_not_route_invalid_email_like_text() -> None:
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["赔偿"],
        sensitive_keywords_json=["辱骂"],
        email_auto_reply_enabled=True,
    )

    result = RuleRouter().route("我的邮箱是 customer@example", bot_profile=bot_profile)

    assert result is None


def test_rule_router_email_auto_reply_can_be_disabled() -> None:
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["赔偿"],
        sensitive_keywords_json=["辱骂"],
        email_auto_reply_enabled=False,
    )

    result = RuleRouter().route("customer@example.com", bot_profile=bot_profile)

    assert result is None
