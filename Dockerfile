# ── Build stage ─────────────────────────────────────────────────────────────
# Install Python dependencies into a virtualenv, then copy it to the final
# image.  This keeps the runtime image small (no pip cache, no compilers).

FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements-prod.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements-prod.txt

# ── Runtime stage ──────────────────────────────────────────────────────────
FROM python:3.12-slim

# Security: run as non-root.
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app

# Bring the virtualenv from the builder.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Application code.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY models_cache/ ./models_cache/
COPY scripts/ ./scripts/
COPY training/ ./training/

# Ownership.
RUN chown -R app:app /app

USER app

# Cloud Run injects PORT; default 8080 for local Docker runs.
ENV PORT=8080
EXPOSE ${PORT}

# No --reload in production.  Uvicorn binds to 0.0.0.0 so Cloud Run can
# reach the container.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
