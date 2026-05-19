# Tracker Strategy Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-driven tracker strategy tuning without a coarse runtime `profile` field.

**Architecture:** Strategy remains a composition of concrete config knobs. A new read-only `strategy-report` command summarizes tracker-side candidate buckets and qB runtime outcomes, while recommended YAML examples document balanced, upload-farming, and space-saving combinations.

**Tech Stack:** Python, Typer CLI, Pydantic config models, pytest, YAML docs.

---

### Task 1: Strategy Report Helper

**Files:**
- Modify: `src/seed_agent/actions/pt.py`
- Test: `tests/test_pt_actions.py`

- [x] Write a failing helper test for candidate and runtime outcome buckets.
- [x] Implement `strategy_report()` as a read-only aggregation helper.
- [x] Verify the focused test passes with `uv run pytest -q tests/test_pt_actions.py::test_strategy_report_groups_tracker_signals_and_runtime_outcomes`.

### Task 2: Strategy Report CLI

**Files:**
- Modify: `src/seed_agent/cli.py`
- Test: `tests/test_cli.py`

- [x] Write a failing CLI test for `seed-agent strategy-report`.
- [x] Implement `strategy-report` by reusing discover, score, qB read-only listing, and joined candidate evidence.
- [x] Verify the focused test passes with `uv run pytest -q tests/test_cli.py::test_strategy_report_cli_reports_candidate_distribution_and_runtime_outcomes`.

### Task 3: Fine-Grained Strategy Knobs

**Files:**
- Modify: `src/seed_agent/config.py`
- Modify: `src/seed_agent/policies/scoring.py`
- Test: `tests/test_scoring.py`

- [x] Add failing tests for `leecher_score_full_at_multiplier` and `size_partial_max_gb`.
- [x] Add both fields to `DiscoveryConfig` with defaults that preserve existing behavior.
- [x] Update scoring so leecher contribution can ramp toward full credit and large-pack partial size credit can be widened or narrowed.
- [x] Verify focused scoring tests pass.

### Task 4: Recommended Configs And AI Guide

**Files:**
- Modify: `config/example.yaml`
- Create: `config/profiles/tracker-strategy/README.md`
- Create: `config/profiles/tracker-strategy/balanced.yaml`
- Create: `config/profiles/tracker-strategy/upload-farming.yaml`
- Create: `config/profiles/tracker-strategy/space-saving.yaml`
- Create: `docs/ai/modules/tracker-strategy.md`

- [x] Document the two new knobs in `config/example.yaml`.
- [x] Add recommendation-only YAML examples without a `strategy_profile` field.
- [x] Add the repo-local AI guide for the evidence-driven optimization loop.

### Task 5: Verification

**Files:**
- Validate code and docs changed above.

- [ ] Run focused tests: `uv run pytest -q tests/test_scoring.py tests/test_pt_actions.py::test_strategy_report_groups_tracker_signals_and_runtime_outcomes tests/test_cli.py::test_strategy_report_cli_reports_candidate_distribution_and_runtime_outcomes`.
- [ ] Run CLI smoke: `uv run seed-agent --help`.
- [ ] Run lint on touched Python: `uv run ruff check src/seed_agent/actions/pt.py src/seed_agent/cli.py src/seed_agent/config.py src/seed_agent/policies/scoring.py tests/test_pt_actions.py tests/test_cli.py tests/test_scoring.py`.
