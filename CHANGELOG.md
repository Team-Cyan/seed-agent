# Changelog

All notable project changes are tracked here.

## Unreleased

## 0.8.1 - 2026-06-01

### Added

- Added project logo and icon assets, wired them into the README, Web UI
  favicon/sidebar branding, Docker image metadata, Compose example, and Unraid
  DockerMan template.

### Fixed

- Web static serving now returns browser-renderable MIME types for SVG and PNG
  image assets.

## 0.8.0 - 2026-06-01

### Added

- Added explicit Want List toolbar actions for refreshing configured
  Douban/IMDb sources and for manually triggering torrent search against the
  current source/type filters.

## 0.7.0 - 2026-06-01

### Added

- Added configurable Want List media routing through
  `downloader.media_category_map`, so movie, TV, and anime wants can target
  different qB categories instead of relying only on legacy fallback names.
- Added visual Web UI editors for downloader budget pools, qB category
  policies, and Want List media-type routing, reducing the need to hand-edit
  downloader YAML for common setup.

### Changed

- Refined the Web UI configuration surface with broader Chinese/English dynamic
  copy coverage, collapsed tracker cards that hide status details until opened,
  and mobile settings actions that no longer occupy fixed viewport space.

## 0.6.1 - 2026-05-31

### Fixed

- Want List and intent enqueue now route movie requests to the configured
  `movie` qB category and show/episode/anime requests to `tv` when those
  policies exist, instead of sending all resource downloads through the
  upload-farming `seed` category.

## 0.6.0 - 2026-05-31

### Added

- Want List candidate review now shows all saved M-Team candidates for an item,
  with matching releases ranked first and lower-match releases kept visible for
  explicit operator override.
- Web UI candidate review now exposes release size, seeder/leecher counts,
  M-Team tags, inferred quality tags, score, reasons, risks, release selection,
  dry-run enqueue preview, and user-confirmed qB enqueue actions.
- M-Team API-backed intent search now supplements Douban/IMDb ID lookup with a
  broad title/year fallback query and keeps non-matching candidates for review
  instead of hiding them before ranking.

### Changed

- Required, preferred, and excluded search keywords now act as ranking and
  review requirements for intent search, allowing old or urgent items to be
  force-selected from lower-match candidates.
- Mobile Web UI controls, Want List cards, and candidate modals now use larger
  touch targets, clearer action labels, keyboard-accessible candidate opening,
  sticky modal headers, backdrop/Escape close behavior, and actionable dimmed
  styling for lower-match releases.

## 0.5.2 - 2026-05-29

### Fixed

- Web Settings tracker cards now render and the add-site button works when the
  UI is opened from non-localhost HTTP hosts such as Unraid LAN addresses.
- Want List source saves can immediately sync configured Douban/IMDb lists into
  local intent state, and Want List search now syncs configured sources before
  searching while keeping downloads disabled.

## 0.5.1 - 2026-05-28

### Fixed

- Docker and Unraid deployments can now start the settings Web UI beside the
  long-running scheduler with `SEED_AGENT_WEB_ENABLED=true`, publish container
  port `8765`, and open DockerMan's WebUI button at the live local service.
- Unraid deployment docs now explain how to diagnose a healthy scheduler
  container whose WebUI button is unavailable because no web process or port
  mapping is present.

## 0.5.0 - 2026-05-26

### Added

- Web Settings UI now shows the active config path, supports schema-validated
  diff previews before non-tracker config saves, and can edit search,
  acquisition-decision, and Want List source settings without accepting
  plaintext secret values.
- Resource intent runs can ingest a configured public Douban wanted list and use
  M-Team API-backed intent search with execute-time deferred download-token
  resolution plus configurable required, preferred, and excluded release-title
  keywords such as Remux, 2160p, HDR, or Dolby Vision.
- Web UI now includes a Want List page backed by intent state, with Douban and
  IMDb sources, source/type filters, merged source evidence, media type, added
  time, and search/download status.
- Want List ingestion now canonicalizes duplicate wants by Douban/IMDb external
  IDs so multiple configured lists do not duplicate searches or downloads.
