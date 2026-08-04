# Changelog

All notable project changes are tracked here.

## Unreleased

## 0.21.0 - 2026-08-04

### Added

- Added a configurable hard seeders/leechers ratio ceiling and publication-age
  scoring so upload-farming admission can prefer fresh, proportionally demanded
  torrents without imposing a hard large-torrent size ceiling.
- Standardized optional PT upper limits so `0` and `null` both disable the
  configured ceiling, including size, competition, leecher, active-download,
  and remaining-download limits.
- Added immutable enqueue-time swarm snapshots with candidate age, score,
  reasons, and qB hash for later 2/8/24-hour outcome analysis.

### Changed

- Re-score refreshed M-Team detail data immediately before download-token
  generation and suppress exact duplicate torrent titles against the live qB
  pool and within each enqueue batch.

### Fixed

- Stop renegotiating SQLite WAL mode on every state read, use non-migrating Web
  read paths, and return structured 503 JSON if `/api/ops` or
  `/api/state/summary` cannot read SQLite instead of dropping the connection.

## 0.20.5 - 2026-08-02

### Fixed

- Scoped `pt_filters.max_active_downloads` to the configured default `seed`
  category so upload-farming headroom no longer blocks Want List movie, TV, or
  anime downloads. Media acquisition remains independent from PT FREE-only
  filtering while retaining its selected pool, remaining-download, and disk
  safety checks.

## 0.20.4 - 2026-08-01

### Changed

- Exposed `pt_scoring` through the validated atomic config-section API so live
  enqueue thresholds can be tuned without direct host-file edits.

### Fixed

- Kept normalized Want List items eligible for scheduled catch-up even when a
  daily search had already succeeded before those items were synced, draining
  the backlog in bounded ten-item batches.
- Reused the atomic Want List batch boundary for scheduler searches and attached
  the scheduler run ID to search history, preventing provider failures from
  leaving partially updated candidates or intent states.

## 0.20.3 - 2026-07-30

### Fixed

- Persisted Web Want List batch-search candidates, intent states, and search
  history in one atomic SQLite transaction, using bulk upserts and full rollback
  on any write failure instead of opening several write transactions per item.
- Preserved terminal or concurrently enqueued intents when a slower batch search
  completes, preventing stale results from replacing the selected candidate.

## 0.20.2 - 2026-07-30

### Changed

- Want List candidate actions now report actual enqueue, already-queued,
  in-progress, and runtime-gate outcomes instead of treating every completed
  request as a successful qB add.
- Web write routes now require JSON, reject cross-site browser writes, bound
  request bodies, and serve static assets with revalidation so candidate
  subtitle/UI updates are not hidden by stale browser assets.

### Fixed

- Made daily Want List source refresh and torrent search track separate durable
  success markers across the complete scheduler history, catch up missed
  non-midnight runs, retry failed source refreshes, and keep source-only sync
  independent from qB and tracker providers.
- Prevented configured-source failures from advancing Telegram cursors, and
  contained M-Team intent-search throttling or outages without terminating the
  scheduler or leaving its run unfinished.
- Kept direct enqueue idempotent under repeated and concurrent clicks, avoided
  qB access for invalid or already-enqueued requests, and evaluated runtime
  gates before resolving the selected M-Team download token.
- Protected SQLite state and sidecar files with owner-only permissions, fixed
  cross-timezone backoff comparisons, preserved the correct selected release
  when merging terminal intents, and moved merged Want List search history.
- Redacted multi-word authorization credentials and Telegram bot tokens from
  persisted intent, scheduler, heartbeat, and audit evidence.

## 0.20.1 - 2026-07-29

### Changed

- Telegram polling now requires an explicit chat allowlist and advances a
  durable update cursor only after the intent cycle succeeds.
- Upgraded the async test runtime to `pytest-asyncio` 1.4 for native Python
  3.14 support instead of retaining the pre-1.0 event-loop policy integration.
- Want List candidate buttons now execute the reviewed qB add immediately,
  removing the redundant preview-and-confirm step from the Web UI.
