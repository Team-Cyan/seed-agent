# Phase 2 Usage

This guide covers the resource intent loop: local inbox ingestion, search,
ranking, rejection, explicit candidate selection, and enqueue reuse.

## Config Setup

Start from `config/example.yaml`. Keep downloader credentials and tracker cookies under `local/secrets/`, and keep source inbox/export files under `local/inbox/`.

The local inbox path is configured by `want_decision.inbox_ref`:

```yaml
want_decision:
  inbox_ref: local/inbox/intents.jsonl
```

`local/inbox/*` is gitignored because it can contain private watch preferences or chat-export text.

The local `seed-agent web` UI can also edit the low-risk Phase 2 intent
thresholds, default resolution, preferred languages, inbox path, search
preferences, and Want List source settings. It writes a YAML section only after
the full project config passes schema validation and shows a before/after diff
preview; source credentials still stay in `local/secrets/` and are not entered
as plaintext in the UI. Generic source integration refs remain YAML/API-level
configuration until those sources have a product-ready UI.

The same Web UI exposes a Want List page. It reads local intent state, shows
canonical Douban/IMDb source labels, media type, added time, and
search/download status. The page can trigger search-only dry runs for filtered
rows. Clicking a row opens candidate review: matching releases appear first with
score, size, M-Team tags, inferred quality tags, and ranking reasons; lower-match
releases remain visible and dimmed so an operator can force a download when
waiting for Remux/Blu-ray/4K is not worth it. qB enqueue still requires an
explicit candidate button click, which executes immediately without another
preview or browser confirmation; search itself never enqueues.

For a movie Remux-first Douban/IMDb-to-M-Team intent flow:

```yaml
tracker_sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.example/fallback
    api_key_ref: local/secrets/mt.api-key
    discovery_mode: api
    api_discovery:
      mode: movie
      only_free: false
      sort_field: seeders
      sort_order: desc

want_decision:
  default_resolution: 2160p
  series_search_mode: season

release_preferences:
  quality_tag_scores:
    remux: 20
    dolby_vision: 15
    hdr10_plus: 10
    webdl: -10

want_sources:
  want_lists:
    - provider: douban
      id: douban-me
      label: 我
      enabled: true
      user_name: example-user
    - provider: imdb
      id: imdb-weekend
      label: 周末清单
      enabled: true
      watchlist_url: https://www.imdb.com/user/p.example/watchlist/
      export_ref: local/inbox/imdb-weekend.csv
```

`quality_tag_scores` is the Want List ranking preference map for M-Team
API-backed intent search. Keys are canonical tag groups, and values are integer
score adjustments. Aliases in the same group count once, so `BluRay`,
`Blu-ray`, `Bluray`, `Blue-Ray`, and `蓝光` do not stack. Negative tag scores
push a candidate into the lower-match review group instead of hiding it.

For TV/anime episode intents, `series_search_mode: season` searches and ranks
full-season packs. Use `series_search_mode: episode` when the operator prefers
one episode at a time.

## Local Inbox Shape

The JSONL inbox accepts one JSON object per line. Supported text keys are `raw_text`, `text`, `message`, and `title`. Supported id keys are `source_event_id`, `event_id`, and `id`.

Example:

```json
{"id":"movie-1","text":"Inception 2010 1080p","requested_at":"2026-04-22T00:00:00+00:00"}
{"id":"show-1","message":"Severance S02E03 2160p"}
```

## Intent Commands

Use these commands for a step-by-step operator flow:

```bash
uv run seed-agent intent-add "download Inception 2010 1080p" --config config/example.yaml
uv run seed-agent intent-inbox --config config/example.yaml
uv run seed-agent intent-search <intent-id> --config config/example.yaml
uv run seed-agent intent-rank <intent-id> --config config/example.yaml
uv run seed-agent intent-review --config config/example.yaml
```

`intent-review` shows intents that are normalized, searched, or waiting for
operator selection, with top candidates and `confirmation_required` status.

## Reject Flow

To stop working on an intent:

```bash
uv run seed-agent intent-reject <intent-id> --config config/example.yaml
```

Rejection only mutates local SQLite state and writes audit records. It does not
call qBittorrent.

## Enqueue Flow

Dry-run enqueue first:

```bash
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml
```

Execute only after the selected release and output decision look correct. Use
`--release-id` to enqueue an ambiguous or lower-ranked candidate explicitly:

```bash
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml --execute
uv run seed-agent intent-enqueue <intent-id> --release-id <release-id> --config config/example.yaml --execute
```

`intent-enqueue` uses a high-confidence ranked release by default. When
`--release-id` is provided, that release is selected for this enqueue attempt
and stored as the final selected release only after a successful execute.

## Combined Run-Once

`intent-run-once` processes intents ingested from the configured inbox and
enabled source adapters during that invocation:

```bash
uv run seed-agent intent-run-once --config config/example.yaml
uv run seed-agent intent-run-once --config config/example.yaml --execute
```

The command is dry-run by default. If the inbox is absent and no source adapter
emits events, it exits with an empty JSON result and does not search configured
sites.

## Runtime And Audit

Phase 2 uses the same workspace-local runtime files as Phase 1:

```bash
sqlite3 .seed-agent/state.db '.tables'
sqlite3 .seed-agent/state.db 'select state, count(*) from intents group by state;'
sqlite3 .seed-agent/state.db 'select intent_id, title, score, confidence, confirmation_required from release_candidates order by created_at desc limit 10;'
tail -n 20 .seed-agent/audit.jsonl
rg '"action":"intent\\.(ingest|search|rank|reject)"|"action":"qb\\.enqueue"' .seed-agent/audit.jsonl
```

Audit output is redacted before printing and writing, including passkeys, tokens, cookies, and password-like fields.

If a deployment has old rows from the removed confirm flow, run the post-deploy
cleanup SQL once:

```bash
sqlite3 .seed-agent/state.db < docs/operations/post-deploy-cleanup.sql
```

## Integration Sources

The current integration adapters are local/off by default:

- `file_inbox`: reads local JSONL inbox files.
- `telegram`: parses Telegram update payloads without running a bot loop.
- `wechat_bridge`: parses bridge payloads without depending on a live WeChat session.
- `want_lists` with `provider: douban`: reads the newest actions from Douban's
  personal-interest RSS through `user_name` and can also read a local
  wanted-list export JSON as the authoritative full-list recovery source. RSS
  pagination is not available; the legacy `max_pages` field is accepted only
  for backwards-compatible configuration parsing and has no effect.
- `want_lists` with `provider: imdb`: reads IMDb watchlist/list CSV exports and
  best-effort public page data, preserving IMDb title IDs and source labels.

Want List sources are canonicalized by `douban:<subject_id>` and `imdb:<tt_id>`
aliases. Repeated wants from multiple configured lists are kept as source
evidence on the earliest canonical intent rather than duplicated as new rows.

Secrets and tokens stay outside version control under `local/secrets/`.
