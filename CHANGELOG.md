# Changelog

All notable project changes are tracked here.

## Unreleased

## 0.3.0 - 2026-05-16

### Added

- `seed-agent web` now exposes read-only state, budget pool, and heartbeat health
  API endpoints for local operator visibility without opening Docker logs.
- The local Web UI now opens on a read-only status overview that displays
  heartbeat health, candidate/intent state counts, and configured budget pools.
- Added `scripts/bump_version.py` to keep release metadata files aligned during
  deployment-facing version bumps.

## 0.2.2 - 2026-05-15

### Fixed

- `schedule-run` now writes compact per-cycle summaries to stdout so Unraid's
  Docker log viewer can stay responsive while detailed decisions remain in
  audit/state files.

## 0.2.1 - 2026-05-15

### Added

- Candidate state now preserves enqueue-time evidence, including size, demand,
  discount, free-window, and scoring reasons.
- Review, daily-report, and prune-preview output now join candidate evidence with
  qB runtime outcomes for operator tuning.

### Fixed

- Cleanup keeps currently uploading managed torrents even when an older
  no-upload marker exists.

## 0.2.0 - 2026-05-15

### Added

- Local `seed-agent web` settings UI for tracker configuration, preserving the
  YAML reference versus local secret file boundary and exposing safe
  tracker-local validation, site probe, and dry-run preview actions.

### Performance

- qB live torrent loading now uses one all-category listing when multiple
  category policies need review, while preserving the narrower category-filtered
  request for single-policy checks.
- Runtime state enrichment now batches SQLite reads and writes for managed
  torrents, avoiding per-torrent connection churn during review, prune, and
  scheduler cycles.

### Fixed

- Cleanup ownership is now granted by configured qB category membership only;
  tags remain audit/search metadata and no longer grant delete authority outside
  the mutable category.
- Enqueue gating now plans accepted candidates by score against remaining
  download headroom, so a full queue can start the best fitting candidates and
  pause the rest instead of applying one global paused flag to the whole batch.
- Runtime download-pressure checks now ignore zero-progress stopped download
  entries, preventing paused queue placeholders from blocking future higher
  priority candidates.
- Cleanup now observes completed active seeds for a configurable no-upload
  window before deletion, instead of pausing first and losing the ability to
  observe upload contribution during that window.
- M-Team API discovery can now fetch multiple pages with `api_discovery.max_pages`,
  so a page full of already-managed high-score candidates does not starve new
  enqueue opportunities.
- M-Team API discovery no longer does detail enrichment for every search result
  by default, keeping multi-page discovery responsive.
- Container entrypoint and deployment templates now support `SEED_AGENT_PRUNE=true`
  so scheduled Docker deployments can actually run cleanup each cycle.
- `run-once` now skips candidates already tracked as enqueued or active, avoiding
  repeated qB add attempts for the same accepted torrent.

### Added

- M-Team API-driven discovery with `api_key_ref`, FREE filtering, activity-oriented
  sorting, deferred `genDlToken` download URL generation for accepted execute-mode
  enqueue candidates, and `site-probe` discovery-mode visibility.
- M-Team API discovery can now send native OpenAPI search filters such as
  categories, sources, mediums, standards, codecs, teams, processings, labels,
  keyword/IMDB/Douban/DMM fields, date ranges, `hot`, `offer`, and explicit
  discount enums.
- Discovery scoring now supports hard candidate size bounds through
  `min_size_gb` and `max_size_gb`, plus configurable soft preferred size ranges.
- `min_seeders` and `max_leechers` discovery settings now participate in scoring
  as hard bounds when configured.
- qBittorrent category policies and logical budget pools, including mutable seed
  categories, add-only media categories, over-budget paused enqueue behavior, and
  pool usage summaries.
- Policy-aware audit context for enqueue and cleanup decisions.
- A Docker image build path, container entrypoint, and operator documentation for
  running the agent as either a long-lived polling container or an externally
  scheduled single-run job.