- Scheduled Want List source refresh now follows the configured daily/every-cycle
  cadence independently from tracker search. M-Team backoff no longer prevents
  the daily Douban/IMDb refresh, while already-enqueued intents remain excluded
  from candidate searches.
- Prometheus counters now aggregate the complete SQLite history, expired
  tracker backoffs no longer report active, and the metrics route follows the
  same optional Web token policy as API routes.

### Fixed

- Prevented candidate release metadata from merging unrelated Want List
  intents, terminal intents from being searched again, stale search results
  from surviving refresh, and stale concurrent writes from regressing terminal
  candidate or intent state.
- Serialized SQLite restore against StateStore access, made intent merges
  atomic with enqueue claims, and restored tracker secrets if the corresponding
  config write fails.
- Corrected exact season/episode matching, anime M-Team search mode, RSS
  enrichment error propagation, M-Team zero peer counts, Transmission
  category revalidation, and physical reclaim accounting for incomplete
  downloads.
- Redacted sensitive intent text and Web errors, protected audit files with
  owner-only permissions, covered authorization headers, and rejected negative
  scoring-weight compensation.

## 0.20.0 - 2026-07-23

### Added

- Want List candidate review now exposes the tracker subtitle and MediaInfo/NFO
  evidence when those fields are already present in the M-Team search response,
  without issuing a torrent-detail request.

### Changed

- Reworked candidate cards with clearer title, metadata, score, warning, and
  action hierarchy. Duplicate quality aliases and raw tracker enum tags are
  collapsed, while routine score reasons move into an expandable section.

## 0.19.4 - 2026-07-23

### Fixed

- Removed the remaining 100-point validation limit from enqueue score
  breakdowns so uncapped Want List rankings can proceed through preview and
  enqueue flows. Operational score distributions now report `100+` separately.

## 0.19.3 - 2026-07-23

### Fixed

- Replaced the fixed midnight-aligned M-Team rate-limit cooldown with
  endpoint-specific progressive backoff of one, four, twelve, and at most
  twenty-four hours. A successful user-torrent batch snapshot or explicit
  operator clear resets the escalation sequence.

## 0.19.2 - 2026-07-23

### Fixed

- Raised the default process-wide M-Team request interval from 1.25 seconds to
  5 seconds after production rate-limited a short
  `member/getUserTorrentList` pagination burst. The existing environment
  override remains available for bounded operator tuning.

## 0.19.1 - 2026-07-23

### Changed

- Rebalanced default Want List quality preferences so 1080p, Blu-ray, UHD
  Blu-ray, TrueHD, and DTS-HD MA no longer overpower preferred WEB-DL, 2160p,
  Dolby Vision, DDP, and Atmos candidates.
- Removed the implicit default 1080p resolution requirement; explicitly
  requested resolutions still receive the existing match bonus and missing
  resolution risk.

### Fixed

- Preserve release ranking scores above 100 so strong candidates remain
  distinguishable, while keeping confidence bounded for existing confirmation
  and auto-enqueue thresholds.
- Compare uncapped score differences when detecting ambiguous top candidates
  instead of treating every score above 100 as tied at maximum confidence.

## 0.19.0 - 2026-07-20

### Added

- Added a read-only Web UI Run logs page that merges persisted scheduler phase,
  tracker API, Want List search, and redacted audit events into one searchable,
  filterable timeline with manual and automatic refresh.

### Changed

- Moved immediate-cycle, next-cycle, and tracker-backoff runtime controls and
  timing evidence from the Scheduler configuration page to the overview.
- Rebalanced the desktop overview cards so heartbeat and state summaries do not
  dominate wide layouts, and completed dark-mode token coverage for neutral
  controls, active navigation, badges, help controls, and status messages.

### Fixed

- Hide the optional Web API token control on unprotected deployments and reveal
  it only after a `401 Unauthorized` response requires operator input.
- Keep Run logs lazy-loaded until the operator opens the page, avoiding extra
  audit and SQLite reads during ordinary overview startup.

## 0.18.13 - 2026-07-18

### Fixed

