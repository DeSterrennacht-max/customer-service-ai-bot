from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.api.app.db.models.entities import DeliveryStatus, MessageSource
from backend.api.app.services.knowledge_service import RetrievedKnowledge, render_markdown_as_reply, select_knowledge_reply
from backend.api.app.services.response_service import PipelineResult, ResponseService, UNANSWERED_HANDOFF_NOTICE


def test_render_markdown_as_reply_keeps_links_and_lists() -> None:
    markdown = "## 新版工作台地址\n- https://www.007chats.com/dock\n[下载链接](https://tmp.007chats.com/app.exe)"

    reply = render_markdown_as_reply(markdown)

    assert "##" not in reply
    assert "- https://www.007chats.com/dock" in reply
    assert "下载链接：https://tmp.007chats.com/app.exe" in reply


def test_select_knowledge_reply_prefers_relevant_section_over_full_page() -> None:
    markdown = """
## 客户端下载方式

### Windows 电脑端
下载链接：
https://tmp.007chats.com/windows.exe

### Mac 电脑端
下载链接：
https://tmp.007chats.com/mac.dmg

### 手机端 - 苹果
下载方式：
- 在 App Store 国际区搜索应用名称：007 Agent
""".strip()

    reply = select_knowledge_reply("客户端下载方式", markdown, "Windows 客户端怎么下载？")

    assert "Windows 电脑端" in reply
    assert "https://tmp.007chats.com/windows.exe" in reply
    assert "Mac 电脑端" not in reply
    assert "007 Agent" not in reply


def test_select_knowledge_reply_includes_child_sections_for_address_directory_page() -> None:
    markdown = """
## 新版工作台地址

目前可使用以下工作台地址登录：

### CloudFlare
- https://www.007chats.com/dock
- https://www.007proxy.uk/dock

### 阿里 CDN
- https://al.007chatlive.com/dock

## 使用说明
- 如果当前线路较慢，可切换其他线路。
""".strip()

    reply = select_knowledge_reply("新版工作台地址与线路说明", markdown, "新版工作台地址在哪里？")

    assert "新版工作台地址与线路说明" not in reply
    assert "新版工作台地址\n" not in reply
    assert "目前可使用以下工作台地址登录：" in reply
    assert "https://www.007chats.com/dock" in reply
    assert "https://www.007proxy.uk/dock" in reply
    assert "https://al.007chatlive.com/dock" in reply
    assert "使用说明" not in reply


def test_build_answer_for_faq_uses_faq_lookup() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(bot_profile_id=uuid4())
    expected = RetrievedKnowledge(
        text="标准版是 499/坐席/年。",
        evidence=["faq:test-faq"],
        source_type="faq",
        structured=False,
    )

    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: expected
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: pytest.fail("FAQ 路径不应该查知识页")

    text, evidence, source_type, structured = service._build_answer(None, conversation, "价格是多少", "faq")

    assert text == "标准版是 499/坐席/年。"
    assert evidence == ["faq:test-faq"]
    assert source_type == "faq"
    assert structured is False


def test_build_answer_result_carries_faq_images() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(bot_profile_id=uuid4())
    expected = RetrievedKnowledge(
        text="标准版价格见下图。",
        evidence=["faq:test-faq"],
        source_type="faq",
        structured=False,
        image_assets=[
            {
                "url": "https://media.example.com/price.png",
                "object_key": "tenants/test/content-images/faq/price.png",
                "filename": "price.png",
                "content_type": "image/png",
                "size_bytes": 128,
            }
        ],
    )

    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: expected

    result = service._build_answer_result(None, conversation, "价格图", "faq")

    assert result is expected
    assert result.image_assets[0]["url"] == "https://media.example.com/price.png"


def test_build_answer_for_knowledge_uses_page_lookup_without_prefix() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(bot_profile_id=uuid4())
    expected = RetrievedKnowledge(
        text="新版工作台地址\nhttps://www.007chats.com/dock",
        evidence=["knowledge_page:test-page"],
        source_type="knowledge_page",
        structured=True,
    )

    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: pytest.fail("knowledge 路径不应该先查 FAQ")
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: expected

    text, evidence, source_type, structured = service._build_answer(None, conversation, "新版工作台地址在哪里？", "knowledge")

    assert text == "新版工作台地址\nhttps://www.007chats.com/dock"
    assert "根据现有项目资料" not in text
    assert evidence == ["knowledge_page:test-page"]
    assert source_type == "knowledge_page"
    assert structured is True


