# Changelog

All notable project changes are tracked here.

## Unreleased

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

### Changed

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
