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
- support pause/delete flows through explicit decisions.

## Expectations

- dry-run first for mutating operations,
- never widen destructive behavior casually,
- keep managed/unmanaged boundaries explicit,
- make live qB state visible before turning it into automated gating,
- avoid leaking downloader credentials in output.

## Verification

- `uv run pytest -q tests/test_qbittorrent.py tests/test_enqueue_action.py tests/test_prune_action.py`
