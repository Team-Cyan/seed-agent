# Runtime Hardening Refinement Plan

## Scope

Complete the remaining refinement work without adding a tracker site, search
provider, or downloader. M-Team and qBittorrent remain the live reference
integrations. Transmission, Torznab, and RSS remain supported but are not
expanded by this plan.

All downloader mutations remain dry-run first. Scheduler, Web, storage, and
packaging changes must pass an Apple `container` gate before any live Unraid
deployment change.

## Execution Order

1. Build deterministic scheduler and Web integration fixtures.
2. Prove the existing M-Team intent loop with bounded, operator-visible calls.
3. Add evidence replay and deletion guardrails around value/eviction scoring.
4. Complete Web operational evidence and tracker diff preview.
5. Add a durable single-scheduler lease.
6. Add SQLite-safe backup/restore and append-only audit archival.
7. Harden container runtime permissions and read-only-root compatibility.
8. Add optional low-cardinality Prometheus metrics.
9. Run the complete local release gate, then perform a read-only Unraid audit
   and request explicit authorization before deployment or mutation.

The scheduler lease precedes restore so restore can reject an active mutable
runtime. Live Unraid deployment is last so local evidence covers the complete
release candidate.

## Acceptance Matrix

### Scheduler And Web Integration

- A shared fake downloader/provider harness runs a complete scheduler cycle
  without network or downloader access.
- Backfill, prune, PT discovery, enqueue planning, intent source sync/search,
  heartbeat, and persisted phase ordering share one run ID.
- Rate-limit and network backoff skip tracker work while known local prune and
  heartbeat behavior remain testable.
- Web refresh/search remains non-mutating; candidate enqueue is separately and
  explicitly exercised.

### Existing Intent Loop

- A bounded diagnostic surface reports which query path was used: Douban ID,
  IMDb ID, or title/year fallback.
- Season-pack, episode, lower-match, and no-result outcomes are covered without
  adding a provider.
- Live M-Team verification uses an explicit request budget and never resolves a
  download token outside an explicit enqueue action.

### Value And Eviction Evidence

- Candidate value and eviction quality remain standalone stable functions.
- A read-only replay compares old/current outcomes over persisted evidence.
- Reclaim targets, deletion limits, and evidence sufficiency prevent a scoring
  change from widening cleanup silently.
- Agent, external, and unknown disappearance provenance are distinguishable.

### Web Operations

- Tracker changes have before/after diff preview.
- YAML, environment override, and effective scheduler values are distinguishable.
- Backoff, API budget, reclaim target, reclaimed capacity, and cleanup/audit
  history are available through read-only operator surfaces.

### Single Scheduler Ownership

- SQLite stores owner ID, acquisition/renewal timestamps, and expiry.
- A second mutable scheduler is rejected while the lease is current.
- Expired leases can be taken over deterministically.
- Web-only and read-only commands do not acquire the lease.

### Backup And Retention

- Backup uses the SQLite backup API and can be listed and verified.
- Restore defaults to preview, rejects an active scheduler lease, validates the
  schema, and replaces state atomically only with explicit execution.
- Audit archival preserves complete JSONL records, writes compressed archives,
  and never rewrites archived content.
- Runtime doctor reports database, WAL, archive, and backup health.

### Container Security

- The image can run as a non-root UID/GID while writing only mounted runtime
  paths and declared temporary paths.
- Read-only-root execution passes Web and scheduler dry-run smoke tests.
- The base image reference is reproducible and dependency auditing remains
  strict.

### Metrics

- Metrics are disabled unless configured.
- Metrics contain no torrent hash, title, URL, tracker identity, or secret label.
- Scheduler outcomes, phase duration, backoff, API calls, enqueue/delete action
  counts, reclaim bytes, projected usage, and heartbeat age use bounded labels.

### Release And Live Gate

- `pytest`, Ruff, dependency audit, JavaScript syntax, and diff checks pass.
- Apple `container` passes Web-only, read-only-root, and dry-run scheduler smoke.
- The release version and changelog follow the release policy.
- Live Unraid starts with read-only image/config/runtime provenance inspection.
- DockerMan deployment or downloader mutation requires explicit operator
  authorization after the read-only report.

## Commit Boundaries

Keep each implementation independently reviewable:

1. integration harness
2. intent diagnostics and bounded verification
3. evidence replay and cleanup guardrails
4. Web operational evidence
5. scheduler lease
6. state backup and audit retention
7. container hardening
8. optional metrics
9. release documentation and metadata

## Implementation Status

The nine local workstreams are implemented in `0.18.0`. Completion still
requires the full automated/local-container release gate and a read-only live
Unraid provenance report. DockerMan deployment or downloader mutation remains
an explicit operator authorization boundary.
