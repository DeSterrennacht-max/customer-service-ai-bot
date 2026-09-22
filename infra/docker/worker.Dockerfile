FROM python:3.12.14-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock

COPY backend /workspace/backend
COPY shared /workspace/shared

CMD ["celery", "-A", "backend.worker.app.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
