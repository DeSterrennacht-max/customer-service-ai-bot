FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir \
    alembic aiogram "bcrypt==4.0.1" "celery[redis]" fastapi httpx "passlib[bcrypt]" "psycopg[binary]" \
    pydantic-settings "python-jose[cryptography]" python-multipart sqlalchemy "uvicorn[standard]"

COPY . /workspace

CMD ["celery", "-A", "backend.worker.app.celery_app:celery_app", "worker", "--loglevel=INFO"]
