# Scoring Module

## Purpose

Score discovered torrents or ranked releases using explicit policy weights and explainable reasons.

## Primary Files

- `src/seed_agent/policies/scoring.py`
- `src/seed_agent/policies/intent_ranking.py`
- `src/seed_agent/actions/pt.py`
- `src/seed_agent/actions/intent.py`

## Current Responsibilities

- apply configured scoring weights,
- produce explainable breakdowns,
- keep enqueue decisions auditable,
- rank releases for intent workflows.
- apply generic intent-search quality tag scores.

## Expectations

- explanations should remain operator-readable,
- scoring should not absorb site-specific parsing logic,
- ranking should not bypass state/audit expectations.
- generic PT candidates without `left_time_minutes` are still hard-rejected,
- M-Team API candidates may omit discount expiry; if the adapter marks that case,
  scoring gives no left-time points but does not hard-reject an otherwise strong
  current FREE/2xFREE candidate.
- M-Team API candidates that explicitly expose an open-ended FREE window, such
  as `discountEndTime=null` alongside `discount=FREE`, are treated as having a
  known unlimited free window for scoring and execute-time safety gates.
- `pt_filters.min_size_gb` and `pt_filters.max_size_gb` are hard candidate size
  bounds; set `max_size_gb` to `0` or `null` to disable the hard upper bound.
  `preferred_size_min_gb` and `preferred_size_max_gb` only affect the size score
  contribution.
- `pt_filters.min_seeders` and `pt_filters.max_leechers` are hard bounds when
  configured; they protect the seed pool from dead or overly crowded candidates.
- `pt_filters.leecher_score_full_at_multiplier` is a soft demand-shaping knob.
  The default `1.0` preserves the old behavior where `min_leechers` gets full
  leecher credit. Values above `1.0` make candidates ramp from partial credit at
  `min_leechers` to full credit at `min_leechers * multiplier`.
- `pt_filters.target_seed_leecher_ratio` is a soft seed-pressure score input,
  computed as `seeders / max(leechers, 1)`.
- `pt_filters.size_partial_max_gb` is the soft size-credit ceiling after
  `preferred_size_max_gb`. Raise it for upload-farming strategies that allow
  very large hot packs; lower it for space-saving strategies.
- `pt_filters.allow_non_free` lets NORMAL/non-free candidates remain eligible
  without discount-score credit. Keep it false for freeleech-only discovery.
- Use `seed-agent strategy-report --config <config>` before changing strategy
  knobs. It groups current candidates and linked qB runtime outcomes by demand,
  ratio, size, and score.
- When tuning seed-pool scoring, start from live qB outcomes instead of title
  guesses. Compare each executed candidate's enqueue-time `seeders`,
  `leechers`, seed/leecher ratio, size, and free window against later qB
  `uploaded_gb`, upload/download ratio, completion time, and no-upload cleanup
  result.
- Treat absolute seeder count as weak evidence. A candidate with many seeders
  can still perform if leechers are high enough, while low leecher counts and
  high seed/leecher ratio are stronger negative signals for upload farming.
- Do not overfit a single live run. Use live review/prune samples to identify
  suspicious bands, then encode changes as explainable scoring weights or
  retention thresholds with tests.
- Keep quality wishes such as Remux, BluRay, WEB-DL, 2160p, HDR10+, Dolby
  Vision, DDP, TrueHD, FLAC, or ASS subtitles in `release_preferences.quality_tag_scores`.
  Values are integer score adjustments keyed by canonical tag group. Each group
  counts once per release even when multiple aliases are present, so `BluRay`
  plus `Blu-ray` does not double-score.
- For TV/anime resource intents, `want_decision.series_search_mode=season` treats
  SxxEyy requests as season-pack searches and does not penalize missing episode
  tokens. Use `episode` when the operator wants one episode at a time.
- Want List titles can arrive as mixed Chinese and English aliases, such as a
  Douban Chinese title followed by an English title. Intent release ranking
  scores title match against the full title and script-specific aliases, then
  uses the best title score so an English tracker result is not unfairly
  penalized by the Chinese title token.

## Verification

- `uv run pytest -q tests/test_scoring.py tests/test_intent_ranking.py`
