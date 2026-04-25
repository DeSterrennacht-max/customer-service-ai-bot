from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import httpx

from backend.api.app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)

TELEGRAM_ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
]


class TelegramWebhookRegistrationError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class TelegramWebhookRegistration:
    url: str
    description: str | None = None


class TelegramWebhookService:
    def __init__(
        self,
        settings: Settings | None = None,
        post: Callable[..., httpx.Response] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._post = post or httpx.post

    def register_bot_profile_webhook(self, bot_profile: Any) -> TelegramWebhookRegistration | None:
        if not getattr(bot_profile, "is_active", True):
            logger.info("Skip Telegram webhook registration for inactive bot profile %s", getattr(bot_profile, "id", "unknown"))
            return None

        token = (getattr(bot_profile, "telegram_bot_token", None) or "").strip()
        if not token or token == "CHANGE_ME":
            if self.settings.app_env == "production":
                raise TelegramWebhookRegistrationError("Telegram Bot token is missing or still uses the placeholder value.", status_code=400)
            logger.info("Skip Telegram webhook registration because bot token is not configured.")
            return None

        base_url = self._public_base_url()
        if not base_url:
            if self.settings.app_env == "production":
                raise TelegramWebhookRegistrationError(
                    "APP_PUBLIC_BASE_URL or NEXT_PUBLIC_API_BASE_URL must be configured before automatic webhook registration.",
                    status_code=500,
                )
            logger.info("Skip Telegram webhook registration because public base URL is not configured.")
            return None

        webhook_url = self.build_webhook_url(bot_profile, base_url)
        payload: dict[str, Any] = {"url": webhook_url, "allowed_updates": TELEGRAM_ALLOWED_UPDATES}
        if self.settings.webhook_secret:
            payload["secret_token"] = self.settings.webhook_secret

        try:
            response = self._post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            description = None
            try:
                description = exc.response.json().get("description")
            except Exception:
                description = None
            raise TelegramWebhookRegistrationError(
                f"Telegram setWebhook failed: {description or f'HTTP {exc.response.status_code}'}",
                status_code=400 if exc.response.status_code in {400, 401, 404} else 502,
            ) from exc
        except Exception as exc:
            raise TelegramWebhookRegistrationError("Telegram setWebhook request failed.") from exc

        if not data.get("ok"):
            description = data.get("description") or "Telegram API returned ok=false."
            error_code = data.get("error_code")
            status_code = 400 if error_code in {400, 401, 404} else 502
            raise TelegramWebhookRegistrationError(f"Telegram setWebhook failed: {description}", status_code=status_code)

        return TelegramWebhookRegistration(url=webhook_url, description=data.get("description"))

    def unregister_bot_profile_webhook(self, bot_profile: Any, drop_pending_updates: bool = True) -> str | None:
        token = (getattr(bot_profile, "telegram_bot_token", None) or "").strip()
        if not token or token == "CHANGE_ME":
            logger.info("Skip Telegram webhook deletion because bot token is not configured.")
            return None

        payload = {"drop_pending_updates": drop_pending_updates}
        try:
            response = self._post(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            description = None
            try:
                description = exc.response.json().get("description")
            except Exception:
                description = None
            raise TelegramWebhookRegistrationError(
                f"Telegram deleteWebhook failed: {description or f'HTTP {exc.response.status_code}'}",
                status_code=400 if exc.response.status_code in {400, 401, 404} else 502,
            ) from exc
        except Exception as exc:
            raise TelegramWebhookRegistrationError("Telegram deleteWebhook request failed.") from exc

        if not data.get("ok"):
            description = data.get("description") or "Telegram API returned ok=false."
            error_code = data.get("error_code")
            status_code = 400 if error_code in {400, 401, 404} else 502
            raise TelegramWebhookRegistrationError(f"Telegram deleteWebhook failed: {description}", status_code=status_code)

        return data.get("description")

    @staticmethod
    def build_webhook_url(bot_profile: Any, public_base_url: str) -> str:
        identifier = (getattr(bot_profile, "telegram_bot_username", None) or "").strip().lstrip("@")
        if not identifier:
            bot_profile_id = getattr(bot_profile, "id", None)
            if not bot_profile_id:
                raise TelegramWebhookRegistrationError("Bot profile id is required to build webhook URL.", status_code=500)
            identifier = str(bot_profile_id)
        return f"{public_base_url.rstrip('/')}/telegram/webhook/{quote(identifier, safe='')}"

    def _public_base_url(self) -> str | None:
        public_base_url = (self.settings.public_base_url or os.getenv("NEXT_PUBLIC_API_BASE_URL") or "").strip()
        return public_base_url.rstrip("/") or None
