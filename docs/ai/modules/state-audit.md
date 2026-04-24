# State And Audit Module

## Purpose

Persist local lifecycle knowledge and durable decision evidence.

## Primary Files

- `src/seed_agent/state.py`
- `src/seed_agent/audit.py`
- `tests/test_state.py`
- `tests/test_audit.py`

## Current Responsibilities

- store local candidate/intent lifecycle state,
- persist release candidates and enqueue metadata,
- write append-only redacted audit records.

## Expectations

- do not treat local state as disposable,
- redact secrets in audit output,
- keep state changes explainable and reviewable.

## Verification

- `uv run pytest -q tests/test_state.py tests/test_audit.py`
