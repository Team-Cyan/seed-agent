# Project Overview

## What `seed-agent` Is

`seed-agent` is a Docker-first PT automation app for personal NAS and homelab
deployments.

It is:

- a Docker image and Compose-oriented runtime,
- a config-first strategy runner,
- a CLI-first operator tool,
- an auditable automation layer over PT discovery and qBittorrent actions,
- a future platform for intent-driven acquisition workflows.

It is not:

- a dashboard-first product,
- a full MoviePilot clone,
- a general media server,
- a browser-login automation project.

## Product Shape

The current architecture has two shipped loops:

1. PT upload strategy loop
   - discover candidates,
   - score them,
   - enqueue them to qBittorrent,
   - review managed torrents,
   - prune cold managed torrents,
   - record audit decisions.

2. Resource intent loop
   - ingest or add intents,
   - search candidate releases,
   - rank releases,
   - confirm or reject ambiguous choices,
   - enqueue the chosen result through the same downloader path.

## Core Runtime Surfaces

- CLI: `src/seed_agent/cli.py`
- Docker image: `Dockerfile`
- Container entrypoint: `docker/entrypoint.sh`
- Publish workflow: `.github/workflows/docker-publish.yml`
- Config: `src/seed_agent/config.py`
- Models: `src/seed_agent/models.py`
- State store: `src/seed_agent/state.py`
- Audit: `src/seed_agent/audit.py`

## Current Site Story

- `nexusphp`: RSS-first with richer feed fields
- `mteam`: RSS discovery, API-key detail enrichment, and API-driven discovery

Important nuance:

- RSS must stay in the codebase because it is useful for other sites and fallback flows.
- M-Team API discovery is the preferred authenticated path when an API key is configured.

## Current Downloader Story

- qBittorrent is the only implemented downloader.
- Mutations should stay dry-run first.
- qBittorrent state remains the operational source of truth.
- `seed-agent` local state explains policy and intent lifecycle.
- Category policies separate mutable seed pools from add-only media pools.
- Logical budget pools affect enqueue pause behavior and cleanup visibility.

## Current Durable Files

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`
- `local/inbox/*`
- `local/secrets/*`

## Documentation Strategy

Use docs in layers:

- README for humans and high-level orientation
- root `AGENTS.md` for agent entry routing
- `docs/ai/` for shared AI session efficiency
- `docs/specs/` for durable product/design decisions
- `docs/plans/` for implementation sequencing
- `docs/operations/` for operator procedures
- `docs/roadmap.md` for current state and next work

## Session Guidance

For most sessions, the model should not need to read the full history. Read:

1. this file,
2. the relevant module doc(s),
3. the roadmap item,
4. only then the matching spec or handoff note if needed.
