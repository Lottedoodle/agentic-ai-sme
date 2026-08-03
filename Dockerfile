# Glow Beauty Shop — FastAPI backend (ECS / ECR)
# Build from repo root:
#   docker build -t glow-beauty-api .
#   docker run --env-file .env -p 8000:8000 glow-beauty-api

FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependency layer (cache-friendly)
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./backend/
RUN uv sync --project backend --frozen --no-dev --no-install-project

# Application source — package import path is `backend.*`
COPY backend/ ./backend/
RUN uv sync --project backend --frozen --no-dev

EXPOSE 8000

# Non-root for ECS
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["uv", "run", "--project", "backend", "uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
