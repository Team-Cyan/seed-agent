# qBittorrent Module

## Purpose

Own qBittorrent integration for enqueue, review, and cleanup-safe downloader actions.

## Primary Files

- `src/seed_agent/downloaders/qbittorrent.py`
- `src/seed_agent/actions/qb.py`
- `src/seed_agent/cli.py`

## Current Responsibilities

- authenticate to qB Web API,
- add torrents,
- inspect managed torrents,
- expose live runtime signals such as current upload/download speeds and
  remaining download volume,
- expose joined operator evidence that links enqueue-time candidate signals with
  later qB runtime outcomes in `review`, `daily-report`, and prune previews,
- reconcile known active hashes that are absent from a real qB live listing into
  local missing/deleted evidence,
- revive stale local `deleted` evidence when qB still reports the same hash as
  live,
- keep enqueue-like CLI commands aligned on the same qB runtime view during
  dry-run and execute flows,
- support pause/delete flows through explicit decisions.

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

## Verification

- `uv run pytest -q tests/test_qbittorrent.py tests/test_enqueue_action.py tests/test_prune_action.py`
