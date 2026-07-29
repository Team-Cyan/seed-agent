# Roadmap

This roadmap is intentionally a single vertical list: completed work is ordered
by completion period, and unfinished work is ordered by current priority.

## Timeline And Priority List

- Completed 2026-04 - Foundation
  - Python package bootstrap with `uv`, Typer CLI, tests, and linting.
  - Config-first project structure.
  - SQLite local state and append-only redacted audit log.
  - Thin `AGENTS.md`, `.agents/`, and `docs/` routing for future agent sessions.

- Completed 2026-04 - PT upload strategy loop
  - RSS discovery, score-based candidate evaluation, dry-run-first qBittorrent
    enqueue, managed torrent review, daily reports, and `run-once`.
  - Balanced cleanup with managed-category protection and auditable decisions.
  - Scheduler command surface with free-window preview/enforcement.
  - Scheduled pruning through `run-once --prune` and `schedule-run --prune`.
  - Enqueue-time evidence persistence for finite and unlimited M-Team free
    windows.

- Completed 2026-04 - qB category and budget safety
  - Category policy became the cleanup authority boundary.
  - Mutable `seed` pools and add-only media pools were separated.
  - Shared budget pools reject over-capacity enqueue without widening cleanup.
  - Runtime enqueue gates use score-prioritized headroom planning.
  - Stopped zero-progress placeholders are excluded from active download
    liability calculations.

- Completed 2026-04 - M-Team API discovery
  - M-Team RSS remained supported.
  - API-key detail enrichment and API-driven discovery were added.
  - Native OpenAPI filters, FREE/discount filtering, activity sorting, and
    deferred `genDlToken` resolution were implemented.
  - `site-probe` reports authenticated access mode and discovery mode.

- Completed 2026-04 - Deployment readiness
  - Docker image build path, container entrypoint, Compose example, Kubernetes
    CronJob example, healthcheck, heartbeat, and runtime status.
  - GHCR publish workflow with multi-arch images, semver tags, short-SHA tags,
    OCI labels, and release-version validation.
  - Unraid DockerMan template and operator docs.
  - Release version policy documented: code/ops fixes bump patch by `0.0.1`,
    new features bump minor by `0.1.0`, docs-only may keep version.

- Completed 2026-05 - Runtime evidence and cleanup refinement
  - qB live-state refresh batches policy torrent loading and SQLite enrichment.
  - `completion_on <= 0` is treated as unknown completion time.
  - Zero-total-upload managed torrents can be observed and pruned after the
    configured no-upload window.
  - Completed mutable-category seeds can be pruned by an explicit low-upload
    retention policy when operator strategy values demand quality over keeping
    every completed seed.
  - `review`, `daily-report`, and prune previews join enqueue-time evidence
    with qB runtime outcomes.
  - Currently uploading managed torrents are protected from stale no-upload
    cleanup.
  - Mutable seed cleanup selects incomplete cold or zero-upload torrents only
    when the configured budget pool is over budget; current cleanup deletes
    selected files directly and completed seeds remain available for upload.
  - Missing-from-qB reconciliation marks disappeared hashes as locally deleted
    and revives stale deleted evidence when hashes reappear.

- Completed 2026-05 - Evidence-driven tracker strategy
  - `strategy-report` exposes live pool size/upload/ratio/download evidence.
  - Scoring uses soft seeder/leecher pressure rather than an absolute seed cap.
  - `allow_non_free`, leecher ramping, large-pack partial size credit, and
    recommended balanced/upload-farming/space-saving profiles are available.
  - M-Team `api_discovery.min_seeders` and `min_leechers` can now be `null` to
    inherit global discovery thresholds, while explicit `0` keeps native API
    filtering open.

- Completed 2026-05 - Resource intent loop
  - Intent add, file inbox ingestion, deterministic parsing, RSS-backed search,
    ranking, ambiguity handling, confirm/reject commands, and enqueue reuse.
  - Source adapter skeletons for file inbox, Telegram, WeChat bridge, Douban,
    and subscription config shape.
  - `intent run-once` can ingest configured sources and process the intent loop.