def test_handle_customer_message_prefers_faq_before_knowledge() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    faq_result = RetrievedKnowledge(
        text="标准版是 499/坐席/年，优惠价 400 USDT；高级版是 799/坐席/年，优惠价 700 USDT。",
        evidence=["faq:pricing"],
        source_type="faq",
        structured=False,
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
    )
    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: faq_result
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: pytest.fail("FAQ 命中后不应再查知识页")
    service.handoff.create_ticket = lambda *args, **kwargs: pytest.fail("FAQ 命中后不应转人工")

    result = service.handle_customer_message(None, conversation, "标准版多少钱", {}, None)

    assert result.action == "template_reply"
    assert result.intent == "faq"
    assert result.text == faq_result.text
    assert result.evidence == ["faq:pricing"]


def test_function_consultation_faq_answers_without_handoff() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    faq_result = RetrievedKnowledge(
        text="007chat 支持多坐席客服、Telegram 接待、人工接管和知识库回复。",
        evidence=["faq:functions"],
        source_type="faq",
        structured=False,
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
    )
    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: faq_result if text == "我想咨询具体功能" else None
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: pytest.fail("FAQ 命中后不应再查知识页")
    service.handoff.create_ticket = lambda *args, **kwargs: pytest.fail("FAQ 命中后不应转人工")

    result = service.handle_customer_message(None, conversation, "我想咨询具体功能", {}, None)

    assert result.action == "template_reply"
    assert result.intent == "faq"
    assert result.text == faq_result.text
    assert result.evidence == ["faq:functions"]


def test_handle_customer_message_uses_bot_specific_welcome_message() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        welcome_message="你好，这里是 A 机器人。你可以直接发问题给我。",
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
    )

    result = service.handle_customer_message(None, conversation, "/start", {}, None)

    assert result.action == "template_reply"
    assert result.intent == "welcome"
    assert result.text == "你好，这里是 A 机器人。你可以直接发问题给我。"
    assert result.evidence == ["system:welcome"]


def test_handle_customer_message_uses_bot_email_auto_reply_before_faq() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        email_auto_reply_enabled=True,
        email_auto_reply_message="收到邮箱了，请继续等候开户通知。",
        telegram_bot_token="bot-token",
    )
    service.knowledge.retrieve_faq = lambda *args, **kwargs: pytest.fail("邮箱自动回复不应查 FAQ")
    service.knowledge.retrieve_knowledge_page = lambda *args, **kwargs: pytest.fail("邮箱自动回复不应查知识页")

    result = service.handle_customer_message(None, conversation, "我的邮箱是 customer@example.com，请继续开户。", {}, None)

    assert result.action == "template_reply"
    assert result.intent == "email_capture"
    assert result.text == "收到邮箱了，请继续等候开户通知。"
    assert result.evidence == ["system:email_auto_reply"]
    assert result.source_type == "email_auto_reply"


def test_handle_customer_message_ignores_email_auto_reply_when_disabled() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    ticket = SimpleNamespace(id=uuid4())

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        email_auto_reply_enabled=False,
        email_auto_reply_message="收到邮箱了。",
        telegram_bot_token="bot-token",
        support_group_chat_id="-100200300400",
    )
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: None
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: None
    service.handoff.create_ticket = lambda *args, **kwargs: ticket
    service.handoff.notify_support_group = lambda *args, **kwargs: None

    result = service.handle_customer_message(None, conversation, "我的邮箱是 customer@example.com，请继续开户。", {}, None)

    assert result.action == "handoff"
    assert result.intent == "unanswered"


