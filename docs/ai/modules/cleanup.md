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
- observe completed active seeds for `cleanup.delete_after_no_upload_hours`
  before deleting them for zero upload,
- require pause-before-delete timing,
- keep policy reasoning auditable.

## Verification

- `uv run pytest -q tests/test_cleanup.py tests/test_prune_action.py`
