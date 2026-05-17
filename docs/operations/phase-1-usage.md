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
  default_category: seed
  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: add_paused
      tags: [seed-agent, seed]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: [seed-agent, movie]
    - name: tv
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: add_paused
      tags: [seed-agent, tv]
  budget_pools:
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
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

Cleanup is capacity-driven for mutable seed categories. Cold or zero-upload
torrents are retained while the configured budget pool is under its limit; prune
only pauses or deletes them automatically when space reclamation is actually
needed. Add-only media categories remain protected from cleanup mutations.

```bash
uv run seed-agent discover --config config/example.yaml
uv run seed-agent score --config config/example.yaml
uv run seed-agent run-once --config config/example.yaml
```

Use the dry-run output to confirm:

- candidate filtering looks sane,
- scoring matches your expectations,
- mutable-category torrents are the only ones being considered for cleanup,
- default category and tag assignment are what you want for new downloads,
- shared budget pools reflect your intended logical capacity boundaries.

## Execute Flow

When the dry-run output looks right, rerun the same command with `--execute`:

```bash
uv run seed-agent run-once --config config/example.yaml --execute
uv run seed-agent schedule-run --config config/example.yaml --execute --interval-minutes 30
```

To combine the normal discovery/enqueue loop with managed torrent cleanup,
add `--prune` to `run-once` or `schedule-run`:

```bash
uv run seed-agent schedule-run --config config/example.yaml --execute \
  --interval-minutes 30 \
  --prune
```

`--prune` reuses the same conservative cleanup policy as the standalone
`prune` command: only mutable managed categories are eligible, and cold torrents
are paused before they can be deleted in a later pass.

When `schedule-run --prune` is used, the scheduler interval also becomes the
free-window safety horizon for managed torrents. A torrent with persisted
`free_window_expires_at` that cannot survive until the next scheduled check is
paused before the paid period; already-paused torrents still follow the normal
pause-before-delete delay.

For unattended runs, prefer adding free-window safety flags:

```bash
uv run seed-agent run-once --config config/example.yaml --execute \
  --min-free-window-minutes 180 \
  --require-known-free-window
```

That prevents execute-mode enqueue when a candidate has too little known
remaining free time or when M-Team does not provide a usable free-window value.
If you pass the same flags without `--execute`, the dry-run output previews that
deployment-time safety decision before you mutate qBittorrent.

Execute-mode enqueue also persists a candidate-level `free_window_expires_at`
when the site provides `left_time_minutes`. That timestamp is local operational
state in `.seed-agent/state.db`; it gives later review and cleanup passes a
durable record of the expected free window for torrents that were added by the
agent. If M-Team marks an API candidate as explicitly unlimited, the persisted
expiry is `9999-12-31T23:59:59+00:00`.

Candidate rows that never become linked to a qB torrent are pruned after
`state.candidate_retention_days` days, defaulting to 30. Enqueued, downloading,
seeding, paused, and deleted rows are retained because they explain live cleanup
history.

For long-running scheduler deployments, pair `schedule-run` with:

- `--heartbeat-file` on the scheduler side, and
- `healthcheck --heartbeat-file ... --max-staleness-minutes ...` on the
  supervisor side.

Implementation note: qBittorrent pause operations use the Web API stop endpoint only. That keeps the behavior explicit and predictable in the current Phase 1 loop.

## Audit Inspection

Phase 1 writes append-only audit events to `.seed-agent/audit.jsonl`. The local state database lives at `.seed-agent/state.db`.

Useful inspection commands:

```bash
tail -n 20 .seed-agent/audit.jsonl
rg '"action":"(discover|score|enqueue|pause|delete)"' .seed-agent/audit.jsonl
sqlite3 .seed-agent/state.db '.tables'
sqlite3 .seed-agent/state.db 'select state, count(*) from candidates group by state;'
```

If you want a broader look at the latest records:

```bash
jq -c '.' .seed-agent/audit.jsonl | tail -n 20
```

## Safety Notes

- Only mutable configured categories such as `seed` are eligible for automatic cleanup decisions.
- A mutable category grants management over all torrents already in that qB
  category and all future torrents added there.
- Keep H&R, manual, media-library-associated, and unknown-origin torrents protected.
- Treat qB category management as the safety boundary. Tags remain useful
  metadata for new torrents, but tags alone do not grant delete permission.
- Do not delete unmanaged torrents. For eligible managed delete actions,
  `prune --execute` deletes both the torrent and its files; inspect the `preview`
  block before executing.
- Do not remove or rewrite audit history.

## Budget Notes

- Budget pools are logical qB budgets computed from torrent `size`, not from NAS share inspection.
- A pool may be shared by multiple categories, such as `movie` and `tv` sharing `media`.
- If a pool is already over budget, new torrents may still be added to qB in a paused state.
- Add-only categories may exceed budget, but they never trigger automatic delete.
