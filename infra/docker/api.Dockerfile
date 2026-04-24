FROM python:3.12-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

COPY backend/api/pyproject.toml /tmp/api-pyproject.toml
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir \
    alembic aiogram "bcrypt==4.0.1" "celery[redis]" email-validator fastapi httpx "passlib[bcrypt]" "psycopg[binary]" \
    pydantic-settings "python-jose[cryptography]" python-multipart sqlalchemy "uvicorn[standard]"

COPY . /workspace

CMD ["uvicorn", "backend.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
