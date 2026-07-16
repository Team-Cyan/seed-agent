# Branch And Roadmap Integration

## Goal

Finish the current `feature/web-ui-settings` work as the only unmerged feature
scope, then fold the deep research report into the project roadmap without
confusing shipped settings UI work with future observability/dashboard work.

## Current State

- `main` and `feature/web-ui-settings` currently point at the same commit, but
  the working tree contains uncommitted Web Settings UI changes.
- `feat/phase-1-pt-upload-loop`, `feat/phase-2-resource-intent-loop`, and
  `feat/qb-category-policy-budgeting` are already ancestors of `main`; they do
  not need content merges.
- The older feature branches still have local superpowers worktrees, so cleanup
  should happen only after the current feature is safely committed and merged.
- The research report identifies credibility, collaboration, and observability
  gaps: license, CI, README support matrix, Docker smoke testing, source-status
  clarity, downloader/provider breadth, read-only dashboard/API, and feedback
  loops.

## Approach

Use a narrow integration flow:

1. Treat the dirty `feature/web-ui-settings` tree as the active feature branch.
2. Verify and repair only issues required to make that feature coherent.
3. Commit the Web Settings UI feature separately from roadmap/report updates.
4. Merge the completed feature into `main`.
5. Update `docs/roadmap.md` from the research report, placing items according to
   maturity:
   - short-term credibility tasks under `Next`,
   - architecture-expansion work under `Later`,
   - already-shipped Web Settings UI under `Completed`.
6. Confirm old feature branches are merged before cleaning their worktrees or
   deleting branch refs.

## Scope

In scope:

- Web Settings UI verification and small fixes needed for a coherent feature.
- Version-policy check before any feature commit or release-facing push.
- Roadmap update based on an external review report.
- Git integration into `main`.
- Cleanup of already-merged feature branch worktrees after verification.

Out of scope:

- Building a full read-only dashboard/API in this session.
- Adding Transmission, a second provider, or a feedback-loop engine now.
- Changing qB cleanup authority or widening mutating behavior.
- Touching local secrets or live qBittorrent state.

## Roadmap Mapping

Short-term todo:

- Add a repository `LICENSE`.
- Add a pull-request CI gate beyond Docker image publishing.
- Add a README support matrix and concise public roadmap summary.
- Add a Docker smoke test with example config and mocked site/downloader
  behavior.
- Clarify source adapter status so implemented, skeleton, and planned sources
  are visibly distinct.

Medium-term todo:

- Add a second downloader adapter, with Transmission as the first candidate.
- Add a second non-M-Team API provider to validate provider boundaries.
- Add a read-only dashboard/API for state, audit, pool usage, cleanup decisions,
  and intent queues.
- Turn `site_history_score` into a real feedback loop from tracker/account
  signals, downloader telemetry, historical outcomes, and user confirmations.

## Verification

Required before claiming completion:

- `git merge-base --is-ancestor` confirms old feature branches are already in
  `main`.
- Web Settings UI focused tests pass.
- Existing affected CLI, config, and M-Team tests pass.
- Roadmap diff shows report-derived todo without duplicating completed Web UI
  work.
- Final `git status --short --branch` is clean or only contains explicitly
  accepted local-only leftovers.

## Risks

- The working tree may contain partially generated files such as `__pycache__`;
  these must not be committed.
- Web Settings UI changes may require a feature version bump if they affect
  published behavior.
- Cleaning superpowers worktrees before merge verification could make recovery
  harder, so cleanup must be last.
