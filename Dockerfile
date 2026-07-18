# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
COPY README.md LICENSE ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.14-slim-trixie AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN groupadd --system androidrepo \
    && useradd --system --gid androidrepo --create-home androidrepo

WORKDIR /app
COPY --from=builder --chown=androidrepo:androidrepo /app/.venv /app/.venv
COPY --chown=androidrepo:androidrepo alembic.ini /app/alembic.ini

USER androidrepo

ENTRYPOINT ["androidrepo-bot"]
