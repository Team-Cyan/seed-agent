# Provider Kernel Roadmap

This spec records the long-term direction from the July 2026 deep research
review. It is not a commitment to add a broad plugin framework in the current
release line.

## Goal

Grow `seed-agent` from a qBittorrent/M-Team-focused automation tool into a
small, auditable tracker automation kernel while preserving the existing
Docker-first, dry-run-first, local-state-first operating model.

## Current Baseline

- `Downloader` is the contract for enqueue, listing, pause, delete, and optional
  live status.
- qBittorrent is the live operations baseline.
- Transmission is the first second downloader and validates the contract.
- `SearchProvider` is the contract for resource-intent release search.
- M-Team is the reference authenticated provider.
- Torznab is the first non-M-Team provider and validates the provider boundary.
- `StateStore` and audit JSONL remain the durable explanation layer.

## Reference Patterns

Use reference projects for patterns, not as code or product-shape templates.

- `autobrr`: event/filter/action separation, client-agnostic actions, and
  explainable rule matching.
- `Prowlarr`: indexer management and provider proxy boundaries.
- `cross-seed`: conservative matching against existing local data before adding
  torrents for reseeding.

## Near-Term Kernel Work

Keep the current contracts narrow and testable:

- expand contract tests before adding new implementations,
- keep provider construction config-driven and explicit,
- keep downloader status optional so second adapters can remain useful before
  matching all qB telemetry,
- keep Web and scheduler flows using the same enqueue planning helpers,
- expose status and planning decisions before automating stronger actions.

## Future Capabilities

The following are later-layer capabilities, not current core-loop work:

- announce/event-driven intake similar to autobrr,
- external indexer-manager integration such as Prowlarr/Torznab proxying,
- cross-seed evaluation that maps existing files to equivalent torrents,
- richer provider health and capability reporting,
- optional rule bundle import/export for provider-specific filters.

## Non-Goals

- No broad plugin marketplace in the current phase.
- No browser-login automation as a core dependency.
- No dashboard-first rewrite.
- No automatic cross-seed execution without a conservative dry-run report,
  exact candidate set, and explicit operator execution.
