# Scheduler Observability And Tracker Throttle Refinement

This spec captures the complete repository refinement plan for making
`seed-agent` easier to operate after repeated tracker throttling, unclear
scheduled runs, and hard-to-debug Want List behavior.

## Goals

1. Keep the scheduler implementation simple: a Docker-friendly long-running
   `schedule-run` loop remains the default runtime shape.
2. Make every scheduled cycle traceable by a stable `run_id`.
3. Persist run-level and phase-level evidence in SQLite.
4. Treat tracker throttling as structured runtime state, not log text.
5. Stop subsequent tracker calls immediately after a clear M-Team throttle.
6. Persist enough Want List search status to explain why an item was searched,
   skipped, ranked, enqueued, or blocked by backoff.
7. Expose operator-facing reports before adding richer Web UI surfaces.
8. Keep cleanup decisions explainable with live qB and candidate evidence.
9. Make live config and runtime provenance inspectable without deployment SSH
   spelunking.
10. Provide a read-only operations dashboard without turning the app into a
    dashboard-first product.

## Data Model

The existing `.seed-agent/state.db` remains the durable runtime database. New
tables must be initialized by `StateStore` and preserve WAL/busy-timeout behavior.

### `scheduler_runs`

- `run_id TEXT PRIMARY KEY`
- `started_at TEXT NOT NULL`
- `finished_at TEXT`
- `status TEXT NOT NULL`
- `command TEXT NOT NULL`
- `config TEXT`
- `execute INTEGER NOT NULL`
- `interval_minutes INTEGER`
- `prune_enabled INTEGER NOT NULL`
- `intent_enabled INTEGER NOT NULL`
- `intent_execute INTEGER NOT NULL`
- `backoff_active INTEGER NOT NULL`
- `backoff_until TEXT`
- `discovered INTEGER`
- `scored INTEGER`
- `accepted INTEGER`
- `enqueued INTEGER`
- `intent_ingested INTEGER`
- `intent_searched INTEGER`
- `intent_ranked INTEGER`
- `intent_enqueue_candidates INTEGER`
- `warning_count INTEGER NOT NULL`
- `error TEXT`
- `summary_json TEXT NOT NULL`

### `scheduler_run_events`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL`
- `phase TEXT NOT NULL`
- `event TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `message TEXT`
- `payload_json TEXT`

Phase names are stable operator vocabulary:

- `startup`
- `backoff_check`
- `prune`
- `pt_discovery`
- `pt_score`
- `pt_enqueue`
- `intent_source_sync`
- `intent_search`
- `intent_rank`
- `intent_enqueue`
- `heartbeat`
- `sleep`

### `tracker_backoffs`

- `site TEXT NOT NULL`
- `endpoint TEXT NOT NULL`
- `active INTEGER NOT NULL`
- `created_at TEXT NOT NULL`
- `until TEXT NOT NULL`
- `reason TEXT NOT NULL`
- `source TEXT`
- `run_id TEXT`
- `PRIMARY KEY (site, endpoint)`

### `tracker_api_events`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `site TEXT NOT NULL`
- `endpoint TEXT NOT NULL`
- `event TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `run_id TEXT`
- `status_code INTEGER`
- `api_code TEXT`
- `rate_limited INTEGER NOT NULL`
- `message TEXT`
- `request_json TEXT`
- `response_json TEXT`

### `want_search_runs`

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `intent_id TEXT NOT NULL`
- `run_id TEXT`
- `source TEXT NOT NULL`
- `searched_at TEXT NOT NULL`
- `status TEXT NOT NULL`
- `search_enabled INTEGER NOT NULL`
- `results_count INTEGER NOT NULL`
- `best_score INTEGER`
- `selected_release_id TEXT`
- `backoff_active INTEGER NOT NULL`
- `backoff_until TEXT`
- `message TEXT`
- `payload_json TEXT`

## Runtime Behavior

- `schedule-run` generates a `run_id` before any phase work starts.
- Heartbeat and all JSON log lines include `run_id`.
- Phase logs are newline JSON records, not decorative text headers.
- On active backoff, the scheduler records a skipped run and does not call PT,
  cleanup, or Want List tracker-search phases.
- M-Team API errors expose structured fields:
  - endpoint
  - code
  - message
  - `rate_limited`
- M-Team throttle from `/torrent/search` or `/torrent/genDlToken` records a
  tracker backoff and prevents subsequent M-Team calls in that cycle.
- Existing `schedule-backoff.json` remains a compatibility artifact while the
  SQLite `tracker_backoffs` table becomes the authoritative shared throttle
  state for scheduler and Web handlers.

## Commands

Add read-only report/doctor commands:

- `scheduler-report`
- `tracker-api-report`
- `contribution-report`
- `config-status`
- `config-diff`
- `runtime-doctor`

These commands should never mutate qBittorrent or tracker state.

## Web UI

The Web UI adds a compact read-only operations surface:

- current scheduler heartbeat and backoff
- recent scheduler runs
- recent tracker API warnings
- recent Want List search statuses

The surface stays operational and dense; it should not become a marketing-style
dashboard or replace CLI reports.

## Verification

Required verification for the full refinement:

- focused unit tests for M-Team rate-limit classification and propagation
- focused state tests for all new SQLite tables and migrations
- focused CLI tests for `run_id`, reports, and scheduler persistence
- focused Web tests for backoff-aware Want List search and ops payloads
- `uv run ruff check .`
- `uv run pytest -q`

Deployment to Unraid is explicitly out of scope for this refinement pass.
