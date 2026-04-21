# Phase 1 Usage

This guide covers the operator flow for the Phase 1 PT upload loop. It stays intentionally narrow: config, dry-run review, execution, and audit inspection.

## Config Setup

1. Start from `config/example.yaml`.
2. Point `downloader.secret_ref` at `local/secrets/qbittorrent.yaml`.
3. Keep any tracker cookies or site credentials in separate local files under `local/secrets/`.
4. Adjust discovery, scoring, and cleanup thresholds for your own managed torrent policy.
5. Keep the config under version control only if it contains no secrets.

Example:

```yaml
downloader:
  type: qbittorrent
  target: unraid-qb
  category: pt-auto
  tags: [seed-agent, pt-auto]
  secret_ref: local/secrets/qbittorrent.yaml
```

## qB Secret File Shape

`local/secrets/qbittorrent.yaml` should contain only the connection fields needed for the qBittorrent Web API:

```yaml
base_url: http://qb.local:8080
username: your-user
password: your-password
```

Keep the file gitignored. Do not add tracker URLs, cookies, or other unrelated secrets here.

## Dry-Run Review Flow

Dry-run is the default behavior for mutating actions. Use it first to inspect what would happen before anything touches qBittorrent.

```bash
uv run seed-agent discover --config config/example.yaml
uv run seed-agent score --config config/example.yaml
uv run seed-agent run-once --config config/example.yaml
```

Use the dry-run output to confirm:

- candidate filtering looks sane,
- scoring matches your expectations,
- managed torrents are the only ones being considered for cleanup,
- category and tag assignment are what you want for new downloads.

## Execute Flow

When the dry-run output looks right, rerun the same command with `--execute`:

```bash
uv run seed-agent run-once --config config/example.yaml --execute
```

Implementation note: qBittorrent pause operations use the Web API stop endpoint only. That keeps the behavior explicit and predictable in the current Phase 1 loop.

## Audit Inspection

Phase 1 writes append-only audit events to `.seed-agent/audit.jsonl`. The local state database lives at `.seed-agent/state.db`.

Useful inspection commands:

```bash
tail -n 20 .seed-agent/audit.jsonl
rg '"action":"(discover|score|enqueue|pause|delete)"' .seed-agent/audit.jsonl
sqlite3 .seed-agent/state.db '.tables'
sqlite3 .seed-agent/state.db 'select count(*) from managed_torrents;'
```

If you want a broader look at the latest records:

```bash
jq -c '.' .seed-agent/audit.jsonl | tail -n 20
```

## Safety Notes

- Managed `pt-auto` torrents are the only ones eligible for Phase 1 cleanup decisions.
- Keep H&R, manual, media-library-associated, and unknown-origin torrents protected.
- Treat category and tag management as part of the safety boundary, not cosmetic metadata.
- Do not delete unmanaged torrents.
- Do not remove or rewrite audit history.

