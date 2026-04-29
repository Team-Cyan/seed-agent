# Roadmap

This file tracks the current project status at a level that is easy for both humans and AI sessions to refresh quickly.

## Completed

### Foundation

- Python package bootstrap with `uv`, Typer CLI, tests, and linting
- Config-first project structure
- SQLite local state
- append-only redacted audit log

### PT Upload Strategy Loop

- RSS discovery for current site adapters
- score-based candidate evaluation
- qBittorrent enqueue path with dry-run first
- managed torrent review
- balanced cleanup policy with pause-before-delete behavior
- daily report and run-once command surface
- unattended scheduler command surface with free-window safety preview and enforcement

### Resource Intent Loop

- intent add and inbox ingestion
- deterministic intent parsing
- RSS-backed search provider
- release ranking and ambiguity handling
- confirm and reject commands
- enqueue reuse through shared downloader path
- intent run-once loop
- source adapter skeletons for file inbox, Telegram, WeChat bridge, and Douban

### M-Team Current Integration

- M-Team RSS parsing
- M-Team `x-api-key` detail enrichment
- real-world confirmation that `torrent/detail` works with the laboratory access token
- deferred `genDlToken` resolution for accepted API candidates during execute-mode enqueue
- M-Team API-driven discovery with native OpenAPI filters, FREE/discount filtering,
  and activity-based sorting
- `site-probe` reporting for authenticated M-Team access and discovery mode

### Deployment Readiness

- Docker image build path for server-side operation
- environment-driven container entrypoint for `run-once`, `enqueue`, and `schedule-run`
- operator docs for long-running pollers vs external scheduled jobs
- healthcheck and heartbeat support for long-running scheduler containers
- first-class Compose and Kubernetes CronJob deployment examples

## In Progress

- Codex project initialization and harness-oriented AI docs

## Next

### qBittorrent Live-State-Grounded Strategy

- ingest richer qB runtime state for better ROI decisions
- improve visibility into active upload/download conditions before enqueue
- use richer live qB state to distinguish saturated seedbox keepers from torrents
  that are merely old or large
- convert live-state visibility into conservative enqueue and prune protections
  only after the runtime summaries have proven useful
- keep recent-upload snapshots durable enough for prune and eviction logic to
  avoid penalizing torrents that are still contributing

### Scheduler And Server Deployments

- extend deployment examples to the user's real target environments after the
  first server install
- add release-publishing steps for DockerHub or another registry

Reference:

- `docs/specs/2026-04-25-qb-category-policy-budgeting.md`

## Later

- rule import/export
- auto-reseed
- local HTTP API
- richer reporting
- optional UI surfaces
- stronger source integrations beyond local skeletons

## Deferred Or Intentionally Not In Scope

- dashboard-first product work
- browser-login automation as a core M-Team strategy
- broad multi-site plugin framework before current module boundaries are stable
