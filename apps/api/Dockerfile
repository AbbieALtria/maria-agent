# Build context = repo root (needs packages/ and uv.lock).
#   docker build -f apps/api/Dockerfile .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY apps/api ./apps/api
RUN uv sync --frozen --no-dev --package maria-api

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app/apps/api
EXPOSE 8000
# Railway injects PORT. Migrations run as the preDeployCommand (see railway.json).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