- A root `VERSION` file and release process guide for Docker image releases.
- A `schedule-run` CLI command for unattended polling loops with structured cycle
  metadata for server-side execution logs.
- A `healthcheck` CLI command, scheduler heartbeat output, and first-class
  Compose and Kubernetes CronJob examples for server deployments.
- qB live-state summaries in `review`, `daily-report`, and `run-once`, including
  current upload/download activity and default-pool visibility.
- Persistent qB runtime snapshots now feed `recent_upload_gb` back into prune
  and eviction decisions so active contributors are less likely to be treated
  as cold torrents.
- `enqueue`, `intent-enqueue`, and `intent-run-once` now expose the same qB live
  runtime summaries and default-pool context as `run-once`, reducing dry-run
  blind spots before queue mutations.
- Optional runtime enqueue gates can now switch accepted torrents to paused-add
  behavior when active downloads or remaining queued volume exceed configured
  thresholds.
- Paused enqueue decisions now carry explicit pause reasons through CLI payloads
  and audit-facing decision summaries, including the intent enqueue flows.
- qB runtime persistence now stamps a first-seen `paused_at` for already-paused
  managed torrents, so prune can eventually delete long-paused items instead of
  keeping them forever on missing timestamp data.
- Conservative runtime enqueue gates now count stalled/meta download states as
  download pressure even when current `dlspeed` is zero.

### Changed

- README and operations docs now treat `seed-agent` as a Docker-first self-hosted
  app, with Docker Compose installation as the primary user path instead of a
  contributor-first local Python workflow.
- Repository AI docs now describe M-Team API discovery as a current capability while
  keeping RSS as a supported fallback path.
- Cleanup decisions for mutable categories use composite eviction ranking before
  applying pause/delete actions.
- Config files under `config/` resolve `local/secrets/...` against the repository
  root.
- Local live operation configs matching `config/live-*.yaml` are ignored by git.
- The example config caps mutable seed candidates at 150 GiB while keeping
  2-80 GiB as the preferred scoring range and requiring at least one seeder.
- Execute-mode operator docs now show how to use polling safely in unattended
  deployments rather than relying on ad hoc local invocations, and the dry-run
  output now documents the same free-window safety preview behavior.
- Deployment guidance now explicitly prefers host-driven scheduled `run-once`
  execution for production-like installs while keeping `schedule-run` available.
- Docker deployment docs now include a dedicated Compose user guide, Docker image
  publishing guide, and a registry-override Compose example that fits both GHCR
  and Docker Hub style image distribution.
- Docker deployment docs now align the documented healthcheck config path with
  the actual container mount contract at `/app/config/config.yaml`.
- GitHub Actions now publishes GHCR images with branch, semver, and short-SHA
  tags, and the Dockerfile carries OCI image metadata.

### Fixed

- Missing M-Team API secret files now fail explicitly instead of producing an empty
  discovery result.
- M-Team API candidates map known discount expiry fields to `left_time_minutes`.
  When the API omits discount expiry for a current FREE/2xFREE result, scoring no
  longer hard-rejects the candidate, but it grants no left-time score.
- M-Team API discovery now reads discount labels from nested `status.discount`,
  maps local `downloads` sorting to the API's `TIMES_COMPLETED` field, and avoids
  bulk download-token generation during discovery.
- M-Team API sorting now emits the documented uppercase enum values such as
  `CREATED_DATE`, `TIMES_COMPLETED`, `LEECHERS`, `SEEDERS`, `SIZE`, and `NAME`.
- qBittorrent prune pool usage now includes add-only categories in shared budget
  totals while keeping cleanup actions restricted to mutable/delete-enabled
  categories.
- Run loops can now preview and enforce candidate rejection when the known free
  window is too short for the configured safety threshold, and scheduled runs
  can require known free-window data before mutating qBittorrent.
