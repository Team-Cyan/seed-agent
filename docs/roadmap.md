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
  - Balanced cleanup with pause-before-delete behavior.
  - Scheduler command surface with free-window preview/enforcement.
  - Scheduled pruning through `run-once --prune` and `schedule-run --prune`.
  - Enqueue-time evidence persistence for finite and unlimited M-Team free
    windows.

- Completed 2026-04 - qB category and budget safety
  - Category policy became the cleanup authority boundary.
  - Mutable `seed` pools and add-only media pools were separated.
  - Shared budget pools can force paused enqueue without widening cleanup.
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
  - Mutable seed cleanup pauses/deletes incomplete cold or zero-upload torrents
    only when the configured budget pool is over budget; completed seeds remain
    available for upload.
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
    Web UI, and `schedule-run` now refreshes configured Want List sources and
    searches/ranks resource candidates every cycle by default while keeping the
    scheduled resource loop dry-run unless `--intent-execute` is explicitly set.
  - M-Team tracker rate-limit responses now trigger a persistent scheduler
    backoff; the container keeps heartbeat liveness but skips PT discovery,
    cleanup, and Want List tracker searches until the local midnight after at
    least 24 hours.
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
  - Prune payloads include structured cleanup evidence for action counts,
    low-upload large torrents, and representative pause/delete samples.
  - Scheduled prune now runs before PT add, PT add can trigger an aggressive
    capacity-pressure cleanup when accepted candidates would otherwise be paused,
    and the Want List intent loop remains the final scheduled phase.
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
  - Current docs now match implemented Transmission, Torznab, Letterboxd, and
    Telegram support, with a docs parity regression test for the support matrix.
  - CI now runs on `main` pushes and includes a strict local dependency audit.
  - Tag pushes can create or update GitHub Releases from the matching
    `CHANGELOG.md` section.
  - Web UI write/search/enqueue POST requests can be protected with optional
    `SEED_AGENT_WEB_TOKEN`; local trusted deployments remain unchanged when it
    is unset.
  - Compose, Unraid DockerMan, and operator docs now expose the optional Web
    write token and the disk reserve setting.
  - A provider-kernel roadmap spec captures later autobrr/Prowlarr/cross-seed
    lessons without expanding current scope into a broad plugin framework.

- Next P0 - Live Unraid stopgap and preview verification
  - Current read-only qB evidence shows the physical disk is overcommitted even
    though the logical `downloads` pool is still under 10 TiB; new local
    headroom planning reports this as `over_existing_liability`.
  - Pause, do not delete, unfinished `seed` category qB tasks before any live
    deployment if the operator authorizes a stopgap mutation.
  - Restore SSH access before host-level Unraid checks such as DockerMan
    container rebuild, `docker port seed-agent`, and live template provenance.
  - After qB is stable, rebuild/update the DockerMan-managed container from the
    updated template, confirm `8765/tcp` publishing, and verify the WebUI button
    and runtime provenance paths.

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
