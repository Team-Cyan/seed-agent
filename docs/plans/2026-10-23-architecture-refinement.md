# Architecture Refinement Plan

Current delivery/status entrypoint: `docs/plans/2026-10-24-media-product-delivery.md`.
This document retains the R0-R5 design sequence. Its earlier local-only, paused NAS
trial and no-release statements are historical and superseded by the latest user
authorization; final role integration/review still precedes production rollout.

Status: authorized for incremental local implementation, 2026-10-23. Supersedes inline media scheduling and
single shared-state assumptions in the original integration plan. No deployment,
large code restructure or new process runtime has been executed by this document.

Contract: `docs/specs/2026-10-23-execution-and-state-boundaries.md`.

## R0 — Baseline And Scope (Done As Architecture Work)

- Preserve reviewed Phase 1 and HTTP isolation checkpoints and unrelated changes.
- Record current inline CLI/Web, shared database/restore and latency coupling.
- Pause NAS trial implementation/apply; retain read-only evidence and scratch plans.
- Keep original-title/Chinese-UI, source authority, Plex-first naming, multiple
  subtitles and receipt-owned cleanup unchanged.

## R0.1 — Shared Configuration Contract (Implement Before Worker Cutover)

- One authoritative configuration directory, one Web/CAS writer; seed and media
  read role-scoped validated views. Worker read-only directory mounts observe atomic
  replacement; no separate editable copies or business-policy environment overrides.
- Separate config source/full/effective-role revisions, actual loaded revision/time,
  image/schema/role status. Keep credentials out of digests/output and mount only
  required provider secret files in the worker.
- Bounded reload and publication-time validation invalidate stale commands/claims.
  Current restrictions override queued work; queued preview never becomes execute.
  Invalid media config blocks media writes without requiring seed to wait or fail.

Gate: cross-instance stale cache/different config source/wrong image are visible;
atomic save is seen by both roles, unrelated tracker edits do not invalidate media
jobs, and policy revocation during blocked network work prevents publication.
Missing provider secrets or invalid media-specific config do not break seed paths.

## R1 — Establish Independent Media Storage

Own `media_import` config/schema/store/runtime and backup/restore integration;
leave existing seed tables and StateStore interfaces intact.

- Introduce explicit media-state location and scoped store/repositories. No media
  schema initialization from seed startup. One machine-local appdata DB, not SMB/NFS.
- Build consistent, idempotent export/import from the existing local media tables,
  validating all receipts, references, generation counts and provider state.
- Preserve old DB/audit and unknown ownership; missing state cannot imply removals.
- Define per-domain restore epoch/claims; no global seed/media lock coupling.

Gate: seed commands work when media DB is locked, missing or corrupt; media restore
cannot stall seed. Populated receipt/history roundtrip and interruption/retry tests
pass. A migration-only preview must not create or remove library artifacts.

## R2 — Independent Media Worker And Bounded Commands

Own media service/worker/commands, Web media handlers and CLI media commands.

- Worker owns due scans and enrichment, reusing reviewed domain core.
- Web/manual CLI submit short commands and return durable IDs/preview results;
  add an explicit bounded local wait option only when useful, never in seed.
- Remove inline media execution from seed scheduler. No fallback to synchronous
  execution when worker is absent. Existing media-enabled configs get clear setup
  diagnostics, not silent loss of media work or changed execute semantics.
- Define command mode/config epoch, coalescing, queue cap, claim expiry and fencing.
  Preview/execute commands cannot merge into a more permissive action.
- Paginate read models and stage inventory in bounded transactions. Preserve all
  source/target/repair/shared-source protections and exact publication recovery.

Gate: a deliberately blocked/slow media provider or scan cannot delay seed cycles
or capacity guard beyond declared baseline tolerance. Assert clocks/phase progress,
not only that a function eventually returns. Duplicate commands remain bounded;
worker restart/restore/config change reject stale actions and do not duplicate links.

## R3 — Deployment Roles, Supervision And Operator Experience

Own container role configuration/entrypoint, health/status and operator docs.

