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
  search-only dry runs for current filters or a single item, reviewing saved
  release candidates, and explicitly enqueueing one release through the same
  intent enqueue path,
- the Web UI Want List toolbar separates source refresh from torrent search:
  refresh syncs configured Douban/IMDb sources into local intent state, while
  search runs the non-mutating torrent search for the current filters. Each
  Want List row also exposes a single-item search action. Already queued wants
  are skipped by default instead of searching M-Team again,
- intent enqueue routes resource downloads by media type through
  `download_client.media_category_map` when configured. Without an explicit map,
  movie requests use `movie` when present, show/episode/anime requests use
  `tv` when present, and unknown resource types fall back to the downloader
  default category,
- the Web UI downloader page exposes visual editors for qB category policies,
  budget pools, and Want List media-type-to-category routing, while still
  preserving the per-section YAML editor for advanced edits,
- schema-validated web config previews that return before/after diffs before
  non-tracker section saves write YAML,
- validated config and secret writes use same-directory atomic replacement, so
  scheduler readers never observe a partially written YAML or credential file,
- per-section web YAML editing for top-level config blocks while preserving a
  single physical runtime config file,
- configured source-event ingestion during `intent-run-once`, including Douban
  wanted-list, IMDb watchlist/list, Letterboxd CSV, and Telegram polling
  events,
- rule/config portability through `config-export` and dry-run-first
  `config-import --rules <file>`, with writes gated by `--execute`,
- read-only product-expansion reports through `release-profiles`,
  `reseed-report`, `headroom-report`, and `quality-replay-report`,
- runtime recovery through `state-backup`, `state-backup-verify`, preview-first
  `state-restore`, and locked `audit-archive`; restore execution is rejected
  while a scheduler lease is active,
- `schedule-run` reads cycle, prune, backfill, free-window, and Intent defaults
  from the YAML `scheduler` section. Explicit CLI flags and container variables
  override those defaults and are reported in scheduler summaries; the Web
  scheduler page also lists environment-derived overrides. Configured
  Want List sources are refreshed every enabled cycle; scheduled torrent search
  follows `scheduler.intent_search_mode` (`daily` once at or after
  `intent_search_hour` by default, with missed runs caught up on the next
  cycle, or `every_cycle`). Operators can still trigger filtered or
  single-item Want List searches manually from the Web UI. Scheduled resource
  enqueue remains a dry-run unless `--intent-execute` is explicitly set, and the
  loop can be disabled with `--no-intent`,
- `schedule-trigger` asks the already-running scheduler process to start one
  cycle immediately. The durable scheduler control state rejects the request
  while a cycle is already running, so the command cannot create a concurrent
  second scheduler. A manual cycle resets the next interval from that cycle's
  start time,
- `scheduler-backoff-clear` deactivates the current M-Team scheduler backoff
  without disabling the shared request pacer or future automatic protection,
- `schedule-run` records a persistent scheduler backoff when M-Team returns
  "request too frequent" responses. While that backoff is active, the scheduler
  keeps writing heartbeat output, skips tracker/API discovery and Want List
  search, but still runs local prune from persisted evidence. Web UI Want List search
  actions read the same backoff file and skip tracker searches during that
  window,
- free-window safety previewing for freeleech-sensitive workflows,
- optional cleanup through `run-once --prune` and scheduled cleanup through
  `schedule-run --prune`. Standalone `run-once --prune` keeps the historical
  post-enqueue cleanup behavior; scheduled cycles run conservative prune before
  PT discovery/enqueue, then run the resource intent loop last,
- scheduled cycles first run tracker source backfill for qB-only live torrents,
  bounded by `scheduler.tracker_backfill_max_api_requests` (default `20`), then
  conservative prune, PT discovery/enqueue, and the resource intent loop.
  Remaining tasks rotate into later cycles by risk and oldest evidence. The
  backfill phase stops on the first rate-limit or network failure and also uses
  the shared request pacer,
- scheduled PT enqueue can run one capacity-pressure prune when accepted
  candidates would otherwise be rejected by runtime gates. That pass uses
  forced space reclamation, refreshes qB state afterward, and recomputes enqueue
  batches before adding,
- stronger prune previews that include live torrent identity, linked candidate
  state, action, reason, and whether delete actions remove files,
