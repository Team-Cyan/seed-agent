# Docker Image Publishing

This document explains how `seed-agent` images should be built and published for
Docker-first deployments.

## Publishing Model

The image should stay generic:

- no embedded secrets,
- no embedded operator config,
- no embedded runtime database,
- no baked-in tracker state.

Everything deployment-specific should come from mounted files and environment
variables.

## Supported Distribution Shapes

The repository is compatible with:

- local-only image builds,
- GitHub Container Registry,
- Docker Hub.

## Build Locally

```bash
docker build -t seed-agent:local .
```

## Tag For A Registry

Docker Hub example:

```bash
docker tag seed-agent:local your-dockerhub-user/seed-agent:latest
docker tag seed-agent:local your-dockerhub-user/seed-agent:0.1.3
```

GHCR example:

```bash
docker tag seed-agent:local ghcr.io/team-cyan/seed-agent:latest
docker tag seed-agent:local ghcr.io/team-cyan/seed-agent:0.1.3
```

## Push

Docker Hub:

```bash
docker push your-dockerhub-user/seed-agent:latest
docker push your-dockerhub-user/seed-agent:0.1.3
```

GHCR:

```bash
docker push ghcr.io/team-cyan/seed-agent:latest
docker push ghcr.io/team-cyan/seed-agent:0.1.3
```

## GitHub-Native Publishing

This repository now includes `.github/workflows/docker-publish.yml`.

On every push to `main`, GitHub Actions publishes a multi-arch image to:

- `ghcr.io/team-cyan/seed-agent:latest`
- `ghcr.io/team-cyan/seed-agent:main`
- `ghcr.io/team-cyan/seed-agent:sha-<commit>`

On version tags such as `v0.1.3`, the same workflow also publishes:

- `ghcr.io/team-cyan/seed-agent:v0.1.3`
- `ghcr.io/team-cyan/seed-agent:0.1.3`
- `ghcr.io/team-cyan/seed-agent:0.1`

The tag workflow checks that the git tag matches the repository `VERSION` file
before publishing.

This is the path that lets Unraid treat `seed-agent` like a normal third-party
container with remote update checks.

## Compose Template Strategy

Compose examples should not assume one fixed registry forever.

Recommended pattern:

- default to a published image for normal users,
- optionally include `build: ..` for local source deployments,
- allow image override through `deploy/seed-agent.env` or direct Compose edits.

The repository already includes:

- `deploy/docker-compose.example.yml`
- `deploy/seed-agent.env.example`

## What Must Stay Mounted

Even when you publish to Docker Hub, operators still need to mount:

- `/app/config`
- `/app/local`
- `/app/.seed-agent`
- optional heartbeat/output paths such as `/state`

That is the contract that keeps the image portable.

## Release Checklist

Before publishing:

1. `uv run pytest -q`
2. `uv run ruff check .`
3. `docker build -t seed-agent:local .`
4. `docker compose --env-file deploy/seed-agent.env.example -f deploy/docker-compose.example.yml config`
5. confirm README and Compose docs match current env vars and volume layout
6. confirm example config does not contain secrets
7. confirm `VERSION`, `pyproject.toml`, and `src/seed_agent/__init__.py` match

## Current Gaps

What is now documented:

- Docker-first installation path
- Compose-based runtime model
- image tagging and push workflow
- CI-driven GHCR publishing workflow
- semver and short-SHA GHCR tags
- OCI image labels
- first-party Unraid template for DockerMan users

What still remains optional future work:

- automated Docker Hub publish workflow
- a fully automated changelog/version bump command