- Replaced per-torrent scheduled M-Team source refresh with paginated
  `member/getUserTorrentList` snapshots for seeding, leeching, and stopped
  incomplete tasks. Batch rows now refresh promotion evidence before
  detail/search fallback, and the existing backfill request budget only limits
  fallback calls.
- Added a six-hour fallback refresh cooldown for tasks absent from the batch
  snapshot when recent tracker evidence already exists, avoiding repeated
  per-torrent detail/search calls without delaying batch promotion updates.
  Incomplete batch misses remain fail-closed cleanup risks during that cooldown.
- Split scheduler backfill reporting into batch and fallback request counts and
  preserve the real batch endpoint when recording rate-limit or availability
  backoff evidence.
- Normalized M-Team HTTP and malformed-JSON failures into structured API errors.
  Any batch error now blocks per-torrent fallback for unmatched tasks while
  preserving valid matches returned before the failure.

## 0.18.12 - 2026-07-17

### Fixed

- Restored the YAML/Web-configurable scheduled tracker-backfill API budget with
  a safe default of 20 requests per cycle. Production showed that 1.25-second
  pacing prevents short bursts but cannot by itself bound M-Team's longer
  cumulative quota window; outstanding tasks continue across later cycles by
  risk and oldest evidence.

## 0.18.11 - 2026-07-17

### Fixed

- Raised the default process-wide M-Team request interval from one second to
  1.25 seconds after production accepted 50 continuous requests and rejected
  the 51st. Scheduled backfill remains unbounded in total and still stops on a
  real rate-limit response.

## 0.18.10 - 2026-07-17

### Added

- Added CLI and Web scheduler controls for triggering one immediate cycle and
  explicitly clearing a stale M-Team backoff.

### Fixed

- Route manual cycles through the active scheduler lease with transactional
  `running`/`waiting` state, reject overlapping triggers, and reset the next
  interval from the manual cycle start instead of requiring a container restart.
- Preserve M-Team request pacing and future automatic backoff after an operator
  clears only the currently recorded cooldown.

## 0.18.9 - 2026-07-16

### Added

- Added a qB-only scheduler capacity guard between full tracker cycles, plus
  hard-cap status, violation, and verified-reclaim observability.

### Changed

- Changed over-budget enqueue behavior from paused adds to pre-qB rejection.
  Legacy `add_paused` YAML is normalized to `reject` when loaded. Capacity
  limits remain deployment-owned YAML/Web UI values rather than repository
  defaults.
- Made mutable-pool hard capacity override soft retention protections and the
  optional per-run capacity-delete limit.
- Removed deployment-specific identities and machine paths from public examples,
  expanded private runtime ignore rules, and added a CI repository-hygiene gate.

### Fixed

- Re-read qB after cleanup and fail closed when committed torrent sizes remain
  above an exact integer-byte pool limit.
- Delete broken incomplete managed torrents and rank qB error states ahead of
  ordinary eviction candidates.
- Prevent rejected candidates from reserving capacity that a later fitting
  candidate can use, and align Web Want List feedback with rejected actions.

## 0.18.8 - 2026-07-15

### Added

- Added atomic Want List enqueue claims and projected category/pool headroom
  reservation across Web, CLI, and scheduled batches.
- Added background scheduler lease renewal and full-schema SQLite backup/restore
  verification.

### Changed

- Clarified that `pt_filters.allow_non_free` governs only PT upload-farming;
  requested Want List releases may be paid while still honoring capacity gates.
- Upgraded GitHub Actions to current Node-compatible releases, pinned every
  external action to an immutable commit, added CI cancellation/timeouts, and
  reduced the repository's default workflow token permission to read-only.
- Made M-Team paging, promotion refresh, and structured throttle/service-error
  handling fail closed without removing the shared one-second request pacer.
- Gated `main` Docker publishing on successful CI for the exact current commit.

### Fixed

- Prevented stale or cross-tracker Web credentials, stale config overwrites,
  explicit-null loss, and unauthenticated API reads when a Web token is enabled.
- Prevented scheduler lease expiry during long phases, duplicate intent enqueue,
  filtered backfill reconciliation gaps, and over-reservation across batches.
