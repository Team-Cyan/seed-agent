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
- for manual live cleanup outside the normal prune decision path, write a
  separate operator audit record in the mounted runtime state area before
  mutation. Include cutoff, category, hash, name, size, state, and whether files
  were deleted.
- after any bulk qB cleanup, re-query qB and record or report the remaining
  matching count instead of assuming deletion succeeded from command output
  alone.
- Preserve the bridge between enqueue-time candidate data and qB live runtime.
  The most useful optimization evidence is the joined view: original
  seeders/leechers/free-window data plus current uploaded bytes, ratio,
  completion time, amount left, state, and cleanup decision.
- For total-zero-upload torrents, record the no-upload observation start from qB
  `added_at` rather than the first time the agent happened to refresh state.
  Otherwise old no-value torrents can survive another full observation window
  just because the local runtime cache was cold.

## Verification

- `uv run pytest -q tests/test_state.py tests/test_audit.py`
