# M-Team API-Driven Discovery

## Goal

Add an API-driven discovery path for `mteam` that can rank and filter candidate torrents using M-Team laboratory access tokens instead of relying on RSS ordering alone.

This spec does **not** remove or rewrite the existing RSS implementation. RSS remains useful as:

- a generic adapter shape for other sites,
- a fallback discovery source when API discovery is unavailable,
- a simple feed source for low-control subscription workflows.

The new work is specifically about making M-Team discovery support higher-value PT strategy inputs such as FREE filtering, sorting by download activity, and richer candidate selection before enqueue.

## Why

The current `mteam` RSS path is now good enough for:

- parsing titles,
- generating usable download links,
- enriching discovered candidates with `size`, `seeders`, `leechers`, and `times_completed` through `x-api-key`.

However, RSS is still weak as a primary discovery surface for M-Team because it does not let the operator control:

- FREE-only filtering,
- sort field and sort order,
- download-count-oriented ranking,
- more targeted category/mode selection before candidates are discovered.

That means the current system can enrich what it already sees, but it cannot yet ask M-Team for the *best* candidates according to PT ROI heuristics. The M-Team OpenAPI `TorrentSearch` shape includes native filters beyond mode/sort, including category, source, medium, standard, codec, team, processing, country, label, keyword, DMM, date range, hot, offer, favorite, and discount fields.

## Scope

Phase this as an additive `mteam` discovery mode, not a general discovery rewrite.

In scope:

- add an M-Team API list/search client authenticated by `api_key_ref`,
- support API-driven candidate discovery for `mteam`,
- preserve the existing `TorrentCandidate` model and scoring pipeline,
- keep the existing RSS implementation in place,
- allow `mteam` config to choose API discovery without breaking current RSS config shape,
- expose enough knobs to support FREE filtering and activity-based sorting.

Out of scope:

- removing the current RSS adapter,
- changing non-M-Team site adapters,
- redesigning the global scoring model,
- qBittorrent policy changes,
- browser-login or cookie-based M-Team flows.

## Desired Operator Experience

Example shape:

```yaml
sites:
  - name: mt
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.cc/api/rss/fetch?dl=1&pageSize=10&sign=secret
    api_key_ref: local/secrets/mt.api-key
    discovery_mode: api
    api_discovery:
      mode: adult
      only_free: true
      sort_field: downloads
      sort_order: desc
      page_size: 50
      # Optional native M-Team filter IDs.
      # categories: [410, 429]
      # standards: [1, 6]
      # video_codecs: [1, 16]
      # sources: [8]
      # mediums: [10]
      # teams: [9]
      # labels_new: []
      # hot: true
      min_seeders: 0
      max_seeders: 200
      min_leechers: 0
      min_times_completed: 0
```

Operator intent:

- use M-Team API as the primary discovery source,
- keep RSS available as a documented alternate path,
- continue to use `detail` through the same access token,
- defer `genDlToken` until execute-mode enqueue for accepted candidates,
- keep the downstream scoring and enqueue commands unchanged.

## Design Direction

### 1. Separate discovery source from enrichment source

Treat M-Team as having two related but distinct concerns:

- discovery: list/search/filter/sort candidates,
- enrichment: fill candidate metadata and produce download links.

The current code already covers enrichment well enough. The new work should add API-driven discovery without coupling it too tightly to RSS parsing. M-Team-native search fields belong in `api_discovery`, not in secret files.

### 2. Keep `TorrentCandidate` as the stable boundary

Whether a candidate came from RSS or API discovery, downstream code should still receive the same `TorrentCandidate` shape.

That keeps these layers stable:

- scoring,
- intent ranking,
- enqueue,
- audit,
- CLI summaries.

### 3. Prefer explicit M-Team-only configuration

Do not force other site adapters to adopt M-Team-specific knobs.

Prefer one of:

- `discovery_mode: rss | api`
- a nested `api_discovery` block only honored for `type: mteam`

This keeps the config honest without pretending every site has the same capabilities.

### 4. Preserve RSS as a first-class fallback

RSS should remain:

- implemented,
- tested,
- documented,
- available for future sites and simpler operator flows.

But for M-Team specifically, API discovery should become the preferred path once implemented.

## Implementation Sketch

1. Add an M-Team API discovery client under `src/seed_agent/sites/mteam.py` or a sibling module.
2. Reverse-engineer or confirm the list/search endpoint shape and supported filters.
3. Add config for `mteam` API discovery mode and filter parameters.
4. Convert API responses into `TorrentCandidate`.
5. Reuse existing enrichment and download-token logic where it still adds value.
6. Update `discover`, `site-probe`, and any search provider wiring so the chosen discovery mode is visible in diagnostics.
7. Document recommended operator setup with `api_key_ref`.

## Acceptance Criteria

- `mteam` can discover candidates without relying on RSS ordering.
- Operator can request FREE-only discovery.
- Operator can sort by an activity-oriented field such as downloads when the API supports it.
- Operator can bound candidate volume with page size or equivalent query controls.
- Returned candidates still flow through existing scoring and enqueue commands unchanged.
- `site-probe` or equivalent diagnostics clearly show whether `mteam` is using RSS or API discovery.
- Existing RSS-based tests and behavior remain intact.

## Open Questions

- What exact M-Team API endpoint should be used for list/search discovery?
- Which sort keys are actually supported by the API and stable enough to document?
- Does the list/search payload already include enough fields to skip a second detail fetch in some cases?
- Should M-Team intent search also prefer API discovery, or should intent search stay RSS-backed until a later step?

## Suggested Next Step

Before implementation, do one short verification pass against the real API:

- identify the stable list/search endpoint,
- capture supported filter/sort parameters,
- confirm which fields come back directly,
- then convert this note into a small execution plan.
