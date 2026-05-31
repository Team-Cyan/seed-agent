# CLI Module

## Purpose

Expose the operator-facing command surface and safe summaries.

## Primary Files

- `src/seed_agent/cli.py`
- `tests/test_cli.py`
- `tests/test_cli_bootstrap.py`

## Current Responsibilities

- command registration,
- config loading,
- dry-run defaults,
- safe JSON summaries,
- site probe diagnostics,
- unattended `schedule-run` orchestration for server-side polling,
- local `web` settings UI server for safe configuration editing,
- Docker entrypoint support for running the settings Web UI beside
  `schedule-run` when `SEED_AGENT_WEB_ENABLED=true`,
- grouped Web UI navigation, mobile section switching, touch-sized controls, and
  modal interactions for the local settings surface,
- read-only web API endpoints for state summary, configured budget pools, and
  heartbeat health,
- web Want List endpoints for listing canonical Douban/IMDb wants, triggering
  search-only dry runs, reviewing saved release candidates, selecting a release,
  and explicitly enqueueing the selected release through the same intent enqueue
  path,
- schema-validated web config previews that return before/after diffs before
  non-tracker section saves write YAML,
- per-section web YAML editing for top-level config blocks while preserving a
  single physical runtime config file,
- configured source-event ingestion during `intent-run-once`, including Douban
  wanted-list and IMDb watchlist/list events,
- free-window safety previewing for freeleech-sensitive workflows,
- optional per-cycle cleanup through `run-once --prune` and `schedule-run --prune`,
- stronger prune previews that include live torrent identity, linked candidate
  state, action, reason, and whether delete actions remove files,
- `review`, `daily-report`, `prune`, `run-once`, and scheduler-backed runs
  report how many known active torrents were reconciled as missing from qB,
- heartbeat reporting and healthcheck probes for long-running deployments.

## Expectations

- do not expose secrets in output,
- keep summaries useful but redacted,
- preserve stable command names unless intentionally versioned,
- keep `run-once` and `schedule-run` payload shapes aligned enough for external
  schedulers and log collectors,
- keep enqueue-like commands aligned on runtime gate reporting so paused-add
  decisions expose both `enqueue_paused_by_pool_policy` and
  `enqueue_paused_reasons`,
- when remaining-download caps are configured, plan enqueue batches by score so
  higher-scoring candidates get the available active-download headroom before
  lower-scoring candidates are added paused,
- exclude zero-progress stopped download placeholders from active download
  liability so old paused queue entries do not block fresh high-priority work,
- preview and enforce risky free-window decisions consistently when the free
  window is unknown or too short for the configured safety threshold,
- keep optional scheduled pruning explicit through `--prune` so cleanup is never
  silently bundled into a long-running deployment,
- expose cleanup preview details before execute-mode mutation,
- pass the scheduler interval into per-cycle pruning so persisted free-window
  expiries can be evaluated against the next scheduled check,
- keep long-running deployment liveness inspectable through structured
  heartbeat output instead of opaque shell wrappers.
- keep web UI actions safe by default: tracker-local validation, site probe,
  search, dry-run previews, and read-only state endpoints must not execute
  enqueue or cleanup mutations. qB enqueue from the Want List must remain an
  explicit candidate-level action with a confirmation step. Candidate review UI
  should keep lower-match releases visibly distinct without making their force
  actions look disabled.

## Verification

- `uv run pytest -q tests/test_cli.py tests/test_cli_bootstrap.py tests/test_run_once.py`
- `uv run seed-agent --help`
- `uv run seed-agent schedule-run --help`
- `uv run seed-agent healthcheck --help`
- `uv run seed-agent web --help`
- `uv run seed-agent intent-run-once --config <config>`
