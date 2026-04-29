# CLI Module

## Purpose

Expose the operator-facing command surface and safe summaries.

## Primary Files

- `src/seed_agent/cli.py`
- `tests/test_cli.py`
- `tests/test_cli_bootstrap.py`

## Current Responsibilities

- command registration,
- config loading,
- dry-run defaults,
- safe JSON summaries,
- site probe diagnostics,
- unattended `schedule-run` orchestration for server-side polling,
- free-window safety previewing for freeleech-sensitive workflows,
- heartbeat reporting and healthcheck probes for long-running deployments.

## Expectations

- do not expose secrets in output,
- keep summaries useful but redacted,
- preserve stable command names unless intentionally versioned,
- keep `run-once` and `schedule-run` payload shapes aligned enough for external
  schedulers and log collectors,
- keep enqueue-like commands aligned on runtime gate reporting so paused-add
  decisions expose both `enqueue_paused_by_pool_policy` and
  `enqueue_paused_reasons`,
- preview and enforce risky free-window decisions consistently when the free
  window is unknown or too short for the configured safety threshold,
- keep long-running deployment liveness inspectable through structured
  heartbeat output instead of opaque shell wrappers.

## Verification

- `uv run pytest -q tests/test_cli.py tests/test_cli_bootstrap.py tests/test_run_once.py`
- `uv run seed-agent --help`
- `uv run seed-agent schedule-run --help`
- `uv run seed-agent healthcheck --help`