def test_dispatch_reply_falls_back_to_original_text_when_generator_fails() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        bot_profile_id=uuid4(),
        telegram_chat_id="123456",
    )
    style = SimpleNamespace(
        tone="friendly",
        banned_phrases_json=[],
        typing_enabled=False,
    )
    sent: dict[str, str] = {}

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return style

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery()

    class FailingGenerator:
        def humanize(self, *args, **kwargs):
            raise RuntimeError("llm unavailable")

    service.generator = FailingGenerator()
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(telegram_bot_token="bot-token")
    service.telegram.send_text_sync = lambda bot_token, chat_id, text: sent.update(
        {"bot_token": bot_token, "chat_id": chat_id, "text": text}
    ) or 10001
    service.conversations.record_message = lambda *args, **kwargs: SimpleNamespace()
    service.audit.record = lambda *args, **kwargs: None

    result = PipelineResult(
        action="template_reply",
        text="你好，我是客服柠檬。",
        evidence=["system:welcome"],
        risk_level="low",
        intent="welcome",
        source_type="system",
    )

    reply = service.dispatch_reply(FakeDb(), conversation, result)

    assert reply == "你好，我是客服柠檬。"
    assert sent == {"bot_token": "bot-token", "chat_id": "123456", "text": "你好，我是客服柠檬。"}


def test_dispatch_reply_sends_email_auto_reply_without_humanizing() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        bot_profile_id=uuid4(),
        telegram_chat_id="123456",
    )
    style = SimpleNamespace(
        tone="friendly",
        banned_phrases_json=[],
        typing_enabled=True,
    )
    sent: dict[str, str] = {}

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return style

    class FakeDb:
        def query(self, *args, **kwargs):
            return FakeQuery()

    class FailingGenerator:
        def humanize(self, *args, **kwargs):
            raise AssertionError("邮箱自动回复不应被风格改写")

        def preserve_structure(self, *args, **kwargs):
            raise AssertionError("邮箱自动回复不应被风格改写")

    service.generator = FailingGenerator()
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(telegram_bot_token="bot-token")
    service.telegram.send_chat_action_sync = lambda *args, **kwargs: pytest.fail("邮箱自动回复不应模拟输入")
    service.telegram.send_text_sync = lambda bot_token, chat_id, text: sent.update(
        {"bot_token": bot_token, "chat_id": chat_id, "text": text}
    ) or 10001
    service.conversations.record_message = lambda *args, **kwargs: SimpleNamespace()
    service.audit.record = lambda *args, **kwargs: None

    result = PipelineResult(
        action="template_reply",
        text="已收到你的邮箱，我们会根据你提供的信息继续处理。",
        evidence=["system:email_auto_reply"],
        risk_level="low",
        intent="email_capture",
        source_type="email_auto_reply",
    )

    reply = service.dispatch_reply(FakeDb(), conversation, result)

    assert reply == "已收到你的邮箱，我们会根据你提供的信息继续处理。"
    assert sent == {
        "bot_token": "bot-token",
        "chat_id": "123456",
        "text": "已收到你的邮箱，我们会根据你提供的信息继续处理。",
    }


def test_handle_customer_message_uses_knowledge_when_faq_misses() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    knowledge_result = RetrievedKnowledge(
        text="Windows 电脑端\n下载链接：https://tmp.007chats.com/windows.exe",
        evidence=["knowledge_page:downloads"],
        source_type="knowledge_page",
        structured=True,
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
    )
    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: None
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: knowledge_result

    result = service.handle_customer_message(None, conversation, "Windows 客户端怎么下载？", {}, None)

    assert result.action == "knowledge_reply"
    assert result.intent == "knowledge"
    assert result.text == knowledge_result.text
    assert result.evidence == ["knowledge_page:downloads"]