- Completed 2026-05 - Douban wanted and M-Team intent search
  - Douban wanted ingestion supports a public user page and local export JSON.
  - Douban events now preserve source user, subject URL, intro, wish date, and
    inferred media type (`movie`, `anime`, `tv`), with mobile subject-page
    enrichment for TV classification when the list page is ambiguous.
  - IMDb watchlist/list ingestion supports CSV exports and best-effort public
    page parsing.
  - M-Team API-backed intent search uses native search, prefers Douban/IMDb ID
    filters when available, and defers download-token resolution until
    execute-mode enqueue.
  - Search preferences use `quality_tag_scores`, a generic tag-group score map
    where aliases such as `BluRay` and `Blu-ray` count once.
  - `want_decision.series_search_mode` controls TV/anime season-pack vs episode search
    and ranking.
  - Want List ingestion stores source evidence and merges duplicate wants by
    `douban:<subject_id>` / `imdb:<tt_id>` aliases.

- Completed 2026-05 - Web UI settings and Want List
  - Local `seed-agent web` command serves the settings UI.
  - Docker and Unraid deployments can publish the settings UI on port `8765`
    while the same container keeps `schedule-run` as the foreground process.
  - Grouped navigation separates run status, Want List, connection settings,
    strategy settings, and a configuration-file overview.
  - Tracker-first settings, read-only status, budget-pool summary, and heartbeat
    health are present.
  - Downloader, discovery, cleanup, acquisition decision, and torrent-filter
    settings can be loaded from YAML and saved through schema validation and
    diff preview.
  - Downloader settings now include visual editors for qB category policies,
    budget pools, and Want List movie/TV/anime routing via
    `download_client.media_category_map`, so these common operations no longer
    require hand-editing YAML.
  - Each settings page exposes its own editable top-level YAML block while the
    runtime still uses one physical config file for Docker, CLI, and Unraid
    compatibility.
  - Search tag-score preferences and Want List source settings can be edited
    without exposing secret values.
  - Generic source integration settings remain in the config/API layer, but the
    Web UI navigation only exposes Douban/IMDb Want List configuration from the
    Want List page until additional sources are product-ready.
  - Want List page shows canonical Douban/IMDb wants with source/type filters,
    source evidence summaries, media type, added time, mobile card layout, and
    search/download queue status.
  - Want List release ranking applies operator-configured quality tag scores,
    including M-Team official tags and inferred title tags, while keeping
    lower-match candidates visible for manual override.
  - Want List toolbar now exposes separate manual actions for refreshing
    configured Douban/IMDb sources and for triggering torrent search against the
    current filters.
  - Want List rows open a candidate review modal. Matching releases stay first
    with score, size, seeder/leecher counts, M-Team tags, inferred quality tags,
    and reasons; lower-match releases stay visible but dimmed for operator
    override.
  - Candidate review now uses a compact evidence hierarchy: equivalent quality
    aliases are deduplicated, raw tracker enum codes are hidden, warnings stay
    visible, routine score reasons are expandable, and existing M-Team search
    subtitle/MediaInfo fields are shown without extra detail requests.
  - Candidate review supports a single deliberate qB enqueue action per
    candidate, with lower-match releases still available for forced enqueue.
    Search remains non-mutating, and M-Team download tokens are still resolved
    only for execute-mode enqueue.
  - Settings pages include mobile section switching and sticky draft/preview/save
    actions inspired by the reference repo UI patterns, without adopting a
    dashboard-first product shape.
  - Mobile Web UI ergonomics now include touch-sized controls, clearer Want List
    row/card affordances, keyboard-accessible candidate opening, sticky modal
    headers, backdrop/Escape modal close behavior, and stronger lower-match
    candidate styling that stays actionable.
  - Web UI and deployment packaging now include seed-agent logo/icon assets,
    favicon/sidebar branding, README branding, OCI image icon metadata, Compose
    labels, Unraid DockerMan icon wiring, and static MIME handling for SVG/PNG
    assets.
  - Web UI Want List search is dry-run/search-only; it does not enqueue or
    download unless the separate intent enqueue path is explicitly executed.
  - Web UI operator guidance now documents the Web UI surfaces, risk levels,
    Web UI vs CLI decision path, runtime provenance checks, and the
    preview-first Want List refresh/search boundary.
  - Want List refresh/search actions show immediate in-progress feedback in the
    Web UI. `schedule-run` refreshes configured Want List sources every enabled
    cycle and searches according to the YAML scheduler policy (`daily` by
    default or `every_cycle`) while keeping scheduled enqueue dry-run unless
    intent execution is explicitly enabled.
  - M-Team tracker rate-limit responses now trigger a persistent scheduler
    backoff; the container keeps heartbeat liveness and local prune active while
    skipping PT discovery and Want List tracker searches. Backoff starts at one
    hour and escalates across consecutive endpoint failures to four, twelve,
    and at most twenty-four hours; a successful batch snapshot resets the
    sequence.
  - Scheduler runs, scheduler phase events, tracker backoffs, tracker API
    events, and Want List search history now persist in SQLite with run IDs for
    post-run debugging.
  - M-Team search and deferred download-token rate-limit errors now propagate as
    structured throttle events so later API calls in the same cycle stop
    immediately.
  - Read-only CLI reports expose scheduler history, tracker API events,
    contribution/low-upload evidence, config status, and runtime doctor checks.
  - The Web UI overview includes an operations panel backed by `/api/ops` for
    recent scheduler, tracker, backoff, and Want List search state.
  - The Web UI Run logs page merges persisted scheduler phase, tracker API,
    Want List search, and redacted audit events into a searchable, filterable,
    auto-refreshing timeline without Docker socket access.
  - Scheduler runtime controls and timing now live in that overview operations
    panel: current phase, next-cycle countdown, rate-limit start/end evidence,
    immediate-cycle trigger, and backoff clearing. The Scheduler tab remains
    configuration-only.
  - Prune payloads include structured cleanup evidence for action counts,
    low-upload large torrents, and representative delete samples.
  - Scheduled prune now runs before PT add, PT add can trigger an aggressive
    capacity-pressure cleanup when accepted candidates would otherwise be paused,
    and the Want List intent loop remains the final scheduled phase.
  - Capacity cleanup deletes mutable seed candidates directly in eviction order
    and stops once its calculated reclaim target is met; prune no longer creates
    paused cleanup placeholders that continue occupying disk.
  - Scheduler defaults now live in one validated YAML section, explicit
    CLI/container overrides are observable, and Web/CLI config writes use atomic
    replacement so long-running readers cannot observe partial YAML.
  - Terminal tracker-backfill misses for incomplete torrents are passed to prune
    as high-risk unknown-free evidence; network outages remain deferred instead
    of triggering blind deletion.
  - Scheduled tracker backfill batch-refreshes M-Team seeding, leeching, and
    stopped incomplete rows and joins them to qB by tracker torrent ID. The
    configurable API budget applies only to detail/search fallback for batch
    misses, while fresh tracker evidence suppresses repeat fallback for six
    hours without removing incomplete batch misses from the fail-closed cleanup
    risk set. The shared 5-second request pacer remains mandatory, and
    rate-limit or network failures stop the rest of the cycle and activate
    scheduler protection.
  - Scheduled conservative cleanup keeps completed low-upload seeds unless space
    reclamation is needed, while the explicit low-upload deletion policy remains
    available for normal prune callers.

