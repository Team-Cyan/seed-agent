# qB Category Policy And Budgeting

Date: 2026-04-25

## Summary

`seed-agent` should stop treating qBittorrent category management as a single hard-coded `pt-auto` boundary.

Instead, it should model each qB category through a unified `CategoryPolicy` object and bind categories to shared logical `BudgetPool` objects.

Together they control:

- whether the category is fully mutable or add-only,
- which shared logical capacity pool the category belongs to,
- what should happen when a category is over budget,
- whether automated deletion is allowed,
- and how new downloads should be enqueued for that category.

The first real-world target is:

- `seed`: fully mutable upload-farming category in the `downloads` pool, automatic delete allowed.
- `movie`: add-only category in the shared `media` pool, no automatic delete.
- `tv`: add-only category in the shared `media` pool, no automatic delete.
- `downloads`: shared logical budget pool set to `10 TiB`.
- `media`: shared logical budget pool set to `10 TiB`.

The project should remain qB-only. It should not gain NAS, SSH, SMB, NFS, or Unraid filesystem inspection responsibilities just to enforce this feature.

## Problem

The current Phase 1 cleanup model assumes one managed category and a small set of tags. That is too narrow for the intended operating model:

- one category such as `seed` should be an autonomous pool that `seed-agent` may add to, pause, and delete from without per-item confirmation,
- other categories such as `movie` and `tv` should still be visible to the strategy engine and accept automatic adds,
- but those add-only categories must never be automatically deleted,
- and categories such as `movie` and `tv` may need to share one logical budget because they consume the same underlying storage pool.

The design needs to preserve a clear safety boundary:

- category policy decides what the agent may do,
- qB remains the only required runtime dependency,
- and budget enforcement should not require filesystem-level access.

## Goals

- Replace the single managed-category assumption with a reusable per-category policy model.
- Allow one or more categories to be fully mutable.
- Allow one or more categories to be add-only.
- Give every category the same configuration shape.
- Represent shared logical budgets explicitly in config.
- Allow multiple categories to point at the same budget pool.
- Base budget calculations on qB torrent `size` totals, not NAS disk inspection.
- Support "add to qB but do not start downloading" when a category is over budget.
- Make over-budget state auditable now, and notification-friendly later.
- Keep deletion policy explainable and based on a composite ranking instead of a single hard threshold.

## Non-Goals

- Connecting to NAS storage to inspect real share usage.
- Introducing category-specific filesystem agents or host-side probes.
- Building notifications in this slice.
- Replacing existing dry-run safety for mutating downloader commands.
- Designing the full multi-site replenishment strategy in this spec.

## CategoryPolicy And BudgetPool Model

Each qB category should be configured through one unified object. Logical capacity should be configured separately through named `BudgetPool` objects so multiple categories can share one pool.

Proposed shape:

```yaml
download_client:
  type: qbittorrent
  target: unraid-qb
  secret_ref: local/secrets/qbittorrent.yaml

  category_policies:
    - name: seed
      mode: mutable
      budget_pool: downloads
      delete_enabled: true
      over_budget_behavior: reject
      tags: [seed-agent, seed]
    - name: movie
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: reject
      tags: [seed-agent, movie]
    - name: tv
      mode: add_only
      budget_pool: media
      delete_enabled: false
      over_budget_behavior: reject
      tags: [seed-agent, tv]

  budget_pools:
    # Illustrative values only; deployments choose their own limits.
    - name: downloads
      max_size_tib: 10
    - name: media
      max_size_tib: 10
```

Expected `CategoryPolicy` fields:

- `name`: qB category name.
- `mode`: `mutable` or `add_only`.
- `budget_pool`: name of the shared logical capacity pool for this category.
- `delete_enabled`: explicit deletion permission gate.
- `over_budget_behavior`: supported value is `reject`; legacy `add_paused`
  input is migrated during config loading.
- `tags`: tags that should be attached to new torrents enqueued into this category.

Expected `BudgetPool` fields:

- `name`: logical pool identifier.
- `max_size_tib`: logical capacity budget shared by all categories assigned to the pool.

Notes:

- `delete_enabled` must not silently override `mode`. A category should be deletable only when both configuration and policy logic allow it.
- `budget_pool` belongs on every category so the config remains uniform and future notifications have a consistent source of truth.
- Source-site labeling should prefer qB tags, not a proliferation of subcategories. For example, use tags like `site:mteam` rather than categories such as `seed-mteam`.
- `movie` and `tv` should both point to the `media` pool because they share the same underlying storage budget even though they remain separate qB categories.

## Budget Semantics

Budget must be computed from qB's logical torrent sizes aggregated across all categories assigned to the same pool.

For this feature, pool usage is:

```text
sum(
  torrent.size
  for torrents
  where torrent.category is assigned to pool.name
)
```

This is an intentional approximation. qB on this host exposes category save paths such as `/downloads/seed`, `/media/movie`, and `/media/tv`, but it does not provide a reliable per-category real-disk-used metric through the current Web API integration. The project should therefore treat torrent `size` totals as the authoritative budgeting input.

