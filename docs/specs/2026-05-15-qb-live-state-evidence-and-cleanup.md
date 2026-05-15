# qB Live-State Evidence And Cleanup

## Goal

Complete the first qB live-state strategy pass in two stages:

1. Build an evidence report that joins enqueue-time candidate signals with later
   qB runtime outcomes.
2. Use that evidence to make cleanup previews safer and more explainable before
   changing any enqueue automation.

The live-state enqueue planner remains a later roadmap item.

## Current State

`seed-agent` already records and reports some qB runtime signals:

- qB live rows include upload/download speed, uploaded/downloaded bytes,
  `amount_left`, `completion_on`, and state.
- `StateStore.apply_torrent_runtime()` persists runtime snapshots and computes
  `recent_upload_gb`, `paused_at`, `free_window_expires_at`, and
  `no_upload_since_at`.
- `review`, `daily-report`, `run-once`, and `prune` expose runtime summaries.
- Cleanup already uses category policy as the ownership boundary and has
  no-upload observation logic.

The main gap is durable enqueue-time evidence. Candidate rows currently keep
title, site, state, score, torrent hash, and free-window expiry, but they do not
preserve the original seeders, leechers, discount, left-time, size, or score
reasons that explain why a torrent was selected.

## Stage C: Evidence Report

Add an enqueue-time snapshot to candidate state and surface a joined view in
operator reports.

Persist these fields for discovered/scored/enqueued candidates when available:

- `size_bytes`
- `seeders`
- `leechers`
- `discount`
- `left_time_minutes`
- `score_reasons`

The report should join that snapshot with qB runtime evidence:

- qB hash, name, category, state, size, uploaded, downloaded, ratio,
  `amount_left`, current up/down speed, session upload, completion time, and
  recent upload delta
- candidate state, score, seeders, leechers, discount, left-time, free-window
  expiry, score reasons, first seen, and last updated
- cleanup evidence such as `no_upload_since_at` and the previewed cleanup action
  when a prune preview is being generated

This evidence belongs in JSON payloads produced by existing operator commands,
not in a new UI surface.

Primary surfaces:

- `review`
- `daily-report`
- `prune` preview

## Stage B: Cleanup Evidence Refinement

After the report exists, make cleanup preview output safer and more explainable.

This stage may add protective evidence and preview fields, but it must not widen
delete authority:

- Cleanup remains limited to configured mutable categories with delete enabled.
- Add-only categories remain protected.
- Tags never grant cleanup authority outside the category boundary.
- The first cleanup refinement should favor retaining or observing torrents when
  live evidence is positive or insufficient.

Expected cleanup preview evidence:

- qB runtime summary fields already listed in Stage C
- candidate snapshot fields already listed in Stage C
- `no_upload_since_at`
- `recent_upload_gb`
- `free_window_expires_at`
- cleanup action and reason

Risk-reducing behavior changes are allowed when they only make cleanup more
conservative. Examples:

- protect currently uploading torrents from delete decisions,
- protect torrents with recent upload above the configured threshold,
- make missing evidence visible rather than silently treating it as cold.

Aggressive deletion changes are out of scope.

## Roadmap Placement

The later live-state enqueue planner should stay on the roadmap as a follow-up
that depends on the Stage C evidence report.

Suggested roadmap wording:

- add live-state enqueue headroom planning v2 after evidence reports prove which
  qB runtime signals reliably predict good enqueue outcomes

## Verification

- State tests cover migration and persistence of candidate snapshot fields.
- CLI tests cover joined report fields in `review` and `daily-report`.
- Prune tests cover enriched preview evidence and conservative cleanup behavior.
- Existing qB, cleanup, CLI, and state tests continue to pass.
- `uv run pytest -q`
- `uv run ruff check .`

## Non-Goals

- Do not implement Transmission.
- Do not implement a read-only dashboard/API.
- Do not change live qB state outside existing dry-run/execute semantics.
- Do not add an aggressive enqueue planner in this pass.
