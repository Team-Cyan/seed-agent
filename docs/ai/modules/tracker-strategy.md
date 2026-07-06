# Tracker Strategy Optimization

Use this guide when tuning tracker candidate selection from live evidence.

## Principles

- Do not add a coarse `profile` runtime field for strategy.
- Express strategy through concrete configuration knobs:
  - M-Team `api_discovery` filters and sort order,
  - `pt_filters.min_leechers`,
  - `pt_filters.leecher_score_full_at_multiplier`,
  - `pt_filters.target_seed_leecher_ratio`,
  - `pt_filters.max_size_gb`,
  - `pt_filters.preferred_size_min_gb`,
  - `pt_filters.preferred_size_max_gb`,
  - `pt_filters.size_partial_max_gb`,
  - `pt_scoring.weights`,
  - `pt_scoring.min_score_to_enqueue`,
  - qB runtime gates such as `pt_filters.max_active_downloads` and
    `pt_filters.max_total_amount_left_gb`,
  - downloader free-disk reserve through `pt_filters.min_free_disk_gb`.
- Keep FREE/2xFREE, H&R protection, dry-run first, and mutable-category cleanup
  boundaries unless the operator explicitly changes them.

## Recommended Config Examples

Recommended strategy combinations live under:

`config/profiles/tracker-strategy/`

These examples are copy/merge material, not standalone runtime profiles:

- `balanced.yaml`: baseline behavior.
- `upload-farming.yaml`: favors live demand and upload opportunity.
- `space-saving.yaml`: favors storage control and lower active-download risk.

## Optimization Loop

1. Run `seed-agent strategy-report --config <config>`.
2. Inspect candidate buckets:
   - accepted vs rejected by leechers,
   - seed/leecher ratio,
   - size,
   - score.
3. Inspect runtime outcome buckets:
   - managed torrent count,
   - candidate-evidence coverage,
   - upload count and average upload,
   - outcomes by original candidate leechers, size, and score.
4. Inspect `site_history` in the same report. It should explain sample counts,
   productive/missing/no-upload counts, active backoffs, and whether the score
   is applied or still using the low-sample fallback.
5. Run `seed-agent headroom-report --config <config>` to project accepted
   candidate size against both the default budget pool and the downloader's
   reported free disk headroom before changing enqueue gates.
6. Adjust concrete knobs, not a coarse runtime profile switch.
7. Run `seed-agent run-once --config <config>` without `--execute`.
8. Execute only after accepted candidates and runtime pause gates look sane.
9. Re-run after several cycles before making stronger strategy changes.

## Tuning Direction

For upload farming:

- sort M-Team API discovery by `leechers desc`,
- increase `max_pages`,
- raise `target_seed_leecher_ratio`,
- raise `size_partial_max_gb`,
- remove or raise `max_size_gb`,
- increase leecher weight,
- optionally lower `min_score_to_enqueue` slightly,
- keep qB budget gates so accepted torrents can be added paused when capacity is tight.

For space saving:

- keep `min_leechers` higher,
- keep `target_seed_leecher_ratio` lower,
- keep `max_size_gb` enabled,
- lower `preferred_size_max_gb` and `size_partial_max_gb`,
- keep `max_active_downloads` and `max_total_amount_left_gb` conservative,
- set `min_free_disk_gb` when the downloader shares a physical volume with
  add-only media categories or other services,
- keep `min_score_to_enqueue` higher.

## Evidence Caveat

If runtime outcomes mostly show `qb:*` backfill rows rather than original tracker
candidate ids, do not overfit. First improve candidate-to-qB linkage or wait for
new execute-mode candidates whose enqueue-time evidence is preserved.
