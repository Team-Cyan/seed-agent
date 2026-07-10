# Cleanup Module

## Purpose

Decide when managed torrents should be retained, paused, or deleted under the
balanced safety policy.

## Primary Files

- `src/seed_agent/policies/cleanup.py`
- `src/seed_agent/actions/qb.py`
- `tests/test_cleanup.py`
- `tests/test_prune_action.py`

## Expectations

- protect H&R torrents,
- protect manual torrents,
- protect media-library-associated torrents,
- treat qB category membership as the cleanup ownership boundary,
- never treat tags alone as cleanup authorization outside the configured category,
- observe zero-total-upload managed torrents from qB `added_at` for
  `seed_cleanup.delete_after_no_upload_hours` before deleting them, including
  incomplete downloads that consumed space but never uploaded,
- keep completed seeds available for upload; automated cleanup should not pause
  or delete a completed seed simply because it is cold, has no recent upload, or
  has a free-window expiry, unless the operator explicitly enables completed
  low-upload cleanup,
- delete managed incomplete torrents whose known free window will expire before
  the next scheduled check. Completed seeds are not deleted by this expiry rule,
  because once downloaded they no longer create paid download exposure,
- delete managed incomplete torrents that tracker evidence confirms are
  non-free, such as `discount=normal` or half-discounted rows. Unknown discount
  evidence should not be treated as non-free,
- when `seed_cleanup.delete_completed_low_upload_after_hours` is set, completed
  mutable-category seeds can be deleted without requiring an over-budget pool if
  their no-upload observation window has exceeded that delay and their total
  upload remains below `seed_cleanup.completed_low_upload_min_gb` or their ratio is
  below `seed_cleanup.completed_low_upload_min_ratio`. Scheduled conservative prune
  can opt into requiring space reclamation for this completed low-upload rule,
  so low-demand completed seeds are kept when there is no better candidate
  waiting for capacity,
- keep currently uploading managed torrents even if a stale no-upload marker is
  present,
- require pause-before-delete timing,
- keep policy reasoning auditable.
- distinguish automated lifecycle cleanup from explicit operator cleanup. When
  the user gives a concrete category and age boundary, execute only that bounded
  live set and record the hashes; do not silently convert the one-off operation
  into a broader recurring policy.
- if cleanup is blocked by paused/no-upload observation ambiguity, prefer
  collecting live runtime evidence over pausing everything. Pausing can hide
  whether a torrent is still contributing upload.
- For upload-farming seed pools, a 24-hour zero-upload observation window is too
  slow. The default is now 2 hours: if a managed incomplete torrent has total
  uploaded bytes of zero for at least `seed_cleanup.delete_after_no_upload_hours`,
  prune may preview deletion, but only when the mutable category's budget pool
  is over budget and space reclamation is needed.
- Capacity-pressure prune is the aggressive mode. It is triggered by enqueue
  planning when accepted candidates would be paused by runtime gates, forces
  space reclamation for mutable delete-enabled categories, and then lets the
  caller refresh qB runtime state before enqueueing.
- Existing torrent deletion order is driven by
  `policies.quality.torrent_retention_quality_score()` and
  `torrent_eviction_pressure_score()`. Tune those methods when upload-density
  retention changes are needed instead of embedding ad hoc ranking in cleanup
  callers.
- Always inspect prune preview counts before execute mode. The useful summary is
  action counts, total size/downloaded/left for deletes, state distribution, and
  a sample of names/reasons. Do not execute a broad cleanup from counts alone if
  the category boundary or delete-with-files behavior is unclear.
- Prune previews should include joined candidate evidence and qB runtime fields:
  score reasons, seeders/leechers/free window, ratio, completion time, amount
  left, recent upload, and no-upload observation state.

## Verification

- `uv run pytest -q tests/test_cleanup.py tests/test_prune_action.py`
