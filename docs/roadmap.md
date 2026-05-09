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
- completed active seeds can be observed for a no-upload window before deletion,
  avoiding pause-first cleanup when upload contribution still needs measuring
- daily report and run-once command surface
- unattended scheduler command surface with free-window safety preview and enforcement
- optional scheduled pruning through `run-once --prune` and `schedule-run --prune`
- execute-mode enqueue persists candidate `free_window_expires_at` when a finite
  free window is known
- unlimited M-Team API free windows persist as `9999-12-31T23:59:59+00:00`
- `schedule-run --prune` pauses managed torrents whose persisted free window
  cannot survive until the next scheduled check
- scoring uses a soft seeder/leecher pressure ratio instead of an absolute
  seeder cap, with explicit `allow_non_free` control for NORMAL candidates
- stale unqueued candidate rows are pruned by retention policy while linked qB
  lifecycle rows are kept
- prune payloads include a stronger preview and qB live torrents are backfilled
  into local candidate state when no candidate row exists yet
- runtime enqueue gates use score-prioritized headroom planning, so higher-score
  accepted candidates can start while lower-priority candidates are added paused
- zero-progress stopped download placeholders are excluded from active download
  liability calculations

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
- Docker-first README and Compose user guide for self-hosted NAS deployments
- Compose-level registry override example for GHCR and Docker Hub style image
  distribution
- GHCR publish workflow with multi-arch images, semver tags, short-SHA tags,
  OCI labels, and release-version validation
- documented release version policy: code fixes and operational fixes bump patch
  by `0.0.1`; new features bump minor by `0.1.0`

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
- refine eviction ranking with tracker-side demand signals when available
- add an operator report that summarizes no-upload observation windows and
  pending cleanup deletes before execute-mode pruning

### Scheduler And Server Deployments

- extend deployment examples to the user's real target environments after the
  first server install
- decide whether Docker Hub publishing should mirror GHCR or remain a manual
  downstream republish path
- add a small version bump helper once releases become frequent

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
