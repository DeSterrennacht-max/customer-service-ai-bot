from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TelegramWebhookPayload(BaseModel):
    update_id: int | None = None
    message: dict[str, Any] | None = None
    edited_message: dict[str, Any] | None = None
