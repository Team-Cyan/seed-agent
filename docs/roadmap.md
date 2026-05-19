# Roadmap

This file tracks the current project status at a level that is easy for both humans and AI sessions to refresh quickly.

## Completed

### Foundation

- Python package bootstrap with `uv`, Typer CLI, tests, and linting
- Config-first project structure
- SQLite local state
- append-only redacted audit log
- Thin `AGENTS.md`, `.agents/`, and `docs/` routing for future agent sessions

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
- qB policy torrent loading and runtime SQLite enrichment are batched for lower
  scheduler, review, and prune overhead
- qB `completion_on <= 0` is treated as unknown completion time, preventing
  incomplete torrents from looking like 1969 completions
- zero-total-upload managed torrents are observed from qB `added_at` and can be
  pruned after the configured no-upload window, including incomplete downloads
  that consumed space but never uploaded
- candidate state now preserves enqueue-time evidence such as size,
  seeders/leechers, discount, left time, and score reasons
- `review`, `daily-report`, and prune previews join enqueue-time evidence with
  later qB runtime outcomes such as ratio, completion time, amount left,
  recent upload, and no-upload observation state
- cleanup keeps currently uploading managed torrents instead of allowing stale
  no-upload markers to drive delete decisions
- mutable seed cleanup only pauses or deletes cold/no-upload torrents when the
  configured budget pool is over budget, so normal seed contribution is kept
  until space reclamation is needed
- qB live-state refreshes now reconcile known active candidate hashes that have
  disappeared from qB into local `deleted` state with missing-from-qB evidence
- qB live-state refreshes revive stale local `deleted` evidence when the same
  torrent hash is visible in qB again
- tracker strategy tuning is evidence-driven through `strategy-report`, with
  concrete knobs for leecher score ramping and large-pack partial size credit
  plus recommendation-only config examples for balanced, upload-farming, and
  space-saving strategies

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
- startup and on-demand runtime status reports for version, config path,
  heartbeat, state, audit, and credential-file visibility
- first-class Compose and Kubernetes CronJob deployment examples
- Docker-first README and Compose user guide for self-hosted NAS deployments
- Compose-level registry override example for GHCR and Docker Hub style image
  distribution
- GHCR publish workflow with multi-arch images, semver tags, short-SHA tags,
  OCI labels, and release-version validation
- Docker Hub automation remains deferred; GHCR stays the primary automated
  registry until a runtime-status-verified Unraid install still shows registry
  friction
- documented release version policy: code fixes and operational fixes bump patch
  by `0.0.1`; new features bump minor by `0.1.0`
- version bump helper keeps release metadata files aligned

## In Progress

- Codex project initialization and harness-oriented AI docs

### Web Settings UI

- local `seed-agent web` command for configuration editing
- tracker-first settings UI design and implementation are in place, but the
  surface is still WIP rather than a finished operations UI
- read-only status UI exists for state summary, configured budget pools, and
  scheduler heartbeat health
- downloader, discovery, cleanup, and Phase 2 intent settings can be loaded
  from YAML and saved through schema validation, while complex policy/source
  structures remain intentionally conservative
- remaining work includes stronger UX polish, richer source/search coverage, and
  a clearer split from the future read-only dashboard surface

## Next

### Web Settings UI

- add safe search/source integration editing without exposing secret values
- add clearer before/after config diff preview before saving

### qBittorrent Live-State-Grounded Strategy

- refine eviction ranking with tracker-side demand signals when available
- use the new joined evidence reports to tune cleanup thresholds against real
  upload outcomes before adding more automation
- use missing-from-qB reconciliation evidence to distinguish agent cleanup from
  external/manual qB deletions when upload history suddenly changes

### Scheduler And Server Deployments

- extend deployment examples to the user's real target environments after the
  first server install

Reference:

- `docs/specs/2026-04-25-qb-category-policy-budgeting.md`

## Later

- rule import/export
- auto-reseed
- Transmission downloader support as the first second-downloader adapter
- a second non-M-Team API provider to validate provider boundaries
- read-only dashboard surface for audit, cleanup decisions, and intent queues
- richer reporting and feedback-loop scoring that turns tracker/account signals,
  downloader telemetry, historical outcomes, and user confirmations into real
  `site_history_score` inputs
- live-state enqueue headroom planning v2, after joined evidence proves which
  qB runtime signals reliably predict good enqueue outcomes
- stronger source integrations beyond local skeletons

## Deferred Or Intentionally Not In Scope

- dashboard-first product work
- browser-login automation as a core M-Team strategy
- broad multi-site plugin framework before current module boundaries are stable