def test_handle_customer_message_handoffs_when_faq_and_knowledge_miss() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    ticket = SimpleNamespace(id=uuid4())
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token-from-conversation",
        support_group_chat_id="-100200300400",
        unanswered_fallback_message="稍等，这会儿有点忙，我马上处理",
    )
    captured: dict[str, str] = {}

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: bot_profile
    service.conversations.get_default_bot_profile = lambda db: pytest.fail("未命中转人工不应回退默认 Bot")
    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: None
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: None
    service.handoff.create_ticket = lambda db, conversation, reason, summary_text: captured.update(
        {"reason": reason, "summary_text": summary_text}
    ) or ticket
    service.handoff.notify_support_group = lambda db, ticket, conversation, bot_token, group_chat_id: captured.update(
        {"bot_token": bot_token, "group_chat_id": group_chat_id}
    )

    result = service.handle_customer_message(None, conversation, "我想问一下这个情况", {}, None)

    assert result.action == "handoff"
    assert result.intent == "unanswered"
    assert result.source_type == "handoff"
    assert result.text == UNANSWERED_HANDOFF_NOTICE
    assert result.evidence == [f"handoff:{ticket.id}"]
    assert captured == {
        "reason": "unanswered",
        "summary_text": "我想问一下这个情况",
        "bot_token": "bot-token-from-conversation",
        "group_chat_id": "-100200300400",
    }


def test_handle_customer_message_uses_configured_unanswered_fallback() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    ticket = SimpleNamespace(id=uuid4())
    bot_profile = SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
        support_group_chat_id="-100200300400",
        unanswered_fallback_message="我先帮你转人工，请稍等。",
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: bot_profile
    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: None
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: None
    service.handoff.create_ticket = lambda *args, **kwargs: ticket
    service.handoff.notify_support_group = lambda *args, **kwargs: None

    result = service.handle_customer_message(None, conversation, "没有命中的问题", {}, None)

    assert result.action == "handoff"
    assert result.intent == "unanswered"
    assert result.text == "我先帮你转人工，请稍等。"


def test_handle_business_customer_message_records_and_replies_on_faq_hit() -> None:
    service = ResponseService()
    bot_profile = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
    )
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=bot_profile.tenant_id,
        bot_profile_id=bot_profile.id,
        status="open",
        telegram_chat_id="6059820900",
        telegram_business_connection_id="business-connection-1",
    )
    faq_result = RetrievedKnowledge(
        text="标准版是 499/坐席/年。",
        evidence=["faq:pricing"],
        source_type="faq",
        structured=False,
    )
    captured: dict = {}
    created: dict = {}

    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: faq_result
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: pytest.fail("FAQ 命中后不应查知识页")
    service.conversations.get_or_create_conversation = lambda **kwargs: created.update(kwargs) or conversation
    service.conversations.record_message = lambda *args, **kwargs: captured.update(kwargs)

    resolved_conversation, result = service.handle_business_customer_message(
        db=object(),
        bot_profile=bot_profile,
        conversation=None,
        telegram_chat_id="6059820900",
        telegram_user_id="6059820900",
        display_name="customer",
        business_connection_id="business-connection-1",
        text="标准版多少钱",
        raw_payload={"business_message": {"message_id": 201}},
        telegram_message_id="201",
    )

    assert resolved_conversation is conversation
    assert created["telegram_business_connection_id"] == "business-connection-1"
    assert created["telegram_chat_id"] == "6059820900"
    assert result.action == "template_reply"
    assert result.intent == "faq"
    assert result.text == "标准版是 499/坐席/年。"
    assert captured["content_text"] == "标准版多少钱"
    assert captured["telegram_message_id"] == "201"


def test_handle_business_customer_message_records_and_replies_on_email_hit() -> None:
    service = ResponseService()
    bot_profile = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        email_auto_reply_enabled=True,
        email_auto_reply_message="已收到邮箱。",
    )
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=bot_profile.tenant_id,
        bot_profile_id=bot_profile.id,
        status="open",
        telegram_chat_id="6059820900",
        telegram_business_connection_id="business-connection-1",
    )
    captured: dict = {}
    created: dict = {}

    service.knowledge.retrieve_faq = lambda *args, **kwargs: pytest.fail("邮箱自动回复不应查 FAQ")
    service.knowledge.retrieve_knowledge_page = lambda *args, **kwargs: pytest.fail("邮箱自动回复不应查知识页")
    service.conversations.get_or_create_conversation = lambda **kwargs: created.update(kwargs) or conversation
    service.conversations.record_message = lambda *args, **kwargs: captured.update(kwargs)

    resolved_conversation, result = service.handle_business_customer_message(
        db=object(),
        bot_profile=bot_profile,
        conversation=None,
        telegram_chat_id="6059820900",
        telegram_user_id="6059820900",
        display_name="customer",
        business_connection_id="business-connection-1",
        text="我的邮箱是 customer@example.com，请继续开户。",
        raw_payload={"business_message": {"message_id": 211}},
        telegram_message_id="211",
    )

    assert resolved_conversation is conversation
    assert created["telegram_business_connection_id"] == "business-connection-1"
    assert result.action == "template_reply"
    assert result.intent == "email_capture"
    assert result.text == "已收到邮箱。"
    assert result.source_type == "email_auto_reply"
    assert captured["content_text"] == "我的邮箱是 customer@example.com，请继续开户。"


