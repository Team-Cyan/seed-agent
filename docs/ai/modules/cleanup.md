# Cleanup Module

## Purpose

Decide when managed torrents should be retained or deleted under the
balanced safety policy.

## Primary Files

- `src/seed_agent/policies/cleanup.py`
- `src/seed_agent/actions/qb.py`
- `tests/test_cleanup.py`
- `tests/test_prune_action.py`

## Expectations

- protect H&R torrents, manual torrents, media-library-associated torrents,
  and active uploads during ordinary retention cleanup; these are soft
  protections inside a mutable category and do not override its hard byte cap,
- evaluate incomplete paid/free-window billing risk before those retention
  protections. A managed incomplete task that is known non-free or will cross
  the safety horizon must be deleted; completed protected tasks remain
  protected because they no longer create paid download exposure,
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
- scheduled free-window safety uses at least twice the scheduler interval so a
  delayed or failed cycle cannot cross directly into paid download time,
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
- delete managed incomplete qB rows in `error`, `missingFiles`, or `unknown`
  state even without capacity pressure so failed downloads cannot remain stuck,
- delete capacity-eviction candidates directly; pruning does not use a paused
  observation stage because pausing does not reclaim occupied capacity,
- share the reclaim-byte target and capacity-delete count across all mutable
  category policies in one prune run. Mandatory incomplete billing-risk deletes
  do not consume the optional capacity-eviction count, and a pool already above
  its hard cap bypasses the optional per-run delete limit,
- immediately before an executed delete, re-read downloader state and require
  the torrent to remain present in the authorized category, then rerun the full
  cleanup classification with its latest completion/activity state and retained
  tracker evidence. Always request file deletion, then re-read state and report
  mutation failure if the hash remains,
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
  planning when accepted candidates would be rejected by runtime gates, forces
  space reclamation for mutable delete-enabled categories, deletes in eviction
  order only until the calculated reclaim target is met, and then lets the
  caller refresh qB runtime state before enqueueing.
- Execute-mode prune re-reads qB after mutation and fails closed unless every
  mutable delete-enabled pool is at or below its exact integer-byte limit.
  The scheduler also runs a qB-only capacity guard between full tracker cycles;
  it does not call tracker APIs and only prunes when a hard-cap violation or a
  broken incomplete task is present. It remains read-only unless both scheduler
  execute mode and `scheduler.prune_enabled` are active.
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
