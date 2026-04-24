# Harness Workflow

This repository is intended to work well with many short, targeted Codex sessions instead of a few giant context-heavy sessions.

## Why

Short sessions are usually better here because they:

- reduce repeated context loading,
- make module ownership clearer,
- lower the chance of cross-module accidental edits,
- make verification more focused,
- leave a cleaner audit trail in docs and git history.

## Preferred Session Types

### 1. Project-init session

Use for:

- creating or refining the AI docs skeleton,
- clarifying module boundaries,
- updating roadmap structure,
- adding templates and collaboration rules.

### 2. Module session

Use for:

- one subsystem,
- one bug cluster,
- one integration boundary.

Example:

- M-Team discovery
- qBittorrent state ingest
- cleanup heuristics
- intent ranking

### 3. Roadmap-item session

Use for:

- one concrete next task from `docs/roadmap.md`.

This is usually the best default.

## Recommended Read Budget

Before editing:

1. `AGENTS.md`
2. `docs/roadmap.md`
3. one or two matching module docs

Only add:

- `docs/operations/session-handoff.md` if the task depends on recent unfinished work
- a specific spec or plan if the task changes behavior or architecture

## Recommended Write-Back

At the end of a meaningful task, update:

- the module doc if responsibilities or boundaries changed,
- `docs/roadmap.md` if status changed,
- `docs/operations/session-handoff.md` if a future session would otherwise miss something important.

## Verification Rule

Do not claim completion without running the smallest credible command set, such as:

- focused tests,
- full test suite if shared behavior moved,
- `ruff check`,
- one real CLI probe if the task is integration-heavy.

## Session Naming Heuristic

If you are opening a fresh session, prefer a narrow objective name such as:

- `mteam-api-discovery-spike`
- `qb-review-state-audit`
- `intent-ranking-threshold-tune`
- `cleanup-protective-rules`

Avoid broad names like:

- `seed-agent-improvements`
- `phase-3-work`

## When To Split

Open a new session instead of expanding the current one when:

- a second module becomes the main focus,
- the task turns from implementation into architecture work,
- verification context is starting to dominate the window,
- you need to investigate a new external integration.