def test_handle_business_customer_message_ignores_miss_without_recording_or_handoff() -> None:
    service = ResponseService()
    bot_profile = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
    )

    service.rules.route = lambda text, bot_profile=None: None
    service.knowledge.retrieve_faq = lambda db, bot_profile_id, text: None
    service.knowledge.retrieve_knowledge_page = lambda db, bot_profile_id, text: None
    service.conversations.get_or_create_conversation = lambda **kwargs: pytest.fail("Business 未命中不应创建会话")
    service.conversations.record_message = lambda *args, **kwargs: pytest.fail("Business 未命中不应记录消息")
    service.handoff.create_ticket = lambda *args, **kwargs: pytest.fail("Business 未命中不应转人工")
    service.handoff.notify_support_group = lambda *args, **kwargs: pytest.fail("Business 未命中不应通知客服群")

    conversation, result = service.handle_business_customer_message(
        db=object(),
        bot_profile=bot_profile,
        conversation=None,
        telegram_chat_id="6059820900",
        telegram_user_id="6059820900",
        display_name="customer",
        business_connection_id="business-connection-1",
        text="没有命中的问题",
        raw_payload={"business_message": {"message_id": 202}},
        telegram_message_id="202",
    )

    assert conversation is None
    assert result.action == "ignored"
    assert result.intent == "unanswered"
    assert result.source_type == "business_ignored"


def test_handle_business_customer_message_ignores_handoff_trigger_without_recording() -> None:
    service = ResponseService()
    bot_profile = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
    )

    service.rules.route = lambda text, bot_profile=None: SimpleNamespace(
        action="handoff",
        intent="human_request",
        risk_level="high",
    )
    service.knowledge.retrieve_faq = lambda *args, **kwargs: pytest.fail("Business 人工词命中后不应查 FAQ")
    service.knowledge.retrieve_knowledge_page = lambda *args, **kwargs: pytest.fail("Business 人工词命中后不应查知识页")
    service.conversations.record_message = lambda *args, **kwargs: pytest.fail("Business 人工词命中不应记录消息")
    service.handoff.create_ticket = lambda *args, **kwargs: pytest.fail("Business 人工词命中不应转人工")

    conversation, result = service.handle_business_customer_message(
        db=object(),
        bot_profile=bot_profile,
        conversation=None,
        telegram_chat_id="6059820900",
        telegram_user_id="6059820900",
        display_name="customer",
        business_connection_id="business-connection-1",
        text="我要人工",
        raw_payload={"business_message": {"message_id": 203}},
        telegram_message_id="203",
    )

    assert conversation is None
    assert result.action == "ignored"
    assert result.intent == "human_request"


def test_dispatch_reply_sends_unanswered_handoff_notice_to_customer() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        bot_profile_id=uuid4(),
        telegram_chat_id="123456",
    )
    sent: dict[str, str] = {}

    class EmptyQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeDb:
        def query(self, *args, **kwargs):
            return EmptyQuery()

    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(telegram_bot_token="bot-token")
    service.telegram.send_text_sync = lambda bot_token, chat_id, text: sent.update(
        {"bot_token": bot_token, "chat_id": chat_id, "text": text}
    ) or 10002
    service.conversations.record_message = lambda *args, **kwargs: SimpleNamespace()
    service.audit.record = lambda *args, **kwargs: None

    result = PipelineResult(
        action="handoff",
        text=UNANSWERED_HANDOFF_NOTICE,
        evidence=["handoff:ticket-id"],
        risk_level="high",
        intent="unanswered",
        source_type="handoff",
    )

    reply = service.dispatch_reply(FakeDb(), conversation, result)

    assert reply == UNANSWERED_HANDOFF_NOTICE
    assert sent == {"bot_token": "bot-token", "chat_id": "123456", "text": UNANSWERED_HANDOFF_NOTICE}


