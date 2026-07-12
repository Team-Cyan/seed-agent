# Downloader Module

## Purpose

Own downloader integrations for enqueue, review, and cleanup-safe actions.
qBittorrent remains the reference implementation.

## Primary Files

- `src/seed_agent/downloaders/qbittorrent.py`
- `src/seed_agent/downloaders/transmission.py`
- `src/seed_agent/downloaders/base.py`
- `src/seed_agent/actions/qb.py`
- `src/seed_agent/cli.py`
- `docs/specs/qbittorrent-web-api-contract.md`

## Official Reference

- qBittorrent WebUI API 5.0+: <https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29>

`seed-agent` only targets the latest qBittorrent WebUI API. Do not add legacy
qBittorrent API compatibility unless the project explicitly changes that
support policy.

## Current Responsibilities

- authenticate to qB Web API,
- expose the shared `Downloader` protocol used by PT enqueue and intent
  enqueue,
- add torrents,
- inspect managed torrents,
- expose live runtime signals such as current upload/download speeds and
  remaining download volume,
- preserve qB's current tracker URL in managed torrent metadata so diagnostics
  can infer source-site hints when tags or SQLite evidence are missing,
- expose joined operator evidence that links enqueue-time candidate signals with
  later qB runtime outcomes in `review`, `daily-report`, and prune previews,
- refresh tracker evidence for every incomplete managed torrent regardless of
  qB state, including manually stopped downloads; bounded batches rotate by
  oldest tracker evidence so a fixed API budget cannot starve later torrents,
- reconcile known active hashes that are absent from a real qB live listing into
  local missing/deleted evidence,
- revive stale local `deleted` evidence when qB still reports the same hash as
  live,
- keep enqueue-like CLI commands aligned on the same qB runtime view during
  dry-run and execute flows,
- support pause/delete flows through explicit decisions,
- support Transmission RPC as a second downloader through
  `download_client.type: transmission`, using Transmission labels to carry the
  existing category/tag semantics.

## Expectations

- dry-run first for mutating operations,
- never widen destructive behavior casually,
- keep managed/unmanaged boundaries explicit,
- make live qB state visible before turning it into automated gating,
- keep live-state enqueue headroom planning behind evidence from joined reports;
  do not skip straight from raw qB speed/amount-left fields to aggressive
  automation,
- avoid leaking downloader credentials in output.
- for bulk cleanup, scope by qB category first and only then by age, size,
  state, or score; never use tags alone as a delete boundary,
- before deleting qB torrents with files, print or persist the exact candidate
  list and execute only that bounded hash set,
- if the live qB list is needed for multiple configured categories, prefer one
  all-category listing plus local filtering; if only one category is needed,
  keep the qB category filter to avoid unnecessary host/API work.

## Live Operation Notes

- Manual old-seed cleanup on Unraid should be treated as an explicit operator
  action, not as a silent policy expansion. The previous live cleanup used the
  boundary `category == "seed"` and `added_at < 2026-02-01T00:00:00Z`, wrote an
  audit JSONL under the mounted appdata state folder, then deleted exactly the
  planned hashes with `delete_files=true`.
- qB rows with `state` like `stalledUP` can still be valid seed cleanup
  candidates when the operator's age/category boundary is explicit. Do not
  infer safety from the state string alone; keep the printed candidate set as
  the source of truth.
- If a torrent is missing from qB after previously being linked in local state,
  record that absence locally but do not infer that seed-agent deleted it unless
  an executed `qb.cleanup.delete` audit entry exists for the same hash.
- Transmission is contract-tested as a second implementation, but qBittorrent is
  still the behavioral baseline for cleanup and live Unraid operations.

## Verification

- `uv run pytest -q tests/test_downloader_contracts.py tests/test_qbittorrent.py tests/test_transmission.py tests/test_enqueue_action.py tests/test_prune_action.py`
