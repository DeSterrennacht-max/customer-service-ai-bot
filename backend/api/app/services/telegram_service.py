from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import Any

from aiogram import Bot


logger = logging.getLogger(__name__)


class TelegramService:
    @staticmethod
    def _run_coroutine_sync(coroutine: Coroutine[Any, Any, Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def runner() -> None:
            try:
                result["value"] = asyncio.run(coroutine)
            except BaseException as exc:  # pragma: no cover - thread boundary
                error["value"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()

        if "value" in error:
            raise error["value"]
        return result.get("value")

    async def send_chat_action(
        self,
        bot_token: str,
        chat_id: str,
        action: str = "typing",
        business_connection_id: str | None = None,
    ) -> None:
        bot = Bot(token=bot_token)
        try:
            await bot.send_chat_action(chat_id=chat_id, action=action, business_connection_id=business_connection_id)
        finally:
            await bot.session.close()

    async def send_text(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> int | None:
        bot = Bot(token=bot_token)
        try:
            response = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id,
                business_connection_id=business_connection_id,
            )
            return response.message_id
        except Exception:  # pragma: no cover - network boundary
            logger.exception("Failed to send Telegram message")
            return None
        finally:
            await bot.session.close()

    def send_text_sync(
        self,
        bot_token: str,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> int | None:
        return self._run_coroutine_sync(self.send_text(bot_token, chat_id, text, reply_to_message_id, business_connection_id))

    def send_chat_action_sync(
        self,
        bot_token: str,
        chat_id: str,
        action: str = "typing",
        business_connection_id: str | None = None,
    ) -> None:
        self._run_coroutine_sync(self.send_chat_action(bot_token, chat_id, action, business_connection_id))
