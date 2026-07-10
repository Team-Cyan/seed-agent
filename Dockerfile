# syntax=docker/dockerfile:1.7

ARG AGENT_PYTHON_UV_BASE=ghcr.io/astral-sh/uv:python3.14-trixie
FROM ${AGENT_PYTHON_UV_BASE}

ARG VERSION=0.17.0
ARG REVISION=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="seed-agent" \
    org.opencontainers.image.description="Docker-first PT automation for NAS and homelab downloader operations" \
    org.opencontainers.image.url="https://github.com/Team-Cyan/seed-agent" \
    org.opencontainers.image.source="https://github.com/Team-Cyan/seed-agent" \
    org.opencontainers.image.icon="https://raw.githubusercontent.com/Team-Cyan/seed-agent/main/docs/assets/seed-agent-icon-transparent.png" \
    org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.revision="${REVISION}" \
    org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

COPY pyproject.toml uv.lock README.md VERSION /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project

COPY src /app/src
COPY docker /app/docker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable \
    && chmod +x /app/docker/entrypoint.sh

EXPOSE 8765

ENTRYPOINT ["/app/docker/entrypoint.sh"]
