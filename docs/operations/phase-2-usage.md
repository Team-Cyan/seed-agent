# Phase 2 Usage

This guide covers the resource intent loop: local inbox ingestion, search, ranking, confirmation, and enqueue reuse.

## Config Setup

Start from `config/example.yaml`. Keep downloader credentials and tracker cookies under `local/secrets/`, and keep source inbox/export files under `local/inbox/`.

The local inbox path is configured by `intent.inbox_ref`:

```yaml
intent:
  inbox_ref: local/inbox/intents.jsonl
```

`local/inbox/*` is gitignored because it can contain private watch preferences or chat-export text.

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

`intent-review` shows intents that are normalized, searched, or waiting for confirmation, with top candidates and `confirmation_required` status.

## Confirmation Flow

When a ranked release is ambiguous or risky, confirm the selected release before enqueue:

```bash
uv run seed-agent intent-confirm <intent-id> <release-id> --config config/example.yaml
```

To stop working on an intent:

```bash
uv run seed-agent intent-reject <intent-id> --config config/example.yaml
```

Confirmation and rejection only mutate local SQLite state and write audit records. They do not call qBittorrent.

## Enqueue Flow

Dry-run enqueue first:

```bash
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml
```

Execute only after the selected release and output decision look correct:

```bash
uv run seed-agent intent-enqueue <intent-id> --config config/example.yaml --execute
```

`intent-enqueue` uses confirmed releases, or a high-confidence ranked release that does not require confirmation.

## Combined Run-Once

`intent-run-once` processes intents ingested from the configured inbox during that invocation:

```bash
uv run seed-agent intent-run-once --config config/example.yaml
uv run seed-agent intent-run-once --config config/example.yaml --execute
```

The command is dry-run by default. If the inbox is absent, it exits with an empty JSON result and does not search configured sites.

## Runtime And Audit

Phase 2 uses the same workspace-local runtime files as Phase 1:

```bash
sqlite3 .seed-agent/state.db '.tables'
sqlite3 .seed-agent/state.db 'select state, count(*) from intents group by state;'
sqlite3 .seed-agent/state.db 'select intent_id, title, score, confidence, confirmation_required from release_candidates order by created_at desc limit 10;'
tail -n 20 .seed-agent/audit.jsonl
rg '"action":"intent\\.(ingest|search|rank|confirm|reject)"|"action":"qb\\.enqueue"' .seed-agent/audit.jsonl
```

Audit output is redacted before printing and writing, including passkeys, tokens, cookies, and password-like fields.

## Integration Sources

The current integration adapters are local/off by default:

- `file_inbox`: reads local JSONL inbox files.
- `telegram`: parses Telegram update payloads without running a bot loop.
- `wechat_bridge`: parses bridge payloads without depending on a live WeChat session.
- `douban_wanted`: reads local Douban wanted-list export JSON.

Secrets and tokens stay outside version control under `local/secrets/`.
