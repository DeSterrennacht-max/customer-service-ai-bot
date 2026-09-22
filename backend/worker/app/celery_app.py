from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from backend.api.app.core.config import get_settings

settings = get_settings()
settings.validate_production()
celery_app = Celery("customer_service_bot", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_default_queue = "customer-service-bot"
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.broker_connection_retry_on_startup = True
celery_app.conf.task_ignore_result = True
celery_app.conf.task_routes = {
    name: {"queue": "customer-service-control"}
    for name in ("process_pending_updates", "process_incoming_message", "schedule_deliveries", "recover_deliveries", "release_stale_handoffs")
}
celery_app.conf.imports = (
    "backend.worker.app.tasks.process_incoming_message",
    "backend.worker.app.tasks.build_knowledge_chunks",
    "backend.worker.app.tasks.release_stale_handoffs",
    "backend.worker.app.tasks.deliver_messages",
)
celery_app.conf.beat_schedule = {
    "process-pending-updates": {"task": "process_pending_updates", "schedule": 1.0, "options": {"expires": 5}},
    "schedule-deliveries": {"task": "schedule_deliveries", "schedule": 2.0, "options": {"expires": 5}},
    "recover-interrupted-deliveries": {"task": "recover_deliveries", "schedule": 60.0},
    "release-stale-handoffs-every-5-minutes": {
        "task": "release_stale_handoffs",
        "schedule": schedule(run_every=300.0),
    }
}
