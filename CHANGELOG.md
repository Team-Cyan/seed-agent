# Changelog

All notable project changes are tracked here.

## Unreleased

### Added

- M-Team API-driven discovery with `api_key_ref`, FREE filtering, activity-oriented
  sorting, deferred `genDlToken` download URL generation for accepted execute-mode
  enqueue candidates, and `site-probe` discovery-mode visibility.
- qBittorrent category policies and logical budget pools, including mutable seed
  categories, add-only media categories, over-budget paused enqueue behavior, and
  pool usage summaries.
- Policy-aware audit context for enqueue and cleanup decisions.

### Changed

- Repository AI docs now describe M-Team API discovery as a current capability while
  keeping RSS as a supported fallback path.
- Cleanup decisions for mutable categories use composite eviction ranking before
  applying pause/delete actions.
- Config files under `config/` resolve `local/secrets/...` against the repository
  root.
- Local live operation configs matching `config/live-*.yaml` are ignored by git.

### Fixed

- Missing M-Team API secret files now fail explicitly instead of producing an empty
  discovery result.
- M-Team API candidates map known discount expiry fields to `left_time_minutes`.
  When the API omits discount expiry for a current FREE/2xFREE result, scoring no
  longer hard-rejects the candidate, but it grants no left-time score.
- M-Team API discovery now reads discount labels from nested `status.discount`,
  maps local `downloads` sorting to the API's `TIMES_COMPLETED` field, and avoids
  bulk download-token generation during discovery.
- qBittorrent prune pool usage now includes add-only categories in shared budget
  totals while keeping cleanup actions restricted to mutable/delete-enabled
  categories.