- Completed 2026-07 - Review-driven state inventory hardening
  - Operator-facing SQLite schema inventory now includes scheduler runs,
    scheduler phase events, tracker backoffs, tracker API events, and Want List
    search history.
  - State/audit module docs now describe those operational evidence tables.
  - A schema inventory regression test compares the documented SQLite tables and
    columns against the current `StateStore` schema.
  - Roadmap follow-up planning now uses Apple `container` on the Mac mini as the
    local deployment/debug gate before live Unraid checks.
  - Focused integration coverage now asserts scheduler phase ordering with a
    shared run ID and Web Want List search history persistence without touching
    a downloader.

- Completed 2026-07 - Review roadmap execution
  - `site_history_score` now has a real state-derived feedback loop. The state
    store aggregates candidate/runtime/tracker evidence by site with low-sample
    fallback, `strategy-report` exposes the raw feedback inputs, and CLI/Web
    scoring paths inject applied site history before enqueue decisions.
  - Downloader contract coverage now fixes `add_url`, `list_torrents`, `pause`,
    and `delete` semantics. qBittorrent remains the reference implementation,
    and Transmission is available as the first second downloader via
    `download_client.type: transmission`.
  - SearchProvider contract coverage now covers result shape, empty results,
    provider errors, and release persistence through the intent loop. Torznab is
    available as a second non-M-Team provider for intent search.
  - Want List sources now include Letterboxd CSV exports, and Telegram polling
    can ingest updates through a local secret-backed bot token.
  - Product-expansion CLI surfaces now cover `config-export`, dry-run-first
    `config-import`, `release-profiles`, `reseed-report`, and
    `headroom-report`.

