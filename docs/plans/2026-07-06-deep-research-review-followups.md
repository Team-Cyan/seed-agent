# Deep Research Review Follow-Ups

This plan captures the actionable engineering follow-ups from the July 2026
repository review. It is intentionally scoped to work that reinforces the
existing Docker-first PT strategy runtime instead of expanding `seed-agent` into
a dashboard-first media platform.

## Source Review Takeaways

- The project direction is sound: keep `seed-agent` focused on PT/NAS strategy
  execution, evidence, conservative mutation, and operations visibility.
- The immediate gap is not missing product surface. The gap is stronger
  verification, real feedback inputs, and contract-tested extension points.
- qBittorrent and M-Team remain the reference implementations, but the existing
  `Downloader` and `SearchProvider` protocols should be proven with contract
  tests before adding broader implementations.

## Completed In This Review Pass

- Documented the current SQLite operational evidence tables in
  `docs/operations/config-and-state-fields.md`.
- Updated `docs/ai/modules/state-audit.md` so scheduler runs, phase events,
  tracker backoffs, tracker API events, and Want List search runs are explicitly
  part of the state/audit module responsibilities.
- Added `tests/test_state_schema_inventory.py` to keep the operator-facing
  SQLite inventory aligned with the current `StateStore` schema.
- Added focused P0 integration coverage for scheduler phase ordering with a
  shared run ID and Web Want List search-history persistence without downloader
  mutation.

## Local Container Debug Gate

Use Apple `container` on the Mac mini as the local deployment gate for roadmap
work that changes scheduler, Web, provider, downloader, or runtime packaging
behavior.

- Build the local image with `container build -t seed-agent:local .`.
- Mirror Unraid-style runtime layout under a gitignored local root such as
  `local/runtime/container-unraid/runtime/`.
- Mount that root as `/workspace` and keep the runtime config at
  `/workspace/runtime/config/config.yaml`.
- Keep local scheduler runs dry-run by default with `SEED_AGENT_EXECUTE=false`
  and `SEED_AGENT_INTENT_EXECUTE=false`.
- For Web-only checks, prefer `SEED_AGENT_MODE=web` so smoke tests do not call
  trackers or qBittorrent.
- If host port publishing resets connections on this machine, verify the Web UI
  through the container IP reported by `container list --all`.

## P0 Workstream: Scheduler And Web Preview Integration Tests

Goal: make the safest paths testable without live qBittorrent, live trackers, or
Unraid.

Suggested PRs:

1. Add fake provider and downloader fixtures.
   - Build test doubles that implement the existing provider/downloader
     contracts.
   - Keep them deterministic and local-only.
   - Avoid changing production runtime wiring until tests prove the seams needed
     by current code.

2. Add scheduler-cycle integration coverage.
   - Cover conservative prune, PT discovery/enqueue planning, intent refresh,
     and midnight-only Want List search ordering.
   - Assert scheduler runs and phase events are persisted with a shared run ID.
   - Assert tracker backoff keeps heartbeat liveness while skipping tracker work.
   - Current status: shared run ID and phase ordering are covered; broader fake
     provider/downloader cycle fixtures remain.

3. Add Web Want List preview coverage.
   - Cover refresh, filtered search, and single-item search as non-qB-mutating
     actions.
   - Cover candidate-level explicit enqueue separately.
   - Verify lower-match candidates remain inspectable without becoming the
     default action.
   - Current status: search-history persistence and candidate enqueue preview
     are covered; broader fixture consolidation remains.

Verification target:

- `uv run pytest -q tests/test_run_once.py tests/test_cli.py tests/test_web_settings.py`
- New focused integration tests added with the PR.
- `uv run ruff check .`
- Apple `container` Web-only smoke against `/api/health` and `/api/ops`.

## P1 Workstream: Real `site_history_score` Feedback

Goal: turn the existing scoring input into real evidence instead of leaving it
as the default fallback value.

Suggested PRs:

1. Add state aggregation for historical outcomes.
   - Start with read-only aggregation over existing candidate, runtime,
     scheduler, tracker, and audit evidence.
   - Prefer explainable site/profile-level signals over opaque global scores.

2. Expose feedback inputs in `strategy-report`.
   - Show enough raw counts and time windows for operators to trust the score.
   - Keep this read-only before changing enqueue behavior.

3. Wire feedback into scoring only after reports are inspectable.
   - Preserve current fallback behavior when there is not enough history.
   - Add tests around low-sample-size and tracker-throttled windows.
   - Current status: completed. State aggregation, `strategy-report` output,
     CLI/Web scoring injection, low-sample fallback tests, and throttled-window
     signal tests are in place.

Verification target:

- `uv run pytest -q tests/test_scoring.py tests/test_pt_actions.py`
- New feedback aggregation and strategy-report tests.
- Apple `container` dry-run scheduler smoke after the feedback report changes
  are visible in CLI output.

## P2 Workstream: Extension Contract Tests

Goal: prove extension boundaries before adding more implementations.

Suggested PRs:

1. Add `Downloader` contract tests.
   - Cover `add_url`, `list_torrents`, `pause`, and `delete` semantics.
   - Keep qBittorrent as the reference behavior.

2. Add Transmission as the first second downloader.
   - Implement only the minimum contract first.
   - Keep category, pause/delete, and error redaction behavior explicit.

3. Add `SearchProvider` contract tests.
   - Cover search result shape, empty results, provider errors, and release
     candidate persistence through the intent loop.

4. Add a second non-M-Team provider.
   - Use it to validate provider boundaries, not to start a broad multi-site
     framework.
   - Current status: completed. Downloader/SearchProvider contract suites are
     present, Transmission implements the downloader contract, and Torznab
     implements the second non-M-Team search provider.

Verification target:

- New contract test suites under `tests/`.
- Existing qBittorrent and M-Team tests remain the regression baseline.
- Apple `container` smoke with fake or dry-run configs before any live
  Transmission or non-M-Team provider checks.

## Later Work

- Rule import/export: completed through `config-export` and dry-run-first
  `config-import`.
- Auto-reseed evaluation: completed as read-only `reseed-report`.
- Release profiles: completed through configurable `release_profiles` and the
  `release-profiles` CLI report.
- Live-state enqueue headroom planning v2: completed as read-only
  `headroom-report`.

## Non-Goals

- Do not turn the Web UI into a dashboard-first product.
- Do not make browser-login automation a core M-Team strategy.
- Do not introduce a broad plugin framework before the current provider and
  downloader contracts are proven.
