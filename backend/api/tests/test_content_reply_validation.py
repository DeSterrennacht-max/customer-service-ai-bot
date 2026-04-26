from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.app.routers.faqs import ensure_faq_has_reply_content
from backend.api.app.routers.knowledge_pages import ensure_knowledge_page_has_reply_content


IMAGE_ASSET = {
    "url": "https://media.example.com/image.png",
    "object_key": "tenants/test/content-images/faq/image.png",
    "filename": "image.png",
    "content_type": "image/png",
    "size_bytes": 128,
}


def test_faq_reply_content_allows_blank_answer_when_image_exists() -> None:
    ensure_faq_has_reply_content("   ", [IMAGE_ASSET])


def test_faq_reply_content_rejects_blank_answer_without_images() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_faq_has_reply_content("   ", [])

    assert exc_info.value.status_code == 400


def test_knowledge_reply_content_allows_blank_body_when_image_exists() -> None:
    ensure_knowledge_page_has_reply_content("   ", [IMAGE_ASSET])


def test_knowledge_reply_content_rejects_blank_body_without_images() -> None:
    with pytest.raises(HTTPException) as exc_info:
        ensure_knowledge_page_has_reply_content("   ", [])

    assert exc_info.value.status_code == 400
