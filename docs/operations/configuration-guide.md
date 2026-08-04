# Configuration Guide

This guide explains the current `seed-agent` runtime configuration. Use
`config/example.yaml` as the complete starting file and
`docs/operations/config-and-state-fields.md` as the exhaustive field inventory.

## Configuration Sources And Precedence

The CLI, scheduler, and Web UI use one YAML file selected by `--config` or
`SEED_AGENT_CONFIG`. Docker and Unraid deployments should mount that file and
keep secrets in referenced files under `local/secrets/`.

The Web UI edits the same YAML file through schema validation and atomic
replacement. Environment variables may override documented scheduler startup
controls, but they do not replace tracker, scoring, downloader, cleanup, or Want
List sections.

Before tuning, verify the active path through `/api/config`; a checkout copy is
not proof of the mounted runtime configuration.

## Zero And Null Semantics

Optional PT upper limits use one consistent convention: both `0` and `null`
disable the limit.

| Field | Positive value | `0` or `null` |
| --- | --- | --- |
| `max_seed_leecher_ratio` | Reject above the ratio | No hard ratio ceiling |
| `max_size_gb` | Reject above the GiB size | No hard size ceiling |
| `max_active_downloads` | Limit active seed downloads | No configured slot limit |
| `max_total_amount_left_gb` | Limit remaining download liability | No configured liability limit |

Minimum fields naturally stop restricting at `0`. Additional scoring controls
use these disable rules:

Leecher count intentionally has no upper limit: more leechers normally represent
more demand. Use `max_seed_leecher_ratio` to reject oversupplied swarms, or the
tracker-native `api_discovery.max_seeders` only when an absolute discovery cap
is deliberately required.

- `target_seed_leecher_ratio: 0` disables the soft ratio curve and grants the
  full ratio component.
- `leecher_score_full_at_multiplier: 0` disables the demand ramp and grants full
  leecher credit once `min_leechers` passes.
- `freshness_zero_score_hours: 0` disables publication-age decay and grants full
  freshness credit.
- `weights.freshness: 0` removes freshness from ranking. Rebalance the other
  weights because all scoring weights must still total `100`.

`min_free_disk_gb: 0` removes the additional reserve, but the agent still does
not plan downloads beyond qBittorrent's reported physical free space.
`budget_pools[].max_size_tib` defines an actual storage pool and must remain
positive.

## Tracker Discovery

Each `tracker_sites[]` entry selects RSS or API discovery. M-Team API discovery
is preferred when an API key is available:

```yaml
tracker_sites:
  - name: mteam
    type: mteam
    enabled: true
    rss_url: https://rss.m-team.cc/api/rss/fetch
    api_key_ref: local/secrets/mt.api-key
    discovery_mode: api
    api_discovery:
      modes: [normal, adult]
      only_free: true
      sort_field: leechers
      sort_order: desc
      page_size: 100
      max_pages: 2
      min_seeders: 0
      max_seeders: 0
      min_leechers: 0
```

M-Team native `api_discovery.min_seeders` and `min_leechers` accept `null` to
inherit global PT thresholds. Explicit `0` keeps native API filtering open so
local scoring can make the final decision. `api_discovery.max_seeders: 0`
disables that native upper bound and is the default; set a positive value only
when an absolute discovery ceiling is intentional.

## PT Admission Filters

`pt_filters` contains hard eligibility rules, soft score-shaping controls, and
runtime headroom gates. A quality-oriented upload-farming configuration can use:

```yaml
pt_filters:
  discounts: [free, 2xfree]
  min_left_time_minutes: 120
  min_seeders: 1
  min_leechers: 30
  leecher_score_full_at_multiplier: 2
  target_seed_leecher_ratio: 2
  max_seed_leecher_ratio: 10
  freshness_full_score_hours: 6
  freshness_zero_score_hours: 48
  min_size_gb: 0
  max_size_gb: 0
  preferred_size_min_gb: 2
  preferred_size_max_gb: 300
  size_partial_max_gb: 1000
  max_active_downloads: 8
  max_total_amount_left_gb: 1000
  min_free_disk_gb: 0
  allow_non_free: false
  allow_hr: false
```