- Prioritized incomplete paid/free-window deletion, shared capacity cleanup
  limits across categories, and verified category ownership plus file deletion
  before reporting cleanup success.
- Reclassified cleanup candidates from fresh downloader state immediately before
  deletion, preventing a torrent that just completed or resumed uploading from
  being deleted using stale scan evidence.
- Reserved projected disk, amount-left, and pool liability for paused PT enqueue
  candidates so later candidates cannot reuse capacity already committed to the
  queue.
- Made Transmission category inference conservative and preserved successful
  earlier decisions when a later mutation batch fails.

## 0.18.7 - 2026-07-12

### Changed

- Removed scheduled tracker-backfill task and API request caps. Each cycle now
  resolves every outstanding qB task with the shared one-second M-Team request
  pacer, while rate-limit and network failures still stop the remaining calls
  and activate scheduler protection.
- Removed scheduler policy environment variables from the DockerMan template
  and Compose example. Interval, free-window safety, prune, and Intent execute
  settings now use YAML/Web UI as the deployment source of truth; legacy
  explicit environment overrides remain readable for compatibility.

## 0.18.5 - 2026-07-12

### Fixed

- Serialize all M-Team API request starts across client instances within each
  process with a minimum interval of one second. Search, detail refresh, and
  download-token generation now share the same conservative rate guard, while
  Web and scheduler processes keep independent limits.

## 0.18.4 - 2026-07-12

### Fixed

- Interpret timezone-naive M-Team API timestamps as `Asia/Shanghai` before
  converting them to UTC. Free-window safety no longer overestimates remaining
  promotion time by eight hours.
- Link newly visible qB torrents back to unlinked M-Team candidates by tracker
  torrent ID before falling back to title and size matching. Renamed content
  roots now retain enqueue-time discount and expiry evidence without extra
  tracker searches.

## 0.18.3 - 2026-07-12

### Fixed

- Enforce `allow_non_free=false` as a non-bypassable free-only invariant. Only
  `FREE` and `2xFREE` may pass scoring or execute-time token resolution;
  unknown, normal, and partial discounts fail closed even if misconfigured in
  the discount allowlist.
- Refresh tracker promotion evidence for every incomplete managed torrent,
  including manually stopped qB downloads, and rotate bounded batches by the
  oldest tracker evidence so a fixed API budget cannot starve later tasks.
- Use at least twice the scheduler interval as the free-window enqueue and
  cleanup horizon, preserving an extra cycle of safety before paid download
  time.
- Align the Unraid template and Compose example with the live qBittorrent/Plex
  runtime owner convention of UID 1000 and GID 100.

## 0.18.2 - 2026-07-11

### Fixed

- Preserve the legacy container user when an existing DockerMan installation
  provides neither `PUID` nor `PGID`, preventing image-only upgrades from
  changing mounted appdata ownership expectations to an implicit `1000:1000`.
  Explicit non-root deployments must configure both values together.

## 0.18.1 - 2026-07-11

### Fixed

- Treat configured PT discounts as a strict allowlist unless
  `allow_non_free=true`, preventing high-demand half-discount torrents from
  scoring into a free-only enqueue batch.
- Re-fetch M-Team torrent detail and re-score each accepted API candidate
  immediately before generating its download token. Promotion changes or
  unavailable preflight evidence now fail closed before qBittorrent enqueue.

## 0.18.0 - 2026-07-11

### Added

- Added deterministic scheduler/Web integration fakes and a full local cycle
  test covering prune, PT, Intent, heartbeat, and persisted phase ordering.
- Added bounded per-intent M-Team query diagnostics for Douban ID, IMDb ID, and
  title/year fallback paths.
- Added `quality-replay-report` with inspectable retention/eviction components,
  current-vs-legacy ranking, evidence sufficiency, and deletion provenance.
- Added an expiring SQLite scheduler lease with atomic acquisition, renewal,
  normal/SIGTERM release, and abandoned-owner takeover.