- Completed 2026-07 - Deep research P0-to-later hardening
  - Downloader status now exposes qB free disk headroom, and enqueue-like flows
    pause accepted candidates when existing incomplete downloads already exceed
    downloader-reported available disk.

  - `headroom-report` now projects accepted candidates against both logical
    budget pools and downloader free disk headroom.
  - qB-only live torrents can now be backfilled to tracker source evidence with
    a dry-run-first, API-budgeted `tracker-source-backfill` command. M-Team
    runtime/profile examples use `mteam` as the site identifier while retaining
    compatibility with older `site:mt` hints.
  - `schedule-run` now starts with bounded tracker source backfill before
    pruning and discovery, deletes managed incomplete torrents whose free
    window expires before the next scheduled check, and routes eviction/value
    ranking through standalone quality methods.
  - Active tracker API backoff now suppresses tracker/API phases only. Local
    scheduled prune still runs during backoff, so already-known cleanup evidence
    can act on qBittorrent without making more tracker calls.
  - M-Team API timeouts now create a short network backoff instead of a
    rate-limit backoff. Scheduler cycles stop tracker/API work quickly while
    still running local qBittorrent prune.
  - Current docs now match implemented Transmission, Torznab, Letterboxd, and
    Telegram support, with a docs parity regression test for the support matrix.
  - CI now runs on `main` pushes and includes a strict local dependency audit.
  - Tag pushes can create or update GitHub Releases from the matching
    `CHANGELOG.md` section.
  - Web UI write/search/enqueue POST requests can be protected with optional
    `SEED_AGENT_WEB_TOKEN`; local trusted deployments remain unchanged when it
    is unset.
  - Unprotected Web UI deployments keep the optional token control hidden until
    a server actually returns `401`; desktop status cards use a compact adaptive
    grid, and dark-mode neutral controls use the same theme palette as their
    surrounding panels.
  - Compose, Unraid DockerMan, and operator docs now expose the optional Web
    write token and the disk reserve setting.
  - A provider-kernel roadmap spec captures later autobrr/Prowlarr/cross-seed
    lessons without expanding current scope into a broad plugin framework.

- Completed 2026-07 - Want List score calibration
  - Release scores are no longer capped at 100, preserving useful ordering for
    candidates whose base match and quality preferences exceed that value.
  - Ambiguity uses the uncapped score gap while confidence remains bounded for
    the existing confirmation and auto-enqueue thresholds.
  - Default release preferences no longer grant an implicit 1080p match bonus;
    smaller WEB-DL, Dolby Vision, DDP, and Atmos bonuses are balanced by stronger
    Blu-ray, UHD Blu-ray, 1080p, TrueHD, and DTS-HD MA penalties.

- Completed 2026-07 - Runtime hardening refinement
  - Deterministic fake downloader/provider integration runs a complete local
    scheduler cycle with persisted phase evidence and no mutation.
  - Existing M-Team intent queries have configurable request budgets and
    redacted ID/fallback path diagnostics.
  - Quality replay exposes stable score components and rank deltas; capacity
    cleanup has both byte targets and a per-cycle deletion count guardrail.
  - Web tracker edits have diff preview, and operations output includes bounded
    cleanup events and redacted audit tail evidence.
  - SQLite enforces one mutable scheduler lease with expiry takeover and safe
    termination release.
  - State backup/verify/preview-first restore, locked audit archival, storage
    doctor evidence, retention controls, non-root/read-only-root packaging, and
    optional local Prometheus metrics are implemented.
  - The acceptance matrix and local/live gates are maintained in
    `docs/plans/2026-07-11-runtime-hardening-refinement.md`.

