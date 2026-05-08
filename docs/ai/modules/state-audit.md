# State And Audit Module

## Purpose

Persist local lifecycle knowledge and durable decision evidence.

## Primary Files

- `src/seed_agent/state.py`
- `src/seed_agent/audit.py`
- `tests/test_state.py`
- `tests/test_audit.py`

## Current Responsibilities

- store local candidate/intent lifecycle state,
- persist release candidates and enqueue metadata,
- persist candidate `free_window_expires_at` for execute-mode enqueue when a
  finite free window is known,
- persist `9999-12-31T23:59:59+00:00` for API candidates whose FREE window is
  explicitly unlimited,
- prune stale unqueued candidate rows after the configured retention window,
- backfill qB live torrents into `qb:<hash>` candidate rows when no candidate
  row is linked yet,
- write append-only redacted audit records.

## Expectations

- do not treat local state as disposable,
- preserve free-window state across scheduler cycles so later review and cleanup
  logic can reason from durable enqueue-time evidence,
- expose persisted free-window expiry through managed torrent metadata during
  runtime review/prune enrichment,
- keep enqueued/downloading/seeding/paused/deleted candidate rows during stale
  candidate pruning so cleanup evidence remains durable,
- redact secrets in audit output,
- keep state changes explainable and reviewable.

## Verification

- `uv run pytest -q tests/test_state.py tests/test_audit.py`