This keeps the repo boundary clean:

- no NAS login,
- no share inspection,
- no dependency on filesystem tools outside qB.

## Mutable vs Add-Only Behavior

### Mutable Categories

Mutable categories are autonomous pools. `seed-agent` may:

- enqueue new torrents,
- pause torrents,
- delete torrents,
- delete files together with the torrent,
- and rebalance the pool without asking for item-by-item approval.

The first mutable category is `seed`.

### Add-Only Categories

Add-only categories may receive new torrents from discovery or intent flows, but `seed-agent` must not automatically:

- pause them for capacity reasons,
- delete them,
- or delete their files.

The first add-only categories are `movie` and `tv`.

These categories still benefit from policies because the system should know:

- which category to target for enqueue,
- which budget pool that category consumes,
- what tags to attach,
- how large the shared pool is allowed to grow logically,
- and whether enqueue must be rejected when the projected total is over budget.

## Over-Budget Behavior

The current over-budget behavior is `reject`.

When a category is over budget:

- `seed-agent` must reject the candidate before calling qB,
- a mutable delete-enabled pool should run direct cleanup and verify its live
  committed total after deletion,
- the audit trail should record that the category's budget pool was already over budget,
- and the category should be marked as needing operator attention once a notification system exists.

This behavior applies to both `mutable` and `add_only` categories. Add-only
categories cannot self-reclaim, so they remain blocked until capacity exists.

For `mutable` categories, over-budget state may also trigger candidate eviction work before or after enqueue, depending on the execution flow. For `add_only` categories, over-budget state must never trigger automatic deletion; it only changes start behavior and future operator visibility.

## Deletion Strategy For Mutable Categories

`seed` should not use a single delete threshold such as "delete the largest torrent" or "delete the oldest torrent."

Instead, deletion candidates should be ranked using a composite eviction score. Lower-value torrents should be deleted first.

The composite ranking should consider signals such as:

- recent upload contribution,
- current upload activity,
- upload-per-GiB efficiency,
- age since add,
- age since last meaningful activity,
- whether the torrent appears saturated,
- whether the torrent is consuming a large portion of its pool budget,
- and whether the torrent has persistently underperformed compared with other torrents in the same category.

The exact weights can evolve later, but the contract should remain:

- evaluate multiple signals,
- rank the worst candidates,
- delete only inside mutable categories,
- and keep the decision explainable in audit records.

## qB Integration Implications

The downloader integration should stop assuming one global managed category. Instead, it should support:

- listing torrents by category policy,
- aggregating usage per configured budget pool,
- enqueueing to a selected category with that category's configured tags,
- and optionally adding the torrent in a paused state when policy requires it.

This likely means evolving the current execution path from:

- one downloader category,
- one tag list,
- one managed/unmanaged cleanup boundary,

to:

- many configured category policies,
- many configured budget pools,
- per-category tag defaults,
- per-pool budget evaluation,
- and per-category mutation permissions.

## Safety Rules

- Dry-run remains the default for all mutating downloader commands.
- Automatic delete is allowed only for categories whose policy is explicitly mutable and delete-enabled.
- A mutable category owns every existing and future torrent whose qB category
  matches that policy. Tags are labels for audit/search and must not grant
  cleanup authority by themselves.
- Categories not present in config remain unmanaged and must never be automatically deleted.
- qB category names are part of the safety boundary and should be treated as operator-controlled configuration, not inferred heuristically.
- Audit output must explain whether a torrent was handled under mutable or add-only rules.

## Audit Expectations

Audit events for category-managed operations should include:

- category name,
- category mode,
- budget pool name,
- budget pool limit,
- estimated pool usage before the action,
- whether the pool was over budget,
- whether enqueue used paused-start behavior,
- and the primary reasons behind delete ranking or keep decisions.

This will let the future notification layer surface actionable summaries without changing core policy behavior.

## Migration Notes

The repo currently uses a simpler `downloader.category` plus `downloader.tags` model. Migrating to `category_policies` should be explicit and backward-compatible only if that materially reduces churn. If compatibility adds too much ambiguity, prefer a clean config migration with clear validation errors over a dual-mode design that is hard to reason about.

The important migration invariant is:

- old configs should not accidentally widen delete scope,
- and new configs should make mutable vs add-only intent obvious.

## Testing Expectations

The implementation plan should cover:

- config validation for `CategoryPolicy`,
- config validation for `BudgetPool`,
- per-pool logical size aggregation,
- over-budget enqueue behavior using paused start,
- composite eviction ranking inside mutable categories,
- proof that add-only categories never trigger auto-delete,
- and CLI/report output that surfaces budget state clearly.

## Open Follow-Ups

- How should paused-over-budget torrents be resumed later once capacity pressure improves?
- Should category policy eventually support per-category site preferences or replenishment sources?
- Should mutable-category deletion happen before enqueue, after enqueue, or both depending on urgency?
- What is the minimal audit summary needed before a notification subsystem exists?
