# Multi-stage backend Docker image for Helix API
# Uses uv for fast, reproducible Python dependency management

# --------------- Stage 1: Builder ---------------
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.1 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (cached layer)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --no-editable --no-dev

# Copy source and install project
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev

# --------------- Stage 2: Runtime ---------------
FROM python:3.13-slim AS runtime

WORKDIR /app

# Copy virtual environment with all installed packages
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY --from=builder /app/api /app/api

RUN adduser --disabled-password --gecos '' --uid 1000 appuser \
    && chown -R appuser:appuser /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "api.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
