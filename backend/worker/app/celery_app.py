from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from backend.api.app.core.config import get_settings

settings = get_settings()
celery_app = Celery("customer_service_bot", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_default_queue = "customer-service-bot"
celery_app.conf.imports = (
    "backend.worker.app.tasks.process_incoming_message",
    "backend.worker.app.tasks.send_reply",
    "backend.worker.app.tasks.build_knowledge_chunks",
    "backend.worker.app.tasks.release_stale_handoffs",
)
celery_app.conf.beat_schedule = {
    "release-stale-handoffs-every-5-minutes": {
        "task": "release_stale_handoffs",
        "schedule": schedule(run_every=300.0),
    }
}