- Added SQLite-native state backup, verification, preview-first lease-aware
  restore, locked gzip audit archival, retention controls, and doctor storage
  health.
- Added optional low-cardinality Prometheus metrics derived only from local
  SQLite and heartbeat state.

### Changed

- Added a per-cycle capacity deletion count guardrail while keeping direct
  incomplete paid/free-window risk deletion independent.
- Added tracker before/after diff preview and bounded prune/audit evidence to
  the Web operations API.
- Pinned the container base manifest, dropped privileges through configurable
  numeric `PUID`/`PGID`, and documented a read-only-root Compose shape.

## 0.17.0 - 2026-07-10

### Added

- Added a validated YAML `scheduler` section for cycle timing, free-window
  safety, pruning, tracker backfill, and configurable daily/every-cycle Want
  List search. Explicit CLI and container overrides remain supported and are
  recorded in scheduler summaries.
- Added scheduler settings to the Web UI, config export/import, runtime status,
  example config, and operator field inventory.

### Fixed

- Limited capacity-driven cleanup to a calculated per-pool reclaim target, so
  eviction stops as soon as enough committed capacity has been removed.
- Removed pause-before-delete from prune. Mutable seed cleanup now deletes
  selected torrents and their files directly, while enqueue-time `add_paused`
  safety gates remain available for new downloads.
- Kept `pause_before_delete_hours` as an ignored compatibility input so existing
  mounted configs continue to load after upgrading.
- Made Web, tracker, and CLI config writes validate and normalize the complete
  document before same-directory atomic replacement. Secret writes now use the
  same atomic path with mode `0600`.
- Classified terminal `not_found`/`ambiguous` tracker backfill results for
  incomplete torrents as high-risk unknown-free cleanup evidence, while
  deferring deletion on rate limits, network/API failures, and exhausted API
  budgets.
- Marked scheduler runs with unresolved tracker backfill results as warnings
  instead of reporting ordinary success.

## 0.16.5 - 2026-07-10

### Fixed

- Prioritized qB-only tracker-source backfill for incomplete or stopped
  downloads with unknown free status before ordinary completed seeds.
- Recovered M-Team source evidence directly from tracker `tid` values when
  available, avoiding fragile title-only matching for high-risk incomplete
  downloads.
- Updated M-Team detail enrichment to refresh discount evidence from the detail
  response, so cleanup can delete incomplete torrents once they are confirmed
  non-free.

## 0.16.4 - 2026-07-10

### Fixed

- Made M-Team intent search fail-soft on transient network failures. Manual
  Want List searches and other provider callers now stop M-Team search cleanly
  on timeout/connection errors instead of surfacing raw `httpx` exceptions.

## 0.16.3 - 2026-07-10

### Fixed

- Added short M-Team network backoff handling for API timeouts. Tracker API
  timeouts now stop the current tracker API phase, skip later tracker/search
  work briefly, and still allow local qBittorrent prune to run.
- Kept M-Team rate-limit handling separate from transient network failures, so
  `ReadTimeout`/connection errors no longer get recorded as tracker
  rate-limit events.
- Reduced the default M-Team API timeout so site outages do not hold scheduler
  cycles open for long periods.

## 0.16.2 - 2026-07-10

### Fixed

- Fixed scheduled cleanup being skipped when a tracker API backoff is active.
  The scheduler now skips tracker/API work during backoff but still runs local
  prune, so already-known cleanup evidence can delete or pause qBittorrent
  torrents without waiting for the tracker backoff window to expire.

## 0.16.1 - 2026-07-10

### Fixed

- Fixed cleanup of managed incomplete torrents that are already confirmed
  non-free by tracker evidence. Candidate discount evidence is now carried into
  runtime cleanup metadata, so `discount=normal` incomplete torrents are deleted
  with files during prune instead of waiting on free-window expiry metadata.

## 0.16.0 - 2026-07-10

### Added

- Added scheduler-level tracker source backfill before prune/discovery, bounded
  by explicit limit and API request options.
- Added standalone quality scoring methods for existing-torrent retention and
  new-candidate capacity ordering.

### Changed