- IMDb watchlist/list ingestion supports CSV exports and best-effort public page
  parsing.
- Douban wanted ingestion now preserves source user, subject URL, intro, wish
  date, and inferred media type, with mobile subject-page enrichment for TV
  classification when the public list page is ambiguous.
- `intent.series_search_mode` controls whether TV/anime episode intents search
  and rank full-season packs or individual episodes.
- M-Team API discovery thresholds can inherit global discovery lower bounds by
  setting `api_discovery.min_seeders` or `api_discovery.min_leechers` to `null`;
  explicit `0` still keeps native API lower-bound filtering open.
- M-Team API-backed intent search now uses native Douban/IMDb ID filters when
  available, falls back from Douban ID to IMDb ID when needed, and applies
  Remux/quality keyword preferences locally.

### Fixed

- Want List duplicate evidence now records the incoming source row instead of
  reusing canonical intent fields.
- Intent search now keeps ranked candidates and state on the earliest canonical
  intent when M-Team release metadata reveals that Douban and IMDb IDs refer to
  the same work.
- Repeated wants in one source sync are searched once, and post-search ranking
  follows the canonical intent after alias merges.
- Intent merges preserve a selected release from the duplicate row when the
  canonical row does not already have one.
- Web UI Want List search now ranks the canonical intent after release-ID
  backfill merges.
- Web Settings UI now resets save confirmation after both text input and select
  changes, preventing stale diff previews from confirming a later edit.
- Search priority map inputs now reject malformed entries such as missing values
  or extra delimiters instead of coercing them silently.

## 0.4.1 - 2026-05-19

### Fixed

- Unraid DockerMan template now applies `--restart=unless-stopped`, matching the
  Compose deployment behavior so the long-running scheduler is restarted after
  host/container restarts or unexpected process exits.

## 0.4.0 - 2026-05-19

### Added

- Added `seed-agent strategy-report`, a read-only tracker strategy report that
  groups current candidates and linked qB outcomes by demand, size, score, and
  original enqueue evidence.
- Added recommendation-only tracker strategy config examples for balanced,
  upload-farming, and space-saving tuning.

### Changed

- Added fine-grained discovery knobs for leecher score ramping and large-pack
  partial size credit so strategy can be tuned through concrete config
  combinations instead of a coarse runtime profile field.

## 0.3.3 - 2026-05-18

### Fixed

- qB live-state refreshes now reconcile known active candidate hashes that are
  missing from the current qB torrent list, marking them `deleted` locally and
  storing missing-from-qB evidence for later investigation.
- qB live-state refreshes also revive stale local `deleted` evidence when the
  same torrent hash is visible in qB again.

## 0.3.2 - 2026-05-17

### Added

- Added `seed-agent runtime-status` plus startup runtime-status logging so
  Unraid and Compose installs can see the package version, config path,
  heartbeat path, state/audit paths, and credential-file visibility without
  opening application internals.

### Changed

- Scheduler heartbeat files now include the running package version and config
  path for easier deployment verification.
- Docker Hub automation remains deferred; GHCR stays the primary automated
  registry until a runtime-status-verified Unraid install still shows registry
  update friction.

## 0.3.1 - 2026-05-17

### Fixed

- `discovery.max_size_gb: 0` now disables the hard size ceiling, matching the
  existing `null` unbounded behavior and avoiding accidental rejection of all
  normal-sized candidates.

## 0.3.0 - 2026-05-16

### Added

- `seed-agent web` now exposes read-only state, budget pool, and heartbeat health
  API endpoints for local operator visibility without opening Docker logs.
- The local Web UI now opens on a read-only status overview that displays
  heartbeat health, candidate/intent state counts, and configured budget pools.
- The local Web UI now reads and saves validated downloader, discovery, cleanup,
  and Phase 2 intent configuration sections instead of showing static mock
  fields.
- Added `scripts/bump_version.py` to keep release metadata files aligned during
  deployment-facing version bumps.

### Fixed

- Mutable seed cleanup now only pauses or deletes cold/no-upload torrents when
  the relevant budget pool is over budget, keeping ordinary seed contribution
  intact when no space reclamation is needed.

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