Hard decisions occur before score threshold acceptance:

- FREE-only policy rejects paid PT farming candidates when
  `allow_non_free=false`.
- `min_seeders`, `min_leechers`, size bounds, H&R policy, known free-window
  requirements, and `max_seed_leecher_ratio` may hard-reject a candidate.
- A hard rejection produces score `0`; lowering `min_score_to_enqueue` cannot
  bypass it.

Large torrents remain eligible when `max_size_gb` is disabled. The preferred and
partial size fields change only the size contribution; they do not hard-reject
large high-demand torrents.

## PT Scoring

`pt_scoring.min_score_to_enqueue` is the final score threshold. Every weight is
an integer from `0` through `100`, and the weights must total exactly `100`.

```yaml
pt_scoring:
  min_score_to_enqueue: 80
  weights:
    discount: 20
    leechers: 30
    seeders: 25
    freshness: 15
    left_time: 5
    size: 3
    site_history: 2
```

The `seeders` component represents `seeders / max(leechers, 1)`, not absolute
seeder count. This keeps large popular torrents valuable when demand rises with
competition. `freshness` receives full credit through
`freshness_full_score_hours`, tapers linearly, and reaches zero at
`freshness_zero_score_hours`.

Configurations created before `0.21.0` may omit `weights.freshness`; the loader
adds it as `0` for backward compatibility. A newly saved config emits the field
explicitly.

## Execute-Time Revalidation And Duplicate Safety

M-Team API discovery defers `genDlToken` until execute mode. Immediately before
token generation, the agent refreshes torrent detail and re-scores current
seeders, leechers, discount, and free-window state. A candidate that no longer
passes is rejected without being sent to qBittorrent.

The enqueue path suppresses an already active tracker candidate, an exact
normalized title already present in qB, and lower-ranked duplicate titles in the
same batch. qBittorrent remains the authority for identical infohash rejection.
The agent does not download every `.torrent` only to fingerprint file trees, so
different titles and different infohashes with coincidentally identical files
are not pre-deduplicated.

Successful execute-mode enqueue creates an immutable
`candidate_enqueue_snapshots` row containing the refreshed swarm counts, ratio,
candidate publication age, score, reasons, qB hash, and enqueue time. Strategy
reports group later runtime results into `0-2h`, `2-8h`, `8-24h`, and `24h+`
cohorts.

## Downloader Categories And Capacity

`download_client.category_policies` is the mutation authority boundary:

- `mutable` categories may be managed and cleaned by policy.
- `add_only` categories may receive downloads but are never automatically
  deleted.
- Tags are audit metadata and do not grant cleanup authority.
- `max_active_downloads` counts only the configured default seed category;
  Want List movie, TV, and anime categories do not consume seed slots.

Budget pool caps remain hard storage boundaries even when PT runtime upper
limits are disabled.

## Cleanup, Want List, Scheduler, And State

- `seed_cleanup` controls cold, zero-upload, completed-low-upload, and capacity
  reclamation behavior. Keep destructive execution preview-first.
- `want_sources`, `want_decision`, `release_preferences`, and
  `release_profiles` control requested media acquisition independently from the
  FREE-only PT farming policy.
- `scheduler` owns cycle timing, free-window execution safety, prune, tracker
  backfill, and Want List cadence.
- `local_state` controls candidate and backup retention; SQLite and audit files
  are durable evidence and must not be treated as disposable cache.

See `config/example.yaml` for the complete shape and
`docs/operations/config-and-state-fields.md` for every supported field and
SQLite column.

## Validation And Safe Rollout

Use this sequence after editing configuration:

```bash
seed-agent config-status --config config/config.yaml
seed-agent strategy-report --config config/config.yaml
seed-agent headroom-report --config config/config.yaml
seed-agent run-once --config config/config.yaml
```

Only add `--execute` after reviewing accepted candidates, refreshed ratio and
freshness reasons, duplicate counts, pool usage, and runtime pause reasons.
