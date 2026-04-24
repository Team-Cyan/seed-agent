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

## Verification

- `uv run pytest -q tests/test_scoring.py tests/test_intent_ranking.py`
