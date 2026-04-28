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
- `discovery.min_size_gb` and `discovery.max_size_gb` are hard candidate size
  bounds; `preferred_size_min_gb` and `preferred_size_max_gb` only affect the
  size score contribution.
- `discovery.min_seeders` and `discovery.max_leechers` are hard bounds when
  configured; they protect the seed pool from dead or overly crowded candidates.

## Verification

- `uv run pytest -q tests/test_scoring.py tests/test_intent_ranking.py`