- Keep one image and UI; recommend separate seed and media worker containers on NAS
  with independent resource limits, state paths and leases.
- Hardlink mode uses one common source/library mount; application source writes are
  forbidden, but a common read/write mount is not kernel-enforced source read-only.
  Separate source-RO/target-RW bind mounts cannot satisfy Linux hardlink publication.
  Verify actual mount compatibility; see the current delivery plan's mount contract.
  No qB credentials or Docker socket in media worker. UI may access configured
  domain stores through validated application interfaces, not provider execution.
- Define startup/shutdown/restart exhaustion and independent domain health. Preserve
  existing scheduler entrypoint behavior when media is disabled.
- Update safe setup guide for completed-folder publication and worker migration;
  never run both legacy and new media filesystem writers.

Gate: component shutdown/crash/resource failure remains visible and bounded without
stopping seed; health endpoints distinguish media degradation from seed state.
Existing CLI, configuration, container, acquisition and cleanup regressions pass.

## R4 — Formalize Acquisition/Seed Mutation Boundary

Trace Web/CLI/scheduler enqueue/delete callers to one downloader application boundary.
Use small adapters to existing code, not a blanket rename/move refactor.

- Specify live admission/reservations, category authority, idempotency and ambiguous
  outcome reconciliation for shared pools and multiple callers.
- Preserve tracker/RSS provider semantics and budget/hard-cap protections.
- Prove concurrent acquisition/seed tests before deciding whether another worker
  split provides enough measured benefit to justify it. Until then keep the existing
  seed/acquisition runtime rather than promise fully parallel independent services.

Gate: races cannot oversubscribe capacity, widen delete scope or re-enqueue an accepted
but response-lost task. Account-level rate limits survive any future parallelism.

## R5 — Controlled NAS Acceptance And Final Review

The refined architecture is authorized for local implementation. Resume NAS trial
only after concrete validated homelab operation plans pass independent review. Reuse existing safe-read preflight.

- First run isolated NAS scratch fixture with immutable image manifest and independent
  state/resources; capture pre/post seed/qB health and configuration evidence.
- Separate naturally changing queue progress from trial-induced mutations.
- Actual media mount hardlinks, real providers, poster capability if later implemented,
  Plex recognition/multiple-subtitle playback and legacy migration are separate gates.
- No automatic commit/push/release/production replacement. Feature release follows
  existing minor-version policy and DockerMan-controlled rollout when authorized.

## Review Checklist

- Domain responsibilities and authority are explicit, not merely directory names.
- Main seed path has no media network/file work or media lock acquisition.
- State/restore/failure/resource isolation has executable tests, not health inference.
- New interfaces preserve command mode, revision, ownership and stale-plan rejection.
- First change can be verified without changing a single live seed task.
- Code changes are incremental and each stage returns for independent review.


## Execution And Review Coordination

Continue in coder chat `01a16429-e0f2-7300-aecf-b03c9d93a5ec`; supervisor chat
`01a163d6-0850-7203-8394-9e09b2c2d072` owns plan, independent review and user reporting.
The user explicitly authorized proceeding after raising configuration drift. Preserve
existing complete/paused goal history and establish actual execution tracking for
this authorized local refinement without claiming an unavailable goal API action.

R0.1/R1, R2, and R3/R4 are reviewable local milestones. Send scope, frozen manifest,
requirement-to-test evidence, failures/limits and next step after each milestone;
fix findings before crossing dependent gates. No timer-based supervision. Keep prior
909-test/network-isolation checkpoint and unrelated dirty edits intact. No commit,
push, release, existing production role replacement or real queue/media mutation.


## Latest Authorized Delivery Boundary (2026-10-23)

The user now explicitly authorizes the necessary scoped release commit/push/image
publication, DockerMan production upgrade, and real full movie/TV organization with
quota-aware subtitles. Earlier no-push/no-deploy/preview-only statements are superseded
for this scope. See the production-outcome and daily-quota contract appended to the
integration plan. Complete safe local architecture integration and independent review
first; do not release partial changes or expand unrelated refactors. R4 should prove
current admission invariants, not delay this outcome for an unnecessary rewrite.
