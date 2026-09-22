FROM python:3.12.14-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock

COPY backend /workspace/backend
COPY shared /workspace/shared

CMD ["uvicorn", "backend.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
