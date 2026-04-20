# Seed Agent Design

Date: 2026-04-20

## Summary

`seed-agent` is a standalone AI-first PT and downloader operations toolkit for a personal NAS. It manages torrent discovery, scoring, qBittorrent enqueueing, torrent cleanup, and future resource-intent workflows through structured actions, strong configuration, and auditable decisions.

The project should be easy for an AI agent to operate directly. Phase 1 intentionally avoids a custom UI and instead treats documentation, configuration, dry-run output, and audit records as the primary interface.

## Product Boundary

`seed-agent` is:

- A PT strategy runner.
- A downloader management layer.
- A policy engine for enqueue and cleanup decisions.
- A future intent router for Telegram, WeChat bridge events, and Douban wanted-list items.

`seed-agent` is not:

- A MoviePilot replacement.
- A full media library manager.
- A dashboard-first app.
- A generic autonomous shell agent.
- A tracker publishing tool.

## Phase 1: PT Upload Strategy Loop

Phase 1 builds the smallest useful closed loop for upload-oriented PT operations.

### Goals

- Fetch free and hot torrent candidates from configured PT sites.
- Score candidates with a transparent model inspired by `pt-tools` and `flexget-nexusphp`.
- Enqueue high-confidence candidates into qBittorrent.
- Monitor managed torrents for upload performance.
- Pause or delete cold managed torrents under a balanced safety policy.
- Record every decision in a machine-readable audit log.

### Discovery

Discovery has two engines:

- `free`: looks for discounted candidates such as `free` and `2xfree`.
- `hot`: looks for candidates with promising upload potential based on leecher/seeder dynamics.

Both engines produce the same `TorrentCandidate` model. A site adapter may use RSS alone at first, and later add detail-page enrichment when a site needs extra data.

### Filtering And Scoring

The Phase 1 filter model exposes the parameters that matter most for upload strategy:

- `discount`: accepted discount labels such as `free`, `2xfree`, `50%`, or `2x50%`.
- `seeders`: minimum and maximum allowed seeder counts.
- `leechers`: minimum and maximum allowed leecher counts.
- `left_time`: minimum remaining discount time.
- `hr`: whether H&R torrents are allowed.
- `size`: preferred size range.
- `site_history`: optional site-specific success weight.

The scorer returns both a numeric score and a reason list. Decisions must be explainable without reading source code.

### Downloader Execution

Phase 1 implements qBittorrent first, but uses a downloader abstraction from the start.

The downloader executor should support:

- Add torrent by URL or torrent file.
- Set category.
- Set tags.
- Inspect torrent state.
- Read upload/download counters.
- Pause torrent.
- Delete torrent with or without data.

The first implementation target is qBittorrent Web API. Transmission can be added later behind the same interface.

### Lifecycle State

Managed torrents follow this lifecycle:

```text
discovered -> scored -> enqueued -> downloading -> seeding -> cold -> paused -> deleted
```

The lifecycle state is local metadata. qBittorrent state remains the source of truth for download progress and transfer counters, while `seed-agent` metadata explains policy decisions.

### Cleanup Policy

Phase 1 uses the `balanced` cleanup mode selected by the user.

Automatic cleanup may affect only torrents that are clearly managed by `seed-agent`, for example by category `pt-auto` or tag `seed-agent`.

Protected torrents:

- H&R torrents.
- Manually added torrents.
- Media-library-associated torrents.
- Unknown-origin torrents.
- Torrents below minimum seed time.

Cold candidates can be paused automatically when rules match. Deletion can happen only after the configured pause-before-delete delay, and only for managed torrents that still satisfy the cold criteria.

### Audit Records

Every external downloader change writes an audit record. At minimum, records include:

- Timestamp.
- Target downloader.
- Action name.
- Torrent hash or stable identifier.
- Site and source URL when safe.
- Decision reason.
- Old state summary.
- New state summary.
- Whether confirmation was required and received.
- Rollback instruction when possible.

Secrets such as passkeys, cookies, passwords, and private tracker URLs with sensitive query strings must be redacted.

## Phase 2: Resource Intent Loop

Phase 2 expands `seed-agent` from upload strategy into intent-driven resource acquisition.

### Goals

- Accept resource requests from Telegram messages, WeChat bridge events, and Douban wanted-list sync.
- Convert each request into a structured `ResourceIntent`.
- Search configured PT sites and sources.
- Rank candidate releases.
- Ask for confirmation when multiple candidates are plausible.
- Enqueue selected releases through the same downloader executor.

