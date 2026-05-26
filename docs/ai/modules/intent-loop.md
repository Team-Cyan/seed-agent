# Intent Loop Module

## Purpose

Convert human requests into search/rank/confirm/enqueue workflows.

## Primary Files

- `src/seed_agent/actions/intent.py`
- `src/seed_agent/intent/parse.py`
- `src/seed_agent/search/`
- `src/seed_agent/sources/`
- `tests/test_intent_*`

## Current Responsibilities

- ingest intents,
- ingest Douban wanted events with source user, subject metadata, wish date, and
  inferred media type, using mobile subject-page enrichment when the public list
  page is ambiguous,
- ingest IMDb watchlist/list events from CSV exports or best-effort public page
  parsing,
- merge Douban and IMDb source events into canonical Want List works through
  `douban:<subject_id>` and `imdb:<tt_id>` aliases,
- normalize text,
- search sources,
- rank release candidates,
- confirm or reject ambiguous options,
- enqueue through the shared downloader path.

## Expectations

- preserve deterministic local state transitions,
- keep source metadata on `ResourceIntent.metadata` when it is useful for UI or
  later search behavior,
- preserve source evidence separately from canonical intent rows so repeated
  wants from different configured lists do not duplicate searches or downloads,
- keep search providers modular,
- do not entangle source ingestion with downloader logic.

## Verification

- `uv run pytest -q tests/test_intent_actions.py tests/test_intent_cli.py tests/test_intent_ranking.py tests/test_intent_run_once.py`
