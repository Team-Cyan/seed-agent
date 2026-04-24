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
- normalize text,
- search sources,
- rank release candidates,
- confirm or reject ambiguous options,
- enqueue through the shared downloader path.

## Expectations

- preserve deterministic local state transitions,
- keep search providers modular,
- do not entangle source ingestion with downloader logic.

## Verification

- `uv run pytest -q tests/test_intent_actions.py tests/test_intent_cli.py tests/test_intent_ranking.py tests/test_intent_run_once.py`