### Intent Sources

Initial intent sources:

- `telegram`: message commands such as "find title 1080p" or "download show".
- `wechat_bridge`: external webhook or enterprise WeChat style bridge, not personal-account reverse engineering.
- `douban_wanted`: periodic sync from the user's wanted list.
- `subscription`: ongoing watch rules inspired by Auto_Bangumi, ani-rss, and bgmi.

### Search And Ranking

Search output should be normalized into `ReleaseCandidate` records. Ranking should consider:

- Title match confidence.
- Site priority.
- Discount and free status.
- Seeder and leecher dynamics.
- Resolution and quality preferences.
- File size.
- Existing local duplicates.
- H&R risk.

When confidence is low or multiple candidates are close, the system asks the user to choose. Only one clear high-confidence result may be auto-enqueued.

### Organization Boundary

Phase 2 may record enough metadata for future media organization, but it does not become a full media library manager. File renaming, hardlinking, and library import can be designed as a later separate phase.

## Roadmap

### Rule Import And Export

Inspired by `qb-rss-manager`, support diffable rule import/export before any visual rule editor. Dry-run previews should show which historical or current candidates would match a rule.

### Auto-Reseed

Inspired by `IYUUAutoReseed`, add a conservative reseed layer. Reseeding means matching already-local files to equivalent torrents from other trackers, adding those torrents to the downloader, and verifying existing files instead of redownloading content.

This should be built only after Phase 1 metadata and audit logging are reliable.

### Local HTTP API

Add a local API only when an external integration needs a stable endpoint. The internal request/result models should make this straightforward.

### Optional UI

If a UI is added, it should start as a read-only status and rule-preview surface. Configuration and auditability remain the primary interface.

### Rules Assistant

Use audit history to suggest configuration changes, such as lowering site weights when recent candidates underperform or tightening cleanup thresholds when disk pressure rises.

## Configuration Design

Configuration should be explicit, readable, and easy for an AI agent to edit safely.

Early shape:

```yaml
mode: balanced

sites:
  - name: example
    type: nexusphp
    enabled: true
    rss_url: "https://example.invalid/rss"
    cookie_ref: "local/secrets/pt/example.cookie"

discovery:
  discounts: ["free", "2xfree"]
  min_left_time_minutes: 120
  min_leechers: 8
  max_seeders: 80
  allow_hr: false

scoring:
  min_score_to_enqueue: 70
  weights:
    discount: 30
    leechers: 25
    seeders: 15
    left_time: 15
    size: 10
    site_history: 5

downloader:
  type: qbittorrent
  target: unraid-qb
  category: pt-auto
  tags: ["seed-agent", "pt-auto"]

cleanup:
  cold_after_days: 7
  min_upload_delta_gb: 1
  protect_hr: true
  protect_manual: true
  protect_media_library: true
  pause_before_delete_hours: 24
```

## Proposed Modules

- `seed_agent.models`: shared models for candidates, releases, decisions, and audit events.
- `seed_agent.sites`: PT site adapters, starting with RSS and NexusPHP-like parsing.
- `seed_agent.policies`: discovery filters, scoring, cleanup, and confirmation rules.
- `seed_agent.downloaders`: downloader abstraction and qBittorrent implementation.
- `seed_agent.actions`: structured actions exposed through CLI and future API surfaces.
- `seed_agent.audit`: local JSONL audit logging and redaction helpers.
- `seed_agent.config`: config loading, validation, and secret references.

## Structured Actions

Phase 1 actions:

- `pt.discover_candidates`
- `pt.score_candidates`
- `qb.enqueue_candidates`
- `qb.review_seed_performance`
- `qb.prune_cold_torrents`
- `pt.daily_report`

Phase 2 actions:

- `intent.ingest`
- `intent.search`
- `intent.rank`
- `intent.confirm`
- `intent.enqueue`
- `subscription.sync`

## Testing Strategy

Phase 1 tests should cover:

- Config validation.
- Site adapter parsing fixtures.
- Scoring and reason generation.
- Cleanup protection rules.
- qB executor request construction with mocked HTTP.
- Audit redaction.
- Dry-run behavior.

Live downloader or tracker tests must be opt-in.

## Open Decisions

The design intentionally leaves implementation choices for later planning:

- Exact local database format.
- Whether Phase 1 stores state in SQLite or JSONL plus snapshots.
- Exact CLI command shape.
- First supported real PT site adapters.
- Whether scheduled runs use cron, launchd, or an external runner.
