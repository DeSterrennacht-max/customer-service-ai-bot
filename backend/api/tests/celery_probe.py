"""Explicitly imported by the isolated test worker, never by production workers."""
import os
import hashlib

assert os.environ.get("CSB_INTEGRATION_TESTS") == "1"
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from redis import Redis
from backend.api.app.core.config import get_settings
from backend.api.app.services import delivery_service

assert get_settings().app_env == "test"


async def fake_send(token, item, style):
    client = Redis.from_url(get_settings().redis_url)
    key = "csb-probe:" + hashlib.sha256((token + str(item)).encode()).hexdigest()
    count = client.incr(key)
    client.expire(key, 600)
    if count == 1:
        raise TelegramRetryAfter(method=SendMessage(chat_id=item["chat_id"], text="probe"), message="test retry", retry_after=1)
    return 920000000 + count


delivery_service.send_delivery = fake_send
