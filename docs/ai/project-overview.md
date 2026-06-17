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
   - sync configured Douban and IMDb Want List sources,
   - merge repeated wants by reliable external ID aliases,
   - search candidate releases,
   - rank releases,
   - reject unwanted choices,
   - enqueue an explicit candidate for ambiguous choices,
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
- Architecture snapshot: `docs/architecture.md`

## Release Discipline

- Published Docker image behavior must have an intentional version decision
  before commit, push, or release.
- Code fixes and operational fixes bump the patch slot by `0.0.1`.
- New features bump the minor slot by `0.1.0`.
- Documentation-only changes may keep the version unchanged unless they are part
  of an operator handoff or deployment release.
- When bumping, keep `VERSION`, `Dockerfile`, `pyproject.toml`,
  `src/seed_agent/__init__.py`, and `CHANGELOG.md` aligned.
- After pushing a release intended for Unraid, verify the GHCR tag or manifest
  before touching the live host. Pulling `latest` too early can leave the host
  on the previous digest while the GitHub Action is still publishing.
- A DockerMan-managed Unraid install must be updated through Unraid's template
  update path, not by hand-written `docker rm && docker run` recreation. Manual
  recreation detaches the container from DockerMan metadata and hides the normal
  update status in the Unraid UI.

## Current Site Story

- `nexusphp`: RSS-first with richer feed fields
- `mteam`: RSS discovery, API-key detail enrichment, and API-driven discovery
  plus API-backed intent search

Important nuance:

- RSS must stay in the codebase because it is useful for other sites and fallback flows.
- M-Team API discovery is the preferred authenticated path when an API key is configured.
- Intent search can be Remux-first through generic search keywords and can
  prefer season packs or individual episodes through `want_decision.series_search_mode`.

## Current Downloader Story

- qBittorrent is the only implemented downloader.
- Mutations should stay dry-run first.
- qBittorrent state remains the operational source of truth.
- `seed-agent` local state explains policy and intent lifecycle.
- Category policies separate mutable seed pools from add-only media pools.
- Logical budget pools affect enqueue pause behavior and cleanup visibility.
- A `mutable` qB category is the operator-granted management boundary. When the
  user explicitly authorizes the seed category, current and future torrents in
  that category may be managed by the agent; tags remain audit/search metadata,
  not delete authority outside the category.
- Large manual cleanup requests should still start from a live candidate list
  with category, age, size, and state, then record the exact executed hash set.

## Current Durable Files

- `.seed-agent/state.db`
- `.seed-agent/audit.jsonl`
- `local/inbox/*`
- `local/secrets/*`

## Documentation Strategy

Use docs in layers:

- README for humans and high-level orientation
- root `AGENTS.md` for agent entry routing
- `.agents/` for repo-local agent assets
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
