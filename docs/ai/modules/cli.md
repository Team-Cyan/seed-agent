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
- the Web UI Want List toolbar separates source refresh from torrent search:
  refresh syncs configured Douban/IMDb sources into local intent state, while
  search runs the non-mutating torrent search for the current filters,
- intent enqueue routes resource downloads by media type through
  `downloader.media_category_map` when configured. Without an explicit map,
  movie requests use `movie` when present, show/episode/anime requests use
  `tv` when present, and unknown resource types fall back to the downloader
  default category,
- the Web UI downloader page exposes visual editors for qB category policies,
  budget pools, and Want List media-type-to-category routing, while still
  preserving the per-section YAML editor for advanced edits,
- schema-validated web config previews that return before/after diffs before
  non-tracker section saves write YAML,
- per-section web YAML editing for top-level config blocks while preserving a
  single physical runtime config file,
- configured source-event ingestion during `intent-run-once`, including Douban
  wanted-list and IMDb watchlist/list events,
- `schedule-run` runs the resource intent loop every cycle by default, so
  configured Want List sources are refreshed and searched without requiring the
  operator to click the Web UI buttons. This scheduled resource loop remains a
  dry-run unless `--intent-execute` is explicitly set, and it can be disabled
  with `--no-intent`,
- free-window safety previewing for freeleech-sensitive workflows,
- optional per-cycle cleanup through `run-once --prune` and `schedule-run --prune`,
- stronger prune previews that include live torrent identity, linked candidate
  state, action, reason, and whether delete actions remove files,
- `review`, `daily-report`, `prune`, `run-once`, and scheduler-backed runs
  report how many known active torrents were reconciled as missing from qB,
- discovery-backed command payloads include `discovery_warnings` when an
  enabled site fails at runtime while other sites or flows continue,
- `intent-run-once` payloads include `source_warnings` when configured Want
  List source refresh fails while the intent cycle continues with no new source
  events,
- heartbeat reporting and healthcheck probes for long-running deployments.

## Expectations

- do not expose secrets in output,
- keep summaries useful but redacted,
- preserve stable command names unless intentionally versioned,
- keep `run-once` and `schedule-run` payload shapes aligned enough for external
  schedulers and log collectors,
- keep site discovery warnings visible in both full JSON payloads and
  `schedule-run` summaries so transient tracker errors are diagnosable without
  forcing a container restart,
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
- keep scheduled Want List search non-mutating by default; automatic resource
  qB enqueue requires explicit `--intent-execute`,
- keep configured Want List source refresh failures fail-soft so Douban/IMDb
  availability issues do not restart long-running scheduler containers,
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
