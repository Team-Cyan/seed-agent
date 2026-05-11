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
- `discovery.min_size_gb` and `discovery.max_size_gb` are hard candidate size
  bounds; `preferred_size_min_gb` and `preferred_size_max_gb` only affect the
  size score contribution.
- `discovery.min_seeders` and `discovery.max_leechers` are hard bounds when
  configured; they protect the seed pool from dead or overly crowded candidates.
- `discovery.target_seed_leecher_ratio` is a soft seed-pressure score input,
  computed as `seeders / max(leechers, 1)`. It replaces the old absolute
  `discovery.max_seeders` scoring name; legacy configs are migrated at load time.
- `discovery.allow_non_free` lets NORMAL/non-free candidates remain eligible
  without discount-score credit. Keep it false for freeleech-only discovery.
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

## Verification

- `uv run pytest -q tests/test_scoring.py tests/test_intent_ranking.py`
