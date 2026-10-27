# syntax=docker/dockerfile:1.7

ARG AGENT_PYTHON_UV_BASE=ghcr.io/astral-sh/uv:python3.14-trixie@sha256:fc2acf3556b55b4474fef2d41d267f8f819c8c393fe20ea35e764e2282427de4
FROM ${AGENT_PYTHON_UV_BASE} AS sqlite-io-build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY docker/sqlite_io_native.c docker/build_sqlite_io.py /build/
RUN python /build/build_sqlite_io.py /build/sqlite_io_native.so

FROM ${AGENT_PYTHON_UV_BASE}

ARG VERSION=0.26.0
ARG REVISION=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="seed-agent" \
    org.opencontainers.image.description="Docker-first PT automation for NAS and homelab downloader operations" \
    org.opencontainers.image.url="https://github.com/Team-Cyan/seed-agent" \
    org.opencontainers.image.source="https://github.com/Team-Cyan/seed-agent" \
    org.opencontainers.image.icon="https://raw.githubusercontent.com/Team-Cyan/seed-agent/main/docs/assets/icon.png" \
    org.opencontainers.image.version="${VERSION}" \
    org.opencontainers.image.revision="${REVISION}" \
    org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    HOME=/tmp/seed-agent

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md VERSION /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project

COPY src /app/src
COPY docs/assets/icon.png /app/docs/assets/icon.png
COPY docker /app/docker
COPY --from=sqlite-io-build /build/sqlite_io_native.so /usr/local/lib/seed-agent/sqlite_io_native.so
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable \
    && chmod +x /app/docker/entrypoint.sh
RUN python -c 'import os, runpy, sys; os.setgid(100); os.setuid(1000); sys.argv = ["verify", "--library", "/usr/local/lib/seed-agent/sqlite_io_native.so"]; runpy.run_path("/app/docker/verify_sqlite_io_native.py", run_name="__main__")'

EXPOSE 8765

ENTRYPOINT ["/app/docker/entrypoint.sh"]
