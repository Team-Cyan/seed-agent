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
- real-world confirmation that `genDlToken` and `torrent/detail` work with the laboratory access token
- `site-probe` reporting for authenticated M-Team access

## In Progress

- Codex project initialization and harness-oriented AI docs

## Next

### M-Team API-Driven Discovery

- add API-driven discovery for M-Team
- support FREE filtering and activity-based sorting
- keep RSS intact as fallback and reusable adapter logic

Reference:

- `docs/specs/2026-04-24-mteam-api-driven-discovery.md`

### qBittorrent Live-State-Grounded Strategy

- ingest richer qB runtime state for better ROI decisions
- improve visibility into active upload/download conditions before enqueue
- replace the single managed-category assumption with per-category policy and logical budget control

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
