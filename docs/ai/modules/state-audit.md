# State And Audit Module

## Purpose

Persist local lifecycle knowledge and durable decision evidence.

## Primary Files

- `src/seed_agent/state.py`
- `src/seed_agent/audit.py`
- `src/seed_agent/observability.py`
- `tests/test_state.py`
- `tests/test_audit.py`

## Current Responsibilities

- store local candidate/intent lifecycle state,
- persist release candidates and enqueue metadata,
- persist candidate `free_window_expires_at` for execute-mode enqueue when a
  finite free window is known,
- persist an immutable `candidate_enqueue_snapshots` row with refreshed size,
  seeders/leechers ratio, publication age, score, reasons, hash, and enqueue time
  so later 2/8/24-hour qB outcomes can be compared against the actual enqueue
  decision rather than a later overwritten candidate row,
- persist scheduler runs, scheduler phase events, tracker backoffs, tracker API
  events, and Want List search runs so operator reports and Web ops surfaces can
  explain recent unattended behavior,
- persist scheduler `running`/`waiting` control state and at most one pending
  manual trigger so CLI/Web actions signal the lease owner instead of starting
  a competing scheduler process,
- persist atomic Want List enqueue claims so concurrent Web, CLI, and scheduler
  execution cannot add the same intent/release pair more than once,
- persist source cursors for replay-safe adapters such as Telegram,
- persist `9999-12-31T23:59:59+00:00` for API candidates whose FREE window is
  explicitly unlimited,
- prune stale unqueued candidate rows after the configured retention window,
- backfill qB live torrents into `qb:<hash>` candidate rows when no candidate
  row is linked yet,
- reconcile previously active candidate hashes that disappear from the qB live
  list into local `deleted` state and store `missing_from_qb_*` runtime evidence,
- revive stale `deleted` candidate state when the same hash appears in the qB
  live list again,
- write append-only redacted audit records.
- emit structured redacted runtime JSON to stderr and, for Web/scheduler,
  `.seed-agent/runtime-events.jsonl`; keep runtime retention separate from
  durable audit/state retention. Use a stable cross-process flock and reopen
  each append so concurrent Web/scheduler rotations cannot orphan writes.

## Expectations

- do not treat local state as disposable,
- keep the primary SQLite database, its access lock, and existing WAL/SHM/
  journal sidecars owner-only (`0600`) because release evidence may contain
  credential-bearing download URLs,
- open Web GET state access with `mode=ro`, `cache=private`, and
  `PRAGMA query_only=ON`; Web readers must not initialize schemas, negotiate
  WAL mode, or participate as writable SQLite connections,
- preserve free-window state across scheduler cycles so later review and cleanup
  logic can reason from durable enqueue-time evidence,
- expose persisted free-window expiry through managed torrent metadata during
  runtime review/prune enrichment,
- keep enqueued/downloading/seeding/paused/deleted candidate rows during stale
  candidate pruning so cleanup evidence remains durable,
- redact secrets in audit output,
- create and maintain audit JSONL files with owner-only `0600` permissions,
- keep candidate and intent lifecycle writes monotonic inside one SQLite
  transaction, and keep intent merge data movement atomic with enqueue-claim
  checks. When a duplicate terminal state wins, its selected release must win
  with it and its Want List search history must move to the canonical intent,
- commit Web and scheduled Want List batch-search candidates, intent states,
  and search history in one `BEGIN IMMEDIATE` transaction after network search completes.
  A failed batch write must roll back every intent, and a terminal or selected
  intent observed at commit time must not be overwritten by stale search data,
- keep per-intent `provider_diagnostics` and `search_summary` inside the same
  search-history transaction, including kind/media type, series search mode,
  returned/ranked/filtered/accepted counts. Never add a duplicate standalone
  successful history insert; failures instead emit separate runtime events,
- runtime retention is 2 MiB per file with three backups, owner-only (`0600`),
  and bounded read-only tails. Logging file failures warn once until recovery
  and must not break search or downloader operations,
- keep state changes explainable and reviewable.
- renew the mutable scheduler lease in the background during long tracker,
  prune, discovery, and intent phases, and verify ownership at phase boundaries,
- accept manual triggers only while the scheduler is waiting, consume them
  atomically when the lease owner starts a cycle, and reset the next interval
  from that manual cycle's start,
- verify SQLite backups and restores against the complete current StateStore
  schema. Legacy databases may be accepted only when normal migrations can
  bring a temporary copy to that schema before replacement. Restore must also
  hold the exclusive StateStore access lock so an older connection cannot
  commit into a replaced database,
- for manual live cleanup outside the normal prune decision path, write a
  separate operator audit record in the mounted runtime state area before
  mutation. Include cutoff, category, hash, name, size, state, and whether files
  were deleted.
- after any bulk qB cleanup, re-query qB and record or report the remaining
  matching count instead of assuming deletion succeeded from command output
  alone.
- Treat qB live-state reconciliation as evidence capture, not a qB mutation. A
  missing hash means the torrent is absent from the current Web API listing; it
  does not by itself prove which actor deleted it.
- Keep a short grace window before marking a newly linked hash missing, because
  qB may not immediately show a just-added torrent in the next list response.
- Preserve the bridge between enqueue-time candidate data and qB live runtime.
  The most useful optimization evidence is the joined view: original
  score reasons, seeders/leechers/free-window data plus current uploaded bytes,
  ratio, completion time, amount left, state, and cleanup decision.
- For total-zero-upload torrents, record the no-upload observation start from qB
  `added_at` rather than the first time the agent happened to refresh state.
  Otherwise old no-value torrents can survive another full observation window
  just because the local runtime cache was cold.

## Verification

- `uv run pytest -q tests/test_state.py tests/test_audit.py`
- `uv run pytest -q tests/test_observability.py tests/test_web_settings.py`
