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
  - `review`, `daily-report`, and prune previews join enqueue-time evidence
    with qB runtime outcomes.
  - Currently uploading managed torrents are protected from stale no-upload
    cleanup.
  - Mutable seed cleanup pauses/deletes cold or no-upload torrents only when the
    configured budget pool is over budget.
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
  - Search preferences are generic config knobs:
    `required_keywords`, `preferred_keywords`, and `excluded_keywords`.
  - `intent.series_search_mode` controls TV/anime season-pack vs episode search
    and ranking.
  - Want List ingestion stores source evidence and merges duplicate wants by
    `douban:<subject_id>` / `imdb:<tt_id>` aliases.

- Completed 2026-05 - Web UI settings and Want List
  - Local `seed-agent web` command serves the settings UI.
  - Grouped navigation separates run status, Want List, connection settings,
    strategy settings, and a configuration-file overview.
  - Tracker-first settings, read-only status, budget-pool summary, and heartbeat
    health are present.
  - Downloader, discovery, cleanup, acquisition decision, and torrent-filter
    settings can be loaded from YAML and saved through schema validation and
    diff preview.
  - Each settings page exposes its own editable top-level YAML block while the
    runtime still uses one physical config file for Docker, CLI, and Unraid
    compatibility.
  - Search keyword preferences and Want List source settings can be edited
    without exposing secret values.
  - Generic source integration settings remain in the config/API layer, but the
    Web UI navigation only exposes Douban/IMDb Want List configuration from the
    Want List page until additional sources are product-ready.
  - Want List page shows canonical Douban/IMDb wants with source/type filters,
    source evidence summaries, media type, added time, mobile card layout, and
    search/download queue status.
  - Settings pages include mobile section switching and sticky draft/preview/save
    actions inspired by the reference repo UI patterns, without adopting a
    dashboard-first product shape.
  - Web UI Want List search is dry-run/search-only; it does not enqueue or
    download unless the separate intent enqueue path is explicitly executed.

- Next P0 - Verify and harden Want List in the live Unraid preview
  - Run the Web UI against `local/runtime/unraid-config.yaml`.
  - Confirm Douban/IMDb Want List source settings display correctly with the
    copied local M-Team API key and no secret leaks.
  - Add a small operator note for preview/local runtime setup if the workflow
    proves stable.

- Next P0 - Close the intent automation loop with real M-Team results
  - Run Douban and IMDb ingestion for configured public/export sources.
  - Search M-Team for Remux-first matches.
  - Verify Douban-ID and IMDb-ID searches against real M-Team results.
  - Verify season-pack vs episode behavior on real TV/anime examples.
  - Keep qB enqueue dry-run unless explicitly executing.

- Next P1 - Web UI polish
  - Extend before/after diff preview to tracker edits.
  - Add clearer empty/loading/error states, richer source filters, and stronger
    dashboard-style evidence summaries where they support operations.
  - Split settings UI from the future read-only operations dashboard only after
    the current local tool feels stable.

- Next P1 - qB live-state-grounded strategy
  - Refine eviction ranking with tracker-side demand signals where available.
  - Tune cleanup thresholds against real upload outcomes from joined reports.
  - Distinguish agent cleanup from external/manual qB deletions when upload
    history changes suddenly.

- Next P1 - Reporting and feedback loop
  - Turn tracker/account signals, downloader telemetry, historical outcomes,
    and user confirmations into real `site_history_score` inputs.
  - Add read-only dashboard surfaces for audit, cleanup decisions, and intent
    queues.

- Next P2 - Additional sources and providers
  - Add another non-Douban/IMDb rating/list source to validate source adapter
    boundaries.
  - Add an authenticated or push-style source runner only after local event
    models prove stable.
  - Add a second non-M-Team API provider to validate provider boundaries.

- Next P2 - Downloader expansion
  - Add Transmission as the first second-downloader adapter.
  - Keep qBittorrent as the reference implementation until downloader contracts
    are proven.

- Later - Product expansion
  - Rule import/export.
  - Auto-reseed.
  - Richer configurable release profiles built from composable search/source
    knobs rather than a single hardcoded profile switch.
  - Live-state enqueue headroom planning v2 after joined evidence proves which
    qB runtime signals reliably predict good enqueue outcomes.

- Deferred / intentionally not in scope
  - Dashboard-first product work.
  - Browser-login automation as a core M-Team strategy.
  - Broad multi-site plugin framework before current module boundaries are
    stable.

Reference:

- `docs/architecture.md`
- `docs/specs/2026-04-25-qb-category-policy-budgeting.md`