def test_dispatch_reply_sends_business_message_with_connection_id() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        bot_profile_id=uuid4(),
        telegram_chat_id="123456",
        telegram_business_connection_id="business-connection-1",
    )
    sent: dict[str, str] = {}

    class EmptyQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeDb:
        def query(self, *args, **kwargs):
            return EmptyQuery()

    def fake_send_text_sync(bot_token: str, chat_id: str, text: str, **kwargs):
        sent.update({"bot_token": bot_token, "chat_id": chat_id, "text": text, **kwargs})
        return 10003

    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(telegram_bot_token="bot-token")
    service.telegram.send_text_sync = fake_send_text_sync
    service.conversations.record_message = lambda *args, **kwargs: SimpleNamespace()
    service.audit.record = lambda *args, **kwargs: None

    result = PipelineResult(
        action="template_reply",
        text="这是 Business 回复。",
        evidence=["faq:test"],
        risk_level="low",
        intent="faq",
        source_type="faq",
    )

    reply = service.dispatch_reply(FakeDb(), conversation, result)

    assert reply == "这是 Business 回复。"
    assert sent == {
        "bot_token": "bot-token",
        "chat_id": "123456",
        "text": "这是 Business 回复。",
        "business_connection_id": "business-connection-1",
    }


def test_dispatch_reply_sends_text_then_object_storage_photos() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        bot_profile_id=uuid4(),
        telegram_chat_id="123456",
        telegram_business_connection_id="business-connection-1",
    )
    calls: list[dict[str, str]] = []
    recorded_payload: dict = {}

    class EmptyQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeDb:
        def query(self, *args, **kwargs):
            return EmptyQuery()

    def fake_send_text_sync(bot_token: str, chat_id: str, text: str, **kwargs):
        calls.append({"kind": "text", "bot_token": bot_token, "chat_id": chat_id, "text": text, **kwargs})
        return 10004

    def fake_send_photo_sync(bot_token: str, chat_id: str, photo: str, **kwargs):
        calls.append({"kind": "photo", "bot_token": bot_token, "chat_id": chat_id, "photo": photo, **kwargs})
        return 10005

    def fake_record_message(*args, **kwargs):
        recorded_payload.update(kwargs["raw_payload_json"])
        return SimpleNamespace()

    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(telegram_bot_token="bot-token")
    service.telegram.send_text_sync = fake_send_text_sync
    service.telegram.send_photo_sync = fake_send_photo_sync
    service.conversations.record_message = fake_record_message
    service.audit.record = lambda *args, **kwargs: None

    result = PipelineResult(
        action="template_reply",
        text="请看价格图。",
        evidence=["faq:pricing"],
        risk_level="low",
        intent="faq",
        source_type="faq",
        image_assets=[
            {
                "url": "https://media.example.com/price.png",
                "object_key": "tenants/test/content-images/faq/price.png",
                "filename": "price.png",
                "content_type": "image/png",
                "size_bytes": 128,
            }
        ],
    )

    reply = service.dispatch_reply(FakeDb(), conversation, result)

    assert reply == "请看价格图。"
    assert calls == [
        {
            "kind": "text",
            "bot_token": "bot-token",
            "chat_id": "123456",
            "text": "请看价格图。",
            "business_connection_id": "business-connection-1",
        },
        {
            "kind": "photo",
            "bot_token": "bot-token",
            "chat_id": "123456",
            "photo": "https://media.example.com/price.png",
            "business_connection_id": "business-connection-1",
        },
    ]
    assert recorded_payload["photo_message_ids"] == [10005]


