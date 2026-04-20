# Inspiration Pool

This document captures the project inspirations for `seed-agent`. It is a research map, not a dependency list. The goal is to learn patterns and product boundaries, then implement a small, coherent local tool.

## Phase 1 Inspirations

### pt-tools

Repository: https://github.com/sunerpy/pt-tools

Useful ideas:

- RSS-driven free torrent discovery.
- Multi-site and multi-downloader management.
- Filter rules for precise download decisions.
- Free-period end handling: pause or delete unfinished downloads when the discount ends.
- Automatic torrent cleanup by seeding time, ratio, inactivity, H&R protection, and disk reserve.
- Web UI is useful as product evidence, but `seed-agent` should not copy the UI in Phase 1.

What to learn:

- Lifecycle management is as important as discovery.
- Cleanup must be policy-driven and explainable.
- Discount-end behavior should be represented explicitly, not hidden in ad hoc timers.

### flexget-nexusphp

Repository: https://github.com/appotry/flexget-nexusphp

Useful ideas:

- A compact PT filtering model based on `discount`, `seeders`, `leechers`, `left-time`, and `hr`.
- Site adapters for NexusPHP-like trackers.
- Practical safety guidance around crawl frequency and page pressure.
- Remembering discount information to reduce tracker load.

What to learn:

- The Phase 1 scoring model should expose these dimensions directly.
- Site-specific parsing belongs in adapters.
- The default fetch cadence should be conservative.

### flexget_qbittorrent_mod

Repository: https://github.com/madwind/flexget_qbittorrent_mod

Useful ideas:

- qBittorrent operations beyond enqueue: update, delete, inspect, and adjust behavior.
- Automatic reseed, sign-in, stats, and message push as optional capabilities.
- The README itself warns that a "big mix" can become hard to use.

What to learn:

- Split capabilities into small modules instead of building one large plugin.
- Keep message push and automatic sign-in as optional roadmap features.
- Treat qB operations as a first-class executor, not raw API calls scattered through policies.

## Phase 2 Inspirations

### PT-Plugin-Plus

Repository: https://github.com/appotry/PT-Plugin-Plus

Useful ideas:

- Browser-page entry points for PT actions.
- One-click search from Douban and IMDb pages.
- Multi-site search and push-to-downloader flows.
- Per-site downloader and save-path mapping.

What to learn:

- Phase 2 should model "resource intent" separately from "torrent candidate".
- Douban should be an intent source, not a special case inside downloader logic.
- Human confirmation is natural when several releases match one intent.

### Auto_Bangumi

Repository: https://github.com/EstrellaXD/Auto_Bangumi

Useful ideas:

- RSS-based subscription and episode tracking.
- Automatic naming and media-library-friendly organization.
- Season and episode offset handling.
- Health/status visibility for sources.

What to learn:

- Subscription state should be explicit.
- Download decisions and file organization are related but separate phases.
- Phase 2 can add subscription logic without making Phase 1 depend on media-library organization.

### ani-rss

Repository: https://github.com/wushuo894/ani-rss

Useful ideas:

- Automatic RSS subscription, download, scraping, and organization for anime.
- Docker-first deployment.
- Clear documentation for non-programmer operators.

What to learn:

- Good docs can substitute for a lot of UI in early versions.
- Source health and subscription status are important observability concepts.

### bgmi

Repository: https://github.com/codysk/bgmi-docker-all-in-one

Useful ideas:

- All-in-one subscription service plus downloader packaging.
- Explicit Docker volume layout and runtime environment variables.
- Notes about peer connectivity and host networking.

What to learn:

- Deployment notes should explain network constraints for downloaders.
- `seed-agent` should not hide qB connectivity assumptions.

## Future Inspirations

### qb-rss-manager

Repository: https://github.com/Nriver/qb-rss-manager

Useful ideas:

- RSS rule import/export.
- Bulk editing of rules.
- Real-time match preview.
- Spreadsheet-like editing ergonomics.

What to learn:

- A future rules tool should support diffable import/export before building a UI.
- Rule previews are valuable and can start as CLI dry-run output.

### IYUUAutoReseed

Repository: https://github.com/appotry/IYUUAutoReseed

Useful ideas:

- Automatic reseeding across PT sites.
- Use existing local files to seed equivalent torrents from other trackers.
- qBittorrent and Transmission support.
- Multi-disk and multi-download-directory awareness.

What "reseed" means:

If a file already exists locally, the tool can find equivalent torrents on other trackers, add those torrents to the downloader, point them at the existing data, and verify the files. This increases upload opportunities without downloading duplicate content.

What to learn:

- Reseed belongs in a separate capability layer after Phase 1.
- The file-to-torrent matching model must be conservative and auditable.

### MoviePilot, vertex, nas-tools

Repositories:

- https://github.com/jxxghp/MoviePilot
- https://github.com/vertex-app/vertex
- https://github.com/wangyan/nas-tools

Useful ideas:

- Product boundaries for NAS automation.
- Plugin-like extension points.
- Separation of discovery, matching, download, and organization.

What to avoid:

- Do not build a large dashboard in Phase 1.
- Do not copy a broad platform architecture before the local strategy loop proves useful.

## Non-Goals For Early Versions

- Full web dashboard.
- Full media library manager.
- Automatic publishing/uploading to trackers.
- Broad plugin marketplace.
- Browser automation as a core dependency.
- Unrestricted shell execution.
