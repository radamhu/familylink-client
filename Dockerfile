# ── builder: install deps (needs gcc for asyncpg C extension) ────────────────
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[server]"

# ── runtime: minimal image, no build tools ───────────────────────────────────
FROM python:3.13-slim

ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_LEVEL=info

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY logging_config.json .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn familylink_server.main:app --host 0.0.0.0 --port 8000 --log-config logging_config.json"]