def test_dispatch_reply_sends_object_storage_photo_without_text() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        bot_profile_id=uuid4(),
        telegram_chat_id="123456",
    )
    calls: list[dict[str, str]] = []
    message = SimpleNamespace(delivery_status=None)
    recorded_payload: dict = {}
    audit_payload: dict = {}

    class EmptyQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class FakeDb:
        def query(self, *args, **kwargs):
            return EmptyQuery()

    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(telegram_bot_token="bot-token")
    service.telegram.send_text_sync = lambda *args, **kwargs: pytest.fail("图片-only 回复不应发送空文本")

    def fake_send_photo_sync(bot_token: str, chat_id: str, photo: str, **kwargs):
        calls.append({"kind": "photo", "bot_token": bot_token, "chat_id": chat_id, "photo": photo, **kwargs})
        return 10006

    def fake_record_message(*args, **kwargs):
        recorded_payload.update(kwargs["raw_payload_json"])
        return message

    service.telegram.send_photo_sync = fake_send_photo_sync
    service.conversations.record_message = fake_record_message
    service.audit.record = lambda *args, **kwargs: audit_payload.update(kwargs["detail_json"])

    result = PipelineResult(
        action="template_reply",
        text="",
        evidence=["faq:pricing"],
        risk_level="low",
        intent="faq",
        source_type="faq",
        image_assets=[
            {
                "url": "https://media.example.com/price.png",
                "object_key": "tenants/test/content-images/faq/price.png",
                "filename": "price.png",
                "content_type": "image/png",
                "size_bytes": 128,
            }
        ],
    )

    reply = service.dispatch_reply(FakeDb(), conversation, result)

    assert reply == ""
    assert calls == [
        {
            "kind": "photo",
            "bot_token": "bot-token",
            "chat_id": "123456",
            "photo": "https://media.example.com/price.png",
            "business_connection_id": None,
        }
    ]
    assert audit_payload["sent"] is True
    assert recorded_payload["photo_message_ids"] == [10006]
    assert message.delivery_status == DeliveryStatus.SENT


def test_followup_message_reuses_recent_context_before_generic_knowledge_lookup() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    knowledge_result = RetrievedKnowledge(
        text="007chat 在线客服系统费用\n- 标准版：499 / 坐席 / 年",
        evidence=["knowledge_page:pricing"],
        source_type="knowledge_page",
        structured=True,
    )
    current_customer_id = uuid4()
    last_bot_id = uuid4()
    previous_customer_id = uuid4()

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
    )
    service.rules.route = lambda text, bot_profile=None: None
    service._get_recent_messages = lambda db, conversation, limit=6: [
        SimpleNamespace(id=current_customer_id, source=MessageSource.CUSTOMER, content_text="10个坐席"),
        SimpleNamespace(
            id=last_bot_id,
            source=MessageSource.BOT,
            content_text="007chat 按坐席按年收费。标准版和高级版价格不同，如果您告诉我需要几个坐席，我可以继续帮您确认更合适的方案。",
            intent="faq",
        ),
        SimpleNamespace(id=previous_customer_id, source=MessageSource.CUSTOMER, content_text="价格是多少"),
    ]

    faq_queries: list[str] = []
    knowledge_queries: list[str] = []

    def fake_retrieve_faq(db, bot_profile_id, text):
        faq_queries.append(text)
        return None

    def fake_retrieve_knowledge(db, bot_profile_id, text):
        knowledge_queries.append(text)
        if text == "价格是多少 10个坐席":
            return knowledge_result
        if text == "10个坐席":
            pytest.fail("短跟进消息不应该直接按裸文本去查知识页")
        return None

    service.knowledge.retrieve_faq = fake_retrieve_faq
    service.knowledge.retrieve_knowledge_page = fake_retrieve_knowledge

    result = service.handle_customer_message(object(), conversation, "10个坐席", {}, None)

    assert result.action == "knowledge_reply"
    assert result.text == knowledge_result.text
    assert "价格是多少 10个坐席" in faq_queries
    assert knowledge_queries == ["价格是多少 10个坐席"]