- Managed incomplete torrents whose known free window expires before the next
  scheduled check are now deleted with files instead of only paused.
- Capacity planning now orders accepted candidates through the shared candidate
  value method, while cleanup orders low-quality existing torrents through the
  shared retention quality method.

## 0.15.0 - 2026-07-10

### Added

- Added `tracker-source-backfill` for dry-run-first, API-budgeted recovery of
  tracker source evidence for qB-only live torrents, with conservative M-Team
  title and size matching.

### Changed

- Standardized M-Team profile/example site identifiers on `mteam` while keeping
  compatibility with older `site:mt` hints and tracker URL inference.

## 0.14.1 - 2026-07-06

### Added

- Added qBittorrent free-disk status reporting to enqueue planning and
  `headroom-report`, so existing incomplete downloads can pause new accepted
  candidates even when the logical budget pool is still below its limit.
- Added optional `SEED_AGENT_WEB_TOKEN` protection for Web UI write/search/enqueue
  POST requests.
- Added GitHub Release automation from versioned changelog sections.
- Added docs parity coverage for the current downloader/search/source support
  matrix.

### Changed

- Updated README, architecture, AI docs, Compose, Unraid, and operator docs to
  reflect Transmission, Torznab, Letterboxd, Telegram polling, Web write-token,
  and disk headroom support.
- CI now also runs on `main` pushes and includes a strict local dependency
  audit.

## 0.14.0 - 2026-07-06

### Added

- Added SQLite-backed site history scoring feedback for tracker and Want List
  candidate ranking, with strategy report evidence and Web/CLI coverage.
- Added Transmission downloader and Torznab search provider adapters with
  contract tests.
- Added Letterboxd and Telegram Want List source ingestion paths.
- Added CLI tools for config import/export, release profile inspection, reseed
  reporting, and disk headroom reporting.
- Added Apple Container local debugging guidance plus schema/docs parity tests
  for the SQLite state inventory.

### Changed

- Updated the review roadmap and AI module docs to reflect the completed local
  container-first roadmap execution.

## 0.13.0 - 2026-07-04

### Added

- Added SQLite-backed scheduler runs, phase events, tracker backoffs, tracker
  API events, and Want List search history for durable operational debugging.
- Added structured M-Team rate-limit handling across search and deferred
  download-token resolution, with scheduler/Web backoff reads from SQLite.
- Added read-only CLI reports for scheduler history, tracker API events,
  contribution/low-upload review, config status, and runtime doctor checks.
- Added Web UI `/api/ops` and an overview operations panel for recent scheduler,
  tracker, backoff, and Want List search state.

### Changed

- `schedule-run` now emits run IDs and phase JSON logs, records heartbeat
  summaries with run identity, aborts further tracker work immediately after
  M-Team frequency errors, and persists backoff until at least 24 hours later at
  local midnight.
- Prune payloads now include structured cleanup evidence summarizing action
  counts, low-upload large torrents, and representative pause/delete samples.

## 0.12.1 - 2026-07-03

### Changed

- Added a persistent scheduler backoff after M-Team "request too frequent"
  responses. During backoff, `schedule-run` keeps heartbeat liveness but skips
  PT discovery, cleanup, and Want List work until the local midnight after at
  least 24 hours.
- Web UI Want List torrent search now reads the same scheduler backoff file and
  skips bulk or single-item M-Team searches while backoff is active.

## 0.12.0 - 2026-07-03

### Changed

- Limited scheduled Want List torrent search to the local midnight hour while
  keeping source refresh in the regular scheduler loop.
- Added a Web UI action to search a single Want List item manually.
- Skipped already queued Want List items during default torrent search so M-Team
  is not queried again for downloaded or selected resources.

## 0.11.3 - 2026-07-03

### Changed

- Switched the Docker build to the shared Python 3.14 uv base image and cached
  dependency installation before copying application source.
- Updated M-Team upload-farming discovery examples to query both `normal` and
  `adult` modes while keeping freeleech and leecher-sorted filters.
- Raised the Docker scheduler example interval to 60 minutes to reduce tracker
  API pressure.

