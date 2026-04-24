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
- site probe diagnostics.

## Expectations

- do not expose secrets in output,
- keep summaries useful but redacted,
- preserve stable command names unless intentionally versioned.

## Verification

- `uv run pytest -q tests/test_cli.py tests/test_cli_bootstrap.py`
- `uv run seed-agent --help`