def test_quantity_price_followup_calculates_totals_instead_of_repeating_generic_faq() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(
        bot_profile_id=uuid4(),
        status="open",
        tenant_id=uuid4(),
        telegram_chat_id="123456",
        id=uuid4(),
    )
    current_customer_id = uuid4()
    last_bot_id = uuid4()
    previous_customer_id = uuid4()
    generic_answer = "007chat 按坐席按年收费。标准版和高级版价格不同，如果您告诉我需要几个坐席，我可以继续帮您确认更合适的方案。"
    pricing_result = RetrievedKnowledge(
        text="标准版是 499/坐席/年，优惠价 400 USDT；高级版是 799/坐席/年，优惠价 700 USDT。如需我也可以继续帮您对比两个版本。",
        evidence=["faq:pricing-detail"],
        source_type="faq",
        structured=False,
    )

    service.conversations.record_message = lambda *args, **kwargs: None
    service.conversations.get_bot_profile = lambda db, bot_profile_id: SimpleNamespace(
        high_risk_keywords_json=["人工"],
        sensitive_keywords_json=["诈骗"],
        telegram_bot_token="bot-token",
    )
    service.rules.route = lambda text, bot_profile=None: None
    service._get_recent_messages = lambda db, conversation, limit=6: [
        SimpleNamespace(id=current_customer_id, source=MessageSource.CUSTOMER, content_text="2位坐席"),
        SimpleNamespace(id=last_bot_id, source=MessageSource.BOT, content_text=generic_answer, intent="faq"),
        SimpleNamespace(id=previous_customer_id, source=MessageSource.CUSTOMER, content_text="价格多少"),
    ]

    faq_queries: list[str] = []

    def fake_retrieve_faq(db, bot_profile_id, text):
        faq_queries.append(text)
        if text == "2位坐席":
            pytest.fail("短追问不应该先按当前消息直接查 FAQ")
        if text in {"价格多少 2位坐席", f"{generic_answer} 2位坐席"}:
            return RetrievedKnowledge(text=generic_answer, evidence=["faq:generic-price"], source_type="faq")
        if text == "标准版多少钱":
            return pricing_result
        return None

    service.knowledge.retrieve_faq = fake_retrieve_faq
    service.knowledge.retrieve_knowledge_page = lambda *args, **kwargs: pytest.fail("价格明细 FAQ 足够时不应查知识页")

    result = service.handle_customer_message(object(), conversation, "2位坐席", {}, None)

    assert result.action == "template_reply"
    assert result.intent == "faq"
    assert "按你说的 2 位坐席" in result.text
    assert "标准版：499/坐席/年，合计 998 元/年；优惠价合计 800 USDT" in result.text
    assert "高级版：799/坐席/年，合计 1598 元/年；优惠价合计 1400 USDT" in result.text
    assert result.evidence == ["faq:pricing-detail", "system:quantity_price_quote"]
    assert "标准版多少钱" in faq_queries


def test_followup_quantity_accepts_common_chinese_numbers() -> None:
    assert ResponseService._extract_quantity("两位坐席") == 2
    assert ResponseService._extract_quantity("十个账号") == 10


def test_handoff_uses_conversation_bot_profile_group_instead_of_default_bot() -> None:
    service = ResponseService()
    conversation = SimpleNamespace(bot_profile_id=uuid4(), id=uuid4())
    ticket = SimpleNamespace(id=uuid4())
    bot_profile = SimpleNamespace(
        telegram_bot_token="bot-token-from-conversation",
        support_group_chat_id="-100200300400",
    )
    captured: dict[str, str] = {}

    service.handoff.create_ticket = lambda db, conversation, reason, summary_text: ticket
    service.handoff.notify_support_group = lambda db, ticket, conversation, bot_token, group_chat_id: captured.update(
        {"bot_token": bot_token, "group_chat_id": group_chat_id}
    )
    service.conversations.get_bot_profile = lambda db, bot_profile_id: bot_profile
    service.conversations.get_default_bot_profile = lambda db: pytest.fail("转人工选群不应该再依赖默认 Bot")

    result = service._handoff(None, conversation, "我要人工", SimpleNamespace(intent="human_request"))

    assert result.action == "handoff"
    assert result.intent == "human_request"
    assert captured == {
        "bot_token": "bot-token-from-conversation",
        "group_chat_id": "-100200300400",
    }