## 0.11.2 - 2026-06-23

### Changed

- Raised the supported Python runtime baseline to 3.14+.
- Added runtime provenance to the Web UI and API so operators can see the active
  config path, runtime root, state database, and heartbeat file.
- Made Want List candidate enqueue preview-first in the Web UI; qB mutations now
  require an explicit confirmation after preview.
- Added strategy summaries and release preference presets to the release
  matching settings page.
- Improved mobile Web UI density, Want List empty states, and Web UI port
  conflict guidance.
- Added a Web UI operator guide and linked the Web UI/CLI decision path from
  the main docs.

## 0.11.1 - 2026-06-18

### Changed

- Revised release-tag help text to use device-neutral wording and polished the
  English descriptions for HDR, source, audio, and subtitle tags.

## 0.11.0 - 2026-06-17

### Changed

- Renamed Web UI settings pages and config sections to domain-specific names:
  `tracker_sites`, `pt_filters`, `pt_scoring`, `download_client`,
  `seed_cleanup`, `want_decision`, `release_preferences`, `want_sources`, and
  `local_state`.
- Removed legacy compatibility for `pt_filters.max_seeders` and the
  `max_size_gb: 0` unlimited sentinel; use
  `pt_filters.target_seed_leecher_ratio` and `max_size_gb: null` instead.
- Replaced Want List search keyword preferences with
  `release_preferences.quality_tag_scores`, a canonical release-tag score map
  where aliases such as `BluRay`, `Blu-ray`, `Bluray`, `Blue-Ray`, and `蓝光`
  count once per candidate.
- Want List candidate ranking now reads quality tags from release titles and
  M-Team metadata, applies positive or negative integer tag scores, and marks
  negatively scored tag matches as lower-match candidates without hiding them.

### Added

- Added a structured Web UI editor for common release tags, including
  descriptions and alias help for video source, HDR, codec, audio, and common
  TV/anime subtitle/audio tags.
- Added `docs/operations/config-and-state-fields.md` to inventory all
  user-facing config keys and SQLite state tables/columns.

## 0.9.2 - 2026-06-13

### Fixed

- qBittorrent add responses with `pending_count > 0` and no failures are now
  treated as accepted instead of failed, matching the live qB response shape.
- `schedule-run` no longer exits the long-running Docker process after a
  recoverable cycle error; one-shot `--max-cycles` runs still fail fast.

## 0.9.1 - 2026-06-13

### Fixed

- Dashboard attention warnings now ignore normal Want List review-required
  states and only warn for actual failed candidate or intent records.

## 0.9.0 - 2026-06-13

### Changed

- Simplified Want List candidate review to a single explicit qB enqueue action
  per candidate, removing the old Web select and enqueue-preview buttons.
- Removed the legacy intent confirm flow from the CLI, Web API, intent state
  enum, and audit decisions. Ambiguous candidates can now be enqueued directly
  with `intent-enqueue --release-id`.
- Intent ranking now treats movie, TV, and anime quality preferences
  separately, keeping Remux as a movie-only hard requirement.

### Added

- Added one-time post-deploy SQLite cleanup SQL for deployments that still have
  old `confirmed` intent rows.

## 0.8.16 - 2026-06-12

### Changed

- `schedule-run --prune` now runs conservative cleanup before PT discovery and
  enqueue, then runs the Want List intent loop last.
- When accepted PT candidates would be paused by runtime capacity gates,
  scheduled enqueue runs one aggressive mutable-pool cleanup pass, refreshes qB
  runtime state, and recomputes enqueue batches before adding.

### Fixed

- Scheduled conservative cleanup now keeps completed low-upload seeds unless
  space reclamation is actually needed, while preserving the explicit
  low-upload deletion behavior for normal prune callers.

## 0.8.15 - 2026-06-11

### Fixed

- Configured Want List source refresh failures now appear as
  `source_warnings` instead of crashing scheduler cycles, so temporary Douban
  or IMDb fetch errors do not restart the container.

## 0.8.14 - 2026-06-11

### Fixed