- `review`, `daily-report`, `prune`, `run-once`, and scheduler-backed runs
  report how many known active torrents were reconciled as missing from qB,
- `tracker-source-backfill` can reconcile qB-only live torrents back to tracker
  source evidence. It is API-budgeted, supports category/limit scoping, stays
  dry-run unless `--execute` is passed, and currently uses conservative
  title-plus-size matching for M-Team,
- discovery-backed command payloads include `discovery_warnings` when an
  enabled site fails at runtime while other sites or flows continue,
- `intent-run-once` payloads include `source_warnings` when configured Want
  List source refresh fails while the intent cycle continues with no new source
  events,
- heartbeat reporting and healthcheck probes for long-running deployments.
- optional Prometheus `/metrics` output derived only from local SQLite and
  heartbeat evidence, with fixed low-cardinality labels and no tracker or
  downloader calls during scrape.

## Expectations

- do not expose secrets in output,
- keep summaries useful but redacted,
- preserve stable command names unless intentionally versioned,
- keep `run-once` and `schedule-run` payload shapes aligned enough for external
  schedulers and log collectors,
- route manual scheduler triggers through the active scheduler lease and
  durable `running`/`waiting` state; never start a parallel one-shot process,
- keep site discovery warnings visible in both full JSON payloads and
  `schedule-run` summaries so transient tracker errors are diagnosable without
  forcing a container restart,
- keep enqueue-like commands aligned on runtime gate reporting so rejected
  decisions expose `enqueue_blocked_by_runtime_gate` and
  `enqueue_blocked_reasons`; the legacy paused-policy flag remains `false`
  during compatibility migration,
- when remaining-download caps are configured, plan enqueue batches by score so
  higher-scoring candidates get the available active-download headroom before
  lower-scoring candidates are rejected before qB is called,
- exclude zero-progress stopped download placeholders from active download
  liability so old paused queue entries do not block fresh high-priority work,
- preview and enforce risky free-window decisions consistently when the free
  window is unknown or too short for the configured safety threshold,
- keep scheduled pruning explicit through YAML or `--prune`. When enabled, schedule order
  must remain tracker source backfill, conservative prune, PT add, then Want
  List source refresh, with Want List torrent search following the configured
  daily/every-cycle policy,
- keep scheduled Want List search non-mutating by default; automatic resource qB enqueue requires explicit
  `--intent-execute`,
- when M-Team rate limits scheduled discovery, keep the container alive through
  heartbeat updates but skip PT discovery and Want List search until the shared
  scheduler backoff expires. The backoff must not become a tight retry loop,
- keep configured Want List source refresh failures fail-soft so Douban/IMDb
  availability issues do not restart long-running scheduler containers,
- expose cleanup preview details before execute-mode mutation,
- pass the scheduler interval into per-cycle pruning so persisted free-window
  expiries can be evaluated against the next scheduled check,
- keep schedule's first prune conservative: completed low-upload seeds should
  require space reclamation there. The aggressive pass belongs to enqueue-time
  capacity pressure only, when better accepted candidates are waiting,
- keep long-running deployment liveness inspectable through structured
  heartbeat output instead of opaque shell wrappers.
- keep web UI actions safe by default: tracker-local validation, site probe,
  search, dry-run previews, and read-only state endpoints must not execute
  enqueue or cleanup mutations. qB enqueue from the Want List must remain an
  explicit candidate-level action with a confirmation step. Candidate review UI
  should keep lower-match releases visibly distinct without making their force
  actions look disabled.
- keep `config-import` dry-run by default and validate the merged config before
  atomically writing. Imported rule bundles should not contain secret values,
  only secret refs.

## Verification

- `uv run pytest -q tests/test_cli.py tests/test_cli_bootstrap.py tests/test_run_once.py`
- `uv run pytest -q tests/test_downloader_contracts.py tests/test_search_contracts.py`
- `uv run seed-agent --help`
- `uv run seed-agent schedule-run --help`
- `uv run seed-agent healthcheck --help`
- `uv run seed-agent web --help`
- `uv run seed-agent intent-run-once --config <config>`
- `uv run seed-agent tracker-source-backfill --config <config> --category seed --limit 1 --max-api-requests 2`