- Completed 2026-07 - Free-only billing safety hardening
  - `allow_non_free=false` is now a fail-closed PT upload-farming invariant at
    scoring and again before M-Team token generation; only zero-cost
    FREE/2xFREE promotions pass that flow. Want List acquisition is intentionally
    independent and may select paid releases for requested works.
  - Every incomplete managed qB task is eligible for bounded tracker refresh,
    including manually stopped downloads, with oldest-evidence rotation to
    avoid fixed-budget starvation.
  - Scheduled enqueue and expiry cleanup share a safety horizon of at least two
    scheduler intervals.
  - Unraid packaging defaults to UID 1000 and GID 100, matching the live
    qBittorrent and Plex application user convention.
  - M-Team timezone-naive promotion timestamps are interpreted as
    `Asia/Shanghai`, and qB rows retain candidate evidence through tracker-ID
    reconciliation even when their content-root names differ.
  - Search, detail, and token API calls share a per-process 5-second minimum
    request interval after production rate-limited a short
    `member/getUserTorrentList` pagination burst at 1.25-second spacing; Web and
    scheduler processes remain independently limited.
  - DockerMan and Compose no longer duplicate scheduler policy as environment
    overrides; YAML/Web UI is the deployment source of truth for those fields.

- Completed 2026-07 - Whole-project safety review hardening
  - Want List enqueue now has cross-process idempotency claims and uses the
    selected category's projected pool, active-slot, amount-left, and disk
    headroom across the complete batch.
  - Scheduler ownership renews in the background through long phases, tracker
    failures stop later API work without suppressing local fail-closed cleanup,
    and category-filtered backfill still reconciles every live downloader hash.
  - Incomplete paid/free-window billing risk takes precedence over ordinary
    H&R/manual/media retention protection. Capacity reclaim targets and delete
    limits are shared across mutable categories, while executed deletes recheck
    category authority, reclassify fresh completion/activity state, and verify
    file-removing completion.
  - PT and Want List batch planning reserve projected pool, amount-left, and disk
    liability only for candidates that pass every runtime gate. Rejected
    candidates do not consume capacity needed by a later candidate that fits.
  - M-Team clients propagate structured throttle/service errors, stop pagination
    from raw page exhaustion, clear stale promotion expiry evidence, and keep a
    shared 5-second per-process request pacer. Scheduled source backfill's
    detail/search fallback also has a 20-request default budget because pacing
    alone does not bound longer-window cumulative quotas; batch snapshot
    pagination is paced but does not consume that fallback budget.
  - Web config writes use revisions and preserve explicit nulls and hidden
    fields. API responses redact credentials, secret refs stay within runtime
    `local/secrets`, tracker drafts cannot reuse unrelated credentials, and an
    enabled Web token protects both read and write APIs.
  - Transmission uses conservative label-to-category authority, SQLite
    backup/restore verifies the complete migratable schema, and `main` Docker
    publishing waits for successful CI on the exact current commit.
  - GitHub Actions use current Node-compatible releases pinned to immutable
    commits, bounded job timeouts, same-branch CI cancellation, and read-only
    default repository workflow permissions.

- Completed 2026-07 - Exact mutable-pool hard capacity enforcement
  - Budget pool limits remain explicit deployment-owned configuration, while
    enforcement measures qB's full committed torrent sizes with exact
    integer-byte comparisons. The repository does not encode a personal NAS
    capacity as a product default.
  - Projected enqueue that would exceed a pool is rejected before qB is called;
    legacy `add_paused` YAML is migrated to `reject` and newly saved config no
    longer exposes paused enqueue as a capacity behavior.
  - A pool already over its hard limit bypasses soft retention protections and
    the optional per-run capacity delete limit, then re-reads qB after deletion
    and fails closed if the committed total remains above the configured cap.
  - Broken incomplete managed rows in qB error states are direct-delete cleanup
    candidates, with error rows ranked ahead of ordinary eviction candidates.
  - The scheduler runs a qB-only capacity guard between full tracker cycles;
    it shares scheduler ownership, calls no tracker API, and only invokes prune
    for a hard-cap violation or broken incomplete task.
  - Prune summaries expose before/after pool usage, verified committed and
    downloaded reclaim, hard-cap violations, and final invariant status.

- Completed 2026-07 - Public repository hygiene
  - Public examples use generic account and credential placeholders; personal
    capacities, account identifiers, private IPs, and host paths stay in ignored
    deployment files.
  - Top-level runtime config, state, inbox payloads, secret files, database
    files, cookies, private keys, and torrent files are ignored by default.
  - CI scans tracked paths and content for private runtime files, local home
    paths, RFC1918 addresses, private keys, and high-confidence access tokens.