- M-Team intent search now stops gracefully on non-zero search API responses
  instead of crashing the scheduler cycle and triggering a container restart.

## 0.8.13 - 2026-06-11

### Fixed

- M-Team API search now reports non-zero API responses as discovery warnings
  instead of silently treating them as zero candidates, so scheduler logs show
  rate limits and tracker-side errors without forcing a container restart.

## 0.8.12 - 2026-06-11

### Added

- M-Team API discovery can now omit `mode` by setting `api_discovery.mode: null`,
  allowing a broad tracker search sorted by downloads or other configured
  fields.

## 0.8.11 - 2026-06-11

### Added

- M-Team API discovery can now scan multiple browse modes from one site config
  with `api_discovery.modes`, while deduplicating torrents found in more than
  one mode.
- Docker entrypoint and deployment templates now expose
  `SEED_AGENT_INTENT_EXECUTE` so unattended schedulers can explicitly enqueue
  accepted Want List matches.

## 0.8.10 - 2026-06-10

### Changed

- Added an explicit completed low-upload cleanup policy for mutable seed pools,
  allowing demand-first operators to prune completed seeds that stop uploading
  after an observation window.

### Fixed

- qBittorrent enqueue now accepts `Ok` add responses without a trailing period.
- qBittorrent enqueue failures now include a redacted response-body excerpt so
  live add failures can be diagnosed without exposing tracker tokens.

## 0.8.9 - 2026-06-09

### Added

- Web UI Want List rows now show the best saved candidate score directly in
  the list and mobile cards, making low-value items easier to skip.

### Fixed

- Improved mobile Web UI header spacing by hiding the tiny section group label
  on narrow screens.
- Improved Want List release ranking for mixed Chinese/English titles by
  scoring title aliases separately and using the best title match.

## 0.8.8 - 2026-06-09

### Fixed

- Restricted Web UI tracker API key writes to `local/secrets/` so a submitted
  secret reference cannot write outside the project secret directory.
- Extended audit and URL redaction to cover API key field/query names such as
  `api_key`, `apikey`, and `x-api-key`.

## 0.8.7 - 2026-06-08

### Added

- Added dedicated PNG assets for the README header, GitHub social preview, and
  repository icon use cases.

### Changed

- Updated Docker, Compose, and Unraid icon references to a transparent icon URL
  with a new filename to avoid stale DockerMan icon caches.
- Refined Web UI static styling and interaction feedback for current settings
  surfaces.

### Fixed

- Removed the icon's outer background and shadow so Unraid and Web UI icon
  surfaces render with a clean transparent background.
- Reworked the README header image to avoid GitHub SVG font-spacing and
  clipping issues.

## 0.8.6 - 2026-06-07

### Fixed

- M-Team deferred download-token timeouts now reject only the affected candidate
  instead of crashing `schedule-run`, preventing restart loops when
  `genDlToken` is temporarily unreachable.

## 0.8.5 - 2026-06-06

### Fixed

- Web UI Want List refresh and torrent search actions now show immediate
  in-progress feedback and disable duplicate refresh/search clicks while the
  request is running.
- Web UI Want List rows now display only the source date while the API keeps
  the full available timestamp and precision metadata.
- `schedule-run` now refreshes configured Want List sources and runs the
  resource intent search/rank cycle every scheduler cycle by default. The
  scheduled resource loop stays non-mutating unless `--intent-execute` is
  explicitly set.

## 0.8.4 - 2026-06-05

### Fixed

- Linked accepted candidates to matching live qBittorrent torrents before
  enqueue planning, preventing scheduler restart loops when qB already contains
  the torrent but local candidate state has not yet been associated with its
  hash.

## 0.8.3 - 2026-06-05

### Fixed

- Completed managed seeds now remain available for upload during automated
  cleanup instead of being paused or deleted because they are cold, have no
  recent upload, or have an expiring free window.

## 0.8.2 - 2026-06-04

### Fixed

- qBittorrent login now accepts the `204 No Content` success response with a
  session cookie returned by qBittorrent 5.2.1, preventing Unraid scheduler
  restart loops caused by misclassified successful logins.

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
