# Cleanup Module

## Purpose

Decide when managed torrents should be paused or deleted under the balanced safety policy.

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
  `cleanup.delete_after_no_upload_hours` before deleting them, including
  incomplete downloads that consumed space but never uploaded,
- observe completed active seeds with no recent upload for
  `cleanup.delete_after_no_upload_hours` before deleting them,
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
  slow. The default is now 2 hours: if a managed torrent has total uploaded
  bytes of zero for at least `cleanup.delete_after_no_upload_hours`, prune may
  preview deletion even when the torrent is still incomplete.
- Always inspect prune preview counts before execute mode. The useful summary is
  action counts, total size/downloaded/left for deletes, state distribution, and
  a sample of names/reasons. Do not execute a broad cleanup from counts alone if
  the category boundary or delete-with-files behavior is unclear.

## Verification

- `uv run pytest -q tests/test_cleanup.py tests/test_prune_action.py`