- Completed 2026-07 - Live Unraid hard-cap release gate
  - The `0.18.9` image passed the Apple `container` gate as a non-root runtime
    and was deployed through the DockerMan-managed template path.
  - Production cleanup converged the mutable downloads pool below its configured
    hard cap with direct file deletion and post-delete qB verification.
  - DockerMan metadata, runtime config provenance, heartbeat version, container
    health, qB error state, and logical pool usage were verified after deploy.
  - Scheduler manual control now signals the existing lease owner through
    durable `running`/`waiting` state. CLI/Web triggers reject overlapping
    cycles, reset the next interval from the manual cycle start, and expose an
    explicit stale-backoff clear action without disabling future protection.
  - Keep the detailed acceptance matrix in
    `docs/plans/2026-07-11-runtime-hardening-refinement.md`.

- Completed 2026-07 - Whole-repository correctness hardening
  - Want List identity now comes only from trusted source evidence; tracker
    candidate IDs cannot merge unrelated intents, terminal wants stay terminal,
    and refreshed searches replace stale release snapshots.
  - Candidate/intent lifecycle writes and intent merges are concurrency-safe,
    enqueue claims block destructive merges, and SQLite restore excludes active
    StateStore connections.
  - Telegram polling is allowlisted and replay-safe, persisted text/error/audit
    surfaces redact credentials, and tracker secret writes roll back if config
    persistence fails.
  - M-Team/RSS parsing, exact episode matching, Transmission ownership checks,
    incomplete-download disk reclaim accounting, and cumulative metrics now
    preserve their intended operational semantics.

- Next P0 - Add scheduler and Web preview integration coverage
  - Add fake downloader/provider fixtures that can run a scheduler cycle without
    touching qBittorrent or a tracker.
  - Cover `schedule-run --prune --intent` phase ordering, persistent run/event
    recording, tracker backoff skip behavior, and heartbeat liveness. Scheduler
    phase ordering and shared run IDs are covered; broader fake-provider cycle
    coverage remains.
  - Cover Web Want List refresh/search preview behavior so search remains
    non-mutating and qB enqueue stays candidate-level and explicit. Search
    history persistence and enqueue preview are covered; broader refresh/search
    fixture consolidation remains.
  - Verify scheduler/Web changes in a local Apple `container` deployment before
    touching live Unraid.
  - Keep the detailed task split in
    `docs/plans/2026-07-06-deep-research-review-followups.md`.

- Next P0 - Close the intent automation loop with real M-Team results
  - Run Douban and IMDb ingestion for configured public/export sources.
  - Verify Douban-ID, IMDb-ID, and title/year fallback searches against real
    M-Team results, including cases where only WEB-DL or lower-match candidates
    exist.
  - Verify the Web UI candidate review and explicit qB enqueue flow on live
    Unraid with a safe dry-run first.
  - Verify season-pack vs episode behavior on real TV/anime examples.
  - Keep qB enqueue dry-run unless explicitly executing.

- Next P1 - Web UI polish
  - Extend before/after diff preview to tracker edits.
  - Add richer source filters and stronger dashboard-style evidence summaries
    where they support operations.
  - Split settings UI from the future read-only operations dashboard only after
    the current local tool feels stable.

- Next P1 - qB live-state-grounded strategy
  - Refine eviction ranking with tracker-side demand signals where available.
  - Tune cleanup thresholds against real upload outcomes from joined reports.
  - Distinguish agent cleanup from external/manual qB deletions when upload
    history changes suddenly.
  - Prefer read-only contribution and headroom reports before changing cleanup
    thresholds or executing deletions.

- Deferred / intentionally not in scope
  - Dashboard-first product work.
  - Browser-login automation as a core M-Team strategy.
  - Broad multi-site plugin framework before current module boundaries are
    stable.

Reference:

- `docs/architecture.md`
- `docs/specs/2026-04-25-qb-category-policy-budgeting.md`
- `docs/specs/2026-07-06-provider-kernel-roadmap.md`
- `docs/plans/2026-07-06-deep-research-review-followups.md`
